"""
NAIL Institute — Horizon 1: GA Runner
========================================
CLI entry point for the Genetic Algorithm threshold optimizer.

Usage:
    python3 -m exp20_pathology_collider.run_ga --population 12 --generations 15 --rounds 3
    python3 -m exp20_pathology_collider.run_ga --population 6 --generations 5 --rounds 2 --quick

Options:
    --population N     Number of genomes per generation (default: 12)
    --generations N    Number of GA iterations (default: 15)
    --rounds N         Collider rounds per defended phase (default: 3)
    --model MODEL      LLM model for Collider runs (default: config.FAST_MODEL)
    --fast-model MODEL LLM model for overseer (default: config.FAST_MODEL)
    --elitism N        Top N survive unchanged (default: 2)
    --mutation-rate F  Per-gene mutation probability (default: 0.2)
    --no-seed          Don't include V3 thresholds as initial seed
    --quick            Quick test: population=4, generations=3, rounds=2
"""

import argparse
import json
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import PRIMARY_MODEL, FAST_MODEL, DATA_DIR
from shared.logger import ExperimentLogger
from shared.system_monitor import SystemMonitor

from .ga_optimizer import GeneticOptimizer, Genome


def main():
    parser = argparse.ArgumentParser(
        description="Horizon 1: Genetic Algorithm Threshold Optimizer"
    )
    parser.add_argument("--population", type=int, default=12,
                        help="Population size (default: 12)")
    parser.add_argument("--generations", type=int, default=15,
                        help="Number of generations (default: 15)")
    parser.add_argument("--rounds", type=int, default=3,
                        help="Collider rounds per evaluation (default: 3)")
    parser.add_argument("--model", type=str, default=FAST_MODEL,
                        help=f"LLM model (default: {FAST_MODEL})")
    parser.add_argument("--fast-model", type=str, default=FAST_MODEL,
                        help=f"Overseer model (default: {FAST_MODEL})")
    parser.add_argument("--elitism", type=int, default=2,
                        help="Elite survivors per generation (default: 2)")
    parser.add_argument("--mutation-rate", type=float, default=0.2,
                        help="Per-gene mutation rate (default: 0.2)")
    parser.add_argument("--no-seed", action="store_true",
                        help="Don't seed population with V3 thresholds")
    parser.add_argument("--quick", action="store_true",
                        help="Quick test: pop=4, gen=3, rounds=2")

    args = parser.parse_args()

    # Quick mode overrides
    if args.quick:
        args.population = 4
        args.generations = 3
        args.rounds = 2

    # Setup logging and monitoring
    run_id = time.strftime("%Y%m%d_%H%M%S")
    logger = ExperimentLogger(
        experiment_name="exp20_ga_optimizer",
        run_id=run_id,
    )
    monitor = SystemMonitor(
        experiment_name="exp20_ga_optimizer",
        run_id=run_id,
        interval_s=15,
    )
    monitor.start()

    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  NAIL INSTITUTE — HORIZON 1: GA THRESHOLD OPTIMIZER         ║")
    print("  ║                                                             ║")
    print("  ║  Evolving defense thresholds for optimal security +         ║")
    print("  ║  competency equilibrium                                     ║")
    print("  ║                                                             ║")
    print(f"  ║  Population:  {args.population:<48}║")
    print(f"  ║  Generations: {args.generations:<48}║")
    print(f"  ║  Rounds:      {args.rounds:<48}║")
    print(f"  ║  Model:       {args.model:<48}║")
    print(f"  ║  Seed V3:     {str(not args.no_seed):<48}║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("=" * 70 + "\n")

    logger.log_event("info", message=f"GA optimizer started: "
                     f"pop={args.population}, gen={args.generations}, "
                     f"rounds={args.rounds}, model={args.model}")

    # Create and run optimizer
    optimizer = GeneticOptimizer(
        pop_size=args.population,
        generations=args.generations,
        rounds=args.rounds,
        model=args.model,
        fast_model=args.fast_model,
        elitism=args.elitism,
        mutation_rate=args.mutation_rate,
        seed_v3=not args.no_seed,
        logger=logger,
    )

    start = time.time()
    best = optimizer.evolve()
    total_time = time.time() - start

    # Save results
    output_path = optimizer.save_results()

    # Print final summary
    print("\n" + "=" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  HORIZON 1 — COMPLETE                                       ║")
    print("  ╠═══════════════════════════════════════════════════════════════╣")
    print(f"  ║  Best Fitness: {best.fitness:.4f}                                      ║")
    print(f"  ║  Best Genome:  {best.genome_id:<48}║")

    res = best.evaluation_results
    print(f"  ║                                                             ║")
    print(f"  ║  Detection:    {res.get('detection_rate', 0):.0%}                                           ║")
    print(f"  ║  Accuracy:     {res.get('accuracy', 0):.0%}                                           ║")
    print(f"  ║  Corruption:   {res.get('corruption', 0):.0%}                                           ║")
    print(f"  ║  Blocked:      {res.get('blocked', 0)}                                              ║")
    print(f"  ║  Blue Mems:    {res.get('blue_memories', 0)}                                             ║")
    print(f"  ║                                                             ║")
    print(f"  ║  Total Time:   {total_time/60:.1f} min                                       ║")
    print(f"  ║  Evaluations:  {len(optimizer.all_genomes)}                                            ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print(f"\n  Results: {output_path}")
    print("=" * 70 + "\n")

    # Log completion
    logger.log_event("info", data=best.to_dict(),
                     message=f"GA complete: fitness={best.fitness:.4f}")

    # Stop monitoring and print resource summary
    monitor.stop()
    summary = monitor.get_summary()
    try:
        from rich.table import Table
        from rich.console import Console
        table = Table(title=f"System Resources: exp20_ga_optimizer ({run_id})")
        table.add_column("Metric")
        table.add_column("Value")
        for k, v in summary.items():
            table.add_row(str(k), str(round(v, 1) if isinstance(v, float) else v))
        Console().print(table)
    except ImportError:
        for k, v in summary.items():
            print(f"  {k}: {v}")

    print(f"\n{'Experiment complete':>22} in {total_time:.1f}s")

    return best


if __name__ == "__main__":
    main()
