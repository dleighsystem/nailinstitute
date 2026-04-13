"""
NAIL Containment Primitives — Paper 8 Reference Implementation
================================================================

Four novel containment primitives for rogue agent detection,
prevention, and termination:

1. **Behavioral Envelope Enforcement (BEE)** — Runtime constraint
   verification against formal behavioral specifications.

2. **Semantic Drift Fencing (SDF)** — Real-time detection of
   semantic deviation from task mandates via embedding distance.

3. **Checkpoint Integrity Attestation (CIA)** — Cryptographic
   verification of agent state persistence using HMAC signatures.

4. **Cascading Circuit Breakers (CCB)** — Multi-level automatic
   termination with graduated response (resource, anomaly, scope).

Usage:

    >>> from integration.containment import (
    ...     BehavioralEnvelope,
    ...     SemanticDriftFence,
    ...     CheckpointAttestor,
    ...     CascadingCircuitBreaker,
    ...     ContainmentStack,
    ... )
    >>>
    >>> # Quick start: minimum viable containment
    >>> stack = ContainmentStack.minimum_viable()
    >>> result = stack.check_action(action="search_db", args={"query": "..."})
    >>> if result.blocked:
    ...     print(f"BLOCKED: {result.reason}")

Reference:
    Leigh, D. (2026). "Real-Time Detection, Prevention, and Containment
    of Rogue Autonomous Agents: A Seven-Layer Defense Architecture."
    NAIL Institute Working Paper 8.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# COMMON TYPES
# ═══════════════════════════════════════════════════════════════════════════

class ContainmentAction(str, Enum):
    """Action to take when containment is triggered."""
    ALLOW = "allow"
    WARN = "warn"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"
    TERMINATE = "terminate"


class ViolationType(str, Enum):
    """Classification of envelope violations."""
    TOOL_NOT_ALLOWED = "tool_not_allowed"
    TOOL_FORBIDDEN = "tool_forbidden"
    SCOPE_VIOLATION = "scope_violation"
    BEHAVIORAL_VIOLATION = "behavioral_violation"
    RESOURCE_EXCEEDED = "resource_exceeded"
    ANOMALY_DETECTED = "anomaly_detected"
    SCOPE_BOUNDARY = "scope_boundary"
    DRIFT_DETECTED = "drift_detected"
    INTEGRITY_FAILURE = "integrity_failure"


@dataclass
class ContainmentResult:
    """Result of a containment check."""
    action: ContainmentAction
    blocked: bool
    violation_type: Optional[ViolationType] = None
    reason: str = ""
    layer: str = ""
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @staticmethod
    def allow(layer: str = "") -> "ContainmentResult":
        return ContainmentResult(
            action=ContainmentAction.ALLOW, blocked=False, layer=layer,
        )

    @staticmethod
    def block(reason: str, violation_type: ViolationType,
              layer: str = "", **meta: Any) -> "ContainmentResult":
        return ContainmentResult(
            action=ContainmentAction.BLOCK,
            blocked=True,
            violation_type=violation_type,
            reason=reason,
            layer=layer,
            metadata=meta,
        )


# ═══════════════════════════════════════════════════════════════════════════
# PRIMITIVE 1: BEHAVIORAL ENVELOPE ENFORCEMENT (BEE)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Rule:
    """A single behavioral constraint rule.

    Rules are evaluated against action context. They can reference:
    - ``tool_call.name`` — the tool being called
    - ``tool_call.args.*`` — arguments to the tool
    - ``session.*`` — session-level context (user, permissions, etc.)
    - ``history.*`` — aggregated history (counts, patterns)
    """
    expression: str
    description: str = ""
    on_violation: ContainmentAction = ContainmentAction.BLOCK

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Evaluate rule against context. Returns True if rule PASSES."""
        try:
            return bool(eval(self.expression, {"__builtins__": {}}, context))
        except Exception as e:
            logger.warning("Rule evaluation failed (%s): %s", self.expression, e)
            return False  # Fail-closed: treat evaluation errors as violations


