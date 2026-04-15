"""
EXP38: Market Manipulation via RL in Calibrated LOB Simulator
==============================================================
NAIL Institute — Adversarial Agent Training

This experiment implements the approach described in FCA market
surveillance research: training RL agents in calibrated limit
order book simulators to discover novel market manipulation
strategies, then using those strategies to stress-test and
improve detection systems.

Components:
    lob.py        — High-performance limit order book engine
    reward.py     — FCA stylized-fact calibrated reward function
    market_env.py — Gymnasium environment for RL training
    train.py      — PPO training with surveillance callbacks
    run.py        — End-to-end orchestrator + NAIL monitor overlay

Quick start:
    # Smoke test
    python -m experiments.exp38_market_manipulation.run --smoke-only

    # Quick training (5k steps)
    python -m experiments.exp38_market_manipulation.run --quick

    # Full training (1.5M steps)
    python -m experiments.exp38_market_manipulation.run
"""

from .lob import BackgroundTrader, LimitOrderBook, Order, OrderType, Side, Trade
from .market_env import MarketManipulationEnv
from .reward import (
    ManipulationMetrics,
    RewardConfig,
    compute_reward,
    compute_surveillance_score,
)

__all__ = [
    "BackgroundTrader",
    "LimitOrderBook",
    "ManipulationMetrics",
    "MarketManipulationEnv",
    "Order",
    "OrderType",
    "RewardConfig",
    "Side",
    "Trade",
    "compute_reward",
    "compute_surveillance_score",
]
