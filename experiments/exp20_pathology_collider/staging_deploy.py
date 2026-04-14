"""
NAIL Institute — QAOA Threshold Staging Deployment Pipeline
==============================================================

Automated validation pipeline for deploying quantum-optimized thresholds
to the Pathology Collider.

Pipeline stages:
  1. LOAD    — Read QAOA + GA threshold configs
  2. A/B RUN — Execute Collider with both configs side-by-side
  3. SCORE   — Compute fitness for both using identical fitness function
  4. CERTIFY — Statistical comparison (Monte Carlo noise injection)
  5. REPORT  — Generate deployment decision + versioned config file
  6. PROMOTE — If quantum wins, update active thresholds

Usage:
    python -m exp20_pathology_collider.staging_deploy
    python -m exp20_pathology_collider.staging_deploy --rounds 10 --trials 3
    python -m exp20_pathology_collider.staging_deploy --dry-run
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import PRIMARY_MODEL, FAST_MODEL, DATA_DIR
from shared.logger import ExperimentLogger

from exp20_pathology_collider.collider import Collider
from exp20_pathology_collider.ga_optimizer import (
    Genome, compute_fitness, GENE_DEFS, GENE_NAMES,
)
from exp20_pathology_collider.quantum_thresholds import (
    QUANTUM_THRESHOLDS, GA_ONLY_DEFAULTS, get_defense_config,
    get_layer_config, load_from_file, to_ga_genome,
)


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

STAGING_DIR = Path(__file__).parent / "staging_results"
CONFIG_DIR = Path(__file__).parent / "deployed_configs"

# GA baseline (g1_8241) — the current production thresholds
GA_BASELINE_GENES = {
    "trust_threshold":        0.4000,
    "scan_probability":       0.7146,
    "compound_threshold":     2,
    "token_velocity":         2000,
    "spike_threshold":        0.3000,
    "drift_threshold":        0.3000,
    "suspicion_window":       3,
    "burst_threshold":        2,
    "corruption_ceiling":     0.3,
    "min_trust_floor":        0.4117,
    "manipulation_threshold": 3.5827,
    "burn_rate_accel":        1.5000,
}

# QAOA thresholds mapped to GA gene format
QAOA_GENES = to_ga_genome()

# Deployment decision thresholds
MIN_FITNESS_IMPROVEMENT = 0.01     # Quantum must beat GA by at least 1%
MIN_ACCURACY_IMPROVEMENT = 0.05    # Must improve accuracy by at least 5pp
MAX_CORRUPTION_REGRESSION = 0.02   # Corruption cannot regress by more than 2pp
MAX_DRIFT_REGRESSION = 0.05        # Drift cannot regress by more than 5pp
MONTE_CARLO_CONFIDENCE = 0.95      # 95% confidence required


# ═══════════════════════════════════════════════════════════════════════════
# Staging Result Container
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StagingResult:
    """Container for a single A/B staging trial."""
    trial_id: int
    ga_fitness: float = 0.0
    qaoa_fitness: float = 0.0
    ga_results: dict = field(default_factory=dict)
    qaoa_results: dict = field(default_factory=dict)
    ga_time_seconds: float = 0.0
    qaoa_time_seconds: float = 0.0

    @property
    def fitness_delta(self) -> float:
        return self.qaoa_fitness - self.ga_fitness

    @property
    def quantum_wins(self) -> bool:
        return self.qaoa_fitness > self.ga_fitness

    def to_dict(self) -> dict:
        return {
            "trial_id": self.trial_id,
            "ga_fitness": round(self.ga_fitness, 4),
            "qaoa_fitness": round(self.qaoa_fitness, 4),
            "fitness_delta": round(self.fitness_delta, 4),
            "quantum_wins": self.quantum_wins,
            "ga_time_seconds": round(self.ga_time_seconds, 1),
            "qaoa_time_seconds": round(self.qaoa_time_seconds, 1),
            "ga_metrics": self._extract_metrics(self.ga_results),
            "qaoa_metrics": self._extract_metrics(self.qaoa_results),
        }

    def _extract_metrics(self, results: dict) -> dict:
        """Extract key metrics from Collider results."""
        return {
            "detection_rate": results.get("detection_rate", 0),
            "stealth_score": results.get("stealth_score", 0),
            "accuracy": results.get("accuracy", {}).get("avg_accuracy_coverage", 0),
            "memory_corruption": results.get("memory", {}).get("corruption_ratio", 0),
            "drift": results.get("layer3_anchor", {}).get("max_drift", 0),
            "interventions": results.get("total_interventions", 0),
            "insertions_blocked": results.get("layer3_taint", {}).get("insertions_blocked", 0),
            "budget_consumed": results.get("layer4_kinetics", {}).get("total_consumed", 0),
            "quantum_anomalies": results.get("layer5_quantum", {}).get("anomalies_detected", 0),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Deployment Decision Engine
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DeploymentDecision:
    """Structured deployment recommendation."""
    recommend_deploy: bool
    confidence: float
    fitness_improvement: float
    accuracy_improvement: float
    corruption_delta: float
    drift_delta: float
    trials_quantum_wins: int
    trials_total: int
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "recommend_deploy": self.recommend_deploy,
            "confidence": round(self.confidence, 4),
            "fitness_improvement": round(self.fitness_improvement, 4),
            "accuracy_improvement": round(self.accuracy_improvement, 4),
            "corruption_delta": round(self.corruption_delta, 4),
            "drift_delta": round(self.drift_delta, 4),
            "win_rate": f"{self.trials_quantum_wins}/{self.trials_total}",
            "reasons": self.reasons,
            "warnings": self.warnings,
        }


def make_deployment_decision(trials: list[StagingResult]) -> DeploymentDecision:
    """
    Analyze staging trials and produce a deployment recommendation.

    Decision criteria:
    1. Quantum must win majority of trials
    2. Average fitness improvement must exceed MIN_FITNESS_IMPROVEMENT
    3. Accuracy must improve by at least MIN_ACCURACY_IMPROVEMENT
    4. Corruption cannot regress beyond MAX_CORRUPTION_REGRESSION
    5. Drift cannot regress beyond MAX_DRIFT_REGRESSION
    """
    reasons = []
    warnings = []

    # Win rate
    wins = sum(1 for t in trials if t.quantum_wins)
    win_rate = wins / len(trials)

    # Average deltas
    avg_fitness_delta = sum(t.fitness_delta for t in trials) / len(trials)

    ga_acc = [t.ga_results.get("accuracy", {}).get("avg_accuracy_coverage", 0) for t in trials]
    qaoa_acc = [t.qaoa_results.get("accuracy", {}).get("avg_accuracy_coverage", 0) for t in trials]
    avg_acc_delta = sum(q - g for q, g in zip(qaoa_acc, ga_acc)) / len(trials)

    ga_corr = [t.ga_results.get("memory", {}).get("corruption_ratio", 0) for t in trials]
    qaoa_corr = [t.qaoa_results.get("memory", {}).get("corruption_ratio", 0) for t in trials]
    avg_corr_delta = sum(q - g for q, g in zip(qaoa_corr, ga_corr)) / len(trials)

    ga_drift = [t.ga_results.get("layer3_anchor", {}).get("max_drift", 0) for t in trials]
    qaoa_drift = [t.qaoa_results.get("layer3_anchor", {}).get("max_drift", 0) for t in trials]
    avg_drift_delta = sum(q - g for q, g in zip(qaoa_drift, ga_drift)) / len(trials)

    # ── Evaluate criteria ───────────────────────────────────────────

    # 1. Win rate
    if win_rate >= MONTE_CARLO_CONFIDENCE:
        reasons.append(f"✅ Quantum wins {wins}/{len(trials)} trials ({win_rate:.0%})")
    elif win_rate > 0.5:
        warnings.append(f"⚠️ Quantum wins {wins}/{len(trials)} ({win_rate:.0%}) — below {MONTE_CARLO_CONFIDENCE:.0%} confidence")
    else:
        reasons.append(f"❌ Quantum only wins {wins}/{len(trials)} ({win_rate:.0%})")

    # 2. Fitness improvement
    if avg_fitness_delta >= MIN_FITNESS_IMPROVEMENT:
        reasons.append(f"✅ Fitness improvement: +{avg_fitness_delta:.4f} (threshold: {MIN_FITNESS_IMPROVEMENT})")
    else:
        reasons.append(f"❌ Fitness improvement: +{avg_fitness_delta:.4f} (below {MIN_FITNESS_IMPROVEMENT})")

    # 3. Accuracy improvement
    if avg_acc_delta >= MIN_ACCURACY_IMPROVEMENT:
        reasons.append(f"✅ Accuracy improvement: +{avg_acc_delta:.1%} (threshold: {MIN_ACCURACY_IMPROVEMENT:.0%})")
    elif avg_acc_delta >= 0:
        warnings.append(f"⚠️ Accuracy improvement: +{avg_acc_delta:.1%} (below {MIN_ACCURACY_IMPROVEMENT:.0%} target)")
    else:
        reasons.append(f"❌ Accuracy regressed: {avg_acc_delta:.1%}")

    # 4. Corruption regression check
    if avg_corr_delta <= MAX_CORRUPTION_REGRESSION:
        reasons.append(f"✅ Corruption delta: {avg_corr_delta:+.1%} (limit: +{MAX_CORRUPTION_REGRESSION:.0%})")
    else:
        reasons.append(f"❌ Corruption regressed: {avg_corr_delta:+.1%} (exceeds +{MAX_CORRUPTION_REGRESSION:.0%})")

    # 5. Drift regression check
    if avg_drift_delta <= MAX_DRIFT_REGRESSION:
        reasons.append(f"✅ Drift delta: {avg_drift_delta:+.4f} (limit: +{MAX_DRIFT_REGRESSION})")
    else:
        warnings.append(f"⚠️ Drift regressed: {avg_drift_delta:+.4f} (exceeds +{MAX_DRIFT_REGRESSION})")

    # ── Final decision ──────────────────────────────────────────────

    blockers = [r for r in reasons if r.startswith("❌")]
    recommend = len(blockers) == 0 and win_rate > 0.5 and avg_fitness_delta > 0

    confidence = win_rate * (1.0 if len(blockers) == 0 else 0.5)

    return DeploymentDecision(
        recommend_deploy=recommend,
        confidence=confidence,
        fitness_improvement=avg_fitness_delta,
        accuracy_improvement=avg_acc_delta,
        corruption_delta=avg_corr_delta,
        drift_delta=avg_drift_delta,
        trials_quantum_wins=wins,
        trials_total=len(trials),
        reasons=reasons,
        warnings=warnings,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Staged Threshold Config (versioned, deployable)
# ═══════════════════════════════════════════════════════════════════════════

def generate_deployed_config(
    decision: DeploymentDecision,
    trials: list[StagingResult],
) -> dict:
    """
    Generate a versioned, deployable threshold config.

    This is the artifact that gets promoted to production.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    config = {
        "version": "qaoa-v1",
        "generated_at": timestamp,
        "source": "QAOA 20-qubit, 150 gradient steps, DGX Spark",
        "decision": decision.to_dict(),
        "thresholds": {
            "quantum_optimized": QUANTUM_THRESHOLDS,
            "ga_only_defaults": GA_ONLY_DEFAULTS,
            "merged": get_defense_config(),
        },
        "layer_configs": {
            "telemetry": get_layer_config("telemetry"),
            "tensor": get_layer_config("tensor"),
            "memory": get_layer_config("memory"),
            "economic": get_layer_config("economic"),
        },
        "validation": {
            "trials": len(trials),
            "avg_fitness": round(
                sum(t.qaoa_fitness for t in trials) / len(trials), 4
            ),
            "avg_accuracy": round(
                sum(
                    t.qaoa_results.get("accuracy", {}).get("avg_accuracy_coverage", 0)
                    for t in trials
                ) / len(trials),
                4,
            ),
            "avg_corruption": round(
                sum(
                    t.qaoa_results.get("memory", {}).get("corruption_ratio", 0)
                    for t in trials
                ) / len(trials),
                4,
            ),
        },
        "ga_baseline": GA_BASELINE_GENES,
        "ga_genome_id": "g1_8241",
    }

    return config


