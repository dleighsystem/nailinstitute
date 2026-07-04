"""Continuous compliance-drift monitor."""

from compliance import (
    ComplianceMonitor,
    Jurisdiction,
    Party,
    RiskTier,
    WorkflowProfile,
    capabilities_from_events,
)

_DEPLOYER_CAPS = {"human_oversight", "operational_logging", "post_market_monitoring"}


def _profile(caps):
    return WorkflowProfile("agent", Party.DEPLOYER, RiskTier.HIGH,
                           capabilities=frozenset(caps), jurisdictions=(Jurisdiction.EU,))


def test_no_drift_when_unchanged():
    mon = ComplianceMonitor()
    mon.set_baseline("acme", _profile(_DEPLOYER_CAPS))
    result = mon.check("acme", _profile(_DEPLOYER_CAPS))
    assert not result.has_drift
    assert result.drifts == []


def test_regression_when_capability_lost():
    fired = []
    mon = ComplianceMonitor(on_drift=lambda org, r: fired.append((org, r)))
    mon.set_baseline("acme", _profile(_DEPLOYER_CAPS))            # Art.26 satisfied
    # a later re-check where post_market_monitoring is no longer present
    result = mon.check("acme", _profile(_DEPLOYER_CAPS - {"post_market_monitoring"}))

    assert result.has_drift
    reg = next(d for d in result.drifts if d.control_id == "EU-AIA-ART26")
    assert reg.kind == "regression"
    assert reg.from_status == "satisfied"
    assert fired and fired[0][0] == "acme"                       # on_drift fired for the org


def test_resolution_when_capability_gained():
    mon = ComplianceMonitor()
    mon.set_baseline("acme", _profile(set()))                    # everything a gap
    result = mon.check("acme", _profile(_DEPLOYER_CAPS))
    resolved = [d for d in result.drifts if d.kind == "resolved"]
    assert any(d.control_id == "EU-AIA-ART26" for d in resolved)


def test_new_violation_drift():
    mon = ComplianceMonitor()
    mon.set_baseline("acme", _profile(_DEPLOYER_CAPS))
    result = mon.check("acme", _profile(_DEPLOYER_CAPS | {"social_scoring"}))
    viol = next(d for d in result.drifts if d.control_id == "EU-AIA-ART5")
    assert viol.kind == "new_violation"
    assert result.regressions   # violations count as regressions for alerting


def test_on_drift_not_called_without_drift():
    calls = []
    mon = ComplianceMonitor(on_drift=lambda org, r: calls.append(org))
    mon.set_baseline("acme", _profile(_DEPLOYER_CAPS))
    mon.check("acme", _profile(_DEPLOYER_CAPS))
    assert calls == []


def test_capabilities_from_fleet_event_kinds():
    caps = capabilities_from_events([
        "oversight.intervention", "flight_recorder.entry", "monitor.scan", "unmapped.kind"])
    assert caps == {"human_oversight", "immutable_audit_log", "post_market_monitoring"}


def test_drift_result_serialises():
    mon = ComplianceMonitor()
    mon.set_baseline("acme", _profile(_DEPLOYER_CAPS))
    result = mon.check("acme", _profile(_DEPLOYER_CAPS - {"human_oversight"}))
    d = result.to_dict()
    assert d["org"] == "acme" and d["has_drift"] is True
    assert d["report"]["profile"] == "agent"
