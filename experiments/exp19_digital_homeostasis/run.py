"""
NAIL Institute — Experiment 19: Digital Homeostasis
====================================================
Master runner for all Experiment 19 sub-experiments.

Phase 2 of the Build-Solution Manifesto:
"Build the Agentic Immune System"

Sub-experiments:
  19a — Macrophage: Deadlock detection + agent kill/respawn
  19b — Apoptosis:  Convergence detection + state purge + entropy injection
  19c — Compound:   Multi-pathology pipeline defense

USAGE:
  conda activate nail_experiments
  cd /home/dleighsystems/Desktop/NAIL\ institute/experiments
  python -m exp19_digital_homeostasis.run

  Or with nohup:
  PYTHONUNBUFFERED=1 nohup conda run --no-capture-output -n nail_experiments \
    python -u -m exp19_digital_homeostasis.run > ../exp19.log 2>&1 &
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import DATA_DIR


def run_all():
    """Run all Experiment 19 sub-experiments sequentially."""
    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  NAIL INSTITUTE — EXPERIMENT 19: DIGITAL HOMEOSTASIS        ║")
    print("  ║  Phase 2: The Agentic Immune System                        ║")
    print("  ║                                                             ║")
    print("  ║  19a  Macrophage  — Deadlock Kill/Respawn                   ║")
    print("  ║  19b  Apoptosis   — Convergence Purge                      ║")
    print("  ║  19c  Compound    — Multi-Pathology Defense                 ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("=" * 70 + "\n")

    overall_start = time.time()
    results = {}
    timings = {}

    # ── 19a: Macrophage ──────────────────────────────────────────────────
    print("\n" + "▶" * 35)
    print("  STARTING: Experiment 19a — Macrophage Intervention")
    print("▶" * 35 + "\n")
    t0 = time.time()
    try:
        from exp19_digital_homeostasis.exp19a_macrophage import run_experiment as run_19a
        results["exp19a"] = run_19a()
        timings["exp19a"] = time.time() - t0
        print(f"\n  ✅ Exp19a completed in {timedelta(seconds=int(timings['exp19a']))}")
    except Exception as e:
        print(f"\n  ❌ Exp19a FAILED: {e}")
        import traceback
        traceback.print_exc()
        timings["exp19a"] = time.time() - t0
        results["exp19a"] = {"error": str(e)}

    # ── 19b: Apoptosis ───────────────────────────────────────────────────
    print("\n" + "▶" * 35)
    print("  STARTING: Experiment 19b — Apoptosis Protocol")
    print("▶" * 35 + "\n")
    t0 = time.time()
    try:
        from exp19_digital_homeostasis.exp19b_apoptosis import run_experiment as run_19b
        results["exp19b"] = run_19b()
        timings["exp19b"] = time.time() - t0
        print(f"\n  ✅ Exp19b completed in {timedelta(seconds=int(timings['exp19b']))}")
    except Exception as e:
        print(f"\n  ❌ Exp19b FAILED: {e}")
        import traceback
        traceback.print_exc()
        timings["exp19b"] = time.time() - t0
        results["exp19b"] = {"error": str(e)}

    # ── 19c: Compound Immunity ───────────────────────────────────────────
    print("\n" + "▶" * 35)
    print("  STARTING: Experiment 19c — Compound Immunity")
    print("▶" * 35 + "\n")
    t0 = time.time()
    try:
        from exp19_digital_homeostasis.exp19c_compound import run_experiment as run_19c
        results["exp19c"] = run_19c()
        timings["exp19c"] = time.time() - t0
        print(f"\n  ✅ Exp19c completed in {timedelta(seconds=int(timings['exp19c']))}")
    except Exception as e:
        print(f"\n  ❌ Exp19c FAILED: {e}")
        import traceback
        traceback.print_exc()
        timings["exp19c"] = time.time() - t0
        results["exp19c"] = {"error": str(e)}

    # ── Final Summary ────────────────────────────────────────────────────
    total_time = time.time() - overall_start

    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  EXPERIMENT 19 — COMPLETE SUMMARY                           ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("=" * 70)

    # 19a summary
    if "exp19a" in results and "error" not in results["exp19a"]:
        r = results["exp19a"]
        b = r.get("baseline", {})
        im = r.get("immune", {})
        print(f"\n  19a Macrophage:")
        print(f"    Baseline consensus rate:  {b.get('consensus_rate', '?')}")
        print(f"    Immune consensus rate:    {im.get('consensus_rate', '?')}")
        print(f"    Baseline avg rounds:      {b.get('avg_rounds', '?')}")
        print(f"    Immune avg rounds:        {im.get('avg_rounds', '?')}")
        print(f"    Macrophage interventions: {im.get('total_macrophage_interventions', '?')}")
        print(f"    Escalation interventions: {im.get('total_escalation_interventions', '?')}")

    # 19b summary
    if "exp19b" in results and "error" not in results["exp19b"]:
        r = results["exp19b"]
        b = r.get("baseline", {})
        im = r.get("immune", {})
        print(f"\n  19b Apoptosis:")
        print(f"    Baseline avg similarity:  {b.get('avg_similarity', '?')}")
        print(f"    Immune avg similarity:    {im.get('avg_similarity', '?')}")
        print(f"    Baseline sim trend:       {b.get('similarity_trend', '?')}")
        print(f"    Immune sim trend:         {im.get('similarity_trend', '?')}")
        print(f"    Apoptosis events:         {im.get('apoptosis_count', '?')}")

    # 19c summary
    if "exp19c" in results and "error" not in results["exp19c"]:
        r = results["exp19c"]
        b = r.get("baseline", {})
        im = r.get("immune", {})
        print(f"\n  19c Compound Immunity:")
        print(f"    Baseline avg quality:     {b.get('avg_quality', '?')}")
        print(f"    Immune avg quality:       {im.get('avg_quality', '?')}")
        print(f"    Total interventions:      {im.get('total_interventions', '?')}")
        if im.get("intervention_counts"):
            for itype, count in im["intervention_counts"].items():
                print(f"      {itype}: {count}")

    print(f"\n  Timing:")
    for exp, t in timings.items():
        print(f"    {exp}: {timedelta(seconds=int(t))}")
    print(f"    TOTAL: {timedelta(seconds=int(total_time))}")

    # Save master results
    master_results = {
        "experiment": "exp19_digital_homeostasis",
        "timestamp": datetime.now().isoformat(),
        "total_time_seconds": round(total_time, 1),
        "timings": {k: round(v, 1) for k, v in timings.items()},
        "sub_experiment_count": 3,
    }
    master_file = DATA_DIR / "exp19_master_results.json"
    with open(master_file, "w") as f:
        json.dump(master_results, f, indent=2, default=str)

    print(f"\n  Master results saved to {master_file}")
    print("=" * 70)
    print(f"  Experiment 19 complete. Total time: {timedelta(seconds=int(total_time))}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_all()
