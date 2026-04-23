"""R2 integration tests — verify each NAIL package auto-emits into a fleet sink.

These tests install a CapturingSink, exercise each package's hot path,
and assert the expected fleet event shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Sibling-package path setup so we can import the four producer packages.
ROOT = Path(__file__).resolve().parents[2]
for sib in ("foresight", "rehearsal", "arsenal", "shield"):
    p = ROOT / sib
    if p.is_dir():
        sys.path.insert(0, str(p))

from fleet import (
    CapturingSink, set_sink, NullSink, get_sink, HAS_ARSENAL,
)


@pytest.fixture
def capture():
    sink = CapturingSink()
    set_sink(sink)
    try:
        yield sink
    finally:
        set_sink(NullSink())


# ── foresight: HeuristicCritic emits foresight.verdict ──────────────
def test_foresight_heuristic_emits_verdict(capture):
    from foresight import Plan, Step, HeuristicCritic
    plan = Plan(goal="t", steps=[Step("refunds.issue", {"amount_gbp": 50})])
    HeuristicCritic().critique(plan)
    kinds = [e.kind for e in capture.events]
    assert "foresight.verdict" in kinds
    ev = next(e for e in capture.events if e.kind == "foresight.verdict")
    assert ev.attrs["verdict"] in ("allow", "hold", "reject")
    assert ev.attrs["model"] == "heuristic"
    assert ev.attrs["n_steps"] == 1


def test_foresight_emits_severity_on_reject(capture):
    from foresight import Plan, Step, HeuristicCritic
    plan = Plan(goal="t", steps=[Step("refunds.issue", {"amount_gbp": 9_999})])
    HeuristicCritic().critique(plan)
    ev = next(e for e in capture.events if e.kind == "foresight.verdict")
    assert ev.attrs["verdict"] == "reject"
    assert ev.severity == "warn"


# ── shield: process emits shield.process ────────────────────────────
def test_shield_process_emits(capture):
    from shield import process
    process("hello world", source="user-123", chain=False)
    ev = next(e for e in capture.events if e.kind == "shield.process")
    assert ev.attrs["source"] == "user-123"
    assert ev.attrs["is_injection"] is False
    assert ev.severity == "info"


def test_shield_emits_warn_when_secrets_detected(capture):
    from shield import process
    process("contact me at jane@example.com please", source="user",
            chain=False)
    ev = next(e for e in capture.events if e.kind == "shield.process")
    assert ev.attrs["n_secrets"] >= 1
    assert ev.severity == "warn"


# ── arsenal: requires_token emits allow + deny ──────────────────────
def test_arsenal_emits_allow_and_deny(capture):
    from arsenal import (
        mint, set_session_tokens, requires_token, generate_keypair,
        MissingToken,
    )
    import tempfile, pathlib
    td = pathlib.Path(tempfile.mkdtemp())
    key = generate_keypair(name="r2", directory=td)

    @requires_token("refunds.issue")
    def do_refund(*, amount_gbp: float, customer_id: str):
        return {"ok": True, "id": customer_id}

    # No token in scope → deny
    set_session_tokens([])
    with pytest.raises(MissingToken):
        do_refund(amount_gbp=10, customer_id="C-1")

    deny_evs = [e for e in capture.events if e.kind == "arsenal.deny"]
    assert len(deny_evs) == 1
    assert deny_evs[0].attrs["tool"] == "refunds.issue"
    assert deny_evs[0].attrs["reason_class"] == "MissingToken"
    assert deny_evs[0].severity == "error"

    # Mint a token, retry → allow
    tok = mint(tool="refunds.issue", agent="bot-1", session="s-1",
               limits={"calls": 3, "cumulative_gbp": 100},
               ttl_seconds=60, key=key)
    set_session_tokens([tok])
    out = do_refund(amount_gbp=20, customer_id="C-2")
    assert out["ok"] is True

    allow_evs = [e for e in capture.events if e.kind == "arsenal.allow"]
    assert len(allow_evs) == 1
    assert allow_evs[0].attrs["tool"] == "refunds.issue"
    assert allow_evs[0].attrs["amount_gbp"] == 20.0


# ── rehearsal: requires_rehearsal emits rehearsal.verdict ──────────
def test_rehearsal_emits_verdict(capture):
    from rehearsal import Sandbox, Verdict, requires_rehearsal
    from rehearsal.verdict import RehearsalDenied

    sb = Sandbox()

    @sb.shadow("refunds.issue")
    def shadow_refund(*, amount_gbp: float):
        return {"shadow": True, "amount_gbp": amount_gbp}

    @sb.policy("refunds.issue")
    def policy_refund(args, world, shadow_result):
        if args["amount_gbp"] > 100:
            return Verdict.deny("over £100 cap")
        return Verdict.allow("ok")

    @requires_rehearsal("refunds.issue", sandbox=sb)
    def real_refund(*, amount_gbp: float):
        return {"real": True, "amount_gbp": amount_gbp}

    # ALLOW path
    real_refund(amount_gbp=10)
    # DENY path
    with pytest.raises(RehearsalDenied):
        real_refund(amount_gbp=999)

    rev = [e for e in capture.events if e.kind == "rehearsal.verdict"]
    assert len(rev) == 2
    verdicts = [e.attrs["verdict"] for e in rev]
    assert verdicts == ["allow", "deny"]
    assert rev[1].severity == "error"
    assert rev[0].attrs["tool"] == "refunds.issue"


# ── disable env kill-switch ────────────────────────────────────────
def test_telemetry_disable_env(monkeypatch, capture):
    """When NAIL_TELEMETRY_DISABLED is set BEFORE _telemetry imports fleet,
    no events are emitted. We re-import the shim to re-run the gate."""
    import importlib
    monkeypatch.setenv("NAIL_TELEMETRY_DISABLED", "1")
    import foresight._telemetry as t
    # Reset the cache so the env var is re-checked.
    t._attempted = False
    t._emit_fn = None

    from foresight import Plan, Step, HeuristicCritic
    HeuristicCritic().critique(Plan(goal="t", steps=[Step("x.read", {})]))
    # No events — the shim returned before importing fleet.
    assert capture.events == []

    # Reset for other tests.
    t._attempted = False
    t._emit_fn = None
