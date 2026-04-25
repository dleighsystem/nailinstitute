#!/usr/bin/env python3
"""``nail-inspect-cert`` — pretty-print + verify a NAIL cert bundle.

Usage:
    python scripts/inspect_cert.py path/to/cert_<id>_<sha12>.json
    python scripts/inspect_cert.py path/to/cert_<id>_<sha12>.json --verify
    python scripts/inspect_cert.py path/to/cert_<id>_<sha12>.json --json

What it prints:
    * verdict / letter grade / composite
    * per-axis scores with grade
    * per-metric scores grouped by axis (if metric_evidence present)
    * hard-floor table (PASS/FAIL each)
    * fingerprint (and recomputed sha256 in --verify mode)
    * issuance metadata: timestamp, signoff, NAIL commit, thresholds version

Exit codes:
    0  bundle parses, verdict is PASS or DRY-RUN-PASS
    1  bundle parses but verdict is DENIED / DRY-RUN-DENIED-* or hard-floor failed
    2  bundle file unreadable or malformed
    3  --verify failed (bundle_sha256 doesn't match recomputed)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _c(s: str, color: str, *, on: bool) -> str:
    return f"{color}{s}{RESET}" if on else s


def _verdict_color(v: str) -> str:
    if v == "PASS":
        return GREEN
    if v == "DRY-RUN-PASS":
        return YELLOW
    return RED


def _grade_color(g: str) -> str:
    return {"AAA": GREEN, "AA": GREEN, "A": YELLOW}.get(g, RED)


def _recompute_fingerprint(bundle: dict) -> str:
    """Match cert_pipeline.CertBundle.fingerprint() canonicalisation:
    sort keys, drop the bundle_sha256 field, sha256 the resulting JSON."""
    b = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    canonical = json.dumps(b, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def render(bundle: dict, *, color: bool, show_metrics: bool) -> str:
    lines: list[str] = []
    v = bundle.get("verdict", "?")
    g = bundle.get("letter_grade", "?")
    cs = bundle.get("composite", 0.0)

    lines.append("")
    lines.append(_c("─" * 64, DIM, on=color))
    lines.append(f"  agent_id        : {_c(bundle.get('agent_id','?'), BOLD, on=color)}")
    lines.append(f"  verdict         : {_c(v, _verdict_color(v) + BOLD, on=color)}")
    lines.append(f"  letter_grade    : {_c(g, _grade_color(g) + BOLD, on=color)}")
    lines.append(f"  composite       : {cs:.3f}")
    lines.append(f"  issued_utc      : {bundle.get('issued_utc','?')}")
    lines.append(f"  thresholds_ver  : {bundle.get('thresholds_version','?')}")
    lines.append(f"  nail_commit     : {bundle.get('nail_commit','?')}")
    lines.append(f"  signoff         : {bundle.get('human_signoff_by','—')}")
    lines.append(f"  fingerprint     : {bundle.get('bundle_sha256','?')}")
    lines.append(_c("─" * 64, DIM, on=color))

    # Axes
    lines.append("  axis scores:")
    axes = bundle.get("axes", {}) or {}
    for ax_name, ax in axes.items():
        score = ax.get("score", 0.0)
        ax_grade = ax.get("band", ax.get("grade", "?"))
        bar_n = int(round(score * 20))
        bar = "█" * bar_n + "·" * (20 - bar_n)
        lines.append(
            f"    {ax_name:14s} "
            f"[{_c(bar, _grade_color(ax_grade), on=color)}] "
            f"{score:.3f}  ({_c(ax_grade, _grade_color(ax_grade), on=color)})"
        )
        if show_metrics:
            scores = ax.get("metric_scores", {}) or {}
            bands = ax.get("metric_band", {}) or {}
            evidence = bundle.get("metric_evidence", {}).get(ax_name, {}) or {}
            for mn in sorted(scores):
                ms = scores[mn]
                mg = bands.get(mn, "?")
                mv = evidence.get(mn, {}).get("value", "—")
                lines.append(
                    f"        {mn:34s} val={mv!s:<8s} "
                    f"score={ms:.3f}  ({_c(mg, _grade_color(mg), on=color)})"
                )

    # Hard floors
    lines.append(_c("─" * 64, DIM, on=color))
    lines.append("  hard floors:")
    hf = bundle.get("hard_floor_results", {}) or {}
    if not hf:
        lines.append("    (none recorded)")
    for k, ok in hf.items():
        tag = _c("PASS", GREEN, on=color) if ok else _c("FAIL", RED + BOLD, on=color)
        lines.append(f"    {k:34s} {tag}")

    # Denial reasons (only present on failures)
    reasons = bundle.get("denial_reasons", []) or []
    if reasons:
        lines.append(_c("─" * 64, DIM, on=color))
        lines.append(_c("  denial reasons:", RED + BOLD, on=color))
        for r in reasons:
            lines.append(f"    - {r}")

    lines.append(_c("─" * 64, DIM, on=color))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nail-inspect-cert")
    p.add_argument("bundle", help="Path to a cert bundle JSON")
    p.add_argument("--verify", action="store_true",
                   help="Recompute bundle_sha256 and refuse mismatches.")
    p.add_argument("--json", action="store_true",
                   help="Emit the bundle as raw indented JSON instead of pretty.")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--no-metrics", action="store_true",
                   help="Skip per-metric breakdown under each axis.")
    args = p.parse_args(argv)

    path = Path(args.bundle)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    try:
        bundle = json.loads(path.read_text())
    except Exception as e:
        print(f"error: not valid JSON: {e}", file=sys.stderr)
        return 2

    color = sys.stdout.isatty() and not args.no_color

    if args.json:
        print(json.dumps(bundle, indent=2, sort_keys=True))
    else:
        print(render(bundle, color=color, show_metrics=not args.no_metrics))

    if args.verify:
        claimed = bundle.get("bundle_sha256", "")
        recomputed = _recompute_fingerprint(bundle)
        if claimed == recomputed:
            print(_c(f"  ✓ fingerprint verified  ({recomputed})", GREEN, on=color))
        else:
            print(_c(f"  ✗ FINGERPRINT MISMATCH", RED + BOLD, on=color))
            print(f"    claimed   : {claimed}")
            print(f"    recomputed: {recomputed}")
            return 3

    v = bundle.get("verdict", "")
    if v in ("PASS", "DRY-RUN-PASS"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
