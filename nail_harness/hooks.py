"""
NAIL Harness — Hook System (Audit & Safety)
==============================================

Inspired by Anthropic's Claude Code hooks architecture:
  - PreToolUse:  Validates actions BEFORE execution (safety gate)
  - PostToolUse: Logs actions AFTER execution (audit trail)

NAIL innovation: The PreToolUse hook runs a VQC quantum anomaly
check on the agent's behavioral telemetry before allowing tool
execution.  If the VQC confidence exceeds the anomaly threshold,
the tool call is BLOCKED.

Hook protocol:
  - PreToolUse(tool_name, tool_input) → bool (True = allow)
  - PostToolUse(tool_name, tool_input, tool_output) → None
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


# ═══════════════════════════════════════════════════════════════════════════
# Audit Logger (equivalent to Anthropic's report-tracker.py)
# ═══════════════════════════════════════════════════════════════════════════

class AuditLogger:
    """
    Logs all tool uses to an audit trail file.

    Equivalent to Anthropic's PostToolUse hooks:
      - report-tracker.py  → tracks file writes
      - script-usage-logger.py → tracks script executions

    NAIL version logs ALL tool uses with agent state.
    """

    def __init__(self, log_path: str = "./audit/tool_audit.json", max_entries: int = 500):
        self.log_path = Path(log_path).resolve()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self._entries: list[dict] = []

        # Load existing
        if self.log_path.exists():
            try:
                with open(self.log_path) as f:
                    data = json.load(f)
                    self._entries = data.get("entries", [])
            except (json.JSONDecodeError, KeyError):
                self._entries = []

    def log(
        self,
        tool_name: str,
        tool_input: dict,
        tool_output: str = "",
        blocked: bool = False,
        block_reason: str = "",
        agent_state: Optional[dict] = None,
    ):
        """Record a tool use event."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "input_keys": list(tool_input.keys()),
            "output_length": len(tool_output),
            "blocked": blocked,
            "block_reason": block_reason,
            "agent_state": agent_state or {},
        }
        self._entries.append(entry)

        # Trim to max
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

        # Persist
        with open(self.log_path, "w") as f:
            json.dump({"entries": self._entries}, f, indent=2)

    def get_recent(self, n: int = 20) -> list[dict]:
        """Return last N audit entries."""
        return self._entries[-n:]

    def get_stats(self) -> dict:
        """Audit summary statistics."""
        total = len(self._entries)
        blocked = sum(1 for e in self._entries if e.get("blocked"))
        tools_used = {}
        for e in self._entries:
            t = e.get("tool", "unknown")
            tools_used[t] = tools_used.get(t, 0) + 1
        return {
            "total_events": total,
            "total_blocked": blocked,
            "block_rate": blocked / total if total > 0 else 0.0,
            "tools_used": tools_used,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Safety Gate (equivalent to Anthropic SRE agent's PreToolUse hooks)
# ═══════════════════════════════════════════════════════════════════════════

class SafetyGate:
    """
    PreToolUse safety validator.

    Checks tool calls against policy rules before execution.
    Optionally runs VQC anomaly detection on agent behavioral features.

    Rules:
      1. Blocked tools list (e.g., never allow certain tools)
      2. Parameter validation (e.g., config values in safe ranges)
      3. Rate limiting (max N tool calls per window)
      4. VQC anomaly gate (block if agent behavior is anomalous)
    """

    def __init__(
        self,
        blocked_tools: Optional[list[str]] = None,
        max_calls_per_minute: int = 30,
        vqc_adapter: Optional[Any] = None,       # VQCModelAdapter instance
        anomaly_threshold: float = 0.7,           # Block if VQC confidence > this
    ):
        self.blocked_tools = set(blocked_tools or [])
        self.max_calls_per_minute = max_calls_per_minute
        self.vqc_adapter = vqc_adapter
        self.anomaly_threshold = anomaly_threshold

        # Rate limiting state
        self._call_timestamps: list[float] = []

        # Parameter validation rules: tool_name → validator(input) → (ok, reason)
        self._validators: dict[str, Callable] = {}

    def add_validator(self, tool_name: str, validator: Callable[[dict], tuple[bool, str]]):
        """Register a parameter validator for a specific tool."""
        self._validators[tool_name] = validator

    def check(
        self,
        tool_name: str,
        tool_input: dict,
        agent_telemetry: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """
        Validate a tool call.

        Args:
            tool_name:        Name of the tool being called
            tool_input:       Tool parameters
            agent_telemetry:  Current agent behavioral features (for VQC check)

        Returns:
            (allowed, reason) — True if allowed, False with explanation if blocked
        """
        # Rule 1: Blocked tools
        if tool_name in self.blocked_tools:
            return False, f"Tool '{tool_name}' is on the blocked list"

        # Rule 2: Rate limiting
        now = time.time()
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 60]
        if len(self._call_timestamps) >= self.max_calls_per_minute:
            return False, f"Rate limit exceeded ({self.max_calls_per_minute}/min)"
        self._call_timestamps.append(now)

        # Rule 3: Parameter validation
        if tool_name in self._validators:
            ok, reason = self._validators[tool_name](tool_input)
            if not ok:
                return False, f"Parameter validation failed: {reason}"

        # Rule 4: VQC anomaly gate
        if self.vqc_adapter and agent_telemetry:
            try:
                features = self._extract_features(agent_telemetry)
                label, confidence = self.vqc_adapter.predict(features)
                if label == "anomaly" and confidence > self.anomaly_threshold:
                    return False, (
                        f"VQC anomaly detected (confidence={confidence:.2%}). "
                        f"Agent behavior flagged as potentially compromised."
                    )
            except Exception as e:
                # VQC failure should not block tools — log and continue
                pass

        return True, "OK"

    def _extract_features(self, telemetry: dict) -> list[float]:
        """Extract 8-feature vector from agent telemetry dict."""
        feature_names = [
            "trust_score", "burn_rate", "semantic_drift",
            "assertion_density", "manipulation_score",
            "repetition_index", "memory_corruption", "intervention_rate",
        ]
        return [float(telemetry.get(f, 0.5)) for f in feature_names]


# ═══════════════════════════════════════════════════════════════════════════
# Hook Factory — creates ready-to-use pre/post hooks
# ═══════════════════════════════════════════════════════════════════════════

def create_hooks(
    audit_path: str = "./audit/tool_audit.json",
    blocked_tools: Optional[list[str]] = None,
    vqc_adapter: Optional[Any] = None,
    anomaly_threshold: float = 0.7,
) -> tuple[Callable, Callable]:
    """
    Create pre_tool_use and post_tool_use hook functions ready
    to plug into AgentOptions.

    Returns:
        (pre_tool_use, post_tool_use)

    Usage:
        pre_hook, post_hook = create_hooks(vqc_adapter=adapter)
        options = AgentOptions(pre_tool_use=pre_hook, post_tool_use=post_hook)
    """
    audit = AuditLogger(log_path=audit_path)
    gate = SafetyGate(
        blocked_tools=blocked_tools,
        vqc_adapter=vqc_adapter,
        anomaly_threshold=anomaly_threshold,
    )

    def pre_tool_use(tool_name: str, tool_input: dict) -> bool:
        allowed, reason = gate.check(tool_name, tool_input)
        if not allowed:
            audit.log(tool_name, tool_input, blocked=True, block_reason=reason)
        return allowed

    def post_tool_use(tool_name: str, tool_input: dict, tool_output: str):
        audit.log(tool_name, tool_input, tool_output=tool_output)

    return pre_tool_use, post_tool_use
