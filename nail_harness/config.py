"""
NAIL Harness — Configuration Loader
=======================================

Loads harness.yaml policy configuration and wires up all
SDK components (SafetyGate, TTL, CircuitBreaker, Egress,
Firewall, Guard) from a single YAML file.

Example harness.yaml:

    harness:
      session:
        ttl_seconds: 120
        max_context_tokens: 8192

      budget:
        max_tokens: 50000
        max_cost_usd: 5.00
        max_tool_calls: 100

      egress:
        allowed_domains:
          - "api.openai.com"
          - "*.googleapis.com"
          - "api.stripe.com"
        block_private: true
        block_metadata: true

      firewall:
        additional_patterns:
          - "(?i)GRANT\\s+ALL"
        similarity_threshold: 0.85

      guard:
        model: "nail-guard:v4"
        ollama_host: "http://localhost:11434"
        block_threshold: 3
        timeout_seconds: 10
        fallback_on_error: "allow"

      safety_gate:
        blocked_tools:
          - "system_shell"
          - "raw_sql"
        max_calls_per_minute: 30

      identity:
        drift_threshold: 0.15

      logic:
        max_self_citation_ratio: 0.1

      audit:
        log_path: "./audit/tool_audit.json"
        event_log_path: "./audit/events.json"
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from .circuit_breaker import TTLEnforcer, TokenCircuitBreaker, StateRollback
from .firewall import EgressPolicy, SemanticFirewall, ActionGate
from .guard_client import GuardClient
from .hooks import SafetyGate, AuditLogger, create_hooks


class HarnessConfig:
    """
    Loads harness.yaml and constructs all SDK components.

    Usage:
        config = HarnessConfig.from_yaml("harness.yaml")

        # Use individual components
        config.ttl.start_session()
        config.breaker.record(session_id, tokens_used=100)
        config.gate.check("http_request", {"url": "..."})

        # Or get pre-wired hooks for AgentOptions
        pre_hook, post_hook = config.create_hooks()
    """

    def __init__(self, raw: dict):
        self._raw = raw.get("harness", raw)

        # Session TTL
        session_cfg = self._raw.get("session", {})
        self.ttl = TTLEnforcer(
            ttl_seconds=session_cfg.get("ttl_seconds", 120),
        )

        # Token / Cost budget
        budget_cfg = self._raw.get("budget", {})
        self.breaker = TokenCircuitBreaker(
            max_tokens=budget_cfg.get("max_tokens", 50_000),
            max_cost_usd=budget_cfg.get("max_cost_usd", 5.00),
            max_tool_calls=budget_cfg.get("max_tool_calls", 100),
        )

        # Egress policy
        egress_cfg = self._raw.get("egress", {})
        self.egress = EgressPolicy(
            allowed_domains=egress_cfg.get("allowed_domains"),
            blocked_domains=egress_cfg.get("blocked_domains"),
            block_private=egress_cfg.get("block_private", True),
            block_metadata=egress_cfg.get("block_metadata", True),
        )

        # Semantic firewall
        fw_cfg = self._raw.get("firewall", {})
        self.firewall = SemanticFirewall(
            additional_patterns=fw_cfg.get("additional_patterns"),
            similarity_threshold=fw_cfg.get("similarity_threshold", 0.85),
        )

        # Guard client
        guard_cfg = self._raw.get("guard", {})
        self.guard: Optional[GuardClient] = None
        if guard_cfg.get("model"):
            self.guard = GuardClient(
                model=guard_cfg.get("model", "nail-guard:v4"),
                ollama_host=guard_cfg.get("ollama_host", "http://localhost:11434"),
                block_threshold=guard_cfg.get("block_threshold", 3),
                timeout_seconds=guard_cfg.get("timeout_seconds", 10),
                fallback_on_error=guard_cfg.get("fallback_on_error", "allow"),
            )

        # Combined action gate
        self.gate = ActionGate(
            egress=self.egress,
            firewall=self.firewall,
            guard=self.guard,
        )

        # Safety gate (tool blocking + rate limiting)
        safety_cfg = self._raw.get("safety_gate", {})
        self.safety_gate = SafetyGate(
            blocked_tools=safety_cfg.get("blocked_tools"),
            max_calls_per_minute=safety_cfg.get("max_calls_per_minute", 30),
        )

        # Audit
        audit_cfg = self._raw.get("audit", {})
        self.audit_logger = AuditLogger(
            log_path=audit_cfg.get("log_path", "./audit/tool_audit.json"),
        )
        self.rollback = StateRollback(
            log_path=audit_cfg.get("event_log_path", "./audit/events.json"),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "HarnessConfig":
        """Load configuration from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Harness config not found: {path}")
        raw = yaml.safe_load(path.read_text())
        return cls(raw)

    @classmethod
    def default(cls) -> "HarnessConfig":
        """Create a config with sensible defaults (no YAML file needed)."""
        return cls({"harness": {}})

    def create_hooks(self):
        """
        Create pre_tool_use and post_tool_use hooks that chain:
          1. SafetyGate (blocked tools + rate limiting)
          2. ActionGate (egress + firewall + guard)
          3. AuditLogger (post-use logging)

        Returns:
            (pre_tool_use, post_tool_use) callables for AgentOptions
        """
        def pre_tool_use(tool_name: str, tool_input: dict) -> bool:
            # Safety gate first
            allowed, reason = self.safety_gate.check(tool_name, tool_input)
            if not allowed:
                self.audit_logger.log(
                    tool_name, tool_input, blocked=True, block_reason=reason,
                )
                return False

            # Action gate (egress + firewall + guard)
            allowed, reason = self.gate.check(tool_name, tool_input)
            if not allowed:
                self.audit_logger.log(
                    tool_name, tool_input, blocked=True, block_reason=reason,
                )
                return False

            return True

        def post_tool_use(tool_name: str, tool_input: dict, tool_output: str):
            self.audit_logger.log(tool_name, tool_input, tool_output=tool_output)
            # Also record in event log for rollback capability
            self.rollback.record(
                session_id="default",
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=tool_output,
            )

        return pre_tool_use, post_tool_use
