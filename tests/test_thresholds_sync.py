"""Regression test: run the thresholds sync checker as part of pytest."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_certification_thresholds_in_sync():
    script = ROOT / "scripts" / "check_thresholds_sync.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert proc.returncode == 0, (
        f"thresholds out of sync.\nstdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )


def test_thresholds_json_loads_and_has_required_shape():
    import json
    js = ROOT / "nail_harness" / "thresholds.json"
    data = json.loads(js.read_text())
    for key in ("version", "hard_floors", "axes", "composite_bands"):
        assert key in data, f"missing top-level key: {key}"
    for axis in ("safety", "capability", "operations"):
        assert axis in data["axes"], f"missing axis: {axis}"
        assert "weight" in data["axes"][axis]
        assert "metrics" in data["axes"][axis]
    weights = sum(data["axes"][a]["weight"] for a in data["axes"])
    assert abs(weights - 1.0) < 1e-6, f"weights must sum to 1.0; got {weights}"
    for band in ("AAA", "AA", "A", "FAIL"):
        assert band in data["composite_bands"]


def test_certification_thresholds_md_present():
    md = ROOT / "CERTIFICATION_THRESHOLDS.md"
    assert md.exists(), "CERTIFICATION_THRESHOLDS.md must exist at repo root"
    text = md.read_text()
    assert "Hard Floors" in text
    assert "Composite" in text
    assert "Continuous-Monitoring" in text
