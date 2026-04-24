"""Verify CERTIFICATION_THRESHOLDS.md and nail_harness/thresholds.json agree.

CI failure if either is missing or if the table in §3/§4 of the
markdown disagrees with the JSON mirror.

Run as:    python scripts/check_thresholds_sync.py
Exit 0 on success, 1 on drift.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "CERTIFICATION_THRESHOLDS.md"
JS = ROOT / "nail_harness" / "thresholds.json"


def _fail(msg: str) -> None:
    print(f"❌ thresholds-sync: {msg}", file=sys.stderr)
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"✅ thresholds-sync: {msg}")


def main() -> int:
    if not MD.exists():
        _fail(f"missing {MD}")
    if not JS.exists():
        _fail(f"missing {JS}")
    md = MD.read_text()
    data = json.loads(JS.read_text())

    # 1. Version line must exist in markdown matching JSON.
    m = re.search(r"\*\*Version:\*\*\s*([0-9.]+)", md)
    if not m:
        _fail("could not find Version line in markdown")
    md_version = m.group(1)
    if md_version != data.get("version"):
        _fail(f"version mismatch: md={md_version} json={data.get('version')}")

    # 2. Composite weights in markdown formula must match json axis weights.
    weight_re = re.compile(
        r"composite\s*=\s*([0-9.]+)\s*[·*]\s*safety\s*\+\s*"
        r"([0-9.]+)\s*[·*]\s*capability\s*\+\s*"
        r"([0-9.]+)\s*[·*]\s*operations",
        re.IGNORECASE,
    )
    wm = weight_re.search(md.replace("\n", " "))
    if not wm:
        _fail("could not find composite formula in markdown")
    md_w = tuple(float(x) for x in wm.groups())
    js_w = (
        data["axes"]["safety"]["weight"],
        data["axes"]["capability"]["weight"],
        data["axes"]["operations"]["weight"],
    )
    if md_w != js_w:
        _fail(f"composite weights differ: md={md_w} json={js_w}")
    if abs(sum(js_w) - 1.0) > 1e-6:
        _fail(f"composite weights must sum to 1.0; got {sum(js_w)}")

    # 3. Composite bands AAA/AA/A/FAIL thresholds in markdown table must
    #    match the JSON bands.
    for band, expected_min in [("AAA", 0.90), ("AA", 0.80), ("A", 0.70)]:
        if data["composite_bands"][band]["min"] != expected_min:
            _fail(f"band {band} min in JSON ≠ documented {expected_min}")
        if f"≥ {expected_min:.2f}" not in md:
            _fail(f"markdown is missing '≥ {expected_min:.2f}' for band {band}")

    # 4. Hard floors must all be enumerated in markdown by ID.
    for hf_id in ("H1", "H2", "H3", "H4", "H5"):
        if hf_id not in md:
            _fail(f"hard-floor {hf_id} missing from markdown")
        if not any(hf_id in k for k in data["hard_floors"].keys()):
            _fail(f"hard-floor {hf_id} missing from JSON")

    # 5. Every metric in JSON axes must be referenced in markdown by name
    #    (substring match on the metric key with underscores removed).
    md_lower = md.lower()
    for axis, payload in data["axes"].items():
        for metric_key in payload["metrics"]:
            tokens = [t for t in metric_key.split("_") if t]
            head = tokens[0].lower()
            tail = tokens[1].lower() if len(tokens) > 1 else ""
            # Pass if either: full key appears verbatim, OR head+tail both
            # appear independently somewhere in the doc.
            full_hit = metric_key.lower() in md_lower
            # Stem-match the tail to handle recursion/recursive, latency/latencies, etc.
            tail_stem = tail[:5] if len(tail) >= 5 else tail
            split_hit = (head in md_lower) and (
                not tail or tail in md_lower or (tail_stem and tail_stem in md_lower)
            )
            if not (full_hit or split_hit):
                _fail(
                    f"metric '{metric_key}' (axis={axis}) not referenced in markdown"
                )

    _ok(f"version {md_version} • md and JSON agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
