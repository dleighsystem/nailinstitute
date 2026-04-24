"""End-to-end tests for ApexBrain (all I/O stubbed)."""
from __future__ import annotations

import os
import pytest

from apex.brain import ApexBrain, ApexResponse
from apex.router import SYSTEM_1, SYSTEM_2
from apex.system1 import System1
from apex.system2 import System2


class _Client:
    def __init__(self, response=""):
        self.response = response
        self.calls = []

    def generate(self, model, prompt, **kw):
        self.calls.append((model, prompt))
        return self.response


class _ForceRouter:
    def __init__(self, decision):
        self.decision = decision

    def classify(self, q):
        return self.decision


def _brain(decision, sys1_resp="fast-answer",
           sys2_resp="<thought>t</thought><answer>deep-answer</answer>"):
    return ApexBrain(
        router=_ForceRouter(decision),
        system1=System1(client=_Client(sys1_resp)),
        system2=System2(client=_Client(sys2_resp)),
        enable_shield=False,
        enable_telemetry=False,
    )


def test_brain_routes_sys1_calls_system1():
    b = _brain(SYSTEM_1)
    r = b.process("hi")
    assert r.system == SYSTEM_1
    assert r.answer == "fast-answer"
    assert r.thought == ""


def test_brain_routes_sys2_calls_system2_and_extracts():
    b = _brain(SYSTEM_2)
    r = b.process("solve")
    assert r.system == SYSTEM_2
    assert r.answer == "deep-answer"
    assert r.thought == "t"
    assert r.extras["had_thought_block"] is True


def test_brain_router_exception_falls_back_to_sys1():
    class BadRouter:
        def classify(self, q):
            raise RuntimeError("nope")
    b = ApexBrain(
        router=BadRouter(),
        system1=System1(client=_Client("ok")),
        system2=System2(client=_Client("x")),
        enable_shield=False,
        enable_telemetry=False,
    )
    r = b.process("q")
    assert r.system == SYSTEM_1
    assert "router_error" in r.extras


def test_brain_response_to_dict_is_serialisable():
    import json
    b = _brain(SYSTEM_2)
    r = b.process("q")
    d = r.to_dict()
    json.dumps(d)
    assert d["system"] == SYSTEM_2


def test_brain_records_durations():
    b = _brain(SYSTEM_1)
    r = b.process("q")
    assert r.duration_ms >= 0.0
    assert r.routed_in_ms >= 0.0


def test_brain_telemetry_disabled_runs_silently(monkeypatch):
    """With env disable, .process must not raise even if fleet present."""
    monkeypatch.setenv("NAIL_TELEMETRY_DISABLED", "1")
    from apex import _telemetry
    _telemetry._attempted = False
    _telemetry._emit_fn = None
    b = _brain(SYSTEM_1)
    r = b.process("q")
    assert r.system == SYSTEM_1
