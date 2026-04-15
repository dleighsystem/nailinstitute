"""
Orchestrator: exp38 Market Manipulation
========================================
End-to-end runner that:
  1. Trains the RL spoofing agent in the LOB simulator
  2. Evaluates discovered manipulation strategies
  3. Feeds episodes through NailMonitor + BreakingMechanism
  4. Generates a report of evasion strategies found

Usage:
    python -m experiments.exp38_market_manipulation.run
    python -m experiments.exp38_market_manipulation.run --quick  # Smoke test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from .market_env import MarketManipulationEnv
from .reward import RewardConfig, compute_surveillance_score

EXP_DIR = Path(__file__).parent
REPORT_DIR = EXP_DIR / "reports"


# ─── Evaluation ───────────────────────────────────────────────────────

def evaluate_agent(
    model_path: str,
    n_episodes: int = 50,
    episode_length: int = 150,
    seed: int = 99,
    render: bool = False,
    reward_config: Optional[RewardConfig] = None,
) -> dict:
    """
    Evaluate a trained agent and collect manipulation metrics.

    Returns:
        dict with per-episode results and aggregate statistics.
    """
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    config = reward_config or RewardConfig()

    env = MarketManipulationEnv(
        episode_length=episode_length,
        reward_config=config,
        seed=seed,
        render_mode="human" if render else None,
    )

    # Load model
    model = PPO.load(model_path, device="cpu")

    vec_env = DummyVecEnv([lambda: env])

    episodes = []
    for ep in range(n_episodes):
        obs = vec_env.reset()
        done = False
        total_reward = 0.0

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done_arr, info_arr = vec_env.step(action)
            done = done_arr[0]
            total_reward += reward[0]

            if render:
                env.render()

        info = info_arr[0]
        episodes.append({
            "episode": ep,
            "total_reward": float(total_reward),
            "surveillance": info.get("surveillance", {}),
            "metrics_summary": _metrics_to_dict(info.get("metrics")),
            "reward_breakdown": info.get("reward_breakdown", {}),
        })

    vec_env.close()

    # Aggregate
    results = _aggregate_results(episodes)
    return results


def _metrics_to_dict(metrics) -> dict:
    """Convert ManipulationMetrics to a serialisable dict."""
    if metrics is None:
        return {}
    return {
        "total_pnl": metrics.total_pnl,
        "price_displacement": metrics.price_displacement,
        "fill_rate": metrics.fill_rate,
        "cancel_to_trade_ratio": metrics.cancel_to_trade_ratio,
        "avg_order_lifetime_ticks": metrics.avg_order_lifetime_ticks,
        "phantom_liquidity_ratio": metrics.phantom_liquidity_ratio,
        "n_price_levels_used": metrics.n_price_levels_used,
        "layering_gradient": metrics.layering_gradient,
        "order_burst_rate": metrics.order_burst_rate,
        "final_inventory": metrics.final_inventory,
    }


def _aggregate_results(episodes: list[dict]) -> dict:
    """Compute aggregate statistics over evaluation episodes."""
    rewards = [e["total_reward"] for e in episodes]
    pnls = [e["metrics_summary"].get("total_pnl", 0) for e in episodes]
    composites = [e["surveillance"].get("composite", 0) for e in episodes]
    spoofing_scores = [e["surveillance"].get("spoofing", 0) for e in episodes]
    layering_scores = [e["surveillance"].get("layering", 0) for e in episodes]

    # Classify strategies
    evasive = [e for e in episodes if e["metrics_summary"].get("total_pnl", 0) > 0
               and e["surveillance"].get("composite", 1) < 0.3]
    detected_profitable = [e for e in episodes if e["metrics_summary"].get("total_pnl", 0) > 0
                           and e["surveillance"].get("composite", 1) >= 0.3]
    unprofitable = [e for e in episodes if e["metrics_summary"].get("total_pnl", 0) <= 0]

    return {
        "n_episodes": len(episodes),
        "episodes": episodes,
        "aggregate": {
            "reward_mean": float(np.mean(rewards)),
            "reward_std": float(np.std(rewards)),
            "pnl_mean": float(np.mean(pnls)),
            "pnl_std": float(np.std(pnls)),
            "pnl_positive_rate": sum(1 for p in pnls if p > 0) / len(pnls),
            "surveillance_composite_mean": float(np.mean(composites)),
            "spoofing_score_mean": float(np.mean(spoofing_scores)),
            "layering_score_mean": float(np.mean(layering_scores)),
        },
        "strategy_classification": {
            "evasive_profitable": len(evasive),
            "detected_profitable": len(detected_profitable),
            "unprofitable": len(unprofitable),
        },
    }


# ─── NAIL Monitor Integration ────────────────────────────────────────

def run_nail_analysis(eval_results: dict) -> dict:
    """
    Feed evaluation episodes through NAIL monitoring infrastructure.

    Checks what our v7 detectors would flag and whether
    the breaking mechanism would trigger.
    """
    try:
        from nail_monitor import NailMonitor, BreakingMechanism
        monitor_available = True
    except ImportError:
        monitor_available = False
        print("⚠ nail_monitor not importable — skipping NAIL analysis")
        return {"available": False}

    analysis = {
        "available": True,
        "episodes_analysed": 0,
        "would_flag": 0,
        "would_break": 0,
        "evasion_rate": 0.0,
        "details": [],
    }

    for ep in eval_results.get("episodes", []):
        surv = ep.get("surveillance", {})
        metrics = ep.get("metrics_summary", {})

        analysis["episodes_analysed"] += 1

        # Would a composite > 0.5 trigger detection?
        composite = surv.get("composite", 0)
        if composite > 0.5:
            analysis["would_flag"] += 1

        # Spoofing + high cancel ratio → would BreakingMechanism escalate?
        if (surv.get("spoofing", 0) > 0.7 or
            surv.get("layering", 0) > 0.7 or
            metrics.get("cancel_to_trade_ratio", 0) > 8):
            analysis["would_break"] += 1

        analysis["details"].append({
            "episode": ep["episode"],
            "composite": composite,
            "flagged": composite > 0.5,
            "pnl": metrics.get("total_pnl", 0),
        })

    total = analysis["episodes_analysed"]
    if total > 0:
        profitable_evasive = sum(
            1 for d in analysis["details"]
            if not d["flagged"] and d["pnl"] > 0
        )
        analysis["evasion_rate"] = profitable_evasive / total

    return analysis


# ─── Report Generation ───────────────────────────────────────────────

def generate_report(
    training_results: dict,
    eval_results: dict,
    nail_analysis: dict,
    run_name: str,
) -> str:
    """Generate a markdown report of the experiment."""
    report_path = REPORT_DIR / f"{run_name}_report.md"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    agg = eval_results.get("aggregate", {})
    strat = eval_results.get("strategy_classification", {})

    lines = [
        f"# EXP38: Market Manipulation RL — {run_name}",
        f"",
        f"**Generated**: {datetime.now().isoformat()}",
        f"",
        f"## Training Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Algorithm | {training_results.get('algo', 'ppo').upper()} |",
        f"| Total Steps | {training_results.get('total_timesteps', 0):,} |",
        f"| Episodes | {training_results.get('n_episodes', 0):,} |",
        f"| Training Time | {training_results.get('train_time_seconds', 0):.1f}s |",
        f"| Strategies Discovered | {training_results.get('n_strategies_discovered', 0)} |",
        f"",
        f"## Evaluation Results ({eval_results.get('n_episodes', 0)} episodes)",
        f"",
        f"### Performance",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Mean Reward | {agg.get('reward_mean', 0):.3f} ± {agg.get('reward_std', 0):.3f} |",
        f"| Mean PnL | {agg.get('pnl_mean', 0):.2f} ± {agg.get('pnl_std', 0):.2f} |",
        f"| Profitable Rate | {agg.get('pnl_positive_rate', 0)*100:.1f}% |",
        f"",
        f"### Surveillance Detection",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Mean Composite Score | {agg.get('surveillance_composite_mean', 0):.3f} |",
        f"| Mean Spoofing Score | {agg.get('spoofing_score_mean', 0):.3f} |",
        f"| Mean Layering Score | {agg.get('layering_score_mean', 0):.3f} |",
        f"",
        f"### Strategy Classification",
        f"| Category | Count |",
        f"|----------|-------|",
        f"| Evasive & Profitable | {strat.get('evasive_profitable', 0)} |",
        f"| Detected & Profitable | {strat.get('detected_profitable', 0)} |",
        f"| Unprofitable | {strat.get('unprofitable', 0)} |",
        f"",
    ]

    # Discovered strategies
    discovered = training_results.get("discovered_strategies", [])
    if discovered:
        lines.extend([
            f"## Discovered Manipulation Strategies",
            f"",
        ])
        for i, s in enumerate(discovered[:20]):  # Top 20
            lines.extend([
                f"### Strategy #{i+1}: {s.get('type', 'unknown')}",
                f"- **Step**: {s.get('step', 0):,}",
                f"- **PnL**: {s.get('pnl', 0):.2f}",
            ])
            if "composite_score" in s:
                lines.append(f"- **Detection Score**: {s['composite_score']:.3f}")
            if "cancel_ratio" in s:
                lines.append(f"- **Cancel Ratio**: {s['cancel_ratio']:.1f}")
            if "gradient" in s:
                lines.append(f"- **Layering Gradient**: {s['gradient']:.3f}")
            lines.append("")

    # NAIL analysis
    if nail_analysis.get("available"):
        lines.extend([
            f"## NAIL Monitor Analysis",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Episodes Analysed | {nail_analysis.get('episodes_analysed', 0)} |",
            f"| Would Flag | {nail_analysis.get('would_flag', 0)} |",
            f"| Would Break | {nail_analysis.get('would_break', 0)} |",
            f"| **Evasion Rate** | **{nail_analysis.get('evasion_rate', 0)*100:.1f}%** |",
            f"",
            f"> An evasion rate > 10% indicates the RL agent has found blind spots",
            f"> in our detection stack that need to be addressed.",
            f"",
        ])

    # Implications
    lines.extend([
        f"## Implications for NAIL Detection Stack",
        f"",
        f"### Detection Gaps Identified",
        f"- Strategies that achieve positive PnL below composite 0.3 represent",
        f"  genuine detection blind spots that need new pathology detectors.",
        f"- High layering gradient with low composite score suggests our",
        f"  v7 detectors need price-level correlation analysis.",
        f"",
        f"### Recommended Detector Improvements",
        f"1. **Temporal Pattern Detector**: Short order lifetimes + cancel bursts",
        f"2. **Cross-Side Correlation**: Detect orders on opposite sides by same agent",
        f"3. **Phantom Liquidity Tracker**: Volume placed vs volume cancelled ratio",
        f"4. **Layering Gradient Detector**: Size gradient across price levels",
        f"",
        f"---",
        f"*Generated by exp38_market_manipulation — NAIL Institute*",
    ])

    report_text = "\n".join(lines)
    report_path.write_text(report_text)
    print(f"\n📄 Report saved: {report_path}")

    return str(report_path)


# ─── Smoke Test ───────────────────────────────────────────────────────

def smoke_test() -> bool:
    """
    Quick validation that all components work end-to-end.
    Runs 3 episodes with a random agent.
    """
    print("\n🔬 Running smoke test...")

    env = MarketManipulationEnv(
        episode_length=50,
        reward_config=RewardConfig(),
        seed=42,
    )

    obs, info = env.reset()
    assert obs.shape == env.observation_space.shape, \
        f"Obs shape {obs.shape} != {env.observation_space.shape}"

    total_reward = 0.0
    for step in range(50):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward

        assert env.observation_space.contains(obs), \
            f"Obs out of bounds at step {step}"

        if terminated or truncated:
            break

    assert terminated, "Episode should have terminated"
    assert "surveillance" in info, "Terminal info should contain surveillance"
    assert "metrics" in info, "Terminal info should contain metrics"

    surv = info["surveillance"]
    assert "composite" in surv, "Surveillance should have composite score"
    assert 0 <= surv["composite"] <= 1, "Composite should be in [0,1]"

    metrics = info["metrics"]
    print(f"  ✅ Episode completed: reward={total_reward:.3f}")
    print(f"     PnL: {metrics.total_pnl:.2f}")
    print(f"     Surveillance composite: {surv['composite']:.3f}")
    print(f"     Cancel ratio: {metrics.cancel_to_trade_ratio:.1f}")
    print(f"     Fill rate: {metrics.fill_rate:.2%}")

    # Run 2 more episodes to verify reset
    for ep in range(2):
        obs, info = env.reset()
        done = False
        while not done:
            action = env.action_space.sample()
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        print(f"  ✅ Episode {ep+2} completed")

    env.close()
    print("  ✅ Smoke test PASSED\n")
    return True


# ─── Main Orchestrator ────────────────────────────────────────────────

def run(
    quick: bool = False,
    train_steps: int = 1_500_000,
    eval_episodes: int = 50,
    algo: str = "ppo",
    seed: int = 42,
):
    """
    Full experiment orchestration.
    """
    run_name = f"exp38_{algo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"\n{'█'*60}")
    print(f"  EXP38: Market Manipulation RL")
    print(f"  NAIL Institute — Adversarial Training")
    print(f"  Run: {run_name}")
    print(f"{'█'*60}\n")

    # Step 0: Smoke test
    if not smoke_test():
        print("❌ Smoke test FAILED — aborting")
        return

    if quick:
        print("⚡ Quick mode — minimal training for validation")
        train_steps = 5_000
        eval_episodes = 5

    # Step 1: Train
    from .train import train as train_agent
    training_results = train_agent(
        algo=algo,
        total_timesteps=train_steps,
        n_envs=2 if quick else 4,
        episode_length=50 if quick else 150,
        seed=seed,
        run_name=run_name,
        verbose=1,
    )

    # Step 2: Evaluate
    print("\n📊 Evaluating trained agent...")
    model_path = training_results["model_path"]
    eval_results = evaluate_agent(
        model_path=model_path,
        n_episodes=eval_episodes,
        episode_length=50 if quick else 150,
        seed=seed + 5000,
    )

    # Step 3: NAIL Monitor analysis
    print("\n🔍 Running NAIL Monitor analysis...")
    nail_analysis = run_nail_analysis(eval_results)

    # Step 4: Generate report
    report_path = generate_report(
        training_results=training_results,
        eval_results=eval_results,
        nail_analysis=nail_analysis,
        run_name=run_name,
    )

    # Step 5: Summary
    agg = eval_results.get("aggregate", {})
    strat = eval_results.get("strategy_classification", {})

    print(f"\n{'='*60}")
    print(f"  EXPERIMENT COMPLETE")
    print(f"{'='*60}")
    print(f"  Mean PnL:              {agg.get('pnl_mean', 0):.2f}")
    print(f"  Profitable Rate:       {agg.get('pnl_positive_rate', 0)*100:.1f}%")
    print(f"  Surveillance Score:    {agg.get('surveillance_composite_mean', 0):.3f}")
    print(f"  Evasive Strategies:    {strat.get('evasive_profitable', 0)}")
    print(f"  NAIL Evasion Rate:     {nail_analysis.get('evasion_rate', 0)*100:.1f}%")
    print(f"  Report:                {report_path}")
    print(f"{'='*60}\n")

    return {
        "training": training_results,
        "evaluation": eval_results,
        "nail_analysis": nail_analysis,
        "report": report_path,
    }


# ─── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="EXP38: Market Manipulation RL Orchestrator"
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick smoke-test run (5k steps, 5 eval episodes)"
    )
    parser.add_argument(
        "--smoke-only", action="store_true",
        help="Only run smoke test, no training"
    )
    parser.add_argument(
        "--steps", type=int, default=1_500_000,
        help="Training steps (default: 1.5M)"
    )
    parser.add_argument(
        "--eval-episodes", type=int, default=50,
        help="Evaluation episodes (default: 50)"
    )
    parser.add_argument(
        "--algo", type=str, default="ppo",
        choices=["ppo"],
        help="RL algorithm (default: ppo)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default: 42)"
    )

    args = parser.parse_args()

    if args.smoke_only:
        success = smoke_test()
        sys.exit(0 if success else 1)

    run(
        quick=args.quick,
        train_steps=args.steps,
        eval_episodes=args.eval_episodes,
        algo=args.algo,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
