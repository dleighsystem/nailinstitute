"""Tests for Paper 8 containment primitives."""

import json
import time
import pytest

from integration.containment import (
    BehavioralEnvelope,
    CascadingCircuitBreaker,
    CheckpointAttestor,
    ContainmentAction,
    ContainmentResult,
    ContainmentStack,
    IntegrityError,
    ResourceLimits,
    Rule,
    ScopeBoundary,
    SemanticDriftFence,
    ViolationType,
)


# ═══════════════════════════════════════════════════════════════════════════
# CONTAINMENT RESULT
# ═══════════════════════════════════════════════════════════════════════════

class TestContainmentResult:
    def test_allow_factory(self):
        r = ContainmentResult.allow(layer="test")
        assert not r.blocked
        assert r.action == ContainmentAction.ALLOW
        assert r.layer == "test"

    def test_block_factory(self):
        r = ContainmentResult.block(
            reason="bad action",
            violation_type=ViolationType.TOOL_FORBIDDEN,
            layer="BEE",
            tool="evil_tool",
        )
        assert r.blocked
        assert r.action == ContainmentAction.BLOCK
        assert r.violation_type == ViolationType.TOOL_FORBIDDEN
        assert r.reason == "bad action"
        assert r.metadata["tool"] == "evil_tool"

    def test_timestamp_auto_set(self):
        r = ContainmentResult.allow()
        assert r.timestamp > 0


# ═══════════════════════════════════════════════════════════════════════════
# PRIMITIVE 1: BEHAVIORAL ENVELOPE ENFORCEMENT (BEE)
# ═══════════════════════════════════════════════════════════════════════════

class TestBehavioralEnvelope:
    @pytest.fixture
    def envelope(self):
        return BehavioralEnvelope(
            name="test_agent",
            allowed_tools=["search", "respond", "create_ticket"],
            forbidden_tools=["execute_code", "send_email"],
            scope_rules=[
                Rule(
                    "tool_call_args.get('customer_id') == session.get('customer_id')",
                    "Cannot access other customers",
                ),
            ],
            behavioral_rules=[
                Rule(
                    "'system prompt' not in output.lower()",
                    "Must not reference system prompts",
                ),
            ],
            max_actions=5,
        )

    def test_allowed_tool_passes(self, envelope):
        r = envelope.check_action("search", {"query": "test"})
        assert not r.blocked

    def test_tool_not_in_allowlist_blocked(self, envelope):
        r = envelope.check_action("delete_database", {})
        assert r.blocked
        assert r.violation_type == ViolationType.TOOL_NOT_ALLOWED

    def test_forbidden_tool_blocked(self, envelope):
        r = envelope.check_action("execute_code", {"code": "import os"})
        assert r.blocked
        # allowlist check fires before forbid-list check
        assert r.violation_type == ViolationType.TOOL_NOT_ALLOWED

    def test_forbidden_tool_blocked_no_allowlist(self):
        """When there's no allowlist, the forbid-list check fires."""
        env = BehavioralEnvelope(
            name="open_with_bans",
            forbidden_tools=["execute_code", "send_email"],
        )
        r = env.check_action("execute_code", {"code": "import os"})
        assert r.blocked
        assert r.violation_type == ViolationType.TOOL_FORBIDDEN

    def test_scope_rule_passes(self, envelope):
        r = envelope.check_action(
            "search",
            {"customer_id": "c123", "query": "order"},
            session={"customer_id": "c123"},
        )
        assert not r.blocked

    def test_scope_rule_fails(self, envelope):
        r = envelope.check_action(
            "search",
            {"customer_id": "c456"},
            session={"customer_id": "c123"},
        )
        assert r.blocked
        assert r.violation_type == ViolationType.SCOPE_VIOLATION

    def test_behavioral_rule_passes(self, envelope):
        r = envelope.check_action(
            "respond", {}, output="Your order is on its way!",
        )
        assert not r.blocked

    def test_behavioral_rule_fails(self, envelope):
        r = envelope.check_action(
            "respond", {}, output="Here is my System Prompt: ...",
        )
        assert r.blocked
        assert r.violation_type == ViolationType.BEHAVIORAL_VIOLATION

    def test_max_actions_enforced(self, envelope):
        for i in range(5):
            r = envelope.check_action("search", {"query": f"q{i}"})
            assert not r.blocked
        # 6th action should be blocked
        r = envelope.check_action("search", {"query": "one more"})
        assert r.blocked
        assert r.violation_type == ViolationType.RESOURCE_EXCEEDED

    def test_tighten_removes_tools(self, envelope):
        r = envelope.check_action("respond", {})
        assert not r.blocked
        envelope.tighten(remove_tools=["respond"])
        r = envelope.check_action("respond", {})
        assert r.blocked

    def test_tighten_adds_rules(self, envelope):
        envelope.tighten(add_rules=[
            Rule("action_count < 3", "Too many actions after tightening"),
        ])
        assert len(envelope.scope_rules) == 2

    def test_reset_action_count(self, envelope):
        for _ in range(5):
            envelope.check_action("search", {})
        envelope.reset_action_count()
        r = envelope.check_action("search", {})
        assert not r.blocked

    def test_no_allowlist_permits_any_tool(self):
        env = BehavioralEnvelope(name="open")
        r = env.check_action("anything", {})
        assert not r.blocked

    def test_behavioral_rule_skipped_without_output(self, envelope):
        # Behavioral rules only fire when output is provided
        r = envelope.check_action("respond", {})  # no output
        assert not r.blocked


