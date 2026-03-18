"""
NAIL Institute — Experiment 22: Metamorphic Architectures (Master Runner)
==========================================================================
Phase 1 of the Build-Solution Manifesto: Break the Graph

Three sub-experiments:
  22a: Static Pipeline vs. Metamorphic Graph (quality + efficiency)
  22b: Emergent Topology Under Stress (topology discovery)
  22c: Self-Healing Graph (metamorphic + immune synergy)

USAGE:
  cd "/home/dleighsystems/Desktop/NAIL institute/experiments"
  python -m exp22_metamorphic_graph.run

  Background with logging:
  PYTHONUNBUFFERED=1 nohup python -u -m exp22_metamorphic_graph.run > ../exp22.log 2>&1 &
"""

import json
import sys
import time
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import DATA_DIR


def run_all():
    print("\n" + "═" * 70)
    print("  ╔════════════════════════════════════════════════════════════════╗")
    print("  ║  NAIL INSTITUTE — EXPERIMENT 22: METAMORPHIC ARCHITECTURES   ║")
    print("  ║                                                              ║")
    print("  ║  Phase 1: Break the Graph                                    ║")
    print("  ║                                                              ║")
    print("  ║  22a: Static vs. Metamorphic (quality + efficiency)          ║")
    print("  ║  22b: Emergent Topology (topology discovery)                 ║")
    print("  ║  22c: Self-Healing Graph (metamorphic + immune)              ║")
    print("  ╚════════════════════════════════════════════════════════════════╝")
    print("═" * 70 + "\n")

    overall_start = time.time()
    master_results = {}

    # ── 22a ──
    try:
        from exp22_metamorphic_graph.exp22a_static_vs_meta import run_exp22a
        print("\n▶ Running Exp22a: Static vs. Metamorphic...")
        r = run_exp22a()
        master_results["exp22a"] = {
            "status": "complete",
            "static_quality": r["static"]["avg_quality"],
            "meta_quality": r["metamorphic"]["avg_quality"],
            "static_tokens": r["static"]["avg_tokens"],
            "meta_tokens": r["metamorphic"]["avg_tokens"],
            "meta_avg_agents": r["metamorphic"]["avg_agents"],
            "meta_avg_mutations": r["metamorphic"]["avg_mutations"],
            "runtime_s": r.get("total_runtime_s", 0),
        }
        print(f"  ✅ 22a complete: Static={r['static']['avg_quality']}, "
              f"Meta={r['metamorphic']['avg_quality']}")
    except Exception as e:
        master_results["exp22a"] = {"status": "error", "error": str(e)}
        print(f"  ❌ 22a failed: {e}")
        import traceback; traceback.print_exc()

    # ── 22b ──
    try:
        from exp22_metamorphic_graph.exp22b_emergent_topology import run_exp22b
        print("\n▶ Running Exp22b: Emergent Topology...")
        r = run_exp22b()
        master_results["exp22b"] = {
            "status": "complete",
            "avg_topology_match": r["avg_topology_match"],
            "topology_results": r["topology_results"],
            "runtime_s": r.get("total_runtime_s", 0),
        }
        print(f"  ✅ 22b complete: Avg topology match = {r['avg_topology_match']:.1%}")
    except Exception as e:
        master_results["exp22b"] = {"status": "error", "error": str(e)}
        print(f"  ❌ 22b failed: {e}")
        import traceback; traceback.print_exc()

    # ── 22c ──
    try:
        from exp22_metamorphic_graph.exp22c_selfhealing import run_exp22c
        print("\n▶ Running Exp22c: Self-Healing Graph...")
        r = run_exp22c()
        master_results["exp22c"] = {
            "status": "complete",
            "meta_only_quality": r["metamorphic_only"]["avg_quality"],
            "meta_immune_quality": r["metamorphic_immune"]["avg_quality"],
            "quality_delta": r["comparison"]["quality_delta"],
            "token_delta_pct": r["comparison"]["token_pct_change"],
            "alerts_raised": r["comparison"]["alerts_raised"],
            "runtime_s": r.get("total_runtime_s", 0),
        }
        print(f"  ✅ 22c complete: Meta-only={r['metamorphic_only']['avg_quality']}, "
              f"Meta+Immune={r['metamorphic_immune']['avg_quality']}")
    except Exception as e:
        master_results["exp22c"] = {"status": "error", "error": str(e)}
        print(f"  ❌ 22c failed: {e}")
        import traceback; traceback.print_exc()

    # ── Master Summary ──
    total_elapsed = time.time() - overall_start
    master_results["total_runtime_s"] = round(total_elapsed, 1)
    master_results["total_runtime_human"] = str(timedelta(seconds=int(total_elapsed)))

    out_path = DATA_DIR / "exp22_master_results.json"
    with open(out_path, "w") as f:
        json.dump(master_results, f, indent=2, default=str)

    print("\n" + "═" * 70)
    print(f"  EXPERIMENT 22 COMPLETE — Total runtime: "
          f"{timedelta(seconds=int(total_elapsed))}")
    print(f"  Results: {out_path}")
    print("═" * 70 + "\n")

    return master_results


if __name__ == "__main__":
    run_all()
