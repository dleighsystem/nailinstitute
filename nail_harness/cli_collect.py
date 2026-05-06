"""``nail collect-metrics`` — M14 driver.

End-to-end runner that drives a target subprocess agent through the
NAIL safety + capability + ops measurements, composes a metrics
JSON, optionally pipes it straight into the M15 cert pipeline.

This CLI is the integration glue between:

    * the ``apex.harness`` external-bench runner (M11)
    * the ``arena`` / ``foresight`` / ``canary`` evidence sources
    * the ``cert_pipeline`` scorer + signer (M15)

Two modes:

    --metrics-only    write metrics.json and stop
    --certify         then immediately call certify_agent() (passes
                      --dry-run through unless the model gate is open)

For now (M14 v1), only the apex.harness leg drives a real subprocess.
The arena/foresight/canary metrics are accepted as ``--evidence
KEY=VAL`` overrides until those packages each ship a
``run_for_cert()`` shim. This lets us prove the wiring end-to-end
without waiting for M13.1 or refactoring the safety packages.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .cert_collectors import (
    collect_safety_metrics,
    collect_capability_metrics,
    collect_operations_metrics,
    collect_hard_floors,
    compose_metrics,
    write_metrics,
)


def _parse_kv(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for kv in items or []:
        if "=" in kv:
            k, v = kv.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _maybe_float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    return float(s)


def _maybe_int(s: str | None) -> int | None:
    if s is None or s == "":
        return None
    return int(s)


def _maybe_bool(s: str | None) -> bool:
    if s is None:
        return False
    return s.strip().lower() in ("1", "true", "yes", "y")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nail-collect-metrics",
        description="Drive an agent through the NAIL safety+capability "
                    "measurements and emit a metrics.json (M14).",
    )
    # Capability — apex.harness leg.
    p.add_argument("--bench-cmd", default=None,
                   help="Shell command for one external bench (M11). "
                        "Repeatable behaviour comes via multiple invocations "
                        "feeding --runs-json instead.")
    p.add_argument("--bench-cwd", default=None)
    p.add_argument("--results-json", default=None,
                   help="Path bench writes pass/fail JSON (M11).")
    p.add_argument("--regex", default=None,
                   help="Stdout regex with two int groups (passed, total).")
    p.add_argument("--bench-timeout", type=float, default=600.0)
    p.add_argument("--bench-port", type=int, default=None)
    p.add_argument("--apex-model-name", default="apex-matrix-swarm")
    p.add_argument("--runs-json", default=None,
                   help="Pre-computed list of HarnessRun.to_dict() outputs "
                        "(JSON array). Use this to feed multiple bench "
                        "results without re-running them.")
    # Safety / ops evidence (until each package ships its own shim).
    p.add_argument("--evidence", action="append", default=[],
                   help="KEY=VALUE evidence overrides. Recognised keys: "
                        "breach_rate, benign_total, benign_fps, "
                        "safe_critique_total, safe_critique_rejects, "
                        "hallucination_total, hallucination_hits, "
                        "persona_drift_max, p95_latency_s, "
                        "symbolic_agreed, symbolic_total, "
                        "token_efficiency, edos_depth, cold_start_avail, "
                        "critical_findings, honeytoken_extractions, "
                        "tool_auth_bypasses, pii_secret_leaks, "
                        "human_signoff_present, m17_passed")
    # Output / certify chain.
    p.add_argument("--out", required=True,
                   help="Where to write the metrics.json")
    p.add_argument("--agent-id", default=None,
                   help="If set together with --certify, run the cert "
                        "pipeline immediately on the metrics.")
    p.add_argument("--certify", action="store_true")
    p.add_argument("--signoff-by", default=None)
    p.add_argument("--dry-run-cert", action="store_true",
                   help="Forward --dry-run to the cert pipeline.")
    p.add_argument("--cert-out", default=None,
                   help="Output dir for the cert bundle (default: certifications/)")
    args = p.parse_args(argv)

    ev = _parse_kv(args.evidence)

    # ── 1. Capability: gather HarnessRun-shaped objects ───────────
    runs: list[dict] = []
    if args.runs_json:
        runs.extend(json.loads(Path(args.runs_json).read_text()))
    if args.bench_cmd:
        # Real M11 invocation.
        try:
            from apex.harness import HarnessConfig, run_harness
        except Exception as exc:
            print(f"error: --bench-cmd needs apex installed ({exc})",
                  file=sys.stderr)
            return 4
        cmd = shlex.split(args.bench_cmd)
        cfg = HarnessConfig(
            cmd=cmd, cwd=args.bench_cwd,
            results_json=args.results_json,
            stdout_regex=args.regex,
            timeout_s=args.bench_timeout,
            port=args.bench_port,
            model_name=args.apex_model_name,
            boot_wait_s=2.0,
        )
        run = run_harness(cfg)
        runs.append(run.to_dict())

    # Build harness-run-like duck objects for the collector.
    class _DuckRun:
        def __init__(self, d): self.__dict__.update(d)

    duck_runs = [_DuckRun(r) for r in runs]

    # ── 2. Safety / ops blocks from --evidence overrides ──────────
    safe_critiques = None
    safe_total = _maybe_int(ev.get("safe_critique_total"))
    safe_rej = _maybe_int(ev.get("safe_critique_rejects"))
    if safe_total is not None and safe_rej is not None:
        # Build phantom Critique-like objects so the collector function
        # works without us having to import foresight here.
        class _PhantomCrit:
            def __init__(self, is_reject):
                self._r = is_reject
            def verdict(self): return "reject" if self._r else "allow"
        safe_critiques = (
            [_PhantomCrit(True)] * safe_rej +
            [_PhantomCrit(False)] * (safe_total - safe_rej)
        )

    safety = collect_safety_metrics(
        arena_summary={"breach_rate": float(ev.get("breach_rate", "1.0")),
                       "season_id": ev.get("season_id", "")},
        benign_results=(
            {"total": _maybe_int(ev.get("benign_total")),
             "false_positives": _maybe_int(ev.get("benign_fps")),
             "evidence": ev.get("benign_evidence", "")}
            if ev.get("benign_total") and ev.get("benign_fps") is not None else None
        ),
        foresight_critiques_safe=safe_critiques,
        hallucination_probe_results=(
            {"total": _maybe_int(ev.get("hallucination_total")),
             "hallucinated": _maybe_int(ev.get("hallucination_hits")),
             "evidence": ev.get("hallucination_evidence", "")}
            if ev.get("hallucination_total") and ev.get("hallucination_hits") is not None else None
        ),
        persona_drift_max=_maybe_float(ev.get("persona_drift_max")),
        arena_evidence=ev.get("arena_evidence", ""),
    )

    sym_agreed = _maybe_int(ev.get("symbolic_agreed"))
    sym_total = _maybe_int(ev.get("symbolic_total"))
    sym = ({"agreed": sym_agreed, "total": sym_total}
           if sym_agreed is not None and sym_total is not None else None)

    capability = collect_capability_metrics(
        harness_runs=duck_runs,
        p95_latency_s=_maybe_float(ev.get("p95_latency_s")),
        symbolic_critic_results=sym,
    )

    operations = collect_operations_metrics(
        token_efficiency_ratio=_maybe_float(ev.get("token_efficiency")),
        edos_recursion_depth=_maybe_int(ev.get("edos_depth")),
        cold_start_availability=_maybe_float(ev.get("cold_start_avail")),
    )

    hard_floors = collect_hard_floors(
        critical_findings=int(ev.get("critical_findings", "0")),
        honeytoken_extractions=int(ev.get("honeytoken_extractions", "0")),
        tool_auth_bypasses=int(ev.get("tool_auth_bypasses", "0")),
        pii_secret_leaks=int(ev.get("pii_secret_leaks", "0")),
        human_signoff_present=_maybe_bool(ev.get(
            "human_signoff_present",
            "true" if args.signoff_by else "false")),
        m17_passed=_maybe_bool(ev.get(
            "m17_passed",
            "true" if args.signoff_by else "false")),
    )

    payload = compose_metrics(
        safety=safety, capability=capability,
        operations=operations, hard_floors=hard_floors,
    )

    out_path = write_metrics(payload, args.out)
    print(f"metrics: {out_path}")
    print(f"  safety     keys: {list(payload['safety'].keys())}")
    print(f"  capability keys: {list(payload['capability'].keys())}")
    print(f"  operations keys: {list(payload['operations'].keys())}")
    print(f"  hard_floors    : {payload['hard_floors']}")

    if not args.certify:
        return 0

    if not args.agent_id:
        print("error: --certify requires --agent-id", file=sys.stderr)
        return 5

    # Hand off to M15.
    from .cli_certify import main as certify_main
    cert_argv = [
        "--agent-id", args.agent_id,
        "--metrics-json", str(out_path),
    ]
    if args.signoff_by:
        cert_argv += ["--signoff-by", args.signoff_by]
    if args.cert_out:
        cert_argv += ["--output-dir", args.cert_out]
    if args.dry_run_cert:
        cert_argv += ["--dry-run"]
    print("--- certify ---")
    return certify_main(cert_argv)


if __name__ == "__main__":
    raise SystemExit(main())
