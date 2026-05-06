"""NAIL cert metric collectors (M14).

Adapters that turn real package outputs into the metrics-JSON shape
that ``cert_pipeline`` consumes. One adapter per metric source. Each
adapter is **pure** — it takes a result object and returns a dict. No
network, no subprocess, no global state.

The metrics dict produced by ``compose_metrics()`` has exactly the
shape that ``cli_certify._build_metric_collection`` expects, so the
two halves of the pipeline are interchangeable.

Wiring overview (M14):

    arena.SeasonResult          ─┐
    canary.SimResult            ─┤
    foresight.Critique (sample) ─┼─→ collect_safety_metrics()       ─┐
    nail_monitor drift snapshot ─┘                                    │
                                                                      ├─→ compose_metrics()
    apex.harness.HarnessRun     ─┐                                    │      │
    apex.harness benches list   ─┼─→ collect_capability_metrics() ──┤      ▼
    fleet latency snapshot      ─┘                                    │   metrics.json
                                                                      │      │
    fleet token usage           ─┐                                    │      ▼
    arena EDoS probe outcome    ─┼─→ collect_operations_metrics() ──┘   nail_harness.cli_certify
    canary cold-start probe     ─┘                                          │
                                                                            ▼
                                                                       CertBundle
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol


# ── lightweight protocols (so we don't import the whole stack) ─────
class _HasSummary(Protocol):
    def summary(self) -> dict[str, Any]: ...


# ── safety axis ────────────────────────────────────────────────────
def collect_safety_metrics(
    *,
    arena_summary: dict[str, Any],
    benign_results: Optional[dict[str, Any]] = None,
    foresight_critiques_safe: Optional[Iterable[Any]] = None,
    hallucination_probe_results: Optional[dict[str, Any]] = None,
    persona_drift_max: Optional[float] = None,
    arena_evidence: str = "",
) -> dict[str, dict[str, Any]]:
    """Build the ``safety`` block of the metrics JSON.

    Args:
        arena_summary: ``arena.SeasonResult.summary()`` dict —
            we use ``breach_rate`` for adversarial_bypass_rate.
        benign_results: ``{"total": int, "false_positives": int}`` from
            an arena benign-prompt run.
        foresight_critiques_safe: iterable of ``foresight.Critique``
            objects produced against a curated *safe* plan corpus.
            Reject rate over this corpus = plan_critique_reject_rate_safe.
        hallucination_probe_results: ``{"total": int, "hallucinated": int}``
            from a HAL-01 probe pack.
        persona_drift_max: max observed drift score from nail_monitor.
    """
    out: dict[str, dict[str, Any]] = {}

    bypass_rate = float(arena_summary.get("breach_rate", 1.0))
    out["adversarial_bypass_rate"] = {
        "value": bypass_rate, "source": "arena",
        "raw_evidence": arena_evidence or arena_summary.get("season_id", ""),
    }

    if benign_results:
        total = int(benign_results.get("total", 0))
        fps = int(benign_results.get("false_positives", 0))
        fp_rate = (fps / total) if total > 0 else 0.0
        out["false_positive_rate"] = {
            "value": fp_rate, "source": "arena",
            "raw_evidence": benign_results.get("evidence", ""),
        }

    if foresight_critiques_safe is not None:
        crits = list(foresight_critiques_safe)
        total = len(crits)
        rejects = sum(1 for c in crits if _critique_is_reject(c))
        reject_rate = (rejects / total) if total > 0 else 0.0
        out["plan_critique_reject_rate_safe"] = {
            "value": reject_rate, "source": "foresight",
            "raw_evidence": f"safe_plan_corpus_n={total}",
        }

    if hallucination_probe_results:
        total = int(hallucination_probe_results.get("total", 0))
        hits = int(hallucination_probe_results.get("hallucinated", 0))
        rate = (hits / total) if total > 0 else 0.0
        out["hallucination_liability_rate"] = {
            "value": rate, "source": "foresight",
            "raw_evidence": hallucination_probe_results.get("evidence", ""),
        }

    if persona_drift_max is not None:
        out["persona_drift_max"] = {
            "value": float(persona_drift_max), "source": "nail_monitor",
            "raw_evidence": "drift_window",
        }

    return out


def _critique_is_reject(critique: Any) -> bool:
    """Tolerantly detect a REJECT verdict on a foresight Critique."""
    # New-style: callable .verdict(...)
    v = getattr(critique, "verdict", None)
    if callable(v):
        try:
            return str(v()).lower().endswith("reject")
        except Exception:
            pass
    # Property/attribute
    if v is not None:
        return str(v).lower().endswith("reject")
    # Fallback: max severity
    return str(getattr(critique, "max_severity", "")).lower() == "critical"


# ── capability axis ───────────────────────────────────────────────
def collect_capability_metrics(
    *,
    harness_runs: Iterable[Any],
    p95_latency_s: Optional[float] = None,
    symbolic_critic_results: Optional[dict[str, int]] = None,
) -> dict[str, dict[str, Any]]:
    """Build the ``capability`` block.

    Args:
        harness_runs: iterable of ``apex.harness.HarnessRun`` (M11).
            Pooled pass/total → external_bench_pass_rate; distinct
            ``apex_url`` or ``cmd[0]`` count → bench_coverage_count.
            (We use len(runs) as bench coverage by default.)
        p95_latency_s: from fleet telemetry; if None, fall back to max
            ``duration_s / total`` across runs.
        symbolic_critic_results: ``{"agreed": int, "total": int}``
            from foresight.SymbolicCritic ground-truth checks.
    """
    runs = list(harness_runs)
    pooled_passed = sum(int(getattr(r, "passed", 0)) for r in runs)
    pooled_total = sum(int(getattr(r, "total", 0)) for r in runs)
    pass_rate = (pooled_passed / pooled_total) if pooled_total > 0 else 0.0

    out: dict[str, dict[str, Any]] = {
        "external_bench_pass_rate": {
            "value": pass_rate, "source": "apex.harness",
            "raw_evidence": f"runs={len(runs)} passed={pooled_passed}/{pooled_total}",
        },
        "bench_coverage_count": {
            "value": len(runs), "source": "apex.harness",
            "raw_evidence": f"distinct_runs={len(runs)}",
        },
    }

    if p95_latency_s is None and runs:
        # crude fallback: use max wallclock per item across runs
        per_item = []
        for r in runs:
            tot = int(getattr(r, "total", 0))
            dur = float(getattr(r, "duration_s", 0.0))
            if tot > 0 and dur > 0:
                per_item.append(dur / tot)
        if per_item:
            p95_latency_s = _pct(per_item, 95)

    if p95_latency_s is not None:
        out["p95_latency_s"] = {
            "value": float(p95_latency_s), "source": "fleet",
            "raw_evidence": "harness_wallclock_per_item",
        }

    if symbolic_critic_results is not None:
        agreed = int(symbolic_critic_results.get("agreed", 0))
        total = int(symbolic_critic_results.get("total", 0))
        rate = (agreed / total) if total > 0 else 0.0
        out["symbolic_critic_agreement"] = {
            "value": rate, "source": "foresight",
            "raw_evidence": f"sym_agreed={agreed}/{total}",
        }

    return out


# ── operations axis ───────────────────────────────────────────────
def collect_operations_metrics(
    *,
    token_efficiency_ratio: Optional[float] = None,
    edos_recursion_depth: Optional[int] = None,
    cold_start_availability: Optional[float] = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if token_efficiency_ratio is not None:
        out["token_efficiency_ratio_max"] = {
            "value": float(token_efficiency_ratio), "source": "fleet",
            "raw_evidence": "token_io_window",
        }
    if edos_recursion_depth is not None:
        out["edos_recursion_depth_max"] = {
            "value": int(edos_recursion_depth), "source": "arena",
            "raw_evidence": "edos_probe",
        }
    if cold_start_availability is not None:
        out["cold_start_availability"] = {
            "value": float(cold_start_availability), "source": "canary",
            "raw_evidence": "boot_storm_probe",
        }
    return out


# ── hard floors ────────────────────────────────────────────────────────────────
def collect_hard_floors(
    *,
    critical_findings: int = 0,
    honeytoken_extractions: int = 0,
    tool_auth_bypasses: int = 0,
    pii_secret_leaks: int = 0,
    human_signoff_present: bool = False,
    m17_passed: bool = False,
) -> dict[str, Any]:
    return {
        "critical_findings": int(critical_findings),
        "honeytoken_extractions": int(honeytoken_extractions),
        "tool_auth_bypasses": int(tool_auth_bypasses),
        "pii_secret_leaks": int(pii_secret_leaks),
        "human_signoff_present": bool(human_signoff_present),
        "m17_passed": bool(m17_passed),
    }


# ── top-level composer ───────────────────────────────────────────
def compose_metrics(
    *,
    safety: dict[str, dict[str, Any]],
    capability: dict[str, dict[str, Any]],
    operations: dict[str, dict[str, Any]],
    hard_floors: dict[str, Any],
) -> dict[str, Any]:
    """Compose the final metrics JSON payload."""
    return {
        "safety": safety,
        "capability": capability,
        "operations": operations,
        "hard_floors": hard_floors,
    }


def write_metrics(payload: dict[str, Any], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return p


# ── stats helper ─────────────────────────────────────────────────
def _pct(xs: list[float], pct: float) -> float:
    """Simple linear-interpolation percentile (no numpy)."""
    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (pct / 100.0) * (len(s) - 1)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)
