"""``nail certify-agent`` — CLI for the M15 cert pipeline.

Usage:

    python -m nail_harness.cli_certify \\
        --agent-id acme-customer-bot-v3 \\
        --metrics-json /path/to/metrics.json \\
        [--signoff-by "Alice Smith"] \\
        [--dry-run] \\
        [--output-dir certifications/]

The metrics JSON maps axis → metric_key → {value, source, raw_evidence}
plus a top-level ``hard_floors`` dict, e.g.::

    {
      "safety": {
        "adversarial_bypass_rate": {"value": 0.04, "source": "arena",
                                    "raw_evidence": "battle_log_xyz.json"},
        ...
      },
      "capability": {...},
      "operations": {...},
      "hard_floors": {
        "critical_findings": 0, "honeytoken_extractions": 0,
        "tool_auth_bypasses": 0, "pii_secret_leaks": 0,
        "human_signoff_present": true
      }
    }

In production, this metrics JSON is produced by the upstream
adapters (``arena.export_for_cert``, ``apex.harness.HarnessRun``,
``foresight`` outputs, etc.) — to be wired in M14.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cert_pipeline import (
    CertRequest, MetricCollection, MetricValue,
    certify_agent, load_thresholds,
)


def _build_metric_collection(payload: dict, thresholds: dict) -> MetricCollection:
    mc = MetricCollection()
    for axis in ("safety", "capability", "operations"):
        axis_in = payload.get(axis, {})
        axis_spec = thresholds["axes"][axis]["metrics"]
        for metric_key, entry in axis_in.items():
            spec = axis_spec.get(metric_key)
            if spec is None:
                # Unknown metric — accept but with empty direction so
                # scoring will treat it as missing.
                direction = "max"
            else:
                direction = spec.get("direction", "max")
            mv = MetricValue(
                name=metric_key,
                value=float(entry["value"]),
                direction=direction,
                source=str(entry.get("source", "")),
                raw_evidence=str(entry.get("raw_evidence", "")),
            )
            getattr(mc, axis)[metric_key] = mv
    mc.hard_floors = dict(payload.get("hard_floors", {}))
    return mc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nail-certify-agent",
        description="Run NAIL agent certification pipeline (M15).",
    )
    p.add_argument("--agent-id", required=True,
                   help="Stable identifier for the agent under test.")
    p.add_argument("--metrics-json", required=True,
                   help="Path to a metrics JSON file (see docstring).")
    p.add_argument("--signoff-by", default=None,
                   help="Human operator name. REQUIRED for non-dry-run "
                        "passes (per H5).")
    p.add_argument("--output-dir", default=None,
                   help="Where to write the cert bundle JSON. "
                        "Default: <repo>/certifications/")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip the model-gate; verdict prefixed DRY-RUN-.")
    p.add_argument("--thresholds",
                   default=None,
                   help="Override path to thresholds.json.")
    args = p.parse_args(argv)

    metrics_path = Path(args.metrics_json)
    if not metrics_path.exists():
        print(f"error: metrics file not found: {metrics_path}", file=sys.stderr)
        return 2

    payload = json.loads(metrics_path.read_text())
    thresholds = load_thresholds(args.thresholds)
    mc = _build_metric_collection(payload, thresholds)

    req = CertRequest(
        agent_id=args.agent_id, metrics=mc,
        human_signoff_by=args.signoff_by,
        output_dir=args.output_dir, dry_run=args.dry_run,
    )

    try:
        bundle, out_path = certify_agent(req, thresholds_path=args.thresholds)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    print(f"agent     : {bundle.agent_id}")
    print(f"composite : {bundle.composite}  ({bundle.letter_grade})")
    print(f"verdict   : {bundle.verdict}")
    if bundle.denial_reasons:
        for r in bundle.denial_reasons:
            print(f"  - {r}")
    print(f"bundle    : {out_path}")
    print(f"sha256    : {bundle.bundle_sha256}")
    return 0 if bundle.verdict.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
