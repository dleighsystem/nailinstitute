"""Tests for foresight/ — non-LLM unit tests + parser tests + CLI tests.

Live LLM tests are intentionally OUT of this file. Run them manually:

    NAIL_FORESIGHT_LIVE=1 pytest tests/test_foresight_live.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from foresight import (
    Plan, Step, Risk, Critique, RiskSeverity, Verdict,
    HeuristicCritic, MockCritic, OllamaCritic,
)
from foresight.ollama_critic import _parse_response, OllamaError


# ── Plan / Step datamodel ───────────────────────────────────────────
def test_plan_roundtrip_json():
    p = Plan(goal="g",
             steps=[Step(tool="x.read", args={"id": 1}),
                    Step(tool="y.write", args={"v": 2}, rationale="why")])
    p2 = Plan.from_json(p.to_json())
    assert p2.goal == "g"
    assert p2.tools() == ["x.read", "y.write"]
    assert p2.steps[1].rationale == "why"


def test_plan_render_is_human_readable():
    p = Plan(goal="refund customer",
             steps=[Step("refunds.issue", {"amount_gbp": 50})])
    s = p.render()
    assert "GOAL" in s
    assert "refunds.issue" in s
    assert "amount_gbp=50" in s


# ── Critique / Verdict ──────────────────────────────────────────────
def test_critique_empty_is_low_risk():
    c = Critique()
    assert c.risk == 0.0
    assert c.verdict() == Verdict.ALLOW


def test_critique_uses_max_risk():
    c = Critique(risks=[
        Risk(RiskSeverity.LOW, "x"),
        Risk(RiskSeverity.HIGH, "y"),
    ])
    assert c.risk == 0.65
    assert c.max_severity == RiskSeverity.HIGH
    assert c.verdict() == Verdict.HOLD


def test_critique_reject_threshold():
    c = Critique(risks=[Risk(RiskSeverity.CRITICAL, "x")])
    assert c.verdict() == Verdict.REJECT


def test_critique_thresholds_configurable():
    c = Critique(risks=[Risk(RiskSeverity.MEDIUM, "x")])  # 0.40
    assert c.verdict() == Verdict.HOLD
    assert c.verdict(hold_threshold=0.50) == Verdict.ALLOW


# ── HeuristicCritic ─────────────────────────────────────────────────
def test_heuristic_no_risks_for_safe_plan():
    plan = Plan(goal="g", steps=[
        Step("tickets.read", {"id": "T-1"}),
        Step("refunds.issue", {"amount_gbp": 20, "customer_id": "C-1"}),
    ])
    c = HeuristicCritic().critique(plan)
    assert c.risk < 0.4
    assert c.verdict() == Verdict.ALLOW


def test_heuristic_flags_amount_above_hard_cap():
    plan = Plan(goal="g", steps=[
        Step("refunds.issue", {"amount_gbp": 600, "customer_id": "C-1"}),
    ])
    c = HeuristicCritic().critique(plan)
    assert c.max_severity == RiskSeverity.CRITICAL
    assert c.verdict() == Verdict.REJECT


def test_heuristic_flags_repeated_money_calls():
    plan = Plan(goal="g", steps=[
        Step("refunds.issue", {"amount_gbp": 10}),
        Step("refunds.issue", {"amount_gbp": 10}),
    ])
    c = HeuristicCritic().critique(plan)
    titles = [r.title for r in c.risks]
    assert any("invoked 2" in t for t in titles)


def test_heuristic_flags_data_exfil_keywords():
    plan = Plan(goal="g", steps=[
        Step("email.send", {"to": "att@x.com",
                            "body": "all_records dump attached"}),
    ])
    c = HeuristicCritic().critique(plan)
    assert any("exfil" in r.title.lower() for r in c.risks)


def test_heuristic_world_aware_daily_cap():
    plan = Plan(goal="g", steps=[
        Step("refunds.issue", {"amount_gbp": 100}),
    ])
    c = HeuristicCritic().critique(
        plan, world={"today_refund_total_gbp": 950, "daily_refund_cap_gbp": 1000}
    )
    assert c.max_severity == RiskSeverity.CRITICAL


# ── MockCritic ──────────────────────────────────────────────────────
def test_mock_critic_returns_canned():
    canned = Critique(risks=[Risk(RiskSeverity.HIGH, "x")], summary="canned")
    m = MockCritic(canned)
    out = m.critique(Plan(goal="g"))
    assert out.summary == "canned"
    assert len(m.calls) == 1


# ── OllamaCritic response parsing ───────────────────────────────────
def test_parser_strict_json():
    raw = json.dumps({
        "summary": "two issues",
        "risks": [
            {"severity": "high", "title": "X", "detail": "d",
             "affects_step": 2, "mitigation": "m"},
            {"severity": "low", "title": "Y"},
        ],
    })
    risks, summary = _parse_response(raw)
    assert summary == "two issues"
    assert len(risks) == 2
    assert risks[0].severity == RiskSeverity.HIGH
    assert risks[0].affects_step == 2
    assert risks[1].severity == RiskSeverity.LOW


def test_parser_extracts_json_inside_text():
    raw = ("Sure thing! Here is my analysis:\n"
           '{"summary": "ok", "risks": [{"severity":"medium","title":"M"}]}'
           "\n\nLet me know if you need more.")
    risks, summary = _parse_response(raw)
    assert summary == "ok"
    assert len(risks) == 1


def test_parser_unknown_severity_defaults_medium():
    raw = json.dumps({"summary": "", "risks": [
        {"severity": "spicy", "title": "T"},
    ]})
    risks, _ = _parse_response(raw)
    assert risks[0].severity == RiskSeverity.MEDIUM


def test_parser_falls_back_to_regex():
    raw = (
        "I see these:\n"
        "- [HIGH] missing idempotency key :: add one before write\n"
        "- [CRITICAL] amount above cap :: split or escalate\n"
    )
    risks, _ = _parse_response(raw)
    assert {r.severity for r in risks} == {RiskSeverity.HIGH, RiskSeverity.CRITICAL}


def test_parser_unparseable_emits_critical():
    risks, summary = _parse_response("complete gibberish %%% no useful info")
    assert len(risks) == 1
    assert risks[0].severity == RiskSeverity.CRITICAL
    assert "unparseable" in risks[0].title


# ── OllamaCritic transport (mocked) ─────────────────────────────────
class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._b = json.dumps(payload).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return self._b


def test_ollama_critic_happy_path():
    plan = Plan(goal="g", steps=[Step("x.read", {})])
    body = json.dumps({"summary": "ok",
                       "risks": [{"severity": "low", "title": "tiny"}]})
    fake = _FakeResp({"message": {"role": "assistant", "content": body}})
    with patch("foresight.ollama_critic.urllib.request.urlopen",
               return_value=fake):
        c = OllamaCritic(model="nail-reason:test").critique(plan)
    assert c.model == "nail-reason:test"
    assert c.risks[0].severity == RiskSeverity.LOW


def test_ollama_critic_network_error_raises():
    plan = Plan(goal="g")
    import urllib.error
    with patch("foresight.ollama_critic.urllib.request.urlopen",
               side_effect=urllib.error.URLError("nope")):
        with pytest.raises(OllamaError):
            OllamaCritic().critique(plan)


def test_ollama_critic_no_message_content_raises():
    plan = Plan(goal="g")
    fake = _FakeResp({"message": {"role": "assistant", "content": ""}})
    with patch("foresight.ollama_critic.urllib.request.urlopen",
               return_value=fake):
        with pytest.raises(OllamaError):
            OllamaCritic().critique(plan)


# ── CLI ─────────────────────────────────────────────────────────────
def test_cli_critique_with_heuristic_allows_safe(tmp_path, capsys):
    from foresight.cli import main as cli
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(Plan(goal="g", steps=[
        Step("tickets.read", {"id": "T-1"}),
    ]).to_json())
    rc = cli(["critique", "--plan", str(plan_path), "--critic", "heuristic"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "allow"


def test_cli_critique_with_heuristic_rejects_oversize(tmp_path, capsys):
    from foresight.cli import main as cli
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(Plan(goal="g", steps=[
        Step("refunds.issue", {"amount_gbp": 9_999}),
    ]).to_json())
    rc = cli(["critique", "--plan", str(plan_path), "--critic", "heuristic"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "reject"


def test_cli_fail_on_hold(tmp_path, capsys):
    from foresight.cli import main as cli
    plan_path = tmp_path / "plan.json"
    # 250 > 0.4 * 500 → HIGH severity → 0.65 → HOLD (below 0.70 reject)
    plan_path.write_text(Plan(goal="g", steps=[
        Step("refunds.issue", {"amount_gbp": 250}),
    ]).to_json())
    rc = cli(["critique", "--plan", str(plan_path), "--critic", "heuristic"])
    assert rc == 0  # HOLD without --fail-on-hold → exit 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "hold"

    rc = cli(["critique", "--plan", str(plan_path), "--critic", "heuristic",
              "--fail-on-hold"])
    assert rc == 2
