"""Tri-jurisdiction coverage: UK principles + UK-GDPR, US NIST AI RMF + state laws."""

from compliance import (
    DEFAULT_REGISTRY,
    Framework,
    Jurisdiction,
    Party,
    RiskTier,
    Status,
    WorkflowProfile,
    evaluate,
)


def test_registry_is_tri_jurisdiction():
    js = {c.jurisdiction for c in DEFAULT_REGISTRY.all()}
    assert js == {Jurisdiction.EU, Jurisdiction.UK, Jurisdiction.US}
    assert DEFAULT_REGISTRY.by_jurisdiction(Jurisdiction.UK)
    assert DEFAULT_REGISTRY.by_jurisdiction(Jurisdiction.US)


def test_us_backbone_is_nist_plus_state_law():
    us = DEFAULT_REGISTRY.by_jurisdiction(Jurisdiction.US)
    frameworks = {c.framework for c in us}
    assert Framework.NIST_AI_RMF in frameworks
    assert Framework.US_STATE_LAW in frameworks           # Colorado / NYC
    assert {"US-NIST-GOVERN", "US-CO-SB205", "US-NYC-LL144"} <= {c.control_id for c in us}


def test_uk_principles_and_gdpr_present():
    uk_ids = {c.control_id for c in DEFAULT_REGISTRY.by_jurisdiction(Jurisdiction.UK)}
    assert {"UK-PRIN-FAIRNESS", "UK-PRIN-CONTESTABILITY", "UK-GDPR-ART22"} <= uk_ids


def test_evaluate_across_all_three_jurisdictions():
    report = evaluate(WorkflowProfile(
        "hiring-agent", Party.DEPLOYER, RiskTier.HIGH,
        capabilities={"human_oversight", "operational_logging"},
        jurisdictions=(Jurisdiction.EU, Jurisdiction.UK, Jurisdiction.US),
    ))
    jset = {f.control.jurisdiction for f in report.findings}
    assert jset == {Jurisdiction.EU, Jurisdiction.UK, Jurisdiction.US}
    # A hiring tool with no bias audit trips both Colorado and NYC
    gaps = {f.control.control_id for f in report.gaps}
    assert "US-NYC-LL144" in gaps
    assert "US-CO-SB205" in gaps


def test_bias_audit_capability_satisfies_nyc_ll144():
    report = evaluate(WorkflowProfile(
        "hiring-agent", Party.DEPLOYER, RiskTier.HIGH,
        capabilities={"bias_audit", "consumer_notice"},
        jurisdictions=(Jurisdiction.US,),
    ))
    ll144 = next(f for f in report.findings if f.control.control_id == "US-NYC-LL144")
    assert ll144.status == Status.SATISFIED


def test_nist_functions_apply_at_any_risk_tier():
    report = evaluate(WorkflowProfile(
        "chatbot", Party.DEPLOYER, RiskTier.LIMITED,
        capabilities=set(), jurisdictions=(Jurisdiction.US,),
    ))
    ids = {f.control.control_id for f in report.findings}
    assert {"US-NIST-GOVERN", "US-NIST-MANAGE"} <= ids   # NIST applies regardless of tier
