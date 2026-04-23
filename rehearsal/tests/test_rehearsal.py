"""End-to-end tests for rehearsal/."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rehearsal import (
    Sandbox, Verdict, Outcome,
    requires_rehearsal, Recorder,
    Replayer,
    RehearsalDenied, RehearsalHeld,
    ShadowMissing, PolicyMissing,
)
from rehearsal.decorator import set_world
from rehearsal.recorder import load_jsonl, ToolCall


# ── verdict ─────────────────────────────────────────────────────────
def test_verdict_factories():
    assert Verdict.allow().outcome == Outcome.ALLOW
    assert Verdict.hold("review needed").held
    assert Verdict.deny("over cap").denied
    assert Verdict.allow().to_dict()["outcome"] == "allow"


# ── sandbox: registration + rehearse ────────────────────────────────
def _refunds_sandbox() -> Sandbox:
    sb = Sandbox()

    @sb.shadow("refunds.issue")
    def _shadow(*, amount_gbp, customer_id, **_):
        return {"refund_id": "shadow", "delta_gbp": -float(amount_gbp),
                "customer": customer_id}

    @sb.policy("refunds.issue")
    def _policy(args, shadow_result, world):
        spent = float(world.get("spent_today_gbp", 0))
        amt = float(args.get("amount_gbp", 0))
        if amt > 200:
            return Verdict.deny("over single-call cap £200")
        if spent + amt > 500:
            return Verdict.deny("would exceed daily £500 limit")
        if amt > 50:
            return Verdict.hold("over warning threshold £50")
        return Verdict.allow()

    return sb


def test_sandbox_rehearse_allow():
    r = _refunds_sandbox().rehearse(
        "refunds.issue",
        args={"amount_gbp": 20, "customer_id": "C-1"},
    )
    assert r.verdict.allowed
    assert r.shadow_result["delta_gbp"] == -20


def test_sandbox_rehearse_hold():
    r = _refunds_sandbox().rehearse(
        "refunds.issue",
        args={"amount_gbp": 100, "customer_id": "C-1"},
    )
    assert r.verdict.held


def test_sandbox_rehearse_deny():
    r = _refunds_sandbox().rehearse(
        "refunds.issue",
        args={"amount_gbp": 250, "customer_id": "C-1"},
    )
    assert r.verdict.denied
    assert "200" in r.verdict.reason


def test_sandbox_world_affects_verdict():
    r = _refunds_sandbox().rehearse(
        "refunds.issue",
        args={"amount_gbp": 40, "customer_id": "C-1"},
        world={"spent_today_gbp": 480},  # 480+40 = 520 > 500
    )
    assert r.verdict.denied


def test_sandbox_strict_raises_when_unregistered():
    sb = Sandbox()
    with pytest.raises(ShadowMissing):
        sb.rehearse("unknown.tool")


def test_sandbox_nonstrict_falls_back_to_allow():
    sb = Sandbox()
    r = sb.rehearse("unknown.tool", strict=False)
    assert r.verdict.allowed


def test_sandbox_rejects_non_verdict_policy():
    sb = Sandbox()
    sb.register_shadow("x", lambda **_: None)
    sb.register_policy("x", lambda a, s, w: "not a verdict")
    with pytest.raises(TypeError):
        sb.rehearse("x")


# ── decorator ────────────────────────────────────────────────────────
def test_decorator_allows_real_call_on_allow():
    sb = _refunds_sandbox()
    rec = Recorder()
    real_calls: list = []

    @requires_rehearsal("refunds.issue", sandbox=sb, recorder=rec)
    def real_issue(amount_gbp, customer_id):
        real_calls.append((amount_gbp, customer_id))
        return "ok"

    assert real_issue(amount_gbp=20, customer_id="C-1") == "ok"
    assert real_calls == [(20, "C-1")]
    assert len(rec) == 1


def test_decorator_blocks_on_deny():
    sb = _refunds_sandbox()
    real_calls: list = []

    @requires_rehearsal("refunds.issue", sandbox=sb, recorder=Recorder())
    def real_issue(amount_gbp, customer_id):
        real_calls.append((amount_gbp, customer_id))
        return "ok"

    with pytest.raises(RehearsalDenied):
        real_issue(amount_gbp=300, customer_id="C-1")
    assert real_calls == []


def test_decorator_holds_unless_confirmed():
    sb = _refunds_sandbox()

    @requires_rehearsal("refunds.issue", sandbox=sb, recorder=Recorder())
    def real_issue(amount_gbp, customer_id):
        return f"ok £{amount_gbp}"

    with pytest.raises(RehearsalHeld):
        real_issue(amount_gbp=100, customer_id="C-1")

    # After explicit confirmation, the held call goes through.
    out = real_issue(amount_gbp=100, customer_id="C-1", __nail_confirm__=True)
    assert out == "ok £100"


def test_decorator_uses_world_from_contextvar():
    sb = _refunds_sandbox()

    @requires_rehearsal("refunds.issue", sandbox=sb, recorder=Recorder())
    def real_issue(amount_gbp, customer_id):
        return "ok"

    set_world({"spent_today_gbp": 490})  # tight budget
    with pytest.raises(RehearsalDenied):
        real_issue(amount_gbp=20, customer_id="C-1")
    set_world({})


# ── recorder ────────────────────────────────────────────────────────
def test_recorder_persists_to_jsonl(tmp_path):
    sb = _refunds_sandbox()
    rec = Recorder(jsonl_path=tmp_path / "trace.jsonl")

    @requires_rehearsal("refunds.issue", sandbox=sb, recorder=rec)
    def real(amount_gbp, customer_id):
        return "ok"

    real(amount_gbp=10, customer_id="C-1")
    real(amount_gbp=20, customer_id="C-2")

    loaded = load_jsonl(tmp_path / "trace.jsonl")
    assert len(loaded.calls) == 2
    assert loaded.counts()["allow"] == 2
    assert loaded.by_tool()["refunds.issue"]["allow"] == 2


# ── replayer ────────────────────────────────────────────────────────
def test_replayer_detects_policy_drift(tmp_path):
    sb_old = _refunds_sandbox()
    rec = Recorder(jsonl_path=tmp_path / "trace.jsonl")

    @requires_rehearsal("refunds.issue", sandbox=sb_old, recorder=rec)
    def real(amount_gbp, customer_id):
        return "ok"

    real(amount_gbp=20, customer_id="C-1")  # ALLOW
    real(amount_gbp=80, customer_id="C-2",  # HOLD
         __nail_confirm__=True)

    # Build a stricter sandbox: anything > £10 → DENY
    sb_new = Sandbox()
    sb_new.register_shadow("refunds.issue",
                           lambda **kw: {"delta_gbp": -kw["amount_gbp"]})
    sb_new.register_policy(
        "refunds.issue",
        lambda a, s, w: (Verdict.deny("strict mode")
                         if a["amount_gbp"] > 10 else Verdict.allow()),
    )

    summary = Replayer(sb_new).replay(tmp_path / "trace.jsonl")
    assert not summary.stable
    assert len(summary.changes) == 2
    table = summary.transition_table()
    assert table[("allow", "deny")] == 1
    assert table[("hold", "deny")] == 1


def test_replayer_stable_when_policy_unchanged(tmp_path):
    sb = _refunds_sandbox()
    rec = Recorder(jsonl_path=tmp_path / "t.jsonl")

    @requires_rehearsal("refunds.issue", sandbox=sb, recorder=rec)
    def real(amount_gbp, customer_id):
        return "ok"

    real(amount_gbp=10, customer_id="C-1")
    real(amount_gbp=20, customer_id="C-2")

    summary = Replayer(sb).replay(tmp_path / "t.jsonl")
    assert summary.stable


# ── CLI ──────────────────────────────────────────────────────────────
def test_cli_summarise(tmp_path, capsys):
    from rehearsal.cli import main as cli

    # produce a recording
    sb = _refunds_sandbox()
    rec = Recorder(jsonl_path=tmp_path / "t.jsonl")

    @requires_rehearsal("refunds.issue", sandbox=sb, recorder=rec)
    def real(amount_gbp, customer_id):
        return "ok"

    real(amount_gbp=10, customer_id="C-1")
    with pytest.raises(RehearsalDenied):
        real(amount_gbp=999, customer_id="C-2")

    rc = cli(["summarise", "--recording", str(tmp_path / "t.jsonl")])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_calls"] == 2
    assert out["counts"]["allow"] == 1
    assert out["counts"]["deny"] == 1


def test_cli_replay_with_external_sandbox(tmp_path, capsys):
    from rehearsal.cli import main as cli

    # 1. Produce a recording from a baseline sandbox.
    sb = _refunds_sandbox()
    rec = Recorder(jsonl_path=tmp_path / "t.jsonl")

    @requires_rehearsal("refunds.issue", sandbox=sb, recorder=rec)
    def real(amount_gbp, customer_id):
        return "ok"
    real(amount_gbp=10, customer_id="C-1")
    real(amount_gbp=20, customer_id="C-2")

    # 2. Write an external sandbox file (replicating the same policy).
    sandbox_py = tmp_path / "sb.py"
    sandbox_py.write_text(
        "from rehearsal import Sandbox, Verdict\n"
        "sandbox = Sandbox()\n"
        "@sandbox.shadow('refunds.issue')\n"
        "def _s(*, amount_gbp, customer_id, **_):\n"
        "    return {'delta_gbp': -amount_gbp}\n"
        "@sandbox.policy('refunds.issue')\n"
        "def _p(a, s, w):\n"
        "    if a['amount_gbp'] > 200: return Verdict.deny('cap')\n"
        "    if a['amount_gbp'] > 50:  return Verdict.hold('warn')\n"
        "    return Verdict.allow()\n"
    )

    rc = cli([
        "replay",
        "--recording", str(tmp_path / "t.jsonl"),
        "--sandbox", f"{sandbox_py}:sandbox",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stable"] is True
    assert out["total"] == 2
