"""Per-organisation pathology alerting + kill-switch."""

from fleet.alerts import OrgPathologyAlerter
from fleet.event import Event
from fleet.ingest import Ingest
from fleet.store import Store


def _starvation(agent_id, org, ts):
    return Event(agent_id=agent_id, org=org, kind="tool.retrieval", ts=ts,
                 attrs={"loaded_tools": ["crm_search"], "required_tools": ["approval_gate"]})


def _seeded():
    store = Store()
    ing = Ingest(store)
    # acme: 2 retrieval-starvation findings; globex: 1
    ing.record(_starvation("a1", "acme", 1.0))
    ing.record(_starvation("a2", "acme", 2.0))
    ing.record(_starvation("b1", "globex", 3.0))
    return store


def test_fires_when_org_crosses_threshold():
    alerts = OrgPathologyAlerter(_seeded(), default_threshold=2).evaluate()
    fired = {(a.org, a.pathology): a for a in alerts}
    assert ("acme", "tool_retrieval_manipulation") in fired      # count 2 >= 2
    assert ("globex", "tool_retrieval_manipulation") not in fired  # count 1 < 2
    assert fired[("acme", "tool_retrieval_manipulation")].count == 2


def test_kill_switch_invoked_per_breaching_tenant():
    calls = []
    alerter = OrgPathologyAlerter(
        _seeded(), default_threshold=1,
        kill_switch=lambda org, pathology, count: calls.append((org, pathology, count)),
    )
    alerts = alerter.evaluate()
    assert {a.org for a in alerts} == {"acme", "globex"}
    assert all(a.killed for a in alerts)
    assert ("acme", "tool_retrieval_manipulation", 2) in calls
    assert ("globex", "tool_retrieval_manipulation", 1) in calls


def test_per_pathology_threshold_and_tenant_scope():
    alerter = OrgPathologyAlerter(
        _seeded(), thresholds={"tool_retrieval_manipulation": 5}, default_threshold=1)
    assert alerter.evaluate() == []                     # nobody hits 5
    # org-scoped evaluation only considers that tenant
    acme_only = OrgPathologyAlerter(_seeded(), default_threshold=1).evaluate(org="acme")
    assert {a.org for a in acme_only} == {"acme"}


def test_kill_switch_failure_still_reports_alert():
    def boom(org, pathology, count):
        raise RuntimeError("escalation offline")

    alerts = OrgPathologyAlerter(_seeded(), default_threshold=1, kill_switch=boom).evaluate()
    acme = next(a for a in alerts if a.org == "acme")
    assert acme.killed is False           # kill-switch failed...
    assert acme.count == 2                # ...but the alert is still surfaced


def test_no_alerts_on_benign_fleet():
    store = Store()
    Ingest(store).record(Event(agent_id="a", org="acme", kind="heartbeat", attrs={}))
    assert OrgPathologyAlerter(store, default_threshold=1).evaluate() == []
