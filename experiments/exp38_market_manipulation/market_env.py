"""
Gymnasium Environment: Market Manipulation LOB
================================================
Wraps the LimitOrderBook + BackgroundTrader into a Gymnasium environment
for RL training of adversarial market manipulation agents.

The agent plays the role of a manipulative trader who can:
  - Place limit orders at various price levels
  - Place market orders
  - Cancel previously placed orders
  - Do nothing (wait)

The environment provides a rich observation space including:
  - Order book depth (5 levels, bid + ask)
  - Mid-price history
  - Agent's own order/position state
  - Surveillance metrics (what a detector would see)

Action space is MultiDiscrete:
  [action_type, side, price_offset, size_bucket]

Episode structure:
  1. SETUP phase (50 steps): agent places deceptive orders
  2. PROFIT phase (50 steps): agent tries to execute profit trade
  3. UNWIND phase (50 steps): agent closes position
  Total: 150 steps per episode (configurable)
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .lob import BackgroundTrader, LimitOrderBook, Order, OrderType, Side
from .reward import (
    ManipulationMetrics,
    RewardConfig,
    compute_reward,
    compute_surveillance_score,
)


# ─── Constants ─────────────────────────────────────────────────────────

N_BOOK_LEVELS = 5           # Depth levels observed
PRICE_OFFSET_BUCKETS = 10   # Discrete price offsets (0-9 ticks from mid)
SIZE_BUCKETS = 5            # Order size categories
MAX_LIVE_ORDERS = 20        # Max concurrent orders for the agent

# Action types
ACT_NOOP = 0
ACT_LIMIT_ORDER = 1
ACT_MARKET_ORDER = 2
ACT_CANCEL_OLDEST = 3
ACT_CANCEL_ALL = 4


class MarketManipulationEnv(gym.Env):
    """
    LOB Market Manipulation Environment for RL.

    The RL agent learns to manipulate the order book to create
    profitable price movements while (optionally) evading detection.
    """

    metadata = {"render_modes": ["human", "ansi"], "render_fps": 4}

    def __init__(
        self,
        episode_length: int = 150,
        tick_size: float = 0.01,
        reference_price: float = 100.0,
        reward_config: Optional[RewardConfig] = None,
        background_arrival_rate: float = 0.5,
        seed: Optional[int] = None,
        render_mode: Optional[str] = None,
    ):
        super().__init__()
        self.episode_length = episode_length
        self.tick_size = tick_size
        self.reference_price = reference_price
        self.reward_config = reward_config or RewardConfig()
        self.bg_arrival_rate = background_arrival_rate
        self.render_mode = render_mode

        self._rng = np.random.default_rng(seed)

        # ── Action space ──
        # [action_type(5), side(2), price_offset(10), size_bucket(5)]
        self.action_space = spaces.MultiDiscrete([5, 2, PRICE_OFFSET_BUCKETS, SIZE_BUCKETS])

        # ── Observation space ──
        # Flat vector:
        #   - Book: 5 bid levels (price_offset, qty) + 5 ask levels = 20
        #   - Market state: mid_price_norm, spread, imbalance, volume = 4
        #   - Agent state: inventory, n_live_orders, unrealised_pnl, phase = 4
        #   - Price history: last 10 mid-price changes = 10
        #   - Surveillance: 4 detection metric proxies = 4
        # Total: 42 features
        obs_size = N_BOOK_LEVELS * 4 + 4 + 4 + 10 + 4
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_size,), dtype=np.float32
        )

        # ── Internal state ──
        self.book: Optional[LimitOrderBook] = None
        self.bg_trader: Optional[BackgroundTrader] = None
        self._step_count = 0
        self._agent_orders: list[str] = []  # Live order IDs
        self._agent_inventory = 0
        self._agent_cost_basis = 0.0
        self._agent_total_orders = 0
        self._agent_total_cancels = 0
        self._agent_total_trades = 0
        self._agent_fills: list[tuple[float, int]] = []  # (price, qty)
        self._agent_placed_volume = 0
        self._agent_cancelled_volume = 0
        self._order_timestamps: dict[str, int] = {}
        self._cancel_lifetimes: list[int] = []
        self._orders_per_window: deque[int] = deque(maxlen=5)
        self._cancels_per_window: deque[int] = deque(maxlen=5)
        self._price_at_entry: float = 0.0
        self._intended_side: Optional[Side] = None
        self._episode_orders: list[Order] = []

        # Size mapping
        self._size_map = [50, 100, 250, 500, 1000]

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._rng = np.random.default_rng(seed)

        self.book = LimitOrderBook(
            tick_size=self.tick_size,
            reference_price=self.reference_price,
        )
        self.bg_trader = BackgroundTrader(
            arrival_rate=self.bg_arrival_rate,
            rng=self._rng,
        )

        # Warm up the book with background orders
        for t in range(50):
            bg_orders = self.bg_trader.generate_orders(self.book, t)
            for o in bg_orders:
                self.book.submit_order(o)
            # Process cancels
            for cid in self.bg_trader._pending_cancels:
                self.book.cancel_order_by_id(cid, t)

        # Reset agent state
        self._step_count = 0
        self._agent_orders = []
        self._agent_inventory = 0
        self._agent_cost_basis = 0.0
        self._agent_total_orders = 0
        self._agent_total_cancels = 0
        self._agent_total_trades = 0
        self._agent_fills = []
        self._agent_placed_volume = 0
        self._agent_cancelled_volume = 0
        self._order_timestamps = {}
        self._cancel_lifetimes = []
        self._orders_per_window = deque(maxlen=5)
        self._cancels_per_window = deque(maxlen=5)
        self._price_at_entry = self.book.mid_price
        self._intended_side = None
        self._episode_orders = []

        # Randomly choose the intended manipulation direction
        self._intended_side = self._rng.choice([Side.BID, Side.ASK])

        obs = self._get_obs()
        info = self._get_info()
        return obs, info

    def step(self, action):
        assert self.book is not None

        self._step_count += 1
        timestamp = self._step_count + 50  # Offset by warmup

        step_orders = 0
        step_cancels = 0

        # ── Process agent action ──
        action_type, side_idx, price_offset, size_bucket = action
        side = Side.BID if side_idx == 0 else Side.ASK
        size = self._size_map[min(size_bucket, len(self._size_map) - 1)]
        mid = self.book.mid_price

        if action_type == ACT_LIMIT_ORDER:
            # Price: offset from mid in ticks
            if side == Side.BID:
                price = mid - price_offset * self.tick_size
            else:
                price = mid + price_offset * self.tick_size
            price = round(price / self.tick_size) * self.tick_size
            price = max(price, self.tick_size)

            if len(self._agent_orders) < MAX_LIVE_ORDERS:
                oid = f"AGENT_{self._agent_total_orders:04d}"
                order = Order(
                    order_id=oid,
                    trader_id="RL_AGENT",
                    side=side,
                    price=price,
                    quantity=size,
                    order_type=OrderType.LIMIT,
                    timestamp=timestamp,
                )
                trades = self.book.submit_order(order)
                self._agent_orders.append(oid)
                self._order_timestamps[oid] = timestamp
                self._agent_total_orders += 1
                self._agent_placed_volume += size
                self._episode_orders.append(order)
                step_orders += 1
                self._process_agent_trades(trades)

        elif action_type == ACT_MARKET_ORDER:
            oid = f"AGENT_MKT_{self._agent_total_orders:04d}"
            order = Order(
                order_id=oid,
                trader_id="RL_AGENT",
                side=side,
                price=0.0,
                quantity=size,
                order_type=OrderType.MARKET,
                timestamp=timestamp,
            )
            trades = self.book.submit_order(order)
            self._agent_total_orders += 1
            self._agent_placed_volume += size
            self._episode_orders.append(order)
            step_orders += 1
            self._process_agent_trades(trades)

        elif action_type == ACT_CANCEL_OLDEST:
            if self._agent_orders:
                oldest_id = self._agent_orders.pop(0)
                # Look up remaining volume BEFORE cancel
                remaining_vol = 0
                if oldest_id in self.book._orders:
                    remaining_vol = self.book._orders[oldest_id].remaining
                if self.book.cancel_order_by_id(oldest_id, timestamp):
                    self._agent_total_cancels += 1
                    step_cancels += 1
                    place_time = self._order_timestamps.get(oldest_id, timestamp)
                    self._cancel_lifetimes.append(timestamp - place_time)
                    self._agent_cancelled_volume += remaining_vol

        elif action_type == ACT_CANCEL_ALL:
            for oid in self._agent_orders[:]:
                remaining_vol = 0
                if oid in self.book._orders:
                    remaining_vol = self.book._orders[oid].remaining
                if self.book.cancel_order_by_id(oid, timestamp):
                    self._agent_total_cancels += 1
                    step_cancels += 1
                    place_time = self._order_timestamps.get(oid, timestamp)
                    self._cancel_lifetimes.append(timestamp - place_time)
                    self._agent_cancelled_volume += remaining_vol
            self._agent_orders.clear()

        # ACT_NOOP: do nothing

        self._orders_per_window.append(step_orders)
        self._cancels_per_window.append(step_cancels)

        # ── Process background orders ──
        bg_orders = self.bg_trader.generate_orders(self.book, timestamp)
        for o in bg_orders:
            trades = self.book.submit_order(o)
            # Check if any background trades filled agent's passive orders
            self._process_agent_trades(trades)
        for cid in self.bg_trader._pending_cancels:
            self.book.cancel_order_by_id(cid, timestamp)

        # Prune dead orders from agent's tracking list
        self._agent_orders = [
            oid for oid in self._agent_orders
            if oid in self.book._orders and self.book._orders[oid].is_alive
        ]

        # ── Check episode end ──
        terminated = self._step_count >= self.episode_length
        truncated = False

        # ── Reward ──
        reward = 0.0
        if terminated:
            metrics = self._compute_metrics()
            reward, self._last_reward_breakdown = compute_reward(
                metrics, self.reward_config
            )
            self._last_metrics = metrics
            self._last_surveillance = compute_surveillance_score(metrics)
        else:
            # Small shaping reward: reward for price movement in intended direction
            current_mid = self.book.mid_price
            if self._intended_side == Side.BID:
                # Agent wants price to go DOWN (to buy cheap)
                reward = (self._price_at_entry - current_mid) * 0.001
            else:
                # Agent wants price to go UP (to sell dear)
                reward = (current_mid - self._price_at_entry) * 0.001

        obs = self._get_obs()
        info = self._get_info()

        return obs, reward, terminated, truncated, info

    def _process_agent_trades(self, trades):
        """Update agent inventory from trades."""
        for trade in trades:
            if trade.aggressor_id == "RL_AGENT":
                qty = trade.quantity
                if trade.aggressor_side == Side.BID:
                    self._agent_inventory += qty
                    self._agent_cost_basis += trade.price * qty
                else:
                    self._agent_inventory -= qty
                    self._agent_cost_basis -= trade.price * qty
                self._agent_fills.append((trade.price, qty))
                self._agent_total_trades += 1
            elif trade.passive_id == "RL_AGENT":
                qty = trade.quantity
                if trade.aggressor_side == Side.BID:
                    # Agent was passive ask → sold
                    self._agent_inventory -= qty
                    self._agent_cost_basis -= trade.price * qty
                else:
                    # Agent was passive bid → bought
                    self._agent_inventory += qty
                    self._agent_cost_basis += trade.price * qty
                self._agent_fills.append((trade.price, qty))
                self._agent_total_trades += 1

    def _get_obs(self) -> np.ndarray:
        """Build the observation vector."""
        obs = []
        mid = self.book.mid_price

        # Book depth (normalised offsets from mid)
        bids = self.book.depth(Side.BID, N_BOOK_LEVELS)
        asks = self.book.depth(Side.ASK, N_BOOK_LEVELS)

        for i in range(N_BOOK_LEVELS):
            if i < len(bids):
                obs.extend([(bids[i][0] - mid) / mid, bids[i][1] / 1000.0])
            else:
                obs.extend([0.0, 0.0])
        for i in range(N_BOOK_LEVELS):
            if i < len(asks):
                obs.extend([(asks[i][0] - mid) / mid, asks[i][1] / 1000.0])
            else:
                obs.extend([0.0, 0.0])

        # Market state
        obs.append((mid - self.reference_price) / self.reference_price)  # Normalised mid
        spread = self.book.spread
        if spread == float("inf"):
            spread = 0.0
        obs.append(spread / mid if mid > 0 else 0.0)
        obs.append(self.book.imbalance())
        obs.append(min(len(self.book.trades) / 100.0, 1.0))  # Volume proxy

        # Agent state
        obs.append(self._agent_inventory / 1000.0)
        obs.append(len(self._agent_orders) / MAX_LIVE_ORDERS)
        # Unrealised PnL
        unrealised = self._agent_inventory * mid - self._agent_cost_basis
        obs.append(unrealised / 1000.0)
        # Phase (0-1)
        obs.append(self._step_count / self.episode_length)

        # Price history (last 10 changes)
        mids = self.book.mid_prices
        for i in range(10):
            if len(mids) > i + 1:
                obs.append((mids[-(i+1)] - mids[-(i+2)]) / mid)
            else:
                obs.append(0.0)

        # Surveillance proxies (what the agent can "see" about its own detectability)
        ctr = self._agent_total_cancels / max(self._agent_total_trades, 1)
        obs.append(min(ctr / 10.0, 1.0))
        avg_life = (
            sum(self._cancel_lifetimes) / len(self._cancel_lifetimes)
            if self._cancel_lifetimes else 20.0
        )
        obs.append(min(avg_life / 50.0, 1.0))
        phantom = self._agent_cancelled_volume / max(self._agent_placed_volume, 1)
        obs.append(phantom)
        obs.append(max(self._orders_per_window) / 10.0 if self._orders_per_window else 0.0)

        return np.nan_to_num(
            np.array(obs, dtype=np.float32),
            nan=0.0, posinf=10.0, neginf=-10.0,
        )

    def _get_info(self) -> dict:
        """Return info dict."""
        info = {
            "step": self._step_count,
            "mid_price": self.book.mid_price,
            "spread": self.book.spread,
            "inventory": self._agent_inventory,
            "n_orders": len(self._agent_orders),
            "n_trades": self._agent_total_trades,
        }
        if hasattr(self, "_last_metrics"):
            info["metrics"] = self._last_metrics
            info["surveillance"] = self._last_surveillance
            info["reward_breakdown"] = self._last_reward_breakdown
        return info

    def _compute_metrics(self) -> ManipulationMetrics:
        """Compute end-of-episode manipulation metrics."""
        m = ManipulationMetrics()

        mid = self.book.mid_price

        # PnL
        m.unrealised_pnl = self._agent_inventory * mid - self._agent_cost_basis
        m.realised_pnl = 0.0  # Simplified: all PnL is mark-to-market
        m.total_pnl = m.unrealised_pnl

        # Price displacement
        m.price_displacement = mid - self._price_at_entry
        if self._intended_side == Side.BID:
            m.displacement_direction = -1.0 if m.price_displacement < 0 else 1.0
        else:
            m.displacement_direction = 1.0 if m.price_displacement > 0 else -1.0

        # Execution
        m.fill_rate = (
            sum(qty for _, qty in self._agent_fills) /
            max(self._agent_placed_volume, 1)
        )
        if self._agent_fills:
            m.avg_fill_price = (
                sum(p * q for p, q in self._agent_fills) /
                sum(q for _, q in self._agent_fills)
            )
        m.intended_profit_trade_executed = self._agent_total_trades > 0

        # Spoofing indicators
        m.cancel_to_trade_ratio = (
            self._agent_total_cancels / max(self._agent_total_trades, 1)
        )
        m.avg_order_lifetime_ticks = (
            sum(self._cancel_lifetimes) / len(self._cancel_lifetimes)
            if self._cancel_lifetimes else 0.0
        )
        m.order_to_trade_ratio = (
            self._agent_total_orders / max(self._agent_total_trades, 1)
        )
        m.phantom_liquidity_ratio = (
            self._agent_cancelled_volume / max(self._agent_placed_volume, 1)
        )

        # Layering indicators
        price_levels_used = set()
        level_volumes: dict[float, int] = {}
        for o in self._episode_orders:
            if o.order_type == OrderType.LIMIT:
                price_levels_used.add(o.price)
                level_volumes[o.price] = level_volumes.get(o.price, 0) + o.quantity

        m.n_price_levels_used = len(price_levels_used)
        if level_volumes:
            volumes = list(level_volumes.values())
            total_vol = sum(volumes)
            # Layering gradient: correlation between price distance from mid and size
            if len(volumes) > 1:
                prices = sorted(level_volumes.keys())
                mid_entry = self._price_at_entry
                distances = [abs(p - mid_entry) for p in prices]
                sizes = [level_volumes[p] for p in prices]
                if np.std(distances) > 0 and np.std(sizes) > 0:
                    m.layering_gradient = abs(np.corrcoef(distances, sizes)[0, 1])
                else:
                    m.layering_gradient = 0.0

            # HHI concentration
            shares = [(v / total_vol) ** 2 for v in volumes]
            m.price_level_concentration = sum(shares)

        # Temporal patterns
        m.order_burst_rate = max(self._orders_per_window) if self._orders_per_window else 0.0
        m.cancel_burst_rate = max(self._cancels_per_window) if self._cancels_per_window else 0.0
        m.order_cancel_lag = m.avg_order_lifetime_ticks

        # Final inventory
        m.final_inventory = self._agent_inventory

        return m

    def render(self):
        if self.render_mode == "ansi":
            return self._render_ansi()
        elif self.render_mode == "human":
            print(self._render_ansi())

    def _render_ansi(self) -> str:
        lines = [f"\n{'─' * 50}"]
        lines.append(f" Step {self._step_count}/{self.episode_length}")
        lines.append(f" Mid: {self.book.mid_price:.2f}  Spread: {self.book.spread_ticks:.1f} ticks")
        lines.append(f" Agent: inv={self._agent_inventory} orders={len(self._agent_orders)} "
                     f"trades={self._agent_total_trades} cancels={self._agent_total_cancels}")

        # Mini book display
        asks = self.book.depth(Side.ASK, 3)
        bids = self.book.depth(Side.BID, 3)
        lines.append(" ASK:")
        for p, q in reversed(asks):
            lines.append(f"   {p:8.2f}  [{q:>5d}]")
        lines.append(" ────────────────────")
        for p, q in bids:
            lines.append(f"   {p:8.2f}  [{q:>5d}]")
        lines.append(" BID:")
        lines.append(f"{'─' * 50}")
        return "\n".join(lines)
