"""
NAIL Institute — GA Phase 2: Validate Top Genomes on nemotron:70b
===================================================================
Takes the top genomes from Phase 1 (mistral:7b-instruct) and
re-evaluates them on the primary model (nemotron:70b) with more
rounds for statistical confidence.

Usage:
    python3 -m exp20_pathology_collider.validate_ga --top 3 --rounds 5 --trials 3
"""

import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import PRIMARY_MODEL, FAST_MODEL, DATA_DIR
from shared.logger import ExperimentLogger
from shared.system_monitor import SystemMonitor

from .ga_optimizer import Genome, compute_fitness
from .collider import Collider


def load_top_genomes(top_n: int = 3) -> list[dict]:
    """Load the top N genomes from Phase 1 results."""
    results_file = DATA_DIR / "exp20_ga_results.json"
    with open(results_file) as f:
        data = json.load(f)

    all_genomes = data.get("all_genomes", [])
    sorted_genomes = sorted(all_genomes, key=lambda g: g.get("fitness", 0), reverse=True)

    # Deduplicate by genome_id (same genome may appear in multiple generations)
    seen = set()
    unique = []
    for g in sorted_genomes:
        gid = g["genome_id"]
        if gid not in seen:
            seen.add(gid)
            unique.append(g)
        if len(unique) >= top_n:
            break

    return unique


