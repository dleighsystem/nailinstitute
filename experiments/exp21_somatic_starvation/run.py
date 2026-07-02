#!/usr/bin/env python3
"""
NAIL Institute — Experiment 21: Somatic Starvation Proof
Master Runner and Results Orchestrator
"""

from __future__ import annotations

import os
import sys
import json
import datetime
import traceback

# Ensure experiment sub-modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import exp21a_cpu_asphyxiation
import exp21b_vram_amnesia
import exp21c_async_fission
import exp21d_quantization_decay
import somatic_telemetry

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def main():
    print("=" * 80)
    print("NAIL INSTITUTE — EXPERIMENT 21: SOMATIC STARVATION & PROTECTIVE HYPERVISOR")
    print(f"Master Runner Started: {datetime.datetime.now().isoformat()}")
    print("=" * 80)

    # 1. System Telemetry
    real_telemetry = somatic_telemetry.collect_real_telemetry()
    header = somatic_telemetry.format_somatic_header(real_telemetry)
    print(f"\n[INIT] Real-time Hardware Snapshot:")
    print(f"  {header}\n")

    # 2. Run Sub-experiments
    print("Running exp21a: CPU Asphyxiation...")
    res_a = exp21a_cpu_asphyxiation.run()
    
    print("Running exp21b: VRAM/KV Cache Amnesia...")
    res_b = exp21b_vram_amnesia.run()
    
    print("Running exp21c: Async Thread Fission...")
    res_c = exp21c_async_fission.run()
    
    print("Running exp21d: Quantization Decay...")
    res_d = exp21d_quantization_decay.run()

    # 3. Compile Master Results
    outcomes = [res_a, res_b, res_c, res_d]
    
    print("\n" + "=" * 80)
    print("EXPERIMENT 21 COMPLETE — COMBINED OUTCOMES")
    print("=" * 80)
    print(f"{'Pathology':<25s} {'Baseline':<12s} {'Protected':<12s} {'Containment Rate':>18s}")
    print("-" * 80)
    
    for o in outcomes:
        pathology = o["pathology"]
        base_status = "FAILED" if o["baseline"]["status"] == "failed" else "SUCCESS"
        prot_status = "SUCCESS" if o["protected"]["status"] == "success" else "FAILED"
        containment = f"{o['improvement_pct']:.0f}%"
        print(f"{pathology:<25s} {base_status:<12s} {prot_status:<12s} {containment:>18s}")
    print("=" * 80)

    # Save to disk
    master_data = {
        "experiment": "exp21_somatic_starvation",
        "timestamp": datetime.datetime.now().isoformat(),
        "outcomes": outcomes,
        "telemetry_snapshot": real_telemetry,
    }
    
    master_file = os.path.join(RESULTS_DIR, "exp21_master_latest.json")
    with open(master_file, "w") as f:
        json.dump(master_data, f, indent=2)
        
    print(f"\nMaster results successfully written to: {master_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()
