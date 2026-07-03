"""Org-scoped ingest over HTTP: FleetClient <-> IngestServer, per tenant."""

import pytest

from fleet.event import Event
from fleet.http_client import FleetClient
from fleet.http_server import IngestServer
from fleet.store import Store


@pytest.fixture
def server():
    store = Store(":memory:")
    srv = IngestServer(store, host="127.0.0.1", port=0)
    srv.start()
    yield srv, store
    srv.stop()


def test_client_stamps_its_org_on_emitted_events(server):
    srv, store = server
    FleetClient(srv.url, org="acme", default_agent_id="a1").emit("shield.block")
    assert store.query_events()[0].org == "acme"


def test_body_org_preserved_without_proxy_header(server):
    srv, store = server
    # No client org => no X-NAIL-Org header => the body's org is trusted as-is.
    FleetClient(srv.url, default_agent_id="a1").push(
        Event(agent_id="a1", kind="k", org="acme"))
    assert store.query_events()[0].org == "acme"


def test_proxy_asserted_tenant_overrides_body(server):
    srv, store = server
    # Client is pinned to acme; it pushes an event whose body claims globex.
    # The X-NAIL-Org header (proxy-asserted tenant) must win — no cross-tenant spoof.
    FleetClient(srv.url, org="acme", default_agent_id="a1").push(
        Event(agent_id="a1", kind="k", org="globex"))
    assert store.query_events()[0].org == "acme"


def test_batch_ingest_is_tenant_scoped(server):
    srv, store = server
    FleetClient(srv.url, org="acme").push_many([
        Event(agent_id="a1", kind="k"),
        Event(agent_id="a2", kind="k"),
    ])
    assert store.event_count(org="acme") == 2
    assert {e.org for e in store.query_events()} == {"acme"}


def test_get_routes_are_org_scoped(server):
    srv, store = server
    FleetClient(srv.url, org="acme", default_agent_id="a1").emit("shield.block")
    FleetClient(srv.url, org="globex", default_agent_id="b1").emit("shield.block")

    acme = FleetClient(srv.url, org="acme")
    assert {a["agent_id"] for a in acme.agents()["agents"]} == {"a1"}
    overview = acme.overview()
    assert overview["org"] == "acme" and overview["n_agents"] == 1

    orgs = {o["org"]: o for o in FleetClient(srv.url).orgs()["orgs"]}
    assert orgs["acme"]["agents"] == 1
    assert orgs["globex"]["agents"] == 1
