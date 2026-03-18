#!/usr/bin/env python3
"""
NAIL Horizon Campaign Runner — DGX Execution
=============================================
Executes all three Horizon campaigns using deterministic evaluators
for the framework validation pass, then outputs results to JSON.

  Horizon 1: Threshold Optimization GA (20 pop × 50 generations)
  Horizon 2: Heterogeneous Model-vs-Model (6 attacker profiles × 8 attack types)
  Horizon 3: Polyglot Obfuscation Protocol (3 codebooks × 8 intents)

Usage:
    python run_horizon_campaigns.py
"""

from __future__ import annotations

import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add horizon package
sys.path.insert(0, str(Path(__file__).parent / "horizon"))

from horizon import HorizonRunner
from horizon.ga import ThresholdGA, DEFAULT_SENSORS
from horizon.heterogeneous import HeterogeneousCampaign, ATTACKER_PROFILES, ATTACK_TYPES
from horizon.polyglot import PolyglotCampaign, ALL_CODEBOOKS, ATTACK_INTENTS


RESULTS_DIR = Path(__file__).parent / "experiments" / "data"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def banner(msg: str):
    w = 70
    print(f"\n{'═' * w}")
    print(f"  {msg}")
    print(f"{'═' * w}\n")


def run_horizon_1_detailed():
    """Horizon 1: GA Threshold Optimization — full 50-generation run."""
    banner("HORIZON 1 — Threshold Optimization GA")
    print(f"  Sensors:      {len(DEFAULT_SENSORS)}")
    print(f"  Population:   20")
    print(f"  Generations:  50")
    print(f"  Mutation:     0.15")
    print(f"  Crossover:    0.70")
    print(f"  Elitism:      2")
    print()

    ga = ThresholdGA(
        population_size=20,
        generations=50,
        mutation_rate=0.15,
        crossover_rate=0.70,
        elitism=2,
        seed=42,
    )
    t0 = time.time()
    history = ga.run_with_history()
    elapsed = time.time() - t0

    final = history[-1]
    champion = final.champion

    print(f"\n  ✅ GA complete in {elapsed:.2f}s")
    print(f"  Champion:     {champion.genome_id}")
    print(f"  Fitness:      {champion.fitness:.6f}")
    print(f"  Security:     {champion.security_score:.6f}")
    print(f"  Accuracy:     {champion.accuracy_score:.6f}")
    print(f"\n  Optimised thresholds:")
    for sensor, val in sorted(champion.thresholds.items()):
        print(f"    {sensor:30s} = {val:.4f}")

    # Fitness trajectory
    trajectory = [pop.best_fitness for pop in history]
    print(f"\n  Fitness trajectory (gen 0→50):")
    for i, f in enumerate(trajectory):
        bar = "█" * int(f * 40)
        print(f"    Gen {i:3d}: {f:.4f}  {bar}")

    return {
        "status": "complete",
        "runtime_s": round(elapsed, 2),
        "generations": len(history) - 1,
        "population_size": 20,
        "champion_id": champion.genome_id,
        "champion_fitness": round(champion.fitness, 6),
        "champion_security": round(champion.security_score, 6),
        "champion_accuracy": round(champion.accuracy_score, 6),
        "champion_thresholds": {k: round(v, 6) for k, v in champion.thresholds.items()},
        "fitness_trajectory": [round(f, 6) for f in trajectory],
        "final_population_stats": final.to_dict(),
    }


def run_horizon_2_detailed():
    """Horizon 2: Heterogeneous Model-vs-Model."""
    banner("HORIZON 2 — Heterogeneous Threat Generalisation")
    print(f"  Defender:     nemotron-70b")
    print(f"  Attackers:    {len(ATTACKER_PROFILES) - 1} (excluding defender)")
    print(f"  Attack types: {len(ATTACK_TYPES)}")
    print()

    campaign = HeterogeneousCampaign(defender_id="nemotron-70b")
    t0 = time.time()
    results = campaign.run()
    elapsed = time.time() - t0

    print(f"  ✅ Campaign complete in {elapsed:.2f}s\n")
    print(f"  {'Attacker':<25s} {'Family':<12s} {'Blocked':<10s} {'Evaded':<10s} {'Block %':<10s} {'Gen Score':<10s}")
    print(f"  {'─' * 75}")

    total_blocked = 0
    total_attacks = 0
    for r in results:
        total_blocked += r.total_blocked
        total_attacks += len(r.attacks)
        print(f"  {r.attacker.model_id:<25s} {r.attacker.family.value:<12s} "
              f"{r.total_blocked:<10d} {r.total_evaded:<10d} "
              f"{r.block_rate*100:>7.1f}%   {r.generalisation_score:.4f}")

    overall_block = total_blocked / total_attacks if total_attacks else 0
    print(f"\n  Overall block rate:       {overall_block*100:.1f}%")
    print(f"  Total attacks simulated:  {total_attacks}")

    return {
        "status": "complete",
        "runtime_s": round(elapsed, 2),
        "defender": "nemotron-70b",
        "attackers_tested": len(results),
        "attack_types": len(ATTACK_TYPES),
        "total_attacks": total_attacks,
        "total_blocked": total_blocked,
        "overall_block_rate": round(overall_block, 6),
        "per_attacker": [r.to_dict() for r in results],
    }


