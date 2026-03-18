#!/usr/bin/env python3
"""Re-run only Exp22b (Emergent Topology) after bug fix, and merge results
back into exp22_master_results.json."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))

from exp22_metamorphic_graph.exp22b_emergent_topology import run_exp22b

DATA = ROOT / "experiments" / "data"

def main():
    print("=" * 72)
    print("  Re-running Exp22b: Emergent Topology (bug-fixed)")
    print("=" * 72)

    t0 = time.time()
    result_22b = run_exp22b()
    elapsed = time.time() - t0

    # Save standalone 22b results
    out_path = DATA / "exp22b_results.json"
    with open(out_path, "w") as f:
        json.dump(result_22b, f, indent=2, default=str)
    print(f"\n✅ Exp22b results saved to {out_path}")

    # Merge into master
    master_path = DATA / "exp22_master_results.json"
    if master_path.exists():
        with open(master_path) as f:
            master = json.load(f)
    else:
        master = {}

    master["exp22b"] = result_22b
    # Recalculate total runtime
    total = 0
    for k in ["exp22a", "exp22b", "exp22c"]:
        if k in master and isinstance(master[k], dict):
            total += master[k].get("runtime_s", 0)
    master["total_runtime_s"] = round(total, 1)
    h, rem = divmod(int(total), 3600)
    m, s = divmod(rem, 60)
    master["total_runtime_human"] = f"{h}:{m:02d}:{s:02d}"

    with open(master_path, "w") as f:
        json.dump(master, f, indent=2, default=str)
    print(f"✅ Master results updated at {master_path}")
    print(f"✅ 22b re-run completed in {elapsed:.1f}s")

if __name__ == "__main__":
    main()