class BehavioralEnvelope:
    """
    Behavioral Envelope Enforcement (BEE) — Layer 2.

    Defines a formal specification of what an agent is permitted to do.
    Every action is checked against the envelope in real-time.

    Properties:
        - **Action completeness**: Every agent action is evaluated.
        - **Envelope monotonicity**: Envelope can only be tightened, never
          relaxed without explicit human approval.
        - **Fail-closed**: If evaluation fails, the action is blocked.

    Example::

        envelope = BehavioralEnvelope(
            name="customer_support_v1",
            allowed_tools=["search_kb", "create_ticket"],
            forbidden_tools=["execute_code", "send_email"],
            scope_rules=[
                Rule("tool_call_args.get('customer_id') == session.get('customer_id')",
                     "Cannot access other customers' data"),
            ],
        )

        result = envelope.check_action(
            tool_name="search_kb",
            tool_args={"customer_id": "c123", "query": "order status"},
            session={"customer_id": "c123"},
        )
    """

    def __init__(
        self,
        name: str,
        allowed_tools: list[str] | None = None,
        forbidden_tools: list[str] | None = None,
        scope_rules: list[Rule] | None = None,
        behavioral_rules: list[Rule] | None = None,
        on_violation: ContainmentAction = ContainmentAction.BLOCK,
        max_actions: int | None = None,
    ) -> None:
        self.name = name
        self.allowed_tools = set(allowed_tools) if allowed_tools else None
        self.forbidden_tools = set(forbidden_tools) if forbidden_tools else set()
        self.scope_rules = scope_rules or []
        self.behavioral_rules = behavioral_rules or []
        self.on_violation = on_violation
        self.max_actions = max_actions
        self._action_count = 0
        self._tightened = False

    def check_action(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
        output: str | None = None,
    ) -> ContainmentResult:
        """Check a proposed action against the behavioral envelope."""
        self._action_count += 1
        tool_args = tool_args or {}
        session = session or {}

        # 1. Tool allowlist check
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            return ContainmentResult.block(
                reason=f"Tool '{tool_name}' not in allowed list: {sorted(self.allowed_tools)}",
                violation_type=ViolationType.TOOL_NOT_ALLOWED,
                layer="BEE",
                tool=tool_name,
            )

        # 2. Tool forbid-list check
        if tool_name in self.forbidden_tools:
            return ContainmentResult.block(
                reason=f"Tool '{tool_name}' is explicitly forbidden",
                violation_type=ViolationType.TOOL_FORBIDDEN,
                layer="BEE",
                tool=tool_name,
            )

        # 3. Action count check
        if self.max_actions and self._action_count > self.max_actions:
            return ContainmentResult.block(
                reason=f"Action count ({self._action_count}) exceeds limit ({self.max_actions})",
                violation_type=ViolationType.RESOURCE_EXCEEDED,
                layer="BEE",
                count=self._action_count,
            )

        # 4. Scope rules
        context = {
            "tool_call_name": tool_name,
            "tool_call_args": tool_args,
            "session": session,
            "action_count": self._action_count,
        }
        for rule in self.scope_rules:
            if not rule.evaluate(context):
                return ContainmentResult.block(
                    reason=f"Scope violation: {rule.description or rule.expression}",
                    violation_type=ViolationType.SCOPE_VIOLATION,
                    layer="BEE",
                    rule=rule.expression,
                )

        # 5. Behavioral rules (output-based)
        if output is not None:
            context["output"] = output
            for rule in self.behavioral_rules:
                if not rule.evaluate(context):
                    return ContainmentResult.block(
                        reason=f"Behavioral violation: {rule.description or rule.expression}",
                        violation_type=ViolationType.BEHAVIORAL_VIOLATION,
                        layer="BEE",
                        rule=rule.expression,
                    )

        return ContainmentResult.allow(layer="BEE")

    def tighten(
        self,
        remove_tools: list[str] | None = None,
        add_rules: list[Rule] | None = None,
    ) -> None:
        """Tighten the envelope (monotonic — cannot be undone)."""
        if remove_tools:
            if self.allowed_tools:
                self.allowed_tools -= set(remove_tools)
            self.forbidden_tools |= set(remove_tools)
        if add_rules:
            self.scope_rules.extend(add_rules)
        self._tightened = True
        logger.info("Envelope '%s' tightened: removed=%s, added_rules=%d",
                     self.name, remove_tools, len(add_rules or []))

    def reset_action_count(self) -> None:
        """Reset the action counter (e.g., for a new session)."""
        self._action_count = 0


