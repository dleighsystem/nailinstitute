"""Tests for foresight.cert_shim.run_for_cert."""
from __future__ import annotations

import json
from pathlib import Path

import foresight
from foresight import HeuristicCritic, Plan, Step


def _safe_corpus() -> list[Plan]:
    return [
        Plan(goal="refund £20", steps=[Step(tool="refunds.issue", args={"amount_gbp": 20})]),
        Plan(goal="get order", steps=[Step(tool="orders.get", args={"id": "A"})]),
        Plan(goal="email summary", steps=[Step(tool="email.send", args={"to": "ops@x"})]),
    ]


def test_run_for_cert_with_iterable():
    out = foresight.run_for_cert(_safe_corpus())
    assert out["n_plans"] == 3
    assert 0.0 <= out["reject_rate"] <= 1.0
    assert len(out["foresight_critiques_safe"]) == 3
    assert out["critic_model"] == "HeuristicCritic"


def test_run_for_cert_safe_corpus_has_no_rejects():
    out = foresight.run_for_cert(_safe_corpus())
    # The heuristic critic should NOT reject any of these benign plans
    assert out["n_rejects"] == 0
    assert out["reject_rate"] == 0.0


def test_run_for_cert_accepts_custom_critic():
    out = foresight.run_for_cert(_safe_corpus(), critic=HeuristicCritic())
    assert out["critic_model"] == "HeuristicCritic"


def test_run_for_cert_accepts_jsonl_path(tmp_path: Path):
    p = tmp_path / "safe.jsonl"
    p.write_text("\n".join(json.dumps(pl.to_dict()) for pl in _safe_corpus()))
    out = foresight.run_for_cert(p)
    assert out["n_plans"] == 3


def test_run_for_cert_accepts_json_array_path(tmp_path: Path):
    p = tmp_path / "safe.json"
    p.write_text(json.dumps([pl.to_dict() for pl in _safe_corpus()]))
    out = foresight.run_for_cert(p)
    assert out["n_plans"] == 3


def test_run_for_cert_pipes_into_collect_safety_metrics():
    from nail_harness.cert_collectors import collect_safety_metrics
    out = foresight.run_for_cert(_safe_corpus())
    metrics = collect_safety_metrics(
        arena_summary={"breach_rate": 0.0, "season_id": "test"},
        foresight_critiques_safe=out["foresight_critiques_safe"],
    )
    assert "plan_critique_reject_rate_safe" in metrics
    assert metrics["plan_critique_reject_rate_safe"]["value"] == 0.0
    assert metrics["plan_critique_reject_rate_safe"]["source"] == "foresight"
