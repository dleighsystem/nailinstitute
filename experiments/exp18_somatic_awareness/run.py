#!/usr/bin/env python3
"""
NAIL Institute — Experiment 18: Somatic Awareness (Master Runner)
Phase 3 of the Build-Solution Manifesto

Intervention test: Does injecting physical-layer telemetry into LLM
context windows reduce the confirmed failure modes from Experiment 17
(Container Isolation)?

Sub-experiments:
  18a — Somatic Tool Failures (vs Exp17b: Phantom Tool Failures)
  18b — Somatic Resource Awareness (vs Exp17c: Resource Blindness)
  18c — Somatic GPU Awareness (vs Exp17a: GPU Non-Determinism)

Usage:
  conda run -n nail_experiments python run.py [--skip 18a,18b,18c]
"""

import datetime
import json
import os
import sys
import time
import traceback

# Ensure sub-experiment modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Logging ──────────────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"exp18_run_{TIMESTAMP}.log")


class TeeLogger:
    """Write to both stdout and a log file."""
    def __init__(self, logfile):
        self.terminal = sys.stdout
        self.log = open(logfile, "w", buffering=1)

    def write(self, msg):
        self.terminal.write(msg)
        self.log.write(msg)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


# ── Sub-experiment registry ──────────────────────────────────────
EXPERIMENTS = [
    {
        "id": "18a",
        "name": "Somatic Tool Failures",
        "module": "exp18a_somatic_tool_failures",
        "description": "Intervention for Exp17b: Does network telemetry prevent data fabrication?",
    },
    {
        "id": "18b",
        "name": "Somatic Resource Awareness",
        "module": "exp18b_somatic_resource_awareness",
        "description": "Intervention for Exp17c: Does disk telemetry prevent code self-mutilation?",
    },
    {
        "id": "18c",
        "name": "Somatic GPU Awareness",
        "module": "exp18c_somatic_gpu_awareness",
        "description": "Side-effect test for Exp17a: Does GPU telemetry affect output determinism?",
    },
]


def parse_skip_list(args: list) -> set:
    """Parse --skip flag from command line."""
    skip = set()
    for i, arg in enumerate(args):
        if arg == "--skip" and i + 1 < len(args):
            skip = {x.strip().lower() for x in args[i + 1].split(",")}
    return skip


def run_sub_experiment(exp_info: dict) -> dict:
    """Import and run a single sub-experiment."""
    module_name = exp_info["module"]
    exp_id = exp_info["id"]

    print(f"\n{'#' * 70}")
    print(f"# EXPERIMENT {exp_id.upper()}: {exp_info['name']}")
    print(f"# {exp_info['description']}")
    print(f"# Started: {datetime.datetime.now().isoformat()}")
    print(f"{'#' * 70}\n")

    t0 = time.time()
    try:
        mod = __import__(module_name)
        result = mod.run()
        elapsed = time.time() - t0

        print(f"\n{'#' * 70}")
        print(f"# EXPERIMENT {exp_id.upper()} COMPLETE — {elapsed:.1f}s")
        print(f"{'#' * 70}\n")

        return {
            "id": exp_id,
            "name": exp_info["name"],
            "status": "success",
            "elapsed_seconds": elapsed,
            "result": result,
        }

    except Exception as e:
        elapsed = time.time() - t0
        error_msg = traceback.format_exc()
        print(f"\n{'!' * 70}")
        print(f"! EXPERIMENT {exp_id.upper()} FAILED — {elapsed:.1f}s")
        print(f"! Error: {e}")
        print(error_msg)
        print(f"{'!' * 70}\n")

        return {
            "id": exp_id,
            "name": exp_info["name"],
            "status": "error",
            "elapsed_seconds": elapsed,
            "error": str(e),
            "traceback": error_msg,
        }


