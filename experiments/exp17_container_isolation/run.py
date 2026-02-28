#!/usr/bin/env python3
"""
EXPERIMENT 17: Container Isolation — Master Runner
═══════════════════════════════════════════════════
NAIL Institute

Runs all three sub-experiments from container-isolation.md:
  17a: GPU Non-Determinism Under Load (Fact 1)
  17b: Phantom Tool Failures / Agentic Paranoia (Theory 1)
  17c: Resource Blindness / Logical Mutilation (Theory 2)

Usage:
  python run.py          # Run all three
  python run.py 17a      # Run only GPU non-determinism
  python run.py 17b 17c  # Run specific sub-experiments
"""

import sys
import json
import time
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def run_all(selected=None):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    experiments = {
        "17a": ("exp17a_gpu_nondeterminism", "GPU Non-Determinism Under Load"),
        "17b": ("exp17b_phantom_tool_failures", "Phantom Tool Failures"),
        "17c": ("exp17c_resource_blindness", "Resource Blindness"),
    }

    if selected is None:
        selected = ["17a", "17b", "17c"]

    print("=" * 70)
    print("EXPERIMENT 17: Container Isolation — Master Runner")
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Sub-experiments: {', '.join(selected)}")
    print("=" * 70)
    print(flush=True)

    combined_results = {
        "experiment": "17_container_isolation",
        "timestamp": datetime.now().isoformat(),
        "sub_experiments": {},
    }

    total_t0 = time.time()

    for exp_id in selected:
        if exp_id not in experiments:
            print(f"\n⚠️  Unknown experiment: {exp_id}, skipping")
            continue

        module_name, description = experiments[exp_id]
        print(f"\n{'#' * 70}")
        print(f"# RUNNING: Exp {exp_id} — {description}")
        print(f"{'#' * 70}\n")

        t0 = time.time()
        try:
            # Dynamic import
            mod = __import__(module_name)
            result = mod.run_experiment()
            elapsed = time.time() - t0
            combined_results["sub_experiments"][exp_id] = {
                "status": "complete",
                "elapsed_minutes": elapsed / 60,
                "result_summary": {
                    k: v for k, v in result.items()
                    if k not in ("results",)  # Skip raw results in combined
                },
            }
            print(f"\n✅ Exp {exp_id} completed in {elapsed/60:.1f} minutes")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"\n❌ Exp {exp_id} FAILED after {elapsed/60:.1f} minutes: {e}")
            import traceback
            traceback.print_exc()
            combined_results["sub_experiments"][exp_id] = {
                "status": "failed",
                "elapsed_minutes": elapsed / 60,
                "error": str(e),
            }

    total_elapsed = time.time() - total_t0
    combined_results["total_elapsed_minutes"] = total_elapsed / 60

    # ── Combined Summary ────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("EXPERIMENT 17: COMBINED SUMMARY")
    print(f"{'=' * 70}")
    print(f"\n  Total runtime: {total_elapsed/60:.1f} minutes\n")

    for exp_id, info in combined_results["sub_experiments"].items():
        status = "✅" if info["status"] == "complete" else "❌"
        print(f"  {status} Exp {exp_id}: {info['status']} "
              f"({info['elapsed_minutes']:.1f} min)")

    print(flush=True)

    # Save combined results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    outfile = RESULTS_DIR / f"exp17_combined_{ts}.json"
    latest = RESULTS_DIR / "exp17_combined_latest.json"
    for fpath in [outfile, latest]:
        with open(fpath, "w") as f:
            json.dump(combined_results, f, indent=2, default=str)
    print(f"\nCombined results saved to {outfile}")


if __name__ == "__main__":
    selected = sys.argv[1:] if len(sys.argv) > 1 else None
    run_all(selected)
