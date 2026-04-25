"""Tests for arena.cert_shim.run_for_cert — drop-in for cert_collectors."""
from __future__ import annotations

import arena
from arena import Arena


def test_run_for_cert_returns_collector_compatible_shape():
    out = arena.run_for_cert(rounds=2)
    assert "arena_summary" in out
    s = out["arena_summary"]
    # Required by collect_safety_metrics
    assert "breach_rate" in s
    assert "season_id" in s
    assert isinstance(s["breach_rate"], (int, float))
    assert 0.0 <= s["breach_rate"] <= 1.0


def test_run_for_cert_benign_results_shape():
    out = arena.run_for_cert(rounds=2, include_benign=True)
    benign = out["benign_results"]
    assert benign is not None
    assert {"total", "false_positives", "evidence"} <= benign.keys()
    assert benign["total"] >= 1
    assert benign["false_positives"] >= 0


def test_run_for_cert_can_disable_benign():
    out = arena.run_for_cert(rounds=2, include_benign=False)
    assert out["benign_results"] is None


def test_run_for_cert_accepts_explicit_arena():
    a = Arena.standard()
    out = arena.run_for_cert(a, rounds=2)
    assert out["season_result"] is not None
    assert out["arena_evidence"] == out["arena_summary"]["season_id"]


def test_run_for_cert_pipes_into_collect_safety_metrics():
    """End-to-end: shim → collect_safety_metrics → metric dict."""
    from nail_harness.cert_collectors import collect_safety_metrics
    out = arena.run_for_cert(rounds=2)
    metrics = collect_safety_metrics(
        arena_summary=out["arena_summary"],
        benign_results=out["benign_results"],
        arena_evidence=out["arena_evidence"],
    )
    assert "adversarial_bypass_rate" in metrics
    assert "false_positive_rate" in metrics
    assert metrics["adversarial_bypass_rate"]["source"] == "arena"
