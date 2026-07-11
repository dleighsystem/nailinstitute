"""Continuous compliance drift over fleet telemetry (fleet + nail-compliance bridge)."""

import json

import pytest

compliance = pytest.importorskip("compliance")

from compliance import (
    ComplianceControl,
    ComplianceRegistry,
    Jurisdiction,
    Framework,
    Party,
    RiskTier,
)

from fleet.alerts import WebhookKillSwitch
from fleet.compliance import (
    FleetComplianceWatcher,
    OrgComplianceSpec,
    killswitch_on_drift,
)
from fleet.event import Event
from fleet.http_client import FleetClient
from fleet.http_server import IngestServer
from fleet.ingest import Ingest
from fleet.retention import Retention
from fleet.store import Store


# A tiny fixed registry so tests don't depend on DEFAULT_REGISTRY contents.
REGISTRY = ComplianceRegistry([
    ComplianceControl(
        control_id="TEST-OVERSIGHT",
        jurisdiction=Jurisdiction.EU,
        framework=Framework.EU_AI_ACT,
        reference="Test Art. 14",
        title="Human oversight with interruption",
        party=Party.DEPLOYER,
        requirement="t", guidance="t",
        capabilities_required=("human_oversight", "kill_switch"),
    ),
    ComplianceControl(
        control_id="TEST-PROHIBITED",
        jurisdiction=Jurisdiction.EU,
        framework=Framework.EU_AI_ACT,
        reference="Test Art. 5",
        title="No social scoring",
        party=Party.DEPLOYER,
        requirement="t", guidance="t",
        prohibited_capabilities=("social_scoring",),
        risk_tiers=(RiskTier.ANY,),
    ),
])

SPEC = OrgComplianceSpec(jurisdictions=("eu",))


def _seeded(ts: float = 100.0) -> Store:
    """acme emits oversight + kill-switch evidence; globex emits nothing useful."""
    store = Store()
    ing = Ingest(store)
    ing.record(Event(agent_id="a1", org="acme", kind="oversight.intervention", ts=ts))
    ing.record(Event(agent_id="a1", org="acme", kind="killswitch.fired", ts=ts + 1))
    ing.record(Event(agent_id="b1", org="globex", kind="heartbeat", ts=ts + 2))
    return store


def test_capabilities_derived_per_org():
    w = FleetComplianceWatcher(_seeded(), registry=REGISTRY, default_spec=SPEC)
    assert set(w.profile("acme").capabilities) == {"human_oversight", "kill_switch"}
    assert set(w.profile("globex").capabilities) == set()


def test_point_in_time_report_is_tenant_isolated():
    w = FleetComplianceWatcher(_seeded(), registry=REGISTRY, default_spec=SPEC)
    assert w.report("acme").compliant
    gaps = w.report("globex").gaps
    assert [f.control.control_id for f in gaps] == ["TEST-OVERSIGHT"]


def test_evidence_expiry_is_a_regression_and_fires_kill_switch():
    store = _seeded(ts=100.0)
    fired: list[tuple] = []
    w = FleetComplianceWatcher(
        store, registry=REGISTRY, default_spec=SPEC,
        kill_switch=lambda org, pathology, count: fired.append((org, pathology, count)),
    )
    assert w.baseline("acme").compliant
    assert not w.check("acme").has_drift and not fired

    # The oversight/kill-switch evidence ages out of the telemetry window.
    Retention(store, ttl_s=10.0).apply(now=1000.0)
    res = w.check("acme")

    assert [d.kind for d in res.drifts] == ["regression"]
    assert res.drifts[0].control_id == "TEST-OVERSIGHT"
    assert fired == [("acme", "compliance.regression:TEST-OVERSIGHT", 1)]


def test_prohibited_capability_via_spec_is_new_violation():
    w = FleetComplianceWatcher(_seeded(), registry=REGISTRY, default_spec=SPEC)
    w.baseline("acme")
    w.specs["acme"] = OrgComplianceSpec(
        jurisdictions=("eu",), declared_capabilities=frozenset({"social_scoring"}))
    res = w.check("acme")
    assert any(d.kind == "new_violation" and d.control_id == "TEST-PROHIBITED"
               for d in res.drifts)


def test_failed_webhook_kill_switch_does_not_swallow_drift():
    store = _seeded()

    def poster(url, data, headers, timeout):
        raise OSError("cohort endpoint down")

    w = FleetComplianceWatcher(
        store, registry=REGISTRY, default_spec=SPEC,
        kill_switch=WebhookKillSwitch("http://kill.example/incident", poster=poster),
    )
    w.baseline("acme")
    Retention(store, ttl_s=10.0).apply(now=1000.0)
    res = w.check("acme")  # must not raise
    assert res.has_drift and res.regressions