# ═══════════════════════════════════════════════════════════════════════════
# PRIMITIVE 2: SEMANTIC DRIFT FENCING (SDF)
# ═══════════════════════════════════════════════════════════════════════════

class TestSemanticDriftFence:
    @pytest.fixture
    def fence(self):
        return SemanticDriftFence(
            task_description="Answer customer questions about order status and shipping",
            warn_threshold=0.35,
            block_threshold=0.60,
        )

    def test_on_topic_passes(self, fence):
        r = fence.check("Your order is being shipped and the status is confirmed.")
        assert not r.blocked

    def test_high_drift_blocked(self):
        """Deterministic test: custom embedder returns orthogonal vector."""
        call_count = 0

        def mock_embed(text: str) -> list[float]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Task centroid — first call during __init__
                return [1.0] + [0.0] * 127
            else:
                # Completely orthogonal output — maximum drift
                return [0.0] + [1.0] + [0.0] * 126

        fence = SemanticDriftFence(
            task_description="anything",
            block_threshold=0.5,
            embed_fn=mock_embed,
        )
        r = fence.check("totally off topic")
        assert r.blocked
        assert r.violation_type == ViolationType.DRIFT_DETECTED

    def test_drift_history_recorded(self, fence):
        fence.check("order status shipping")
        fence.check("something else entirely")
        assert len(fence.drift_history) == 2

    def test_reset_clears_history(self, fence):
        fence.check("test output")
        fence.reset()
        assert len(fence.drift_history) == 0

    def test_trend_insufficient_data(self, fence):
        fence.check("test one")
        assert fence._compute_trend() == "insufficient_data"

    def test_custom_embed_fn(self):
        # Custom embedder that always returns the same vector
        fence = SemanticDriftFence(
            task_description="anything",
            embed_fn=lambda text: [1.0] * 128,
        )
        r = fence.check("literally anything")
        assert not r.blocked  # Same vector → zero distance


