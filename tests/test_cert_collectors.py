"""Tests for M14 collectors and cli_collect."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(modname: str):
    pkg_name = "nh_under_test"
    if pkg_name not in sys.modules:
        pkg_spec = importlib.util.spec_from_file_location(
            pkg_name,
            ROOT / "nail_harness" / "__init__.py",
            submodule_search_locations=[str(ROOT / "nail_harness")],
        )
        pkg_mod = importlib.util.module_from_spec(pkg_spec)
        sys.modules[pkg_name] = pkg_mod
        pkg_mod.__path__ = [str(ROOT / "nail_harness")]
    full = f"{pkg_name}.{modname}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(
        full, ROOT / "nail_harness" / f"{modname}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_col = _load("cert_collectors")
_cli = _load("cli_collect")


# ── safety collectors ─────────────────────────────────────────
def test_collect_safety_uses_arena_breach_rate():
    out = _col.collect_safety_metrics(
        arena_summary={"breach_rate": 0.07, "season_id": "s42"},
    )
    assert out["adversarial_bypass_rate"]["value"] == 0.07
    assert out["adversarial_bypass_rate"]["source"] == "arena"
    assert "s42" in out["adversarial_bypass_rate"]["raw_evidence"]


def test_collect_safety_false_positive_rate():
    out = _col.collect_safety_metrics(
        arena_summary={"breach_rate": 0.0},
        benign_results={"total": 50, "false_positives": 3,
                        "evidence": "benign_pack_v1"},
    )
    assert out["false_positive_rate"]["value"] == pytest.approx(0.06)
    assert out["false_positive_rate"]["raw_evidence"] == "benign_pack_v1"


def test_collect_safety_critique_reject_rate():
    """Build a safe-plan corpus where 1 of 4 critiques rejects."""
    crits = [
        SimpleNamespace(verdict=lambda: "allow"),
        SimpleNamespace(verdict=lambda: "hold"),
        SimpleNamespace(verdict=lambda: "reject"),
        SimpleNamespace(verdict=lambda: "allow"),
    ]
    out = _col.collect_safety_metrics(
        arena_summary={"breach_rate": 0.0},
        foresight_critiques_safe=crits,
    )
    assert out["plan_critique_reject_rate_safe"]["value"] == 0.25


def test_collect_safety_hallucination_rate():
    out = _col.collect_safety_metrics(
        arena_summary={"breach_rate": 0.0},
        hallucination_probe_results={"total": 20, "hallucinated": 1,
                                     "evidence": "hal_probe_v2"},
    )
    assert out["hallucination_liability_rate"]["value"] == pytest.approx(0.05)


def test_collect_safety_persona_drift():
    out = _col.collect_safety_metrics(
        arena_summary={"breach_rate": 0.0},
        persona_drift_max=0.18,
    )
    assert out["persona_drift_max"]["value"] == 0.18


# ── capability collectors ─────────────────────────────────────
def test_collect_capability_pools_pass_rate():
    runs = [
        SimpleNamespace(passed=8, total=10, duration_s=10.0),
        SimpleNamespace(passed=18, total=20, duration_s=22.0),
    ]
    out = _col.collect_capability_metrics(harness_runs=runs)
    assert out["external_bench_pass_rate"]["value"] == pytest.approx(26 / 30)
    assert out["bench_coverage_count"]["value"] == 2
    # p95 derived from per-item durations (1.0s and 1.1s)
    assert out["p95_latency_s"]["value"] == pytest.approx(1.1, rel=0.01)


def test_collect_capability_explicit_p95_overrides_fallback():
    runs = [SimpleNamespace(passed=1, total=2, duration_s=10.0)]
    out = _col.collect_capability_metrics(harness_runs=runs,
                                          p95_latency_s=2.5)
    assert out["p95_latency_s"]["value"] == 2.5


def test_collect_capability_symbolic_agreement():
    runs = [SimpleNamespace(passed=10, total=10, duration_s=1.0)]
    out = _col.collect_capability_metrics(
        harness_runs=runs,
        symbolic_critic_results={"agreed": 9, "total": 10},
    )
    assert out["symbolic_critic_agreement"]["value"] == 0.9


def test_collect_capability_zero_runs():
    out = _col.collect_capability_metrics(harness_runs=[])
    assert out["external_bench_pass_rate"]["value"] == 0.0
    assert out["bench_coverage_count"]["value"] == 0


# ── operations collectors ─────────────────────────────────────
def test_collect_operations_passthrough():
    out = _col.collect_operations_metrics(
        token_efficiency_ratio=4.0,
        edos_recursion_depth=2,
        cold_start_availability=0.99,
    )
    assert out["token_efficiency_ratio_max"]["value"] == 4.0
    assert out["edos_recursion_depth_max"]["value"] == 2
    assert out["cold_start_availability"]["value"] == 0.99


def test_collect_operations_omits_none():
    out = _col.collect_operations_metrics(token_efficiency_ratio=4.0)
    assert "token_efficiency_ratio_max" in out
    assert "edos_recursion_depth_max" not in out
    assert "cold_start_availability" not in out


# ── hard floors ───────────────────────────────────────────────
def test_collect_hard_floors_defaults_safe():
    hf = _col.collect_hard_floors()
    assert hf["critical_findings"] == 0
    assert hf["honeytoken_extractions"] == 0
    assert hf["human_signoff_present"] is False


# ── compose + write ───────────────────────────────────────────
def test_compose_metrics_round_trips_to_disk(tmp_path):
    payload = _col.compose_metrics(
        safety={"adversarial_bypass_rate":
                {"value": 0.05, "source": "arena", "raw_evidence": "x"}},
        capability={"external_bench_pass_rate":
                    {"value": 0.9, "source": "apex.harness", "raw_evidence": "y"}},
        operations={"token_efficiency_ratio_max":
                    {"value": 5.0, "source": "fleet", "raw_evidence": "z"}},
        hard_floors=_col.collect_hard_floors(human_signoff_present=True),
    )
    p = _col.write_metrics(payload, tmp_path / "metrics.json")
    assert p.exists()
    back = json.loads(p.read_text())
    assert back["safety"]["adversarial_bypass_rate"]["value"] == 0.05
    assert back["hard_floors"]["human_signoff_present"] is True


# ── cli_collect (integration) ─────────────────────────────────
def test_cli_metrics_only_via_evidence(tmp_path):
    out = tmp_path / "m.json"
    rc = _cli.main([
        "--out", str(out),
        "--evidence", "breach_rate=0.04",
        "--evidence", "benign_total=20", "--evidence", "benign_fps=1",
        "--evidence", "safe_critique_total=10", "--evidence", "safe_critique_rejects=0",
        "--evidence", "hallucination_total=20", "--evidence", "hallucination_hits=1",
        "--evidence", "persona_drift_max=0.10",
        "--evidence", "p95_latency_s=8.0",
        "--evidence", "symbolic_agreed=19", "--evidence", "symbolic_total=20",
        "--evidence", "token_efficiency=4.0",
        "--evidence", "edos_depth=2",
        "--evidence", "cold_start_avail=0.99",
        "--evidence", "human_signoff_present=true",
    ])
    assert rc == 0
    body = json.loads(out.read_text())
    assert body["safety"]["adversarial_bypass_rate"]["value"] == 0.04
    # bench coverage will be 0 because no harness runs were given.
    assert body["capability"]["bench_coverage_count"]["value"] == 0
    assert body["operations"]["edos_recursion_depth_max"]["value"] == 2
    assert body["hard_floors"]["human_signoff_present"] is True


def test_cli_runs_json_feeds_capability(tmp_path):
    runs_path = tmp_path / "runs.json"
    runs_path.write_text(json.dumps([
        {"passed": 8, "total": 10, "duration_s": 10.0,
         "cmd": ["x"], "returncode": 0,
         "pass_rate": 0.8, "parse_source": "json", "parse_error": "",
         "apex_url": "http://x", "apex_model_name": "m"},
        {"passed": 18, "total": 20, "duration_s": 22.0,
         "cmd": ["y"], "returncode": 0,
         "pass_rate": 0.9, "parse_source": "json", "parse_error": "",
         "apex_url": "http://x", "apex_model_name": "m"},
    ]))
    out = tmp_path / "m.json"
    rc = _cli.main([
        "--out", str(out),
        "--runs-json", str(runs_path),
        "--evidence", "breach_rate=0.0",
        "--evidence", "p95_latency_s=2.0",
    ])
    assert rc == 0
    body = json.loads(out.read_text())
    cap = body["capability"]
    assert cap["bench_coverage_count"]["value"] == 2
    assert cap["external_bench_pass_rate"]["value"] == pytest.approx(26 / 30)
    assert cap["p95_latency_s"]["value"] == 2.0


def test_cli_certify_chain_dry_run(tmp_path):
    """End-to-end: M14 collect → write metrics → M15 certify in one call."""
    out = tmp_path / "m.json"
    cert_out = tmp_path / "certs"
    rc = _cli.main([
        "--out", str(out),
        "--agent-id", "e2e-bot",
        "--certify", "--dry-run-cert",
        "--cert-out", str(cert_out),
        "--signoff-by", "Test Operator",
        # AAA-grade evidence
        "--evidence", "breach_rate=0.01",
        "--evidence", "benign_total=20", "--evidence", "benign_fps=0",
        "--evidence", "safe_critique_total=10", "--evidence", "safe_critique_rejects=0",
        "--evidence", "hallucination_total=20", "--evidence", "hallucination_hits=0",
        "--evidence", "persona_drift_max=0.05",
        "--evidence", "p95_latency_s=2.0",
        "--evidence", "symbolic_agreed=20", "--evidence", "symbolic_total=20",
        "--evidence", "token_efficiency=3.0",
        "--evidence", "edos_depth=1",
        "--evidence", "cold_start_avail=0.999",
    ])
    # AAA-grade metrics + a single fake bench run still yields capability
    # coverage = 0 (no runs), so bench_coverage_count → FAIL band → DENY.
    # Add a runs file so capability passes.
    # Re-run with runs json:
    runs_path = tmp_path / "runs.json"
    runs_path.write_text(json.dumps([
        {"passed": 1, "total": 1, "duration_s": 1.0, "cmd": [],
         "returncode": 0, "pass_rate": 1.0, "parse_source": "json",
         "parse_error": "", "apex_url": "", "apex_model_name": ""}
        for _ in range(30)
    ]))
    out2 = tmp_path / "m2.json"
    rc = _cli.main([
        "--out", str(out2),
        "--runs-json", str(runs_path),
        "--agent-id", "e2e-bot",
        "--certify", "--dry-run-cert",
        "--cert-out", str(cert_out),
        "--signoff-by", "Test Operator",
        "--evidence", "breach_rate=0.01",
        "--evidence", "benign_total=20", "--evidence", "benign_fps=0",
        "--evidence", "safe_critique_total=10", "--evidence", "safe_critique_rejects=0",
        "--evidence", "hallucination_total=20", "--evidence", "hallucination_hits=0",
        "--evidence", "persona_drift_max=0.05",
        "--evidence", "p95_latency_s=2.0",
        "--evidence", "symbolic_agreed=20", "--evidence", "symbolic_total=20",
        "--evidence", "token_efficiency=3.0",
        "--evidence", "edos_depth=1",
        "--evidence", "cold_start_avail=0.999",
    ])
    assert rc == 0  # cert pipeline returns 0 on PASS
    bundles = list((cert_out / "dry_run").glob("cert_e2e-bot_*.json"))
    assert len(bundles) >= 1
    bodies = [json.loads(b.read_text()) for b in bundles]
    pass_bodies = [b for b in bodies if b["verdict"] == "DRY-RUN-PASS"]
    assert pass_bodies, f"no DRY-RUN-PASS in {[b['verdict'] for b in bodies]}"
    assert pass_bodies[-1]["letter_grade"] == "AAA"
