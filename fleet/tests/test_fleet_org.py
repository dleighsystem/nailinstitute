"""Multi-tenant (per-organisation) scoping in the fleet telemetry store."""

import sqlite3

from fleet.event import Event
from fleet.ingest import Ingest
from fleet.query import Query
from fleet.rollup import RollUp
from fleet.store import Store


def _seeded():
    store = Store()
    ing = Ingest(store)
    ing.record(Event(agent_id="a1", org="acme", kind="shield.block", ts=100.0))
    ing.record(Event(agent_id="a2", org="acme", kind="shield.block", ts=101.0))
    ing.record(Event(agent_id="b1", org="globex", kind="shield.block", ts=102.0))
    return store


def test_query_events_scoped_by_org():
    store = _seeded()
    assert len(store.query_events(org="acme")) == 2
    assert len(store.query_events(org="globex")) == 1
    assert {e.org for e in store.query_events(org="acme")} == {"acme"}


def test_list_agents_scoped_by_org():
    store = _seeded()
    assert {a["agent_id"] for a in store.list_agents(org="acme")} == {"a1", "a2"}
    assert all(a["org"] == "acme" for a in store.list_agents(org="acme"))
    assert {a["agent_id"] for a in store.list_agents(org="globex")} == {"b1"}


def test_list_orgs_rollup():
    orgs = {o["org"]: o for o in _seeded().list_orgs()}
    assert orgs["acme"]["agents"] == 2 and orgs["acme"]["events"] == 2
    assert orgs["globex"]["agents"] == 1 and orgs["globex"]["events"] == 1


def test_rollup_and_query_by_org():
    store = _seeded()
    assert RollUp(store).by_org() == {"acme": 2, "globex": 1}
    assert Query(store).count(org="acme") == 2
    assert Query(store).count(org="globex") == 1
    assert store.event_count(org="acme") == 2


def test_agent_org_is_immutable_on_reingest():
    store = Store()
    ing = Ingest(store)
    ing.record(Event(agent_id="a1", org="acme", kind="k", ts=1.0))
    ing.record(Event(agent_id="a1", org="", kind="k", ts=2.0))  # later event omits org
    agents = {a["agent_id"]: a for a in store.list_agents()}
    assert agents["a1"]["org"] == "acme"   # org fixed at registration


def test_default_org_is_empty_bucket():
    store = Store()
    Ingest(store).record(Event(agent_id="a", kind="k", ts=1.0))
    assert store.query_events(org="")[0].agent_id == "a"


def test_org_round_trips_through_serialisation():
    ev = Event(agent_id="a", org="acme", kind="k")
    assert Event.from_dict(ev.to_dict()).org == "acme"
    assert Event.from_json(ev.to_json()).org == "acme"


def test_migration_adds_org_to_legacy_db(tmp_path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE events (event_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
            kind TEXT NOT NULL, severity TEXT NOT NULL, ts REAL NOT NULL, attrs TEXT NOT NULL);
        CREATE TABLE agents (agent_id TEXT PRIMARY KEY, first_seen REAL NOT NULL,
            last_seen REAL NOT NULL, meta TEXT NOT NULL DEFAULT '{}');
        """
    )
    conn.execute("INSERT INTO events VALUES ('e1','a1','k','info',1.0,'{}')")
    conn.execute("INSERT INTO agents VALUES ('a1',1.0,1.0,'{}')")
    conn.commit()
    conn.close()

    store = Store(db)  # opens legacy DB -> _migrate adds the org column + indexes
    events = store.query_events()
    assert len(events) == 1 and events[0].org == ""      # legacy rows -> '' bucket
    assert store.list_agents()[0]["org"] == ""
    # org-scoped inserts work post-migration
    Ingest(store).record(Event(agent_id="a2", org="acme", kind="k", ts=2.0))
    assert len(store.query_events(org="acme")) == 1
