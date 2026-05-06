"""``nail certify-agent`` — CLI for the M15 cert pipeline.

Usage (flag-driven):

    python -m nail_harness.cli_certify \\
        --agent-id acme-customer-bot-v3 \\
        --metrics-json /path/to/metrics.json \\
        [--signoff-by "Alice Smith"] \\
        [--dry-run] \\
        [--output-dir certifications/]

Usage (config-driven — preferred for repeatable runs):

    python -m nail_harness.cli_certify --config run_config.yaml

The config file (YAML or JSON) carries everything the CLI flags would,
so a real run isn't a wall of --evidence flags. Schema::

    # run_config.yaml
    agent_id:     "agent-under-test-v3"
    metrics_json: "/runs/2026-04-27/metrics.json"
    signoff_by:   "Operator Name"
    output_dir:   "certifications/"
    dry_run:      false
    thresholds:   null            # null = use installed default
    # optional bookkeeping (preserved into bundle metadata via metrics.json):
    vendor:       "Vendor Inc."
    contact:      "ai-ops@vendor.example"
    notes:        "First production cert"

Any flag passed on the command line overrides the same key in the config
file, so you can keep one config and override --dry-run for rehearsals.

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
        "human_signoff_present": true,
        "m17_passed": true
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


def _load_config(path: str | None) -> dict:
    """Load a YAML or JSON client config. Returns {} when path is None."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {p}")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "PyYAML required to read YAML configs; "
                "use a .json config or `pip install pyyaml`."
            ) from e
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"config must be a mapping, got {type(data).__name__}")
    return data


_CONFIG_KEYS = (
    "agent_id", "metrics_json", "signoff_by",
    "output_dir", "dry_run", "thresholds",
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nail-certify-agent",
        description="Run NAIL agent certification pipeline (M15).",
    )
    p.add_argument("--config", default=None,
                   help="Path to a run_config.yaml or .json. Flag values "
                        "below override matching keys in the config.")
    p.add_argument("--agent-id", default=None,
                   help="Stable identifier for the agent under test.")
    p.add_argument("--metrics-json", default=None,
                   help="Path to a metrics JSON file (see docstring).")
    p.add_argument("--signoff-by", default=None,
                   help="Human operator name. REQUIRED for non-dry-run "
                        "passes (per H5).")
    p.add_argument("--output-dir", default=None,
                   help="Where to write the cert bundle JSON. "
                        "Default: <repo>/certifications/")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip the model-gate; verdict prefixed DRY-RUN-.")
    p.add_argument("--thresholds", default=None,
                   help="Override path to thresholds.json.")
    args = p.parse_args(argv)

    # ── merge config ← flags (flags win when explicitly passed) ──────
    try:
        cfg = _load_config(args.config)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    def pick(flag_val, key, *, is_bool: bool = False):
        if is_bool:
            # argparse store_true defaults False; only override config
            # if the flag was actually passed (i.e. True).
            return True if flag_val else bool(cfg.get(key, False))
        return flag_val if flag_val is not None else cfg.get(key)

    agent_id     = pick(args.agent_id,     "agent_id")
    metrics_json = pick(args.metrics_json, "metrics_json")
    signoff_by   = pick(args.signoff_by,   "signoff_by")
    output_dir   = pick(args.output_dir,   "output_dir")
    dry_run      = pick(args.dry_run,      "dry_run", is_bool=True)
    thresholds_p = pick(args.thresholds,   "thresholds")

    if not agent_id:
        print("error: agent_id is required (via --agent-id or config)",
              file=sys.stderr)
        return 2
    if not metrics_json:
        print("error: metrics_json is required (via --metrics-json or config)",
              file=sys.stderr)
        return 2

    metrics_path = Path(metrics_json)
    if not metrics_path.exists():
        print(f"error: metrics file not found: {metrics_path}", file=sys.stderr)
        return 2

    payload = json.loads(metrics_path.read_text())
    thresholds = load_thresholds(thresholds_p)
    mc = _build_metric_collection(payload, thresholds)

    req = CertRequest(
        agent_id=agent_id, metrics=mc,
        human_signoff_by=signoff_by,
        output_dir=output_dir, dry_run=dry_run,
    )

    try:
        bundle, out_path = certify_agent(req, thresholds_path=thresholds_p)
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
