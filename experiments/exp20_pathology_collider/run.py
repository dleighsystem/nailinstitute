"""
NAIL Institute — Experiment 20: Pathology Collider
====================================================
Master runner for the capstone adversarial simulation.

The Pathology Collider pits an Adversarial Agent (Red Team) against
a Primary Agent (Blue Team) defended by 4 defense layers from mapping.md.

Phases:
  A — Baseline: Red Team attacks with NO defenses (damage measurement)
  B — Defended: Red Team attacks WITH all 4 defense layers (defense validation)

USAGE:
  conda activate nail_experiments
  cd "/home/dleighsystems/Desktop/NAIL institute/experiments"
  python -m exp20_pathology_collider.run

  With custom rounds and model:
  python -m exp20_pathology_collider.run --rounds 10 --model mistral:7b-instruct

  With nohup for long runs:
  PYTHONUNBUFFERED=1 nohup conda run --no-capture-output -n nail_experiments \
    python -u -m exp20_pathology_collider.run > ../exp20.log 2>&1 &
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import PRIMARY_MODEL, FAST_MODEL, DATA_DIR
from shared.logger import ExperimentLogger


def run(num_rounds: int = 20, model: str = PRIMARY_MODEL, fast_model: str = FAST_MODEL):
    """Run the full Pathology Collider experiment."""

    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  NAIL INSTITUTE — EXPERIMENT 20: THE PATHOLOGY COLLIDER     ║")
    print("  ║                                                             ║")
    print("  ║  Capstone Adversarial Simulation from mapping.md            ║")
    print("  ║                                                             ║")
    print("  ║  Red Team: EDoS + Memory Sleepers + Context Poisoning       ║")
    print("  ║  Blue Team: Research Analyst + 4 Defense Layers             ║")
    print("  ║                                                             ║")
    print(f"  ║  Rounds per phase: {num_rounds:<43}║")
    print(f"  ║  Model:            {model:<43}║")
    print(f"  ║  Fast model:       {fast_model:<43}║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("=" * 70 + "\n")

    overall_start = time.time()

    # Initialize logger
    logger = ExperimentLogger(
        experiment_name="exp20_pathology_collider",
        monitor_interval_s=10.0,
        enable_system_monitor=True,
    )
    logger.log_event("info", data={
        "num_rounds": num_rounds,
        "model": model,
        "fast_model": fast_model,
    }, message=f"Experiment 20 started: {num_rounds} rounds, model={model}")

    # Run the collider
    from exp20_pathology_collider.collider import Collider

    collider = Collider(
        num_rounds=num_rounds,
        model=model,
        fast_model=fast_model,
        logger=logger,
    )
    scoreboard = collider.run_full_collider()

    # Finalize
    total_time = time.time() - overall_start
    resource_summary = logger.finalize()

    # ── Save Results ────────────────────────────────────────────────────

    results_file = DATA_DIR / "exp20_collider_results.json"
    full_results = {
        "experiment": "exp20_pathology_collider",
        "timestamp": datetime.now().isoformat(),
        "total_time_seconds": round(total_time, 1),
        "config": {
            "num_rounds": num_rounds,
            "model": model,
            "fast_model": fast_model,
        },
        "scoreboard": scoreboard,
        "resource_summary": resource_summary,
    }

    with open(results_file, "w") as f:
        json.dump(full_results, f, indent=2, default=str)

    # ── Summary ─────────────────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  EXPERIMENT 20 — FINAL REPORT                               ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("=" * 70)

    comp = scoreboard.get("comparison", {})

    print(f"\n  ┌─ DAMAGE COMPARISON ──────────────────────────────────────┐")
    print(f"  │  Memory Corruption:                                      │")
    print(f"  │    Baseline (no defense):  {comp.get('memory_corruption_baseline', 'N/A'):<30}│")
    print(f"  │    Defended (4 layers):    {comp.get('memory_corruption_defended', 'N/A'):<30}│")
    print(f"  │                                                          │")
    print(f"  │  Research Accuracy:                                       │")
    print(f"  │    Baseline:              {comp.get('accuracy_baseline', 'N/A'):<30}│")
    print(f"  │    Defended:              {comp.get('accuracy_defended', 'N/A'):<30}│")
    print(f"  │                                                          │")
    print(f"  │  Defense Performance:                                     │")
    print(f"  │    Attacker Stealth:      {comp.get('stealth_score', 'N/A'):<30}│")
    print(f"  │    Detection Rate:        {comp.get('detection_rate', 'N/A'):<30}│")
    print(f"  │    Interventions:         {comp.get('total_interventions', 'N/A'):<30}│")
    print(f"  └──────────────────────────────────────────────────────────┘")

    print(f"\n  Total time: {timedelta(seconds=int(total_time))}")
    print(f"  Results saved to: {results_file}")
    print(f"  Logs saved to: {logger.get_log_path()}")
    print("=" * 70 + "\n")

    return full_results


def main():
    parser = argparse.ArgumentParser(
        description="NAIL Experiment 20: Pathology Collider"
    )
    parser.add_argument(
        "--rounds", type=int, default=20,
        help="Number of rounds per phase (default: 20)"
    )
    parser.add_argument(
        "--model", type=str, default=PRIMARY_MODEL,
        help=f"Primary model for Red/Blue teams (default: {PRIMARY_MODEL})"
    )
    parser.add_argument(
        "--fast-model", type=str, default=FAST_MODEL,
        help=f"Fast model for defense layer oversight (default: {FAST_MODEL})"
    )
    args = parser.parse_args()
    run(num_rounds=args.rounds, model=args.model, fast_model=args.fast_model)


if __name__ == "__main__":
    main()