def validate_genome(
    genome_data: dict,
    model: str,
    fast_model: str,
    rounds: int,
    trial: int,
    logger: ExperimentLogger,
) -> dict:
    """Run a single validation trial for one genome."""
    genome = Genome(
        genes=genome_data["genes"].copy(),
        genome_id=genome_data["genome_id"],
    )

    collider = Collider(
        num_rounds=rounds,
        model=model,
        fast_model=fast_model,
        logger=None,
    )

    try:
        defended = collider.run_defended_with_genome(genome.genes)
        fitness = compute_fitness(defended)

        results = {
            "genome_id": genome.genome_id,
            "trial": trial,
            "model": model,
            "rounds": rounds,
            "fitness": fitness,
            "detection_rate": defended.get("bridge", {}).get("detection_rate", 0),
            "accuracy": defended.get("accuracy", {}).get("avg_accuracy_coverage", 0),
            "corruption": defended.get("memory", {}).get("corruption_ratio", 0),
            "interventions": defended.get("total_interventions", 0),
            "blocked": defended.get("layer3_taint", {}).get("insertions_blocked", 0),
            "blue_memories": defended.get("memory", {}).get("ground_truth_entries", 0),
            "total_tokens": defended.get("layer4_kinetics", {}).get("total_consumed", 0),
            "persona_drift": defended.get("layer3_anchor", {}).get("current_drift", 0),
        }
    except Exception as e:
        print(f"    ❌ Trial {trial} for {genome.genome_id} failed: {e}")
        results = {
            "genome_id": genome.genome_id,
            "trial": trial,
            "model": model,
            "rounds": rounds,
            "fitness": 0.0,
            "error": str(e),
        }

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="GA Phase 2: Validate top genomes on nemotron:70b"
    )
    parser.add_argument("--top", type=int, default=3,
                        help="Number of top genomes to validate (default: 3)")
    parser.add_argument("--rounds", type=int, default=5,
                        help="Collider rounds per validation (default: 5)")
    parser.add_argument("--trials", type=int, default=3,
                        help="Number of validation trials per genome (default: 3)")
    parser.add_argument("--model", type=str, default=PRIMARY_MODEL,
                        help=f"Validation model (default: {PRIMARY_MODEL})")
    parser.add_argument("--fast-model", type=str, default=FAST_MODEL,
                        help=f"Overseer model (default: {FAST_MODEL})")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d_%H%M%S")
    logger = ExperimentLogger(
        experiment_name="exp20_ga_phase2",
        run_id=run_id,
    )
    monitor = SystemMonitor(
        experiment_name="exp20_ga_phase2",
        run_id=run_id,
        interval_s=15,
    )
    monitor.start()

    # Load top genomes from Phase 1
    top_genomes = load_top_genomes(args.top)

    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  NAIL INSTITUTE — GA PHASE 2: VALIDATION                    ║")
    print("  ║                                                             ║")
    print(f"  ║  Genomes:     {args.top:<48}║")
    print(f"  ║  Trials:      {args.trials:<48}║")
    print(f"  ║  Rounds:      {args.rounds:<48}║")
    print(f"  ║  Model:       {args.model:<48}║")
    print("  ║                                                             ║")
    print("  ║  Validating Phase 1 winners on the primary model            ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("=" * 70 + "\n")

    for i, g in enumerate(top_genomes):
        p1_fitness = g.get("fitness", 0)
        print(f"  Genome {i+1}: {g['genome_id']} "
              f"(Phase 1 fitness: {p1_fitness:.4f})")
    print()

    logger.log_event("info", message=f"Phase 2 started: {args.top} genomes, "
                     f"{args.trials} trials, {args.rounds} rounds, model={args.model}")

    # Run validation
    all_results = []
    start = time.time()

    for gi, genome_data in enumerate(top_genomes):
        gid = genome_data["genome_id"]
        p1_fitness = genome_data.get("fitness", 0)
        print(f"\n{'─'*60}")
        print(f"  Validating genome {gi+1}/{args.top}: {gid}")
        print(f"  Phase 1 fitness: {p1_fitness:.4f}")
        print(f"{'─'*60}")

        genome_trials = []
        for trial in range(1, args.trials + 1):
            trial_start = time.time()
            print(f"\n  Trial {trial}/{args.trials}...")

            result = validate_genome(
                genome_data=genome_data,
                model=args.model,
                fast_model=args.fast_model,
                rounds=args.rounds,
                trial=trial,
                logger=logger,
            )
            trial_time = time.time() - trial_start
            result["trial_time_s"] = round(trial_time, 1)
            genome_trials.append(result)

            print(f"    fitness={result['fitness']:.4f} "
                  f"detect={result.get('detection_rate', '?')} "
                  f"acc={result.get('accuracy', '?')} "
                  f"corrupt={result.get('corruption', '?')} "
                  f"({trial_time/60:.1f}min)")

            logger.log_event("ga_phase2_trial", data=result,
                             message=f"{gid} trial {trial}: fitness={result['fitness']:.4f}")

        # Aggregate trials
        valid_trials = [t for t in genome_trials if "error" not in t]
        if valid_trials:
            avg_fitness = sum(t["fitness"] for t in valid_trials) / len(valid_trials)
            avg_accuracy = sum(t.get("accuracy", 0) for t in valid_trials) / len(valid_trials)
            avg_detection = sum(t.get("detection_rate", 0) for t in valid_trials) / len(valid_trials)
            avg_corruption = sum(t.get("corruption", 0) for t in valid_trials) / len(valid_trials)
        else:
            avg_fitness = avg_accuracy = avg_detection = avg_corruption = 0.0

        genome_summary = {
            "genome_id": gid,
            "genes": genome_data["genes"],
            "phase1_fitness": p1_fitness,
            "phase2_avg_fitness": round(avg_fitness, 4),
            "phase2_avg_accuracy": round(avg_accuracy, 4),
            "phase2_avg_detection": round(avg_detection, 4),
            "phase2_avg_corruption": round(avg_corruption, 4),
            "phase2_trials": genome_trials,
            "valid_trials": len(valid_trials),
            "fitness_change": round(avg_fitness - p1_fitness, 4),
        }
        all_results.append(genome_summary)

        print(f"\n  ► {gid} summary:")
        print(f"    Phase 1 fitness:  {p1_fitness:.4f}")
        print(f"    Phase 2 avg:      {avg_fitness:.4f} ({'+' if avg_fitness >= p1_fitness else ''}{avg_fitness - p1_fitness:.4f})")
        print(f"    Avg accuracy:     {avg_accuracy:.2%}")
        print(f"    Avg detection:    {avg_detection:.2%}")
        print(f"    Avg corruption:   {avg_corruption:.2%}")

    total_time = time.time() - start

    # Determine overall winner
    best = max(all_results, key=lambda g: g["phase2_avg_fitness"])

    # Save results
    output = {
        "config": {
            "model": args.model,
            "fast_model": args.fast_model,
            "rounds": args.rounds,
            "trials": args.trials,
            "top_n": args.top,
            "total_time_s": round(total_time, 1),
        },
        "champion": best["genome_id"],
        "champion_genes": best["genes"],
        "champion_fitness": best["phase2_avg_fitness"],
        "genomes": all_results,
    }

    output_path = DATA_DIR / "exp20_ga_phase2_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    # Final summary
    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  GA PHASE 2 — COMPLETE                                      ║")
    print("  ╠═══════════════════════════════════════════════════════════════╣")
    print(f"  ║  Champion:    {best['genome_id']:<48}║")
    print(f"  ║  P1 Fitness:  {best['phase1_fitness']:.4f}                                      ║")
    print(f"  ║  P2 Fitness:  {best['phase2_avg_fitness']:.4f} ({'+' if best['fitness_change']>=0 else ''}{best['fitness_change']:.4f})                               ║")
    print(f"  ║  Accuracy:    {best['phase2_avg_accuracy']:.2%}                                       ║")
    print(f"  ║  Detection:   {best['phase2_avg_detection']:.2%}                                       ║")
    print(f"  ║  Corruption:  {best['phase2_avg_corruption']:.2%}                                         ║")
    print(f"  ║                                                             ║")
    print(f"  ║  Total Time:  {total_time/60:.1f} min                                      ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print(f"\n  Results: {output_path}")
    print("=" * 70)

    logger.log_event("info", data={"champion": best["genome_id"],
                                    "champion_fitness": best["phase2_avg_fitness"]},
                     message=f"Phase 2 complete: champion={best['genome_id']} "
                             f"fitness={best['phase2_avg_fitness']:.4f}")

    monitor.stop()
    summary = monitor.get_summary()
    try:
        from rich.table import Table
        from rich.console import Console
        table = Table(title=f"System Resources: exp20_ga_phase2 ({run_id})")
        table.add_column("Metric")
        table.add_column("Value")
        for k, v in summary.items():
            table.add_row(str(k), str(round(v, 1) if isinstance(v, float) else v))
        Console().print(table)
    except ImportError:
        for k, v in summary.items():
            print(f"  {k}: {v}")

    print(f"\n   Phase 2 complete in {total_time:.1f}s")


if __name__ == "__main__":
    main()
