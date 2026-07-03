"""Tests for the /v1/audit/tool-retrieval canary server endpoint (AVE-2026-0045)."""

import pytest


def _client():
    pytest.importorskip("httpx")  # fastapi TestClient needs httpx
    from fastapi.testclient import TestClient
    from canary.server import create_app

    app = create_app(enable_llm=False)
    return TestClient(app), app


def _an_agent(app):
    return next(iter(app.state.deployment.targets))


def test_audit_endpoint_flags_starvation():
    client, app = _client()
    resp = client.post("/v1/audit/tool-retrieval", json={
        "agent": _an_agent(app),
        "loaded_tools": ["crm_search"],
        "required_tools": ["approval_gate"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["triggered"] is True
    assert data["reason"] == "required_tool_starved"
    assert data["ave_id"] == "AVE-2026-0045"
    assert data["incidents_total"] >= 1


def test_audit_endpoint_clean_when_aligned():
    client, app = _client()
    resp = client.post("/v1/audit/tool-retrieval", json={
        "agent": _an_agent(app),
        "loaded_tools": ["crm_search", "approval_gate"],
        "authorized_tools": ["crm_search", "approval_gate"],
        "required_tools": ["approval_gate"],
    })
    assert resp.status_code == 200
    assert resp.json()["triggered"] is False


def test_audit_endpoint_unknown_agent_404():
    client, _ = _client()
    resp = client.post("/v1/audit/tool-retrieval", json={"agent": "nope", "loaded_tools": []})
    assert resp.status_code == 404


def test_audit_endpoint_requires_loaded_tools():
    client, app = _client()
    resp = client.post("/v1/audit/tool-retrieval", json={"agent": _an_agent(app)})
    assert resp.status_code == 400