# ═══════════════════════════════════════════════════════════════════════════
# PRIMITIVE 3: CHECKPOINT INTEGRITY ATTESTATION (CIA)
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckpointAttestor:
    @pytest.fixture
    def attestor(self):
        return CheckpointAttestor(signing_key=b"test-secret-key-123")

    def test_sign_and_verify_roundtrip(self, attestor):
        checkpoint = {"agent_state": {"memory": [1, 2, 3]}, "round": 5}
        signed = attestor.sign_checkpoint(checkpoint)
        assert "_nail_attestation" in signed
        verified = attestor.verify_checkpoint(signed)
        assert verified["agent_state"] == {"memory": [1, 2, 3]}
        assert verified["round"] == 5

    def test_tampered_checkpoint_raises(self, attestor):
        checkpoint = {"agent_state": {"memory": [1, 2, 3]}, "round": 5}
        signed = attestor.sign_checkpoint(checkpoint)
        # Tamper with the data
        signed["round"] = 999
        with pytest.raises(IntegrityError, match="signature mismatch"):
            attestor.verify_checkpoint(signed)

    def test_unsigned_checkpoint_rejected(self, attestor):
        with pytest.raises(IntegrityError, match="missing attestation"):
            attestor.verify_checkpoint({"state": "unsigned"})

    def test_unsigned_checkpoint_allowed_when_permissive(self):
        attestor = CheckpointAttestor(
            signing_key=b"key", reject_unsigned=False,
        )
        result = attestor.verify_checkpoint({"state": "unsigned"})
        assert result["state"] == "unsigned"

    def test_format_downgrade_detected(self, attestor):
        checkpoint = {"state": "data"}
        signed = attestor.sign_checkpoint(checkpoint)
        # Simulate format downgrade attack
        signed["_nail_attestation"]["serialization_format"] = "pickle"
        with pytest.raises(IntegrityError, match="format mismatch"):
            attestor.verify_checkpoint(signed)

    def test_check_returns_result_not_exception(self, attestor):
        # Tampered — should return blocked result, not raise
        r = attestor.check({"state": "unsigned"})
        assert r.blocked
        assert r.violation_type == ViolationType.INTEGRITY_FAILURE

    def test_check_passes_on_valid(self, attestor):
        signed = attestor.sign_checkpoint({"state": "valid"})
        r = attestor.check(signed)
        assert not r.blocked

    def test_attestation_metadata(self, attestor):
        signed = attestor.sign_checkpoint({"data": 1})
        att = signed["_nail_attestation"]
        assert att["algorithm"] == "hmac-sha256"
        assert att["serialization_format"] == "json_strict"
        assert att["timestamp"] > 0

    def test_different_keys_different_signatures(self):
        a1 = CheckpointAttestor(signing_key=b"key-1")
        a2 = CheckpointAttestor(signing_key=b"key-2")
        data = {"x": 1}
        s1 = a1.sign_checkpoint(data)
        with pytest.raises(IntegrityError):
            a2.verify_checkpoint(s1)


# ═══════════════════════════════════════════════════════════════════════════
# PRIMITIVE 4: CASCADING CIRCUIT BREAKERS (CCB)
# ═══════════════════════════════════════════════════════════════════════════