# ═══════════════════════════════════════════════════════════════════════════
# PRIMITIVE 2: SEMANTIC DRIFT FENCING (SDF)
# ═══════════════════════════════════════════════════════════════════════════

def _simple_token_embed(text: str) -> list[float]:
    """Fallback embedding: normalized token frequency vector.

    This is a simple baseline for environments without a real embedding
    model. For production use, replace with sentence-transformers or
    an API-based embedder.
    """
    tokens = re.findall(r'\b\w+\b', text.lower())
    vocab: dict[str, int] = {}
    for t in tokens:
        vocab[t] = vocab.get(t, 0) + 1
    total = sum(vocab.values()) or 1
    # Deterministic ordering for reproducibility
    sorted_keys = sorted(vocab.keys())
    vec = [vocab[k] / total for k in sorted_keys]
    # Pad/truncate to fixed dim
    dim = 128
    vec = vec[:dim] + [0.0] * max(0, dim - len(vec))
    return vec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticDriftFence:
    """
    Semantic Drift Fencing (SDF) — Layer 4.

    Detects when an agent's outputs semantically diverge from its
    assigned task, even if outputs pass schema validation.

    Uses embedding-based distance to a task centroid, with configurable
    thresholds for warning and blocking.

    Example::

        fence = SemanticDriftFence(
            task_description="Answer customer questions about order status",
            warn_threshold=0.35,
            block_threshold=0.60,
        )

        result = fence.check("Your order #1234 is being shipped tomorrow.")
        # → ContainmentResult(action=ALLOW)

        result = fence.check("Here's how to make a bomb...")
        # → ContainmentResult(action=BLOCK, reason="Semantic drift: 0.92")
    """

    def __init__(
        self,
        task_description: str,
        warn_threshold: float = 0.35,
        block_threshold: float = 0.60,
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self.task_description = task_description
        self.warn_threshold = warn_threshold
        self.block_threshold = block_threshold
        self._embed = embed_fn or _simple_token_embed
        self._centroid = self._embed(task_description)
        self._drift_history: list[float] = []

    def check(self, output: str) -> ContainmentResult:
        """Check output for semantic drift from the task centroid."""
        output_embedding = self._embed(output)
        similarity = _cosine_similarity(self._centroid, output_embedding)
        distance = 1.0 - similarity
        self._drift_history.append(distance)

        trend = self._compute_trend()

        if distance > self.block_threshold:
            return ContainmentResult.block(
                reason=f"Semantic drift: {distance:.3f} exceeds block threshold {self.block_threshold}",
                violation_type=ViolationType.DRIFT_DETECTED,
                layer="SDF",
                distance=distance,
                trend=trend,
            )
        elif distance > self.warn_threshold:
            return ContainmentResult(
                action=ContainmentAction.WARN,
                blocked=False,
                violation_type=ViolationType.DRIFT_DETECTED,
                reason=f"Semantic drift warning: {distance:.3f} exceeds warn threshold {self.warn_threshold}",
                layer="SDF",
                metadata={"distance": distance, "trend": trend},
            )
        return ContainmentResult.allow(layer="SDF")

    def _compute_trend(self) -> str:
        """Analyze drift trend over recent outputs."""
        if len(self._drift_history) < 3:
            return "insufficient_data"
        recent = self._drift_history[-3:]
        if all(recent[i] < recent[i + 1] for i in range(len(recent) - 1)):
            return "accelerating"
        if all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
            return "recovering"
        return "stable"

    @property
    def drift_history(self) -> list[float]:
        return list(self._drift_history)

    def reset(self) -> None:
        self._drift_history.clear()


# ═══════════════════════════════════════════════════════════════════════════
# PRIMITIVE 3: CHECKPOINT INTEGRITY ATTESTATION (CIA)
# ═══════════════════════════════════════════════════════════════════════════

class IntegrityError(Exception):
    """Raised when checkpoint integrity verification fails."""
    pass


class CheckpointAttestor:
    """
    Checkpoint Integrity Attestation (CIA) — Layer 3/5.

    Provides cryptographic integrity guarantees for agent state
    persistence. Signs checkpoints at write time and verifies
    at load time, defending against AVE-2025-0041 (State Persistence
    Deserialization) and AVE-2025-0042 (Checkpoint Injection Chain).

    Example::

        attestor = CheckpointAttestor(signing_key=b"secret-key-here")

        # At checkpoint save
        checkpoint = {"agent_state": {...}, "round": 5}
        signed = attestor.sign_checkpoint(checkpoint)
        save_to_db(signed)

        # At checkpoint load
        loaded = load_from_db()
        verified = attestor.verify_checkpoint(loaded)
        # Raises IntegrityError if tampered
    """

    ATTESTATION_KEY = "_nail_attestation"
    ALGORITHM = "hmac-sha256"

    def __init__(
        self,
        signing_key: bytes,
        enforce_format: str = "json_strict",
        reject_unsigned: bool = True,
    ) -> None:
        self._key = signing_key
        self._enforce_format = enforce_format
        self._reject_unsigned = reject_unsigned

    def _compute_signature(self, data: dict[str, Any]) -> str:
        """Compute HMAC-SHA256 signature for a data dict."""
        # Remove attestation before signing to avoid circular reference
        clean = {k: v for k, v in data.items() if k != self.ATTESTATION_KEY}
        canonical = json.dumps(clean, sort_keys=True, ensure_ascii=True)
        return hmac.new(
            self._key, canonical.encode("utf-8"), hashlib.sha256,
        ).hexdigest()

    def sign_checkpoint(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        """Add cryptographic attestation to a checkpoint."""
        # Remove any existing attestation
        clean = {k: v for k, v in checkpoint.items() if k != self.ATTESTATION_KEY}
        signature = self._compute_signature(clean)

        clean[self.ATTESTATION_KEY] = {
            "signature": signature,
            "algorithm": self.ALGORITHM,
            "timestamp": time.time(),
            "serialization_format": self._enforce_format,
        }
        return clean

    def verify_checkpoint(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        """Verify checkpoint integrity. Returns clean data or raises IntegrityError."""
        attestation = checkpoint.get(self.ATTESTATION_KEY)

        if attestation is None:
            if self._reject_unsigned:
                raise IntegrityError(
                    "Checkpoint missing attestation — refusing to load "
                    "(possible unsigned state injection)"
                )
            logger.warning("Unsigned checkpoint loaded — integrity not verified")
            return checkpoint

        # Check format
        actual_format = attestation.get("serialization_format", "unknown")
        if actual_format != self._enforce_format:
            raise IntegrityError(
                f"Checkpoint format mismatch: expected '{self._enforce_format}', "
                f"got '{actual_format}' — possible format downgrade attack "
                "(AVE-2025-0042 Checkpoint Injection Chain)"
            )

        # Verify signature
        clean = {k: v for k, v in checkpoint.items() if k != self.ATTESTATION_KEY}
        expected = self._compute_signature(clean)
        if not hmac.compare_digest(expected, attestation["signature"]):
            raise IntegrityError(
                "Checkpoint signature mismatch — state has been tampered with "
                "(possible AVE-2025-0041 State Persistence Deserialization attack)"
            )

        logger.debug(
            "Checkpoint integrity verified (signed at %.0f)",
            attestation.get("timestamp", 0),
        )
        return clean

    def check(self, checkpoint: dict[str, Any]) -> ContainmentResult:
        """Non-raising check — returns ContainmentResult."""
        try:
            self.verify_checkpoint(checkpoint)
            return ContainmentResult.allow(layer="CIA")
        except IntegrityError as e:
            return ContainmentResult.block(
                reason=str(e),
                violation_type=ViolationType.INTEGRITY_FAILURE,
                layer="CIA",
            )


# ═══════════════════════════════════════════════════════════════════════════
# PRIMITIVE 4: CASCADING CIRCUIT BREAKERS (CCB)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ResourceLimits:
    """Configurable resource limits for agents."""
    max_tokens: int = 100_000
    max_cost_usd: float = 10.0
    max_wall_time_seconds: int = 300
    max_actions: int = 50
    max_errors: int = 5
    max_retries: int = 3


@dataclass
class ScopeBoundary:
    """Defines the scope boundary for an agent."""
    allowed_file_paths: list[str] = field(default_factory=list)
    allowed_network_domains: list[str] = field(default_factory=list)
    allowed_db_tables: list[str] = field(default_factory=list)


class CascadingCircuitBreaker:
    """
    Cascading Circuit Breakers (CCB) — Layer 5.

    Three circuit breaker types that cascade with graduated response:

    1. **Resource-Based** — Token, cost, time, action, error limits.
       Triggers graceful termination with state preservation.

    2. **Anomaly-Based** — Monitors NAIL pathology detectors.
       Triggers immediate termination with rollback.

    3. **Scope-Based** — File, network, database boundaries.
       Triggers action block with human escalation.

    Example::

        breaker = CascadingCircuitBreaker(
            resource_limits=ResourceLimits(max_tokens=50_000, max_actions=30),
            scope_boundary=ScopeBoundary(
                allowed_file_paths=["/data/customer/"],
                allowed_network_domains=["api.internal.com"],
            ),
        )

        # In agent loop:
        breaker.record_action(tokens=150, cost=0.003)
        result = breaker.check_resource()

        result = breaker.check_scope(
            tool_name="read_file", args={"path": "/etc/passwd"}
        )
        # → BLOCKED: FILE_SCOPE_VIOLATION
    """

    def __init__(
        self,
        resource_limits: ResourceLimits | None = None,
        scope_boundary: ScopeBoundary | None = None,
        anomaly_threshold_warn: float = 0.7,
        anomaly_threshold_critical: float = 0.9,
    ) -> None:
        self.limits = resource_limits or ResourceLimits()
        self.scope = scope_boundary or ScopeBoundary()
        self.anomaly_warn = anomaly_threshold_warn
        self.anomaly_critical = anomaly_threshold_critical

        # Counters
        self._tokens_used: int = 0
        self._cost_usd: float = 0.0
        self._start_time: float = time.time()
        self._action_count: int = 0
        self._error_count: int = 0
        self._trip_log: list[ContainmentResult] = []

    def record_action(
        self,
        tokens: int = 0,
        cost: float = 0.0,
        error: bool = False,
    ) -> None:
        """Record resource consumption for a single action."""
        self._tokens_used += tokens
        self._cost_usd += cost
        self._action_count += 1
        if error:
            self._error_count += 1

    def check_resource(self) -> ContainmentResult:
        """Check resource-based circuit breakers."""
        elapsed = time.time() - self._start_time

        checks = [
            (self._tokens_used > self.limits.max_tokens,
             f"Token limit exceeded: {self._tokens_used}/{self.limits.max_tokens}"),
            (self._cost_usd > self.limits.max_cost_usd,
             f"Cost limit exceeded: ${self._cost_usd:.4f}/${self.limits.max_cost_usd}"),
            (elapsed > self.limits.max_wall_time_seconds,
             f"Time limit exceeded: {elapsed:.0f}s/{self.limits.max_wall_time_seconds}s"),
            (self._action_count > self.limits.max_actions,
             f"Action limit exceeded: {self._action_count}/{self.limits.max_actions}"),
            (self._error_count > self.limits.max_errors,
             f"Error limit exceeded: {self._error_count}/{self.limits.max_errors}"),
        ]

        for tripped, reason in checks:
            if tripped:
                result = ContainmentResult.block(
                    reason=reason,
                    violation_type=ViolationType.RESOURCE_EXCEEDED,
                    layer="CCB-resource",
                )
                self._trip_log.append(result)
                return result

        return ContainmentResult.allow(layer="CCB-resource")

    def check_anomaly(self, anomaly_score: float) -> ContainmentResult:
        """Check anomaly-based circuit breaker."""
        if anomaly_score > self.anomaly_critical:
            result = ContainmentResult(
                action=ContainmentAction.TERMINATE,
                blocked=True,
                violation_type=ViolationType.ANOMALY_DETECTED,
                reason=f"Critical anomaly score: {anomaly_score:.3f} > {self.anomaly_critical}",
                layer="CCB-anomaly",
                metadata={"anomaly_score": anomaly_score},
            )
            self._trip_log.append(result)
            return result
        elif anomaly_score > self.anomaly_warn:
            return ContainmentResult(
                action=ContainmentAction.REQUIRE_APPROVAL,
                blocked=False,
                violation_type=ViolationType.ANOMALY_DETECTED,
                reason=f"Anomaly warning: {anomaly_score:.3f} > {self.anomaly_warn}",
                layer="CCB-anomaly",
                metadata={"anomaly_score": anomaly_score},
            )

        return ContainmentResult.allow(layer="CCB-anomaly")

    def check_scope(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
    ) -> ContainmentResult:
        """Check scope-based circuit breaker."""
        args = args or {}

        # File path scope
        if "path" in args and self.scope.allowed_file_paths:
            path = args["path"]
            if not any(path.startswith(p) for p in self.scope.allowed_file_paths):
                result = ContainmentResult.block(
                    reason=f"File scope violation: '{path}' not in allowed paths",
                    violation_type=ViolationType.SCOPE_BOUNDARY,
                    layer="CCB-scope",
                    path=path,
                    allowed=self.scope.allowed_file_paths,
                )
                self._trip_log.append(result)
                return result

        # Network scope
        if "url" in args and self.scope.allowed_network_domains:
            url = args["url"]
            domain = _extract_domain(url)
            if domain not in self.scope.allowed_network_domains:
                result = ContainmentResult.block(
                    reason=f"Network scope violation: '{domain}' not in allowed domains",
                    violation_type=ViolationType.SCOPE_BOUNDARY,
                    layer="CCB-scope",
                    domain=domain,
                    allowed=self.scope.allowed_network_domains,
                )
                self._trip_log.append(result)
                return result

        # Database scope
        if "query" in args and self.scope.allowed_db_tables:
            tables = _extract_sql_tables(args["query"])
            unauthorized = tables - set(self.scope.allowed_db_tables)
            if unauthorized:
                result = ContainmentResult.block(
                    reason=f"Database scope violation: tables {unauthorized} not allowed",
                    violation_type=ViolationType.SCOPE_BOUNDARY,
                    layer="CCB-scope",
                    tables=list(unauthorized),
                    allowed=self.scope.allowed_db_tables,
                )
                self._trip_log.append(result)
                return result

        return ContainmentResult.allow(layer="CCB-scope")

    def check_all(
        self,
        tool_name: str = "",
        args: dict[str, Any] | None = None,
        anomaly_score: float = 0.0,
    ) -> ContainmentResult:
        """Run all circuit breaker checks. Returns first failure or ALLOW."""
        for check_fn, check_args in [
            (self.check_resource, {}),
            (self.check_anomaly, {"anomaly_score": anomaly_score}),
            (self.check_scope, {"tool_name": tool_name, "args": args}),
        ]:
            result = check_fn(**check_args)
            if result.blocked:
                return result
        return ContainmentResult.allow(layer="CCB")

    @property
    def trip_log(self) -> list[ContainmentResult]:
        return list(self._trip_log)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "tokens_used": self._tokens_used,
            "cost_usd": self._cost_usd,
            "elapsed_seconds": time.time() - self._start_time,
            "action_count": self._action_count,
            "error_count": self._error_count,
            "trips": len(self._trip_log),
        }

    def reset(self) -> None:
        """Reset all counters and trip log."""
        self._tokens_used = 0
        self._cost_usd = 0.0
        self._start_time = time.time()
        self._action_count = 0
        self._error_count = 0
        self._trip_log.clear()


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    url = url.split("://", 1)[-1]
    return url.split("/", 1)[0].split(":")[0]


def _extract_sql_tables(query: str) -> set[str]:
    """Extract table names from SQL query (basic heuristic)."""
    tables: set[str] = set()
    query_upper = query.upper()
    for keyword in ["FROM", "JOIN", "INTO", "UPDATE", "TABLE"]:
        for match in re.finditer(rf'\b{keyword}\s+(\w+)', query_upper):
            tables.add(match.group(1).lower())
    return tables


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED CONTAINMENT STACK
# ═══════════════════════════════════════════════════════════════════════════

class ContainmentStack:
    """
    Unified containment stack combining all four primitives.

    Provides a single entry point for containment checks, evaluating
    each layer in sequence and returning the first blocking result.

    Example::

        stack = ContainmentStack(
            envelope=BehavioralEnvelope(
                name="support_agent",
                allowed_tools=["search", "respond"],
            ),
            drift_fence=SemanticDriftFence(
                task_description="Answer customer support questions",
            ),
            checkpoint_attestor=CheckpointAttestor(
                signing_key=b"my-secret-key",
            ),
            circuit_breaker=CascadingCircuitBreaker(
                resource_limits=ResourceLimits(max_tokens=50_000),
            ),
        )

        # Check a proposed action
        result = stack.check_action(
            tool_name="search",
            tool_args={"query": "order status"},
            session={"customer_id": "c123"},
        )

        # Check an output
        result = stack.check_output("Your order is on its way!")

        # Check a checkpoint
        result = stack.check_checkpoint({"state": {...}})
    """

    def __init__(
        self,
        envelope: BehavioralEnvelope | None = None,
        drift_fence: SemanticDriftFence | None = None,
        checkpoint_attestor: CheckpointAttestor | None = None,
        circuit_breaker: CascadingCircuitBreaker | None = None,
    ) -> None:
        self.envelope = envelope
        self.drift_fence = drift_fence
        self.attestor = checkpoint_attestor
        self.breaker = circuit_breaker
        self._check_log: list[ContainmentResult] = []

    @classmethod
    def minimum_viable(cls) -> "ContainmentStack":
        """Create a minimum viable containment stack (P0).

        Implements the 5-component stack from Paper 8 § 13.1:
        1. Tool permission whitelist (BEE)
        2. Resource circuit breakers (CCB)
        3. Structured output enforcement (via BEE behavioral rules)
        4. Comprehensive logging (built-in)
        """
        return cls(
            envelope=BehavioralEnvelope(
                name="minimum_viable",
                forbidden_tools=["execute_code", "shell", "eval", "exec"],
                max_actions=100,
            ),
            circuit_breaker=CascadingCircuitBreaker(
                resource_limits=ResourceLimits(
                    max_tokens=100_000,
                    max_cost_usd=10.0,
                    max_wall_time_seconds=300,
                    max_actions=100,
                ),
            ),
        )

    def check_action(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
        anomaly_score: float = 0.0,
    ) -> ContainmentResult:
        """Run all applicable checks on a proposed action."""
        # Layer 2: Behavioral Envelope
        if self.envelope:
            result = self.envelope.check_action(tool_name, tool_args, session)
            self._check_log.append(result)
            if result.blocked:
                return result

        # Layer 5: Circuit Breakers
        if self.breaker:
            result = self.breaker.check_all(tool_name, tool_args, anomaly_score)
            self._check_log.append(result)
            if result.blocked:
                return result

        return ContainmentResult.allow(layer="stack")

    def check_output(self, output: str) -> ContainmentResult:
        """Run output validation checks."""
        # Layer 4: Semantic Drift Fence
        if self.drift_fence:
            result = self.drift_fence.check(output)
            self._check_log.append(result)
            if result.blocked:
                return result

        return ContainmentResult.allow(layer="stack")

    def check_checkpoint(self, checkpoint: dict[str, Any]) -> ContainmentResult:
        """Verify checkpoint integrity."""
        if self.attestor:
            result = self.attestor.check(checkpoint)
            self._check_log.append(result)
            return result

        return ContainmentResult.allow(layer="stack")

    @property
    def check_log(self) -> list[ContainmentResult]:
        return list(self._check_log)


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    # Types
    "ContainmentAction",
    "ContainmentResult",
    "ViolationType",
    "Rule",
    # Primitives
    "BehavioralEnvelope",
    "SemanticDriftFence",
    "CheckpointAttestor",
    "IntegrityError",
    "CascadingCircuitBreaker",
    "ResourceLimits",
    "ScopeBoundary",
    # Stack
    "ContainmentStack",
]
