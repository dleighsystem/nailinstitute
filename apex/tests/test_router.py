"""Tests for apex.router."""
from __future__ import annotations

import pytest

from apex.router import (
    CosineRouter, DomainRouter, GuardRouter,
    SYSTEM_1, SYSTEM_2,
    DEFAULT_SYS1_ANCHORS, DEFAULT_SYS2_ANCHORS,
)
from apex.ollama_client import OllamaError


# ── stub encoders ──────────────────────────────────────────────────
class StubEncoder:
    """Returns deterministic vectors keyed on substring presence."""
    def __init__(self, mapping: dict[str, list[float]], default=None):
        self.mapping = mapping
        self.default = default or [0.5, 0.5, 0.5]

    def encode(self, texts, **_):
        out = []
        for t in texts:
            v = self.default
            for key, vec in self.mapping.items():
                if key.lower() in t.lower():
                    v = vec
                    break
            out.append(list(v))
        return out


class StubClient:
    def __init__(self, response="FAST", raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc
        self.calls = []

    def generate(self, model, prompt, **kw):
        self.calls.append((model, prompt, kw))
        if self.raise_exc:
            raise self.raise_exc
        return self.response


# ── CosineRouter ───────────────────────────────────────────────────
def test_cosine_router_picks_sys1_for_chitchat():
    enc = StubEncoder({
        "hello": [1.0, 0.0, 0.0],   # sys1-ish
        "prove": [0.0, 1.0, 0.0],   # sys2-ish
    })
    sys1 = ("hello there", "hi friend")
    sys2 = ("prove this theorem",)
    r = CosineRouter(sys1_anchors=sys1, sys2_anchors=sys2,
                     encoder=enc, sys2_bias=0.0)
    assert r.classify("hello world") == SYSTEM_1


def test_cosine_router_picks_sys2_for_reasoning():
    enc = StubEncoder({
        "hello": [1.0, 0.0, 0.0],
        "prove": [0.0, 1.0, 0.0],
    })
    sys1 = ("hello there",)
    sys2 = ("prove this theorem", "derive the formula")
    r = CosineRouter(sys1_anchors=sys1, sys2_anchors=sys2,
                     encoder=enc, sys2_bias=0.0)
    assert r.classify("please prove that 2+2=4") == SYSTEM_2


def test_cosine_router_bias_breaks_ties_toward_sys2():
    # Both centroids identical → tie → bias should push to SYSTEM_2.
    enc = StubEncoder({}, default=[1.0, 0.0])
    r = CosineRouter(sys1_anchors=("a",), sys2_anchors=("b",),
                     encoder=enc, sys2_bias=0.05)
    assert r.classify("anything") == SYSTEM_2


def test_cosine_router_score_returns_two_floats():
    enc = StubEncoder({}, default=[1.0, 0.0])
    r = CosineRouter(sys1_anchors=("a",), sys2_anchors=("b",),
                     encoder=enc)
    s1, s2 = r.score("query")
    assert isinstance(s1, float) and isinstance(s2, float)


# ── GuardRouter ────────────────────────────────────────────────────
def test_guard_router_deep_token_routes_sys2():
    client = StubClient(response="DEEP\n")
    r = GuardRouter(client=client)
    assert r.classify("solve this") == SYSTEM_2


def test_guard_router_fast_token_routes_sys1():
    client = StubClient(response="FAST")
    r = GuardRouter(client=client)
    assert r.classify("hi") == SYSTEM_1


def test_guard_router_garbage_falls_back():
    client = StubClient(response="???")
    fallback_calls = []

    class FallbackRouter:
        def classify(self, q):
            fallback_calls.append(q)
            return SYSTEM_2
    r = GuardRouter(client=client, fallback=FallbackRouter())
    assert r.classify("hello") == SYSTEM_2
    assert fallback_calls == ["hello"]


def test_guard_router_client_exception_falls_back():
    client = StubClient(raise_exc=OllamaError("boom"))

    class FallbackRouter:
        def classify(self, q):
            return SYSTEM_1
    r = GuardRouter(client=client, fallback=FallbackRouter())
    assert r.classify("anything") == SYSTEM_1


# ── DomainRouter ───────────────────────────────────────────────────
def test_domain_router_picks_correct_label():
    enc = StubEncoder({
        "math":  [1.0, 0.0, 0.0],
        "code":  [0.0, 1.0, 0.0],
        "story": [0.0, 0.0, 1.0],
    })
    r = DomainRouter(
        anchors={
            "math":  ("math equations",),
            "code":  ("code python",),
            "story": ("story creative",),
        },
        encoder=enc,
    )
    assert r.classify("solve a math problem") == "math"
    assert r.classify("write code in python") == "code"


# ── default anchors are non-empty ──────────────────────────────────
def test_default_anchor_packs_are_populated():
    assert len(DEFAULT_SYS1_ANCHORS) >= 4
    assert len(DEFAULT_SYS2_ANCHORS) >= 4
