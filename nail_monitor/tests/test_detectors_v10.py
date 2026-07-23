"""Tests for v10 credential/egress detectors (OpenAI × Hugging Face chain)."""
from __future__ import annotations

from nail_monitor.detectors_v10 import (
    CredentialAccessVelocityDetector,
    CredentialHarvestingDetector,
    CredentialOverreachDetector,
    EgressAllowlistDetector,
)
from nail_monitor.types import Observation, PathologyType, Severity


def _obs(metadata: dict, output: str = "") -> Observation:
    return Observation(agent_name="agent", output=output, metadata=metadata)


# ── CredentialHarvestingDetector ─────────────────────────────────────────────

def test_harvest_read_then_exfiltrated_is_critical():
    det = CredentialHarvestingDetector()
    assert det.observe(_obs({"secret_reads": {"AWS_SECRET_ACCESS_KEY": "wJalrXUtabc123EXAMPLEKEY"}})) is None
    alert = det.observe(_obs({"tool_calls": [{"name": "http_post", "args": {"body": "k=wJalrXUtabc123EXAMPLEKEY"}}]}))
    assert alert is not None
    assert alert.severity == Severity.CRITICAL
    assert alert.pathology == PathologyType.CREDENTIAL_HARVESTING


def test_harvest_raw_secret_in_output_is_critical():
    det = CredentialHarvestingDetector()
    alert = det.observe(_obs({}, output="here is the key hf_abcdefghijklmnopqrstuvwxyz0123456789"))
    assert alert is not None and alert.severity == Severity.CRITICAL


def test_harvest_bulk_enumeration_is_warning():
    det = CredentialHarvestingDetector()
    alert = det.observe(_obs({"secret_reads": ["AWS_SECRET", "DB_PASS", "HF_TOKEN", "GH_TOKEN"]}))
    assert alert is not None and alert.severity == Severity.WARNING


def test_harvest_name_only_mention_is_silent():
    det = CredentialHarvestingDetector()
    alert = det.observe(_obs({"secret_reads": ["AWS_SECRET_ACCESS_KEY"]},
                             output="I will read AWS_SECRET_ACCESS_KEY"))
    assert alert is None


# ── EgressAllowlistDetector ──────────────────────────────────────────────────

def test_egress_off_allowlist_is_flagged():
    det = EgressAllowlistDetector(allowed_hosts=["huggingface.co"])
    alert = det.observe(_obs({"egress": ["https://evil.example.com/x"]}))
    assert alert is not None
    assert alert.pathology == PathologyType.NOVEL_EGRESS


def test_egress_allowlisted_subdomain_is_silent():
    det = EgressAllowlistDetector(allowed_hosts=["huggingface.co"])
    assert det.observe(_obs({"egress": ["https://api.huggingface.co/models"]})) is None


def test_egress_exfil_sink_is_critical():
    det = EgressAllowlistDetector(allowed_hosts=["huggingface.co"])
    alert = det.observe(_obs({"egress": [{"url": "https://webhook.site/abc", "body": "data"}]}))
    assert alert is not None and alert.severity == Severity.CRITICAL


def test_egress_silent_without_policy():
    det = EgressAllowlistDetector()  # no allowlist
    assert det.observe(_obs({"egress": ["https://anywhere.example.com"]})) is None


# ── CredentialOverreachDetector ──────────────────────────────────────────────

def test_overreach_excess_scope_is_flagged():
    det = CredentialOverreachDetector(authorized_scopes=["read"])
    alert = det.observe(_obs({"credential_scopes": ["s3:*", "iam", "admin"], "action_scope": "iam"}))
    assert alert is not None
    assert alert.severity == Severity.CRITICAL
    assert alert.pathology == PathologyType.CREDENTIAL_OVERREACH


def test_overreach_within_authority_is_silent():
    det = CredentialOverreachDetector(authorized_scopes=["read", "s3:getobject:eval"])
    assert det.observe(_obs({"credential_scopes": ["read"]})) is None


def test_overreach_silent_without_policy():
    det = CredentialOverreachDetector()  # no authorized scopes
    assert det.observe(_obs({"credential_scopes": ["admin"]})) is None


# ── CredentialAccessVelocityDetector ─────────────────────────────────────────

def test_velocity_action_burst_is_critical():
    det = CredentialAccessVelocityDetector(max_actions=5, max_distinct_resources=99)
    alert = None
    for i in range(5):
        alert = det.observe(_obs({"sensitive_action": True, "host": "10.0.0.1"}))
    assert alert is not None and alert.pathology == PathologyType.LATERAL_MOVEMENT


def test_velocity_resource_fanout_is_critical():
    det = CredentialAccessVelocityDetector(max_actions=99, max_distinct_resources=4)
    alert = None
    for i in range(4):
        alert = det.observe(_obs({"sensitive_action": True, "host": f"10.0.0.{i}"}))
    assert alert is not None and alert.pathology == PathologyType.LATERAL_MOVEMENT


def test_velocity_ignores_non_sensitive_turns():
    det = CredentialAccessVelocityDetector(max_actions=2, max_distinct_resources=99)
    assert det.observe(_obs({}, output="just thinking")) is None
    assert det.observe(_obs({}, output="still thinking")) is None
