#!/usr/bin/env python3
"""
NAIL Harness — Red/Blue Evaluator-Optimizer Experiment
=======================================================

Runs the adversarial Red/Blue loop using the nail_harness framework:
  - Red Team (LLM) generates attacks across 5 pathology types
  - Blue Team (VQC + LLM) evaluates & detects
  - Loop adapts: Red adapts to bypass; Blue adapts to catch

Usage:
    cd "/home/dleighsystems/Desktop/NAIL institute"
    source .venv/bin/activate
    python run_evaluator_optimizer.py                  # 10 rounds, default models
    python run_evaluator_optimizer.py --rounds 20      # 20 rounds
    python run_evaluator_optimizer.py --fast            # mistral for both (speed)
    python run_evaluator_optimizer.py --full            # nemotron:70b for Red & Blue
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from nail_harness.evaluator_optimizer import RedBlueLoop


def find_vqc_weights() -> str | None:
    """Find the latest VQC binary weights file."""
    candidates = [
        PROJECT_ROOT / "quantum-research" / "experiments" / "models",
        Path("/home/dleighsystems/quantum-research/experiments/models"),
    ]
    for models_dir in candidates:
        if models_dir.exists():
            weight_files = sorted(models_dir.glob("vqc_binary_weights_*.json"))
            if weight_files:
                return str(weight_files[-1])
    return None


def main():
    parser = argparse.ArgumentParser(
        description="NAIL Red/Blue Evaluator-Optimizer Experiment"
    )
    parser.add_argument("--rounds", type=int, default=10,
                        help="Number of Red/Blue rounds (default: 10)")
    parser.add_argument("--fast", action="store_true",
                        help="Use mistral:7b-instruct for both Red and Blue (fast)")
    parser.add_argument("--full", action="store_true",
                        help="Use nemotron:70b for both (highest quality, slow)")
    parser.add_argument("--red-model", type=str, default=None,
                        help="Override Red Team model")
    parser.add_argument("--blue-model", type=str, default=None,
                        help="Override Blue Team model")
    parser.add_argument("--no-vqc", action="store_true",
                        help="Disable VQC quantum classification")
    parser.add_argument("--output", type=str, default=None,
                        help="Output path for results JSON")
    args = parser.parse_args()

    # ── Model selection ──────────────────────────────────────────
    if args.fast:
        red_model = "mistral:7b-instruct"
        blue_model = "mistral:7b-instruct"
    elif args.full:
        red_model = "nemotron:70b"
        blue_model = "nemotron:70b"
    else:
        red_model = "mistral:7b-instruct"   # Fast red for attack generation
        blue_model = "nemotron:70b"          # Strong blue for evaluation
    red_model = args.red_model or red_model
    blue_model = args.blue_model or blue_model

    # ── VQC weights ──────────────────────────────────────────────
    vqc_path = None if args.no_vqc else find_vqc_weights()

    # ── Banner ───────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 64)
    print("  🔴🔵 NAIL Red/Blue Evaluator-Optimizer Experiment")
    print("=" * 64)
    print(f"  Timestamp:     {ts}")
    print(f"  Rounds:        {args.rounds}")
    print(f"  Red model:     {red_model}")
    print(f"  Blue model:    {blue_model}")
    print(f"  VQC weights:   {vqc_path or 'DISABLED (heuristic mode)'}")
    print(f"  Output:        {args.output or 'auto'}")
    print("=" * 64 + "\n")

    # ── Run ──────────────────────────────────────────────────────
    loop = RedBlueLoop(
        vqc_weights_path=vqc_path,
        red_model=red_model,
        blue_model=blue_model,
    )

    t0 = time.time()
    summary = loop.run(num_rounds=args.rounds, verbose=True)
    elapsed = time.time() - t0

    # ── Results ──────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("  📊 FINAL RESULTS")
    print("=" * 64)
    print(f"  Total Rounds:     {summary['total_rounds']}")
    print(f"  Attacks Detected: {summary['attacks_detected']}")
    print(f"  Attacks Missed:   {summary['attacks_missed']}")
    print(f"  Detection Rate:   {summary['detection_rate']:.1%}")
    print(f"  VQC Mode:         {summary.get('vqc_mode', 'n/a')}")
    print(f"  Elapsed:          {elapsed:.1f}s")
    print(f"  Avg Round Time:   {elapsed / max(summary['total_rounds'], 1):.1f}s")
    print()
    print("  By Attack Type:")
    for atype, stats in summary["by_attack_type"].items():
        dets = stats["detected"]
        tots = stats["total"]
        rate = dets / tots if tots > 0 else 0
        bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
        print(f"    {atype:<25} [{bar}] {rate:.0%} ({dets}/{tots})")

    # ── Save ─────────────────────────────────────────────────────
    if args.output:
        out_path = Path(args.output)
    else:
        results_dir = PROJECT_ROOT / "experiments" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = results_dir / f"red_blue_{stamp}.json"

    loop.save_results(str(out_path))
    print(f"\n  💾 Results saved → {out_path}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
