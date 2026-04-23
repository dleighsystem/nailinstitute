from __future__ import annotations

import json
import time

import pytest

from fleet import (
    Event, Severity, Store, Ingest, RollUp, Heartbeat,
)


# ── Event ────────────────────────────────────────────────────────────
def test_event_autofills_ts_and_id():
    e = Event(agent_id="a", kind="x.y")
    assert e.ts > 0
    assert len(e.event_id) == 32  # uuid4 hex
    assert e.severity == "info"


def test_event_normalises_unknown_severity():
    e = Event(agent_id="a", kind="x.y", severity="spicy")
    assert e.severity == "info"


def test_event_json_roundtrip():
    e = Event(agent_id="a", kind="x.y", severity="warn",
              attrs={"verdict": "hold", "risk": 0.7})
    e2 = Event.from_json(e.to_json())
    assert e2.agent_id == "a"
    assert e2.attrs["verdict"] == "hold"
    assert e2.event_id == e.event_id


# ── Store ────────────────────────────────────────────────────────────
def test_store_in_memory_persists_across_calls():
    s = Store(":memory:")
    s.insert_event(Event(agent_id="a", kind="x"))
    s.insert_event(Event(agent_id="b", kind="x"))
    assert s.event_count() == 2


def test_store_file_backed(tmp_path):
    p = tmp_path / "f.sqlite"
    s1 = Store(p); s1.insert_event(Event(agent_id="a", kind="x")); s1.close()
    s2 = Store(p)
    assert s2.event_count() == 1


def test_store_query_filters():
    s = Store(":memory:")
    now = time.time()
    s.insert_event(Event(agent_id="a", kind="shield.block", ts=now - 100))
    s.insert_event(Event(agent_id="a", kind="arsenal.deny", ts=now - 50))
    s.insert_event(Event(agent_id="b", kind="shield.block", ts=now))
    assert len(s.query_events(agent_id="a")) == 2
    assert len(s.query_events(kind="shield.block")) == 2
    assert len(s.query_events(since=now - 60)) == 2


def test_store_query_order_and_limit():
    s = Store(":memory:")
    for i in range(5):
        s.insert_event(Event(agent_id="a", kind="k", ts=float(i + 1)))
    desc = s.query_events(order="desc", limit=2)
    assert [e.ts for e in desc] == [5.0, 4.0]


# ── Ingest ───────────────────────────────────────────────────────────
def test_ingest_upserts_agent():
    s = Store(":memory:")
    Ingest(s).record(Event(agent_id="a", kind="x"))
    agents = s.list_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "a"


def test_ingest_record_many():
    s = Store(":memory:")
    n = Ingest(s).record_many(
        Event(agent_id=f"a{i}", kind="x") for i in range(3)
    )
    assert n == 3
    assert s.event_count() == 3


# ── Heartbeat ────────────────────────────────────────────────────────
def test_heartbeat_marks_live_within_window():
    s = Store(":memory:")
    hb = Heartbeat(s, live_window_s=10)
    hb.beat("a", ts=time.time())
    statuses = hb.status()
    assert len(statuses) == 1
    assert statuses[0].is_live


def test_heartbeat_marks_stale_outside_window():
    s = Store(":memory:")
    hb = Heartbeat(s, live_window_s=10)
    hb.beat("a", ts=time.time() - 100)
    statuses = hb.status()
    assert not statuses[0].is_live


def test_heartbeat_meta_preserved():
    s = Store(":memory:")
    hb = Heartbeat(s)
    hb.beat("a", meta={"role": "refund"})
    statuses = hb.status()
    assert statuses[0].meta == {"role": "refund"}


# ── RollUp ───────────────────────────────────────────────────────────
def _seed():
    s = Store(":memory:")
    ing = Ingest(s)
    ing.record(Event(agent_id="a", kind="shield.block", severity="warn"))
    ing.record(Event(agent_id="a", kind="arsenal.deny", severity="error",
                     attrs={"tool": "refunds.issue"}))
    ing.record(Event(agent_id="a", kind="arsenal.deny", severity="error",
                     attrs={"tool": "refunds.issue"}))
    ing.record(Event(agent_id="b", kind="arsenal.deny", severity="error",
                     attrs={"tool": "email.send"}))
    ing.record(Event(agent_id="b", kind="foresight.verdict", severity="info",
                     attrs={"verdict": "hold", "risk": 0.6}))
    ing.record(Event(agent_id="c", kind="foresight.verdict", severity="info",
                     attrs={"verdict": "allow", "risk": 0.1}))
    return s


