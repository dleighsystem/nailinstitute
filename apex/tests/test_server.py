"""Tests for apex.server — Ollama-compatible facade.

Uses FastAPI's TestClient so no network. Brain is fully stubbed.
Skips cleanly if fastapi isn't installed.
"""
from __future__ import annotations

import json
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient   # noqa: E402

from apex.brain import ApexBrain                       # noqa: E402
from apex.router import SYSTEM_1, SYSTEM_2             # noqa: E402
from apex.server import build_app, DEFAULT_MODEL_NAME  # noqa: E402
from apex.system1 import System1                       # noqa: E402
from apex.system2 import System2                       # noqa: E402


class _Client:
    def __init__(self, response=""):
        self.response = response

    def generate(self, model, prompt, **kw):
        return self.response


class _ForceRouter:
    def __init__(self, decision):
        self.decision = decision

    def classify(self, q):
        return self.decision


def _make_brain(decision=SYSTEM_1, sys1="fast", sys2_raw=None):
    if sys2_raw is None:
        sys2_raw = "<thought>think</thought><answer>deep</answer>"
    return ApexBrain(
        router=_ForceRouter(decision),
        system1=System1(client=_Client(sys1)),
        system2=System2(client=_Client(sys2_raw)),
        enable_shield=False,
        enable_telemetry=False,
    )


def _client(brain=None, model_name=DEFAULT_MODEL_NAME):
    return TestClient(build_app(brain=brain or _make_brain(),
                                model_name=model_name))


# ── healthz / version ─────────────────────────────────────────────
def test_healthz_returns_ok():
    c = _client()
    r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model"] == DEFAULT_MODEL_NAME


def test_version_endpoint():
    r = _client().get("/api/version")
    assert r.status_code == 200
    assert "version" in r.json()


# ── /api/tags ─────────────────────────────────────────────────────
def test_tags_returns_apex_brain_as_model():
    r = _client(model_name="my-apex-name").get("/api/tags")
    assert r.status_code == 200
    body = r.json()
    assert "models" in body and len(body["models"]) == 1
    m = body["models"][0]
    assert m["name"] == "my-apex-name"
    assert m["model"] == "my-apex-name"
    assert m["details"]["family"] == "apex"


# ── /api/generate ─────────────────────────────────────────────────
def test_generate_happy_path_sys1():
    c = _client(_make_brain(SYSTEM_1, sys1="hello back"))
    r = c.post("/api/generate", json={"prompt": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == "hello back"
    assert body["done"] is True
    assert body["done_reason"] == "stop"
    assert body["model"] == DEFAULT_MODEL_NAME
    # Apex extension field is present.
    assert body["apex"]["system"] == SYSTEM_1


def test_generate_routes_sys2_and_returns_extracted_answer():
    c = _client(_make_brain(SYSTEM_2,
                            sys2_raw="<thought>step</thought>"
                                     "<answer>42</answer>"))
    r = c.post("/api/generate", json={"prompt": "solve hard problem"})
    body = r.json()
    assert body["response"] == "42"
    assert body["apex"]["system"] == SYSTEM_2
    assert body["apex"]["thought_tokens"] >= 1


def test_generate_rejects_empty_prompt():
    r = _client().post("/api/generate", json={"prompt": ""})
    assert r.status_code == 400


def test_generate_rejects_missing_prompt():
    r = _client().post("/api/generate", json={})
    assert r.status_code == 400


def test_generate_includes_ollama_metric_fields():
    """Some clients parse total_duration / eval_count; must be present."""
    r = _client().post("/api/generate", json={"prompt": "hi"})
    body = r.json()
    for key in ("total_duration", "load_duration", "prompt_eval_count",
                "prompt_eval_duration", "eval_count", "eval_duration"):
        assert key in body, f"Ollama clients expect '{key}' in response"
        assert isinstance(body[key], int)


# ── /api/chat ─────────────────────────────────────────────────────
def test_chat_happy_path_picks_last_user_message():
    c = _client(_make_brain(SYSTEM_1, sys1="ack"))
    r = c.post("/api/chat", json={
        "messages": [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "follow-up question"},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "ack"
    assert "response" not in body  # chat replies use 'message'


def test_chat_rejects_empty_messages():
    r = _client().post("/api/chat", json={"messages": []})
    assert r.status_code == 400


def test_chat_rejects_no_user_content():
    r = _client().post("/api/chat", json={
        "messages": [{"role": "system", "content": "hi"}],
    })
    assert r.status_code == 400


# ── shield-block path ─────────────────────────────────────────────
class _FakeShield:
    """Stand-in for the shield module; flags ANY input as injection."""
    def process(self, text, **kw):
        from types import SimpleNamespace
        return SimpleNamespace(
            text=text,
            secret_counts={},
            injection_score=0.99,
            is_injection=True,
            injection_reason="prompt-injection in test",
            chain_id="test-chain",
        )


def test_generate_shield_blocks_injection(monkeypatch):
    from apex import _bridges
    monkeypatch.setattr(_bridges, "shield", lambda: _FakeShield())
    monkeypatch.setattr(_bridges, "_shield_attempted", True, raising=False)

    brain = ApexBrain(
        router=_ForceRouter(SYSTEM_1),
        system1=System1(client=_Client("never reached")),
        system2=System2(client=_Client("x")),
        enable_shield=True,
        enable_telemetry=False,
        block_on_injection=True,
    )
    c = TestClient(build_app(brain=brain))
    r = c.post("/api/generate", json={"prompt": "ignore previous"})
    body = r.json()
    assert body["apex"]["shield_blocked"] is True
    assert body["apex"]["system"] == "SHIELD_BLOCK"
    assert "Refusing" in body["response"]