def print_combined_summary(all_outcomes: list):
    """Print combined summary across all sub-experiments."""
    print("\n" + "=" * 70)
    print("EXPERIMENT 18: SOMATIC AWARENESS — COMBINED RESULTS")
    print("=" * 70)

    # Overview table
    print(f"\n{'Sub-Exp':<8s} {'Name':<30s} {'Status':<10s} {'Time':>8s}")
    print("-" * 60)
    total_time = 0
    for o in all_outcomes:
        status = o["status"].upper()
        elapsed = o["elapsed_seconds"]
        total_time += elapsed
        print(f"{o['id']:<8s} {o['name']:<30s} {status:<10s} {elapsed:>7.1f}s")
    print("-" * 60)
    print(f"{'TOTAL':<8s} {'':30s} {'':10s} {total_time:>7.1f}s")

    # Exp18a summary (if available)
    exp18a = next((o for o in all_outcomes if o["id"] == "18a" and o["status"] == "success"), None)
    if exp18a and exp18a.get("result"):
        print("\n  ┌─ 18a: SOMATIC TOOL FAILURES (vs Exp17b) ────────────────")
        r = exp18a["result"]
        if "summary" in r:
            for entry in r["summary"]:
                if "intervention_effect" in entry:
                    ie = entry["intervention_effect"]
                    m = entry["model"]
                    ph = entry["phase"]
                    print(f"  │  {m} / {ph}:")
                    for k, v in ie.items():
                        print(f"  │    {k}: {v:+.1f}pp")
        print("  └──────────────────────────────────────────────────────")

    # Exp18b summary (if available)
    exp18b = next((o for o in all_outcomes if o["id"] == "18b" and o["status"] == "success"), None)
    if exp18b and exp18b.get("result"):
        print("\n  ┌─ 18b: SOMATIC RESOURCE AWARENESS (vs Exp17c) ─────────")
        r = exp18b["result"]
        if "summary" in r:
            for entry in r["summary"]:
                if "intervention_effect" in entry:
                    ie = entry["intervention_effect"]
                    m = entry["model"]
                    ph = entry["phase"]
                    print(f"  │  {m} / {ph}:")
                    for k, v in ie.items():
                        print(f"  │    {k}: {v:+.1f}pp")
        print("  └──────────────────────────────────────────────────────")

    # Exp18c summary (if available)
    exp18c = next((o for o in all_outcomes if o["id"] == "18c" and o["status"] == "success"), None)
    if exp18c and exp18c.get("result"):
        print("\n  ┌─ 18c: SOMATIC GPU AWARENESS (Side Effect Test) ──────")
        r = exp18c["result"]
        if "results" in r:
            for entry in r["results"]:
                m = entry["model"]
                c = entry["condition"]
                bd = entry["baseline"]["determinism_rate"] * 100
                sd = entry["stressed"]["determinism_rate"] * 100
                xp = "MATCH" if entry["cross_phase_canonical_match"] else "DIFF"
                print(f"  │  {m} / {c}: baseline={bd:.0f}% stressed={sd:.0f}% x-phase={xp}")
        print("  └──────────────────────────────────────────────────────")

    # Overall thesis
    print(f"\n  Phase 3 Thesis: Somatic awareness (physical-layer telemetry in context)")
    print(f"  reduces agentic failure modes confirmed in Experiment 17.")
    print(f"  See individual JSON files in results/ for detailed data.")


def main():
    """Main entry point."""
    skip_list = parse_skip_list(sys.argv[1:])
    logger = TeeLogger(LOG_FILE)
    sys.stdout = logger

    print("=" * 70)
    print("NAIL INSTITUTE — EXPERIMENT 18: SOMATIC AWARENESS")
    print("Phase 3 of the Build-Solution Manifesto")
    print(f"Master Runner Started: {datetime.datetime.now().isoformat()}")
    print(f"Log file: {LOG_FILE}")
    print(f"Skipping: {skip_list if skip_list else 'none'}")
    print("=" * 70)

    # System info
    try:
        import psutil
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        print(f"\nSystem: {psutil.cpu_count()} cores, "
              f"RAM {mem.used / 1e9:.1f}/{mem.total / 1e9:.1f} GB ({mem.percent}%), "
              f"Disk {disk.used / 1e9:.0f}/{disk.total / 1e9:.0f} GB ({disk.percent}%)")
    except Exception:
        pass

    # Run experiments
    all_outcomes = []
    master_t0 = time.time()

    for exp in EXPERIMENTS:
        if exp["id"] in skip_list:
            print(f"\n  ⏭  Skipping {exp['id']}: {exp['name']}")
            all_outcomes.append({
                "id": exp["id"],
                "name": exp["name"],
                "status": "skipped",
                "elapsed_seconds": 0,
            })
            continue

        outcome = run_sub_experiment(exp)
        all_outcomes.append(outcome)

        # If an experiment fails, continue with the next
        if outcome["status"] == "error":
            print(f"  ⚠  {exp['id']} failed but continuing with remaining experiments...")

    master_elapsed = time.time() - master_t0

    # Combined summary
    print_combined_summary(all_outcomes)

    # Save master results
    master_output = {
        "experiment": "18_somatic_awareness",
        "phase": "Phase 3 — Somatic Awareness",
        "timestamp": datetime.datetime.now().isoformat(),
        "total_elapsed_seconds": master_elapsed,
        "sub_experiments": all_outcomes,
    }

    master_file = os.path.join(RESULTS_DIR, f"exp18_master_{TIMESTAMP}.json")
    with open(master_file, "w") as f:
        json.dump(master_output, f, indent=2, default=str)

    latest_file = os.path.join(RESULTS_DIR, "exp18_master_latest.json")
    with open(latest_file, "w") as f:
        json.dump(master_output, f, indent=2, default=str)

    print(f"\n{'=' * 70}")
    print(f"EXPERIMENT 18 COMPLETE — Total: {master_elapsed:.1f}s")
    print(f"Master results: {master_file}")
    print(f"Log: {LOG_FILE}")
    print(f"{'=' * 70}")

    sys.stdout = logger.terminal
    logger.close()


if __name__ == "__main__":
    main()