def test_killswitch_on_drift_only_escalates_regressions():
    fired = []
    on_drift = killswitch_on_drift(lambda *a: fired.append(a))

    class _D:  # duck-typed ComplianceDrift
        def __init__(self, kind, control_id):
            self.kind, self.control_id = kind, control_id

    class _R:
        drifts = [_D("resolved", "TEST-A"), _D("new_gap", "TEST-B"),
                  _D("regression", "TEST-C")]

    on_drift("acme", _R())
    assert fired == [("acme", "compliance.regression:TEST-C", 1)]


def test_baselines_persist_across_watchers():
    store = _seeded()
    w1 = FleetComplianceWatcher(store, registry=REGISTRY, default_spec=SPEC)
    w1.baseline("acme")
    saved = json.dumps(w1.monitor().export_baselines())

    Retention(store, ttl_s=10.0).apply(now=1000.0)
    w2 = FleetComplianceWatcher(store, registry=REGISTRY, default_spec=SPEC)
    w2.monitor().import_baselines(json.loads(saved))
    assert [d.kind for d in w2.check("acme").drifts] == ["regression"]


def test_check_all_covers_every_org():
    w = FleetComplianceWatcher(_seeded(), registry=REGISTRY, default_spec=SPEC)
    results = w.check_all()
    assert set(results) == {"acme", "globex"}
    # globex was never certified: its unmet control surfaces as a new gap.
    assert any(d.kind == "new_gap" for d in results["globex"].drifts)


# ── HTTP surface ────────────────────────────────────────────────────


def test_http_compliance_stateless_without_watcher():
    store = _seeded()
    srv = IngestServer(store, host="127.0.0.1", port=0)
    srv.start()
    try:
        body = FleetClient(srv.url).compliance(org="acme")
    finally:
        srv.stop()
    entry = body["orgs"]["acme"]
    assert entry["drift"] is None
    assert entry["report"]["profile"] == "acme"


def test_http_compliance_live_drift_with_watcher():
    store = _seeded()
    fired = []
    watcher = FleetComplianceWatcher(
        store, registry=REGISTRY, default_spec=SPEC,
        kill_switch=lambda *a: fired.append(a),
    )
    watcher.baseline("acme")
    Retention(store, ttl_s=10.0).apply(now=1000.0)

    srv = IngestServer(store, host="127.0.0.1", port=0,
                       compliance_watcher=watcher)
    srv.start()
    try:
        body = FleetClient(srv.url, org="acme").compliance()
    finally:
        srv.stop()
    drift = body["orgs"]["acme"]["drift"]
    assert drift["has_drift"] is True
    assert drift["drifts"][0]["control_id"] == "TEST-OVERSIGHT"
    assert fired  # polling the live plane escalated the regression


# ── CLI (cron-able live signal) ─────────────────────────────────────


def test_cli_baseline_then_drift_check(tmp_path, capsys):
    from fleet.cli import main

    db = str(tmp_path / "fleet.sqlite")
    bfile = str(tmp_path / "baselines.json")
    ing = Ingest(Store(db))
    ing.record(Event(agent_id="a1", org="acme", kind="oversight.intervention", ts=100.0))
    ing.record(Event(agent_id="a1", org="acme", kind="killswitch.fired", ts=101.0))
    ing.record(Event(agent_id="a1", org="acme", kind="flight_recorder.entry", ts=102.0))
    ing.record(Event(agent_id="a1", org="acme", kind="disclosure.shown", ts=103.0))

    # NOTE: the CLI uses DEFAULT_REGISTRY, so declare the remaining deployer caps.
    declares = ["--declare", "operational_logging",
                "--declare", "post_market_monitoring"]
    args = ["--db", db, "compliance", "--org", "acme",
            "--jurisdictions", "eu", "--baseline-file", bfile] + declares

    assert main(args + ["--baseline"]) == 0
    baseline = json.loads(capsys.readouterr().out)
    assert baseline["orgs"]["acme"]["baseline"]["compliant"] is True

    # Evidence expires; the cron re-check must flag drift and exit 4.
    Retention(Store(db), ttl_s=10.0).apply(now=1000.0)
    assert main(args + ["--exit-nonzero-on-drift"]) == 4
    checked = json.loads(capsys.readouterr().out)
    kinds = {d["kind"] for d in checked["orgs"]["acme"]["drifts"]}
    assert "regression" in kinds
