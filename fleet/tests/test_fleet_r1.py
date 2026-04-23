"""Tests for fleet/ R1 — retention, signing, HTTP server/client, CLI."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from fleet import (
    Event, Store, Ingest, Retention, IngestServer, FleetClient, FleetClientError,
    HAS_ARSENAL, sign_event, verify_envelope,
)


# ── retention ───────────────────────────────────────────────────────
def test_retention_ttl_drops_old_events():
    s = Store(":memory:")
    ing = Ingest(s)
    now = time.time()
    ing.record(Event(agent_id="a", kind="k", ts=now - 1000))
    ing.record(Event(agent_id="a", kind="k", ts=now - 50))
    ing.record(Event(agent_id="a", kind="k", ts=now))
    rep = Retention(s, ttl_s=100).apply(now=now)
    assert rep.deleted_by_ttl == 1
    assert s.event_count() == 2


def test_retention_max_rows_keeps_newest():
    s = Store(":memory:")
    ing = Ingest(s)
    for i in range(5):
        ing.record(Event(agent_id="a", kind="k", ts=float(i + 1)))
    rep = Retention(s, max_rows=2).apply()
    assert rep.deleted_by_cap == 3
    remaining = s.query_events(order="asc")
    assert [e.ts for e in remaining] == [4.0, 5.0]


def test_retention_prunes_orphan_agents():
    s = Store(":memory:")
    ing = Ingest(s)
    ing.record(Event(agent_id="a", kind="k", ts=1.0))
    ing.record(Event(agent_id="b", kind="k", ts=time.time()))
    Retention(s, ttl_s=60).apply()
    agents = [a["agent_id"] for a in s.list_agents()]
    assert agents == ["b"]


def test_retention_no_op_when_disabled():
    s = Store(":memory:")
    Ingest(s).record(Event(agent_id="a", kind="k"))
    rep = Retention(s).apply()
    assert rep.total == 0
    assert s.event_count() == 1


# ── signing (skip if arsenal missing) ──────────────────────────────
arsenal_required = pytest.mark.skipif(
    not HAS_ARSENAL, reason="arsenal package not importable")


@arsenal_required
def test_sign_and_verify_roundtrip(tmp_path):
    from arsenal.keys import generate_keypair
    key = generate_keypair(name="t1", directory=tmp_path)
    ev = Event(agent_id="a", kind="x", attrs={"v": 1})
    env = sign_event(ev, key=key)
    assert "event" in env and "sig" in env
    ev2 = verify_envelope(env, trusted_keys=[key])
    assert ev2.event_id == ev.event_id
    assert ev2.attrs == {"v": 1}


@arsenal_required
def test_verify_rejects_tampered_payload(tmp_path):
    from arsenal.keys import generate_keypair
    from arsenal.errors import InvalidSignature
    key = generate_keypair(name="t2", directory=tmp_path)
    env = sign_event(Event(agent_id="a", kind="x"), key=key)
    env["event"]["agent_id"] = "evil"
    with pytest.raises(InvalidSignature):
        verify_envelope(env, trusted_keys=[key])


@arsenal_required
def test_verify_rejects_unknown_kid(tmp_path):
    from arsenal.keys import generate_keypair
    from arsenal.errors import InvalidSignature
    key_a = generate_keypair(name="ta", directory=tmp_path)
    key_b = generate_keypair(name="tb", directory=tmp_path)
    env = sign_event(Event(agent_id="a", kind="x"), key=key_a)
    with pytest.raises(InvalidSignature):
        verify_envelope(env, trusted_keys=[key_b])


# ── HTTP server + client ───────────────────────────────────────────
@pytest.fixture
def http_server():
    s = Store(":memory:")
    srv = IngestServer(s, host="127.0.0.1", port=0)
    srv.start()
    yield srv, s
    srv.stop()


def test_http_healthz(http_server):
    srv, _ = http_server
    c = FleetClient(srv.url)
    assert c.healthz() == {"ok": True}


def test_http_push_unsigned(http_server):
    srv, store = http_server
    c = FleetClient(srv.url, default_agent_id="bot-1")
    out = c.emit("shield.block", severity="warn", attrs={"reason": "test"})
    assert out["ok"] is True
    assert store.event_count() == 1
    ev = store.query_events()[0]
    assert ev.agent_id == "bot-1"
    assert ev.kind == "shield.block"
    assert ev.attrs == {"reason": "test"}


def test_http_push_batch(http_server):
    srv, store = http_server
    c = FleetClient(srv.url)
    out = c.push_many([
        Event(agent_id="a", kind="k1"),
        Event(agent_id="a", kind="k2"),
        Event(agent_id="b", kind="k1"),
    ])
    assert out["accepted"] == 3
    assert out["rejected"] == []
    assert store.event_count() == 3


def test_http_overview_endpoint(http_server):
    srv, _ = http_server
    c = FleetClient(srv.url)
    c.push(Event(agent_id="a", kind="k", severity="error"))
    o = c.overview()
    assert o["n_events"] == 1
    assert o["by_severity"] == {"error": 1}


def test_http_rejects_bad_json(http_server):
    srv, _ = http_server
    import urllib.request, urllib.error
    req = urllib.request.Request(
        srv.url + "/v1/events", data=b"not json",
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=2)
    assert ei.value.code == 400


def test_http_unknown_path_404(http_server):
    srv, _ = http_server
    import urllib.error
    c = FleetClient(srv.url)
    with pytest.raises(FleetClientError):
        c._get("/no/such/path")


# ── HTTP signed-only mode ──────────────────────────────────────────
@arsenal_required
def test_http_signed_only_accepts_signed(tmp_path):
    from arsenal.keys import generate_keypair
    key = generate_keypair(name="srv", directory=tmp_path)
    s = Store(":memory:")
    srv = IngestServer(s, host="127.0.0.1", port=0, trusted_keys=[key])
    srv.start()
    try:
        c = FleetClient(srv.url, signing_key=key)
        out = c.push(Event(agent_id="a", kind="k"))
        assert out["ok"] is True
        assert s.event_count() == 1
    finally:
        srv.stop()


@arsenal_required
def test_http_signed_only_rejects_unsigned(tmp_path):
    from arsenal.keys import generate_keypair
    key = generate_keypair(name="srv2", directory=tmp_path)
    s = Store(":memory:")
    srv = IngestServer(s, host="127.0.0.1", port=0, trusted_keys=[key])
    srv.start()
    try:
        c = FleetClient(srv.url)  # no signing key
        with pytest.raises(FleetClientError) as ei:
            c.push(Event(agent_id="a", kind="k"))
        assert "401" in str(ei.value)
        assert s.event_count() == 0
    finally:
        srv.stop()


@arsenal_required
def test_http_signed_only_rejects_wrong_key(tmp_path):
    from arsenal.keys import generate_keypair
    server_key = generate_keypair(name="srv3", directory=tmp_path)
    other_key = generate_keypair(name="other", directory=tmp_path)
    s = Store(":memory:")
    srv = IngestServer(s, host="127.0.0.1", port=0, trusted_keys=[server_key])
    srv.start()
    try:
        c = FleetClient(srv.url, signing_key=other_key)
        with pytest.raises(FleetClientError):
            c.push(Event(agent_id="a", kind="k"))
        assert s.event_count() == 0
    finally:
        srv.stop()


# ── CLI prune ──────────────────────────────────────────────────────
def test_cli_prune(tmp_path, capsys):
    from fleet.cli import main as cli
    db = str(tmp_path / "f.sqlite")
    s = Store(db)
    ing = Ingest(s)
    now = time.time()
    ing.record(Event(agent_id="a", kind="k", ts=now - 1000))
    ing.record(Event(agent_id="a", kind="k", ts=now))
    s.close()
    rc = cli(["--db", db, "prune", "--ttl", "100"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deleted_by_ttl"] == 1
    assert out["total"] == 1