def run_horizon_3_detailed():
    """Horizon 3: Polyglot / Obfuscation Protocol."""
    banner("HORIZON 3 — Polyglot Obfuscation Protocol")
    print(f"  Codebooks:    {len(ALL_CODEBOOKS)}")
    print(f"  Intents:      {len(ATTACK_INTENTS)}")
    print()

    campaign = PolyglotCampaign()
    t0 = time.time()
    results = campaign.run()
    elapsed = time.time() - t0

    print(f"  ✅ Campaign complete in {elapsed:.2f}s\n")
    print(f"  {'Codebook':<15s} {'Encoded':<10s} {'Detected':<10s} {'Evaded':<10s} {'Detect %':<10s} {'Evade %':<10s} {'Fidelity':<10s}")
    print(f"  {'─' * 75}")

    total_encoded = 0
    total_detected = 0
    total_evaded = 0
    for r in results:
        total_encoded += r.total_encoded
        total_detected += r.total_detected
        total_evaded += r.total_evaded
        print(f"  {r.codebook.domain:<15s} {r.total_encoded:<10d} {r.total_detected:<10d} "
              f"{r.total_evaded:<10d} {r.detection_rate*100:>7.1f}%   "
              f"{r.evasion_rate*100:>7.1f}%   {r.avg_encoding_fidelity:.4f}")

    overall_detect = total_detected / total_encoded if total_encoded else 0
    overall_evade = total_evaded / total_encoded if total_encoded else 0
    print(f"\n  Overall detection rate:   {overall_detect*100:.1f}%")
    print(f"  Overall evasion rate:     {overall_evade*100:.1f}%")
    print(f"  Total payloads tested:    {total_encoded}")

    # Show sample encoded payloads
    print(f"\n  Sample encoded payloads (baking codebook):")
    baking = results[0]
    for p in baking.payloads[:4]:
        print(f"    Intent:  {p.original_intent[:60]}")
        print(f"    Encoded: {p.encoded_text[:60]}")
        print(f"    Fidelity: {p.encoding_fidelity:.2f}")
        print()

    return {
        "status": "complete",
        "runtime_s": round(elapsed, 2),
        "codebooks_tested": len(results),
        "intents_tested": len(ATTACK_INTENTS),
        "total_encoded": total_encoded,
        "total_detected": total_detected,
        "total_evaded": total_evaded,
        "overall_detection_rate": round(overall_detect, 6),
        "overall_evasion_rate": round(overall_evade, 6),
        "per_codebook": [r.to_dict() for r in results],
    }


def main():
    banner("NAIL HORIZON CAMPAIGNS — DGX EXECUTION")
    print(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"  Platform:  DGX (NVIDIA GB10)")
    print(f"  Mode:      Deterministic evaluators (framework validation)")

    t_total = time.time()

    # Run all three
    h1 = run_horizon_1_detailed()
    h2 = run_horizon_2_detailed()
    h3 = run_horizon_3_detailed()

    total_elapsed = time.time() - t_total

    # Combined results
    combined = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": "DGX (NVIDIA GB10)",
            "mode": "deterministic_evaluators",
            "total_runtime_s": round(total_elapsed, 2),
        },
        "horizon_1_ga": h1,
        "horizon_2_heterogeneous": h2,
        "horizon_3_polyglot": h3,
    }

    # Save results
    outfile = RESULTS_DIR / "horizon_campaign_results.json"
    with open(outfile, "w") as f:
        json.dump(combined, f, indent=2)

    banner("CAMPAIGN SUMMARY")
    print(f"  Horizon 1 (GA):          fitness={h1['champion_fitness']:.4f}  "
          f"security={h1['champion_security']:.4f}  accuracy={h1['champion_accuracy']:.4f}")
    print(f"  Horizon 2 (Hetero):      block_rate={h2['overall_block_rate']*100:.1f}%  "
          f"({h2['total_blocked']}/{h2['total_attacks']} attacks)")
    print(f"  Horizon 3 (Polyglot):    detect={h3['overall_detection_rate']*100:.1f}%  "
          f"evade={h3['overall_evasion_rate']*100:.1f}%")
    print(f"\n  Total runtime: {total_elapsed:.2f}s")
    print(f"  Results saved: {outfile}")
    print()


if __name__ == "__main__":
    main()