def test_rollup_by_agent():
    r = RollUp(_seed())
    assert r.by_agent() == {"a": 3, "b": 2, "c": 1}


def test_rollup_by_kind_filtered():
    r = RollUp(_seed())
    assert r.by_kind(severity="error") == {"arsenal.deny": 3}


def test_rollup_top_tools():
    r = RollUp(_seed())
    top = r.top_tools(kind="arsenal.deny")
    assert top[0] == ("refunds.issue", 2)
    assert ("email.send", 1) in top


def test_rollup_verdict_distribution():
    r = RollUp(_seed())
    d = r.verdict_distribution(kind="foresight.verdict")
    assert d == {"hold": 1, "allow": 1}


def test_rollup_time_window_buckets():
    s = Store(":memory:")
    ing = Ingest(s)
    base = 1_000_000.0
    for i in range(5):
        ing.record(Event(agent_id="a", kind="k", ts=base + i * 30))
    buckets = RollUp(s).time_window(since=base, until=base + 200, bucket_s=60)
    # ts 0,30 -> bucket 0; ts 60,90 -> bucket 1; ts 120 -> bucket 2
    assert buckets == {0: 2, 1: 2, 2: 1}


def test_rollup_agent_summary():
    r = RollUp(_seed())
    a = r.agent_summary("a")
    assert a.n_events == 3
    assert a.by_kind == {"shield.block": 1, "arsenal.deny": 2}
    assert a.by_severity == {"warn": 1, "error": 2}


def test_rollup_overview():
    r = RollUp(_seed())
    o = r.overview()
    assert o["n_events"] == 6
    assert o["n_agents"] == 3
    assert o["by_severity"]["error"] == 3


# ── CLI ──────────────────────────────────────────────────────────────
def test_cli_ingest_then_rollup(tmp_path, capsys):
    from fleet.cli import main as cli
    db = str(tmp_path / "f.sqlite")
    ev = json.dumps({"agent_id": "a", "kind": "shield.block",
                     "severity": "warn"})
    rc = cli(["--db", db, "ingest", "--event", ev])
    assert rc == 0
    capsys.readouterr()  # drain

    rc = cli(["--db", db, "roll-up", "--by", "agent"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"a": 1}


def test_cli_agents_lists_after_ingest(tmp_path, capsys):
    from fleet.cli import main as cli
    db = str(tmp_path / "f.sqlite")
    cli(["--db", db, "ingest", "--event",
         json.dumps({"agent_id": "bot-1", "kind": "x"})])
    capsys.readouterr()
    rc = cli(["--db", db, "agents"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1
    assert out[0]["agent_id"] == "bot-1"
    assert out[0]["is_live"] is True


def test_cli_tail_filters(tmp_path, capsys):
    from fleet.cli import main as cli
    db = str(tmp_path / "f.sqlite")
    for ev in [
        {"agent_id": "a", "kind": "k1"},
        {"agent_id": "a", "kind": "k2"},
        {"agent_id": "b", "kind": "k1"},
    ]:
        cli(["--db", db, "ingest", "--event", json.dumps(ev)])
    capsys.readouterr()
    rc = cli(["--db", db, "tail", "--kind", "k1"])
    assert rc == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 2
    for l in lines:
        assert json.loads(l)["kind"] == "k1"


def test_cli_beat(tmp_path, capsys):
    from fleet.cli import main as cli
    db = str(tmp_path / "f.sqlite")
    rc = cli(["--db", db, "beat", "bot-2", "--meta", '{"role":"trading"}'])
    assert rc == 0
    capsys.readouterr()
    rc = cli(["--db", db, "agents"])
    out = json.loads(capsys.readouterr().out)
    assert out[0]["meta"] == {"role": "trading"}
