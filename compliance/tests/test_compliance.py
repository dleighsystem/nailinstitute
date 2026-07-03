"""Tests for the compliance controls registry + gap engine (EU AI Act slice)."""

from compliance import (
    DEFAULT_REGISTRY,
    Jurisdiction,
    Party,
    RiskTier,
    Status,
    WorkflowProfile,
    evaluate,
)


# ── Registry ───────────────────────────────────────────────────────
def test_registry_has_eu_ai_act_controls():
    ids = {c.control_id for c in DEFAULT_REGISTRY.all()}
    assert {"EU-AIA-ART9", "EU-AIA-ART12", "EU-AIA-ART14", "EU-AIA-ART72"} <= ids
    eu = DEFAULT_REGISTRY.by_jurisdiction(Jurisdiction.EU)
    assert eu and all(c.jurisdiction == Jurisdiction.EU for c in eu)


def test_control_serialisation_round_trips_fields():
    art12 = DEFAULT_REGISTRY.get("EU-AIA-ART12")
    d = art12.to_dict()
    assert d["reference"] == "Article 12"
    assert "immutable_audit_log" in d["capabilities_required"]
    assert d["party"] == "both"


def test_scope_filters_by_party_and_risk_tier():
    deployer_high = DEFAULT_REGISTRY.for_scope(
        jurisdictions=[Jurisdiction.EU], party=Party.DEPLOYER, risk_tier=RiskTier.HIGH)
    ids = {c.control_id for c in deployer_high}
    assert "EU-AIA-ART26" in ids          # deployer obligation
    assert "EU-AIA-ART9" not in ids       # provider-only risk-management control


# ── Gap engine ─────────────────────────────────────────────────────
def test_gap_when_no_capabilities():
    report = evaluate(WorkflowProfile("bare", Party.DEPLOYER, RiskTier.HIGH))
    assert not report.compliant
    art26 = next(f for f in report.findings if f.control.control_id == "EU-AIA-ART26")
    assert art26.status == Status.GAP
    assert "human_oversight" in art26.missing_capabilities


def test_partial_then_satisfied():
    partial = evaluate(WorkflowProfile(
        "p", Party.DEPLOYER, RiskTier.HIGH, capabilities={"human_oversight"}))
    art26 = next(f for f in partial.findings if f.control.control_id == "EU-AIA-ART26")
    assert art26.status == Status.PARTIAL

    full = evaluate(WorkflowProfile(
        "f", Party.DEPLOYER, RiskTier.HIGH,
        capabilities={"human_oversight", "operational_logging", "post_market_monitoring"}))
    art26 = next(f for f in full.findings if f.control.control_id == "EU-AIA-ART26")
    assert art26.status == Status.SATISFIED


def test_prohibited_practice_is_a_violation():
    report = evaluate(WorkflowProfile(
        "banned", Party.PROVIDER, RiskTier.HIGH, capabilities={"social_scoring"}))
    art5 = next(f for f in report.findings if f.control.control_id == "EU-AIA-ART5")
    assert art5.status == Status.VIOLATION
    assert "social_scoring" in art5.triggered_prohibitions
    assert report.violations


def test_violations_and_gaps_sort_first():
    report = evaluate(WorkflowProfile(
        "mix", Party.PROVIDER, RiskTier.HIGH, capabilities={"subliminal_manipulation"}))
    assert report.findings[0].status == Status.VIOLATION   # violation ranked first


def test_summary_counts_and_compliant_flag():
    fully = {
        "adversarial_risk_testing", "data_provenance_controls", "pii_handling",
        "technical_documentation", "immutable_audit_log", "usage_instructions",
        "human_oversight", "kill_switch", "robustness_monitoring", "post_market_monitoring",
    }
    report = evaluate(WorkflowProfile("provider", Party.PROVIDER, RiskTier.HIGH, capabilities=fully))
    summary = report.summary()
    assert summary.get("violation", 0) == 0
    assert report.to_dict()["compliant"] == report.compliant
