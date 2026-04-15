"""
Reward Function: FCA Stylized-Fact Calibrated
==============================================
Shapes RL training reward from publicly available stylized facts about
market manipulation, WITHOUT reverse-engineering any specific FCA
enforcement case.

Sources:
  - FCA Market Watch 79 (July 2024): Spoofing/layering patterns
  - FCA Market Watch 80 (March 2025): Proactive model validation
  - Hagströmer & Nordén (2013): Order-to-trade ratios in spoofing
  - Cao et al. (2014): Layering geometric signatures
  - Cumming et al. (2015): Cancel-to-trade ratio thresholds

Reward components:
  1. PROFIT:    Did the manipulation move the price favourably?
  2. EXECUTION: Did the agent actually trade at the manipulated price?
  3. STEALTH:   Does the pattern evade simple detection heuristics?
  4. PENALTY:   Static penalty for known manipulation signatures

The reward function is designed to train an agent that discovers
NOVEL manipulation strategies — not replicate known ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class ManipulationMetrics:
    """Metrics computed at end of each episode for reward/surveillance."""
    # Profit
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    total_pnl: float = 0.0

    # Price impact
    price_displacement: float = 0.0     # How far mid moved from entry
    displacement_direction: float = 0.0  # +1 if favourable, -1 if adverse

    # Execution quality
    fill_rate: float = 0.0              # Fraction of intended trade that filled
    avg_fill_price: float = 0.0
    intended_profit_trade_executed: bool = False

    # Spoofing indicators (surveillance-visible)
    cancel_to_trade_ratio: float = 0.0
    avg_order_lifetime_ticks: float = 0.0
    order_to_trade_ratio: float = 0.0
    max_one_sided_volume_fraction: float = 0.0
    phantom_liquidity_ratio: float = 0.0  # Cancelled volume / total placed volume

    # Layering indicators
    n_price_levels_used: int = 0
    layering_gradient: float = 0.0      # Size gradient across levels (decreasing = layering)
    price_level_concentration: float = 0.0  # HHI of order sizes across levels

    # Temporal patterns
    order_burst_rate: float = 0.0       # Max orders in any 5-tick window
    cancel_burst_rate: float = 0.0      # Max cancels in any 5-tick window
    order_cancel_lag: float = 0.0       # Avg time between place and cancel

    # Position
    final_inventory: int = 0            # Should be flat for clean manipulation


# ─── Reward Components ─────────────────────────────────────────────────

@dataclass
class RewardConfig:
    """Weights and thresholds for reward components.

    These are the knobs we tune to shape what strategies the RL agent
    discovers. The defaults encourage profitable manipulation that
    avoids the most obvious detection signatures.
    """
    # Profit weights
    w_profit: float = 1.0
    profit_scale: float = 0.01      # Normalise PnL to [-1, 1] range

    # Execution
    w_execution: float = 0.3
    fill_rate_target: float = 0.8   # Reward for filling the intended trade

    # Stealth (reward for evading detection)
    w_stealth: float = 0.5

    # Static detection penalties
    # These represent "obvious" manipulation that any basic system catches
    cancel_ratio_threshold: float = 5.0   # FCA flag threshold
    order_lifetime_threshold: float = 3.0  # Ticks — suspiciously short
    phantom_volume_threshold: float = 0.7  # >70% cancelled = flag

    # Penalty weights
    w_detection_penalty: float = -2.0
    w_inventory_penalty: float = -0.5     # Penalise holding overnight risk

    # Bonus for novel strategies
    w_novelty_bonus: float = 0.2


def compute_reward(
    metrics: ManipulationMetrics,
    config: Optional[RewardConfig] = None,
) -> tuple[float, dict[str, float]]:
    """
    Compute the shaped reward for a manipulation episode.

    Returns:
        (total_reward, component_breakdown)
    """
    cfg = config or RewardConfig()
    components = {}

    # ── 1. Profit component ──
    profit = metrics.total_pnl * cfg.profit_scale
    profit = np.clip(profit, -1.0, 1.0)  # Normalise
    components["profit"] = profit * cfg.w_profit

    # ── 2. Execution component ──
    execution = 0.0
    if metrics.intended_profit_trade_executed:
        execution = min(metrics.fill_rate / cfg.fill_rate_target, 1.0)
    components["execution"] = execution * cfg.w_execution

    # ── 3. Stealth component ──
    # Higher reward for keeping surveillance metrics BELOW detection thresholds
    stealth_scores = []

    # Cancel-to-trade ratio: below 5.0 is stealthy
    if metrics.cancel_to_trade_ratio < cfg.cancel_ratio_threshold:
        ctr_stealth = 1.0 - (metrics.cancel_to_trade_ratio / cfg.cancel_ratio_threshold)
    else:
        ctr_stealth = -1.0  # Penalise for being over threshold
    stealth_scores.append(ctr_stealth)

    # Order lifetime: longer is stealthier (less suspicious)
    if metrics.avg_order_lifetime_ticks > cfg.order_lifetime_threshold:
        lifetime_stealth = min(metrics.avg_order_lifetime_ticks / 20.0, 1.0)
    else:
        lifetime_stealth = -0.5
    stealth_scores.append(lifetime_stealth)

    # Phantom volume: lower is stealthier
    if metrics.phantom_liquidity_ratio < cfg.phantom_volume_threshold:
        phantom_stealth = 1.0 - (metrics.phantom_liquidity_ratio / cfg.phantom_volume_threshold)
    else:
        phantom_stealth = -0.5
    stealth_scores.append(phantom_stealth)

    stealth = np.mean(stealth_scores)
    components["stealth"] = stealth * cfg.w_stealth

    # ── 4. Detection penalty ──
    # Hard penalties for crossing multiple detection thresholds simultaneously
    flags_tripped = 0
    if metrics.cancel_to_trade_ratio > cfg.cancel_ratio_threshold:
        flags_tripped += 1
    if metrics.avg_order_lifetime_ticks < cfg.order_lifetime_threshold:
        flags_tripped += 1
    if metrics.phantom_liquidity_ratio > cfg.phantom_volume_threshold:
        flags_tripped += 1
    if metrics.order_burst_rate > 10:  # >10 orders in 5 ticks
        flags_tripped += 1
    if metrics.n_price_levels_used > 5 and metrics.layering_gradient > 0.3:
        flags_tripped += 1  # Layering signature

    detection_penalty = 0.0
    if flags_tripped >= 3:
        detection_penalty = cfg.w_detection_penalty * (flags_tripped / 5.0)
    elif flags_tripped >= 2:
        detection_penalty = cfg.w_detection_penalty * 0.3
    components["detection_penalty"] = detection_penalty

    # ── 5. Inventory penalty ──
    # Good manipulation ends flat (no overnight risk)
    inventory_penalty = cfg.w_inventory_penalty * abs(metrics.final_inventory) / 1000.0
    components["inventory_penalty"] = inventory_penalty

    # ── 6. Novelty bonus ──
    # Reward strategies that are profitable despite NOT tripping obvious flags
    novelty = 0.0
    if profit > 0.1 and flags_tripped == 0:
        novelty = cfg.w_novelty_bonus  # Profitable AND stealthy = novel
    elif profit > 0.3 and flags_tripped <= 1:
        novelty = cfg.w_novelty_bonus * 0.5
    components["novelty_bonus"] = novelty

    total = sum(components.values())
    components["total"] = total

    return total, components


# ─── Surveillance Score (for NAIL integration) ─────────────────────────

def compute_surveillance_score(metrics: ManipulationMetrics) -> dict[str, float]:
    """
    Compute a surveillance score that NAIL monitoring would see.

    This is the defender's view — the detection system's output.
    The RL agent is trying to keep these LOW while still profiting.
    """
    scores = {}

    # 1. Spoofing score [0, 1]
    spoofing = min(
        (metrics.cancel_to_trade_ratio / 10.0) * 0.4 +
        (1.0 - min(metrics.avg_order_lifetime_ticks / 20.0, 1.0)) * 0.3 +
        min(metrics.phantom_liquidity_ratio, 1.0) * 0.3,
        1.0
    )
    scores["spoofing"] = spoofing

    # 2. Layering score [0, 1]
    layering = min(
        min(metrics.n_price_levels_used / 8, 1.0) * 0.4 +
        min(metrics.layering_gradient, 1.0) * 0.3 +
        (1.0 - min(metrics.price_level_concentration, 1.0)) * 0.3,
        1.0
    )
    scores["layering"] = layering

    # 3. Wash trading score [0, 1]
    # Simplified: if agent is both aggressive buyer and seller in short window
    wash = 0.0  # Would need cross-referencing with other traders
    scores["wash_trading"] = wash

    # 4. Price manipulation score [0, 1]
    price_manip = min(
        abs(metrics.price_displacement) * 10.0 * 0.5 +
        (1.0 if metrics.intended_profit_trade_executed else 0.0) * 0.3 +
        min(abs(metrics.total_pnl) / 1000.0, 1.0) * 0.2,
        1.0
    )
    scores["price_manipulation"] = price_manip

    # 5. Composite abuse score
    scores["composite"] = max(spoofing, layering, price_manip)

    return scores