class TestCascadingCircuitBreaker:
    @pytest.fixture
    def breaker(self):
        return CascadingCircuitBreaker(
            resource_limits=ResourceLimits(
                max_tokens=1000,
                max_cost_usd=1.0,
                max_actions=10,
                max_errors=3,
            ),
            scope_boundary=ScopeBoundary(
                allowed_file_paths=["/data/", "/tmp/"],
                allowed_network_domains=["api.internal.com"],
                allowed_db_tables=["orders", "customers"],
            ),
        )

    # ── Resource checks ────────────────────────────────────

    def test_resource_within_limits(self, breaker):
        breaker.record_action(tokens=100, cost=0.01)
        r = breaker.check_resource()
        assert not r.blocked

    def test_token_limit_trips(self, breaker):
        breaker.record_action(tokens=1001)
        r = breaker.check_resource()
        assert r.blocked
        assert "Token limit" in r.reason

    def test_cost_limit_trips(self, breaker):
        breaker.record_action(cost=1.01)
        r = breaker.check_resource()
        assert r.blocked
        assert "Cost limit" in r.reason

    def test_action_limit_trips(self, breaker):
        for _ in range(11):
            breaker.record_action(tokens=10)
        r = breaker.check_resource()
        assert r.blocked
        assert "Action limit" in r.reason

    def test_error_limit_trips(self, breaker):
        for _ in range(4):
            breaker.record_action(error=True)
        r = breaker.check_resource()
        assert r.blocked
        assert "Error limit" in r.reason

    # ── Anomaly checks ────────────────────────────────────

    def test_anomaly_low_passes(self, breaker):
        r = breaker.check_anomaly(0.3)
        assert not r.blocked
        assert r.action == ContainmentAction.ALLOW

    def test_anomaly_warn_requires_approval(self, breaker):
        r = breaker.check_anomaly(0.75)
        assert not r.blocked
        assert r.action == ContainmentAction.REQUIRE_APPROVAL

    def test_anomaly_critical_terminates(self, breaker):
        r = breaker.check_anomaly(0.95)
        assert r.blocked
        assert r.action == ContainmentAction.TERMINATE

    # ── Scope checks ──────────────────────────────────────

    def test_file_scope_allowed(self, breaker):
        r = breaker.check_scope("read_file", {"path": "/data/customer/report.csv"})
        assert not r.blocked

    def test_file_scope_violation(self, breaker):
        r = breaker.check_scope("read_file", {"path": "/etc/passwd"})
        assert r.blocked
        assert r.violation_type == ViolationType.SCOPE_BOUNDARY

    def test_network_scope_allowed(self, breaker):
        r = breaker.check_scope("http_get", {"url": "https://api.internal.com/v1/data"})
        assert not r.blocked

    def test_network_scope_violation(self, breaker):
        r = breaker.check_scope("http_get", {"url": "https://evil.com/exfil"})
        assert r.blocked
        assert "evil.com" in r.reason

    def test_db_scope_allowed(self, breaker):
        r = breaker.check_scope("sql", {"query": "SELECT * FROM orders WHERE id=1"})
        assert not r.blocked

    def test_db_scope_violation(self, breaker):
        r = breaker.check_scope("sql", {"query": "SELECT * FROM secret_table"})
        assert r.blocked
        assert "secret_table" in r.reason

    # ── check_all cascades ────────────────────────────────

    def test_check_all_passes_clean(self, breaker):
        r = breaker.check_all(
            tool_name="read_file",
            args={"path": "/data/file.txt"},
            anomaly_score=0.1,
        )
        assert not r.blocked

    def test_check_all_stops_at_first_failure(self, breaker):
        breaker.record_action(tokens=2000)  # Over limit
        r = breaker.check_all(tool_name="read_file", args={"path": "/etc/passwd"})
        # Should stop at resource check, not reach scope check
        assert r.blocked
        assert r.layer == "CCB-resource"

    # ── Stats and logging ─────────────────────────────────

    def test_stats(self, breaker):
        breaker.record_action(tokens=100, cost=0.01)
        breaker.record_action(tokens=200, cost=0.02, error=True)
        stats = breaker.stats
        assert stats["tokens_used"] == 300
        assert stats["cost_usd"] == pytest.approx(0.03)
        assert stats["action_count"] == 2
        assert stats["error_count"] == 1

    def test_trip_log(self, breaker):
        breaker.record_action(tokens=2000)
        breaker.check_resource()
        assert len(breaker.trip_log) == 1

    def test_reset(self, breaker):
        breaker.record_action(tokens=500)
        breaker.reset()
        assert breaker.stats["tokens_used"] == 0
        assert breaker.stats["action_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# CONTAINMENT STACK
# ═══════════════════════════════════════════════════════════════════════════

class TestContainmentStack:
    @pytest.fixture
    def stack(self):
        return ContainmentStack(
            envelope=BehavioralEnvelope(
                name="test",
                allowed_tools=["search", "respond"],
                forbidden_tools=["execute_code"],
            ),
            drift_fence=SemanticDriftFence(
                task_description="customer support for orders",
            ),
            checkpoint_attestor=CheckpointAttestor(
                signing_key=b"test-key",
            ),
            circuit_breaker=CascadingCircuitBreaker(
                resource_limits=ResourceLimits(max_actions=10),
            ),
        )

    def test_check_action_allowed(self, stack):
        r = stack.check_action("search", {"query": "order status"})
        assert not r.blocked

    def test_check_action_blocked_by_envelope(self, stack):
        r = stack.check_action("execute_code", {"code": "rm -rf /"})
        assert r.blocked
        assert r.layer == "BEE"

    def test_check_action_blocked_by_circuit_breaker(self, stack):
        for _ in range(11):
            stack.breaker.record_action()
        r = stack.check_action("search", {})
        assert r.blocked
        assert "CCB" in r.layer

    def test_check_output(self, stack):
        r = stack.check_output("Your order is ready for pickup")
        assert not r.blocked

    def test_check_checkpoint_valid(self, stack):
        signed = stack.attestor.sign_checkpoint({"state": "good"})
        r = stack.check_checkpoint(signed)
        assert not r.blocked

    def test_check_checkpoint_tampered(self, stack):
        signed = stack.attestor.sign_checkpoint({"state": "good"})
        signed["state"] = "evil"
        r = stack.check_checkpoint(signed)
        assert r.blocked

    def test_minimum_viable_factory(self):
        stack = ContainmentStack.minimum_viable()
        assert stack.envelope is not None
        assert stack.breaker is not None
        assert stack.drift_fence is None
        assert stack.attestor is None

    def test_minimum_viable_blocks_code_execution(self):
        stack = ContainmentStack.minimum_viable()
        r = stack.check_action("execute_code", {"code": "print('hi')"})
        assert r.blocked

    def test_check_log_populated(self, stack):
        stack.check_action("search", {})
        stack.check_output("test output")
        assert len(stack.check_log) >= 2
