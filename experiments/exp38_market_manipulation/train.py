"""
Training Script: RL Market Manipulation Agent
==============================================
Trains a PPO agent to discover market manipulation strategies
in a calibrated LOB simulator.

Usage:
    python -m experiments.exp38_market_manipulation.train
    python -m experiments.exp38_market_manipulation.train --algo sac --steps 3000000
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from stable_baselines3 import PPO, SAC
from stable_baselines3.common.callbacks import (
    BaseCallback,
    CheckpointCallback,
    EvalCallback,
)
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import SubprocVecEnv

from .market_env import MarketManipulationEnv
from .reward import RewardConfig


# ─── Paths ──────────────────────────────────────────────────────────────

EXP_DIR = Path(__file__).parent
LOG_DIR = EXP_DIR / "logs"
MODEL_DIR = EXP_DIR / "models"
EVAL_DIR = EXP_DIR / "eval"


# ─── Custom Callback ───────────────────────────────────────────────────

class SurveillanceLogCallback(BaseCallback):
    """
    Logs surveillance scores and manipulation metrics
    at episode end for analysis.
    """

    def __init__(self, log_path: Path, verbose: int = 0):
        super().__init__(verbose)
        self.log_path = log_path
        self.episode_rewards: list[float] = []
        self.surveillance_scores: list[dict] = []
        self.manipulation_summaries: list[dict] = []
        self._episode_count = 0

    def _on_step(self) -> bool:
        # Check for episode completions in vectorised envs
        for idx, done in enumerate(self.locals.get("dones", [])):
            if done:
                info = self.locals.get("infos", [{}])[idx]
                self._episode_count += 1

                if "surveillance" in info:
                    self.surveillance_scores.append({
                        "episode": self._episode_count,
                        "step": self.num_timesteps,
                        **info["surveillance"],
                    })

                if "metrics" in info:
                    m = info["metrics"]
                    self.manipulation_summaries.append({
                        "episode": self._episode_count,
                        "step": self.num_timesteps,
                        "total_pnl": m.total_pnl,
                        "cancel_to_trade_ratio": m.cancel_to_trade_ratio,
                        "phantom_liquidity_ratio": m.phantom_liquidity_ratio,
                        "n_price_levels_used": m.n_price_levels_used,
                        "layering_gradient": m.layering_gradient,
                        "fill_rate": m.fill_rate,
                    })

                if "reward_breakdown" in info:
                    self.logger.record(
                        "custom/reward_profit",
                        info["reward_breakdown"].get("profit", 0),
                    )
                    self.logger.record(
                        "custom/reward_stealth",
                        info["reward_breakdown"].get("stealth", 0),
                    )
                    self.logger.record(
                        "custom/reward_detection_penalty",
                        info["reward_breakdown"].get("detection_penalty", 0),
                    )

                # Log every 100 episodes
                if self._episode_count % 100 == 0 and self.verbose > 0:
                    avg_composite = np.mean([
                        s.get("composite", 0) for s in self.surveillance_scores[-100:]
                    ])
                    avg_pnl = np.mean([
                        m.get("total_pnl", 0) for m in self.manipulation_summaries[-100:]
                    ])
                    print(
                        f"[Ep {self._episode_count}] "
                        f"Avg PnL: {avg_pnl:.2f} | "
                        f"Avg Surveillance: {avg_composite:.3f}"
                    )

        return True

    def _on_training_end(self) -> None:
        """Save collected data to disk."""
        self.log_path.mkdir(parents=True, exist_ok=True)

        if self.surveillance_scores:
            with open(self.log_path / "surveillance_scores.json", "w") as f:
                json.dump(self.surveillance_scores, f, indent=2, default=str)

        if self.manipulation_summaries:
            with open(self.log_path / "manipulation_summaries.json", "w") as f:
                json.dump(self.manipulation_summaries, f, indent=2, default=str)


class StrategyDiscoveryCallback(BaseCallback):
    """
    Detects novel manipulation strategies by tracking
    which reward components dominate and how surveillance
    scores evolve.
    """

    def __init__(self, discovery_threshold: float = 0.7, verbose: int = 0):
        super().__init__(verbose)
        self.discovery_threshold = discovery_threshold
        self.discovered_strategies: list[dict] = []

    def _on_step(self) -> bool:
        for idx, done in enumerate(self.locals.get("dones", [])):
            if done:
                info = self.locals.get("infos", [{}])[idx]
                surv = info.get("surveillance", {})
                metrics = info.get("metrics", None)

                if not metrics:
                    continue

                # Strategy: High PnL + Low Detection = evasive manipulation
                if metrics.total_pnl > 50 and surv.get("composite", 1.0) < 0.3:
                    self.discovered_strategies.append({
                        "type": "evasive_manipulation",
                        "step": self.num_timesteps,
                        "pnl": metrics.total_pnl,
                        "composite_score": surv.get("composite", 0),
                        "cancel_ratio": metrics.cancel_to_trade_ratio,
                        "phantom_ratio": metrics.phantom_liquidity_ratio,
                        "n_levels": metrics.n_price_levels_used,
                    })
                    if self.verbose:
                        print(
                            f"\n🔍 EVASIVE STRATEGY FOUND at step {self.num_timesteps}! "
                            f"PnL={metrics.total_pnl:.1f}, "
                            f"Detection={surv.get('composite', 0):.3f}"
                        )

                # Strategy: Layering discovered
                if (metrics.n_price_levels_used >= 3 and
                        metrics.layering_gradient > self.discovery_threshold):
                    self.discovered_strategies.append({
                        "type": "layering",
                        "step": self.num_timesteps,
                        "pnl": metrics.total_pnl,
                        "levels": metrics.n_price_levels_used,
                        "gradient": metrics.layering_gradient,
                    })

                # Strategy: Spoofing pattern (high cancel, short lifetime)
                if (metrics.cancel_to_trade_ratio > 5 and
                        metrics.avg_order_lifetime_ticks < 3):
                    self.discovered_strategies.append({
                        "type": "spoofing",
                        "step": self.num_timesteps,
                        "pnl": metrics.total_pnl,
                        "cancel_ratio": metrics.cancel_to_trade_ratio,
                        "avg_lifetime": metrics.avg_order_lifetime_ticks,
                    })

        return True


# ─── Environment Factory ──────────────────────────────────────────────

def make_env(
    episode_length: int = 150,
    reward_config: Optional[RewardConfig] = None,
    seed: int = 0,
    rank: int = 0,
):
    """Create a single environment instance."""
    def _init():
        env = MarketManipulationEnv(
            episode_length=episode_length,
            reward_config=reward_config or RewardConfig(),
            seed=seed + rank,
        )
        env = Monitor(env)
        return env
    return _init


# ─── Training ─────────────────────────────────────────────────────────

def train(
    algo: str = "ppo",
    total_timesteps: int = 1_500_000,
    n_envs: int = 4,
    episode_length: int = 150,
    learning_rate: float = 3e-4,
    batch_size: int = 256,
    n_steps: int = 2048,
    seed: int = 42,
    checkpoint_freq: int = 50_000,
    eval_freq: int = 25_000,
    verbose: int = 1,
    reward_config: Optional[RewardConfig] = None,
    run_name: Optional[str] = None,
) -> dict:
    """
    Train the RL manipulation agent.

    Returns:
        dict with training results and discovered strategies.
    """
    if run_name is None:
        run_name = f"{algo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    run_log_dir = LOG_DIR / run_name
    run_model_dir = MODEL_DIR / run_name
    run_eval_dir = EVAL_DIR / run_name

    for d in [run_log_dir, run_model_dir, run_eval_dir]:
        d.mkdir(parents=True, exist_ok=True)

    config = reward_config or RewardConfig()

    print(f"\n{'='*60}")
    print(f"  Market Manipulation RL Training")
    print(f"  Algorithm: {algo.upper()}")
    print(f"  Steps: {total_timesteps:,}")
    print(f"  Environments: {n_envs}")
    print(f"  Episode Length: {episode_length}")
    print(f"  Run: {run_name}")
    print(f"{'='*60}\n")

    # ── Build vectorised environments ──
    env_fns = [make_env(episode_length, config, seed, i) for i in range(n_envs)]
    train_env = SubprocVecEnv(env_fns)
    # Note: obs are already normalised in MarketManipulationEnv._get_obs()
    # so we skip VecNormalize to avoid NaN issues on startup

    eval_env_fn = [make_env(episode_length, config, seed + 1000, 0)]
    eval_env = SubprocVecEnv(eval_env_fn)

    # ── Callbacks ──
    surveillance_cb = SurveillanceLogCallback(
        log_path=run_log_dir, verbose=verbose
    )
    discovery_cb = StrategyDiscoveryCallback(verbose=verbose)
    checkpoint_cb = CheckpointCallback(
        save_freq=checkpoint_freq // n_envs,
        save_path=str(run_model_dir),
        name_prefix="manipulation_agent",
    )
    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path=str(run_model_dir / "best"),
        log_path=str(run_eval_dir),
        eval_freq=eval_freq // n_envs,
        n_eval_episodes=10,
        deterministic=True,
    )

    callbacks = [surveillance_cb, discovery_cb, checkpoint_cb, eval_cb]

    # ── Create model ──
    # Ensure n_steps doesn't exceed total_timesteps / n_envs
    effective_n_steps = min(n_steps, max(total_timesteps // n_envs, 64))

    if algo.lower() == "ppo":
        model = PPO(
            "MlpPolicy",
            train_env,
            learning_rate=learning_rate,
            n_steps=effective_n_steps,
            batch_size=min(batch_size, effective_n_steps * n_envs),
            n_epochs=10,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            vf_coef=0.5,
            max_grad_norm=0.5,
            verbose=verbose,
            seed=seed,
            device="cpu",
            policy_kwargs=dict(
                net_arch=dict(pi=[256, 256], vf=[256, 256]),
            ),
        )
    elif algo.lower() == "sac":
        # SAC requires continuous action space — wrap
        # For now, fall back to PPO with multi-discrete
        print("⚠ SAC requires continuous actions. Using PPO instead.")
        model = PPO(
            "MlpPolicy",
            train_env,
            learning_rate=learning_rate,
            n_steps=n_steps,
            batch_size=batch_size,
            verbose=verbose,
            seed=seed,
            device="cpu",
            policy_kwargs=dict(
                net_arch=dict(pi=[256, 256], vf=[256, 256]),
            ),
        )
    else:
        raise ValueError(f"Unknown algorithm: {algo}")

    # ── Train ──
    t0 = time.time()
    model.learn(
        total_timesteps=total_timesteps,
        callback=callbacks,
        progress_bar=True,
    )
    train_time = time.time() - t0

    # ── Save ──
    final_path = run_model_dir / "final_model"
    model.save(str(final_path))

    # ── Summary ──
    results = {
        "algo": algo,
        "total_timesteps": total_timesteps,
        "train_time_seconds": train_time,
        "n_episodes": surveillance_cb._episode_count,
        "n_strategies_discovered": len(discovery_cb.discovered_strategies),
        "discovered_strategies": discovery_cb.discovered_strategies,
        "model_path": str(final_path),
        "log_path": str(run_log_dir),
    }

    # Save results
    with open(run_log_dir / "training_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"  Training Complete!")
    print(f"  Episodes: {results['n_episodes']}")
    print(f"  Time: {train_time:.1f}s")
    print(f"  Strategies Discovered: {results['n_strategies_discovered']}")
    print(f"  Model: {final_path}")
    print(f"{'='*60}\n")

    train_env.close()
    eval_env.close()

    return results


# ─── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Train RL Market Manipulation Agent"
    )
    parser.add_argument(
        "--algo", type=str, default="ppo",
        choices=["ppo", "sac"],
        help="RL algorithm (default: ppo)"
    )
    parser.add_argument(
        "--steps", type=int, default=1_500_000,
        help="Total training timesteps (default: 1.5M)"
    )
    parser.add_argument(
        "--envs", type=int, default=4,
        help="Number of parallel environments (default: 4)"
    )
    parser.add_argument(
        "--episode-length", type=int, default=150,
        help="Steps per episode (default: 150)"
    )
    parser.add_argument(
        "--lr", type=float, default=3e-4,
        help="Learning rate (default: 3e-4)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default: 42)"
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Run name (default: auto-generated)"
    )
    parser.add_argument(
        "--stealth-weight", type=float, default=0.5,
        help="Stealth reward weight (default: 0.5)"
    )
    parser.add_argument(
        "--detection-penalty", type=float, default=-2.0,
        help="Detection penalty weight (default: -2.0)"
    )

    args = parser.parse_args()

    config = RewardConfig(
        w_stealth=args.stealth_weight,
        w_detection_penalty=args.detection_penalty,
    )

    train(
        algo=args.algo,
        total_timesteps=args.steps,
        n_envs=args.envs,
        episode_length=args.episode_length,
        learning_rate=args.lr,
        seed=args.seed,
        run_name=args.name,
        reward_config=config,
    )


if __name__ == "__main__":
    main()