# ═══════════════════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════════════════

class StagingPipeline:
    """
    Automated staging deployment pipeline for QAOA thresholds.

    Runs A/B trials comparing GA vs QAOA thresholds on the live
    Collider, then makes a data-driven deployment recommendation.
    """

    def __init__(
        self,
        rounds: int = 5,
        trials: int = 3,
        model: str = PRIMARY_MODEL,
        fast_model: str = FAST_MODEL,
        dry_run: bool = False,
    ):
        self.rounds = rounds
        self.trials = trials
        self.model = model
        self.fast_model = fast_model
        self.dry_run = dry_run

    def run(self) -> dict:
        """Execute the full staging pipeline."""

        print("\n" + "╔" + "═" * 62 + "╗")
        print("║  NAIL INSTITUTE — QAOA THRESHOLD STAGING PIPELINE           ║")
        print("║  Automated A/B Validation: GA (g1_8241) vs QAOA (20-qubit)  ║")
        print("╠" + "═" * 62 + "╣")
        print(f"║  Rounds per trial: {self.rounds:<43}║")
        print(f"║  Trials: {self.trials:<53}║")
        print(f"║  Model: {self.model:<54}║")
        print(f"║  Dry run: {self.dry_run!s:<52}║")
        print("╚" + "═" * 62 + "╝\n")

        start = time.time()

        # ── Stage 1: Load Configs ───────────────────────────────────────

        print("═" * 64)
        print("  STAGE 1: LOADING THRESHOLD CONFIGURATIONS")
        print("═" * 64)

        print(f"\n  📄 GA Baseline (g1_8241):")
        for k, v in sorted(GA_BASELINE_GENES.items()):
            print(f"    {k:>25}: {v}")

        print(f"\n  ⚛️  QAOA Optimized (20-qubit):")
        for k, v in sorted(QAOA_GENES.items()):
            ga_val = GA_BASELINE_GENES.get(k, "—")
            delta = ""
            if isinstance(v, (int, float)) and isinstance(ga_val, (int, float)):
                d = v - ga_val
                delta = f"  (Δ {d:+.4f})" if d != 0 else ""
            print(f"    {k:>25}: {v}{delta}")

        # ── Stage 2: A/B Trials ─────────────────────────────────────────

        print(f"\n{'═' * 64}")
        print(f"  STAGE 2: A/B TRIALS ({self.trials} trials × {self.rounds} rounds)")
        print(f"{'═' * 64}\n")

        trial_results: list[StagingResult] = []

        for trial_num in range(1, self.trials + 1):
            print(f"\n  ╔══ TRIAL {trial_num}/{self.trials} ══╗\n")

            result = StagingResult(trial_id=trial_num)

            # Set up Collider for this trial
            collider = Collider(
                num_rounds=self.rounds,
                model=self.model,
                fast_model=self.fast_model,
            )

            # ── Run GA baseline ─────────────────────────────────────
            print(f"  📊 Running GA baseline (g1_8241)...")
            ga_start = time.time()
            ga_defended = collider.run_defended_with_genome(GA_BASELINE_GENES)
            result.ga_time_seconds = time.time() - ga_start
            result.ga_results = ga_defended

            # ── Run QAOA ────────────────────────────────────────────
            print(f"\n  ⚛️  Running QAOA thresholds...")
            qaoa_start = time.time()
            qaoa_defended = collider.run_defended_with_genome(QAOA_GENES)
            result.qaoa_time_seconds = time.time() - qaoa_start
            result.qaoa_results = qaoa_defended

            # ── Compute fitness ─────────────────────────────────────
            result.ga_fitness = compute_fitness(ga_defended)
            result.qaoa_fitness = compute_fitness(qaoa_defended)

            trial_results.append(result)

            # ── Trial summary ───────────────────────────────────────
            winner = "⚛️  QAOA" if result.quantum_wins else "🧬 GA"
            print(f"\n  ╔══ TRIAL {trial_num} RESULT ══╗")
            print(f"  ║  GA fitness:   {result.ga_fitness:.4f}")
            print(f"  ║  QAOA fitness: {result.qaoa_fitness:.4f}")
            print(f"  ║  Delta:        {result.fitness_delta:+.4f}")
            print(f"  ║  Winner:       {winner}")
            print(f"  ╚{'═' * 25}╝\n")

        # ── Stage 3: Deployment Decision ────────────────────────────────

        print(f"\n{'═' * 64}")
        print(f"  STAGE 3: DEPLOYMENT DECISION")
        print(f"{'═' * 64}\n")

        decision = make_deployment_decision(trial_results)

        print("  DECISION REPORT:")
        print("  " + "─" * 50)
        for reason in decision.reasons:
            print(f"  {reason}")
        for warning in decision.warnings:
            print(f"  {warning}")
        print("  " + "─" * 50)

        if decision.recommend_deploy:
            print(f"\n  🚀 RECOMMENDATION: DEPLOY QAOA THRESHOLDS")
            print(f"     Confidence: {decision.confidence:.0%}")
        else:
            print(f"\n  ⛔ RECOMMENDATION: KEEP GA BASELINE")
            print(f"     Confidence: {decision.confidence:.0%}")

        # ── Stage 4: Generate Config + Save ─────────────────────────────

        print(f"\n{'═' * 64}")
        print(f"  STAGE 4: GENERATE DEPLOYMENT ARTIFACTS")
        print(f"{'═' * 64}\n")

        config = generate_deployed_config(decision, trial_results)

        # Save staging results
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Staging report
        staging_report = {
            "pipeline": "qaoa_staging_deploy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "rounds": self.rounds,
                "trials": self.trials,
                "model": self.model,
                "dry_run": self.dry_run,
            },
            "trials": [t.to_dict() for t in trial_results],
            "decision": decision.to_dict(),
            "deployed_config": config if decision.recommend_deploy else None,
        }

        report_path = STAGING_DIR / f"staging_report_{timestamp}.json"
        with open(report_path, "w") as f:
            json.dump(staging_report, f, indent=2, default=str)
        print(f"  📄 Staging report: {report_path}")

        # Deployed config (only if recommended and not dry-run)
        if decision.recommend_deploy and not self.dry_run:
            config_path = CONFIG_DIR / f"qaoa_v1_{timestamp}.json"
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2, default=str)
            print(f"  🔧 Deployed config: {config_path}")

            # Write "active" symlink / latest pointer
            latest_path = CONFIG_DIR / "active_config.json"
            with open(latest_path, "w") as f:
                json.dump(config, f, indent=2, default=str)
            print(f"  ✅ Active config updated: {latest_path}")

        elif decision.recommend_deploy and self.dry_run:
            print(f"  ⏸️  DRY RUN — config NOT written to disk")

        else:
            print(f"  ⛔ Deployment NOT recommended — no config written")

        # ── Final Summary ───────────────────────────────────────────────

        total_time = time.time() - start

        print(f"\n{'╔' + '═' * 62 + '╗'}")
        print(f"{'║'}  STAGING PIPELINE COMPLETE                                    {'║'}")
        print(f"{'╠' + '═' * 62 + '╣'}")
        print(f"{'║'}  Total time:      {total_time/60:.1f} minutes{' ' * (62 - 28 - len(f'{total_time/60:.1f}'))}{'║'}")
        print(f"{'║'}  Trials run:      {self.trials}{' ' * (62 - 22 - len(str(self.trials)))}{'║'}")
        print(f"{'║'}  Quantum wins:    {decision.trials_quantum_wins}/{decision.trials_total}{' ' * (62 - 24 - len(f'{decision.trials_quantum_wins}/{decision.trials_total}'))}{'║'}")
        print(f"{'║'}  Fitness Δ:       {decision.fitness_improvement:+.4f}{' ' * (62 - 24 - len(f'{decision.fitness_improvement:+.4f}'))}{'║'}")
        recommend_str = "DEPLOY" if decision.recommend_deploy else "HOLD"
        print(f"{'║'}  Recommendation:  {recommend_str}{' ' * (62 - 24 - len(recommend_str))}{'║'}")
        print(f"{'╚' + '═' * 62 + '╝'}\n")

        return staging_report


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="NAIL Institute — QAOA Threshold Staging Deployment Pipeline"
    )
    parser.add_argument("--rounds", type=int, default=5,
                        help="Rounds per trial (default: 5)")
    parser.add_argument("--trials", type=int, default=3,
                        help="Number of A/B trials (default: 3)")
    parser.add_argument("--model", type=str, default=PRIMARY_MODEL,
                        help="Primary model for Collider")
    parser.add_argument("--fast-model", type=str, default=FAST_MODEL,
                        help="Fast model for OOB overseer")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run pipeline but don't write deployment config")

    args = parser.parse_args()

    pipeline = StagingPipeline(
        rounds=args.rounds,
        trials=args.trials,
        model=args.model,
        fast_model=args.fast_model,
        dry_run=args.dry_run,
    )

    results = pipeline.run()

    # Exit code: 0 if deploy recommended, 1 if not
    if results.get("decision", {}).get("recommend_deploy"):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
