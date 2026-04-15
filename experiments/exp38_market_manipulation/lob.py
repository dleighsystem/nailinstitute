"""
Limit Order Book (LOB) Engine
==============================
A high-performance, event-driven limit order book that models realistic
market microstructure for adversarial RL training.

Calibrated to:
  - FTSE 100 mid-cap liquidity (~£5M daily volume)
  - Realistic bid-ask spreads (2-8 ticks)
  - Kyle's lambda price impact
  - Poisson background order arrival
  - FCA Market Watch 79/80 surveillance-relevant features

Design priorities:
  1. Speed (pure Python, no dependencies beyond numpy) — target >10K steps/s
  2. Observable (full order-level audit trail for NAIL monitoring)
  3. Calibratable (all parameters exposed for sensitivity analysis)
"""

from __future__ import annotations

import bisect
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np


# ─── Types ────────────────────────────────────────────────────────────────

class Side(Enum):
    BID = auto()
    ASK = auto()


class OrderType(Enum):
    LIMIT = auto()
    MARKET = auto()
    CANCEL = auto()


@dataclass
class Order:
    """A single order in the LOB."""
    order_id: str
    trader_id: str
    side: Side
    price: float        # Ignored for MARKET orders
    quantity: int
    order_type: OrderType
    timestamp: int       # Discrete time step
    is_alive: bool = True

    # Tracking
    filled_quantity: int = 0
    cancel_timestamp: Optional[int] = None

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def is_filled(self) -> bool:
        return self.filled_quantity >= self.quantity

    @property
    def lifetime(self) -> Optional[int]:
        """Ticks the order was alive before cancel/fill."""
        if self.cancel_timestamp is not None:
            return self.cancel_timestamp - self.timestamp
        return None


@dataclass
class Trade:
    """A matched trade."""
    trade_id: str
    timestamp: int
    price: float
    quantity: int
    aggressor_id: str
    passive_id: str
    aggressor_side: Side


@dataclass
class PriceLevel:
    """Orders queued at a single price level (FIFO)."""
    price: float
    orders: list[Order] = field(default_factory=list)

    @property
    def total_quantity(self) -> int:
        return sum(o.remaining for o in self.orders if o.is_alive)

    @property
    def order_count(self) -> int:
        return sum(1 for o in self.orders if o.is_alive)

    def add(self, order: Order):
        self.orders.append(order)

    def remove(self, order_id: str) -> Optional[Order]:
        for o in self.orders:
            if o.order_id == order_id and o.is_alive:
                o.is_alive = False
                return o
        return None

    def clean(self):
        """Remove dead orders."""
        self.orders = [o for o in self.orders if o.is_alive and o.remaining > 0]


# ─── Limit Order Book ─────────────────────────────────────────────────────

class LimitOrderBook:
    """
    Price-time priority limit order book.

    Supports:
      - Limit orders (place at price)
      - Market orders (immediate fill)
      - Cancellations
      - Full order-level audit trail

    Calibrated parameters are set via __init__ but the book itself
    is a pure matching engine — no background order generation here.
    """

    def __init__(
        self,
        tick_size: float = 0.01,
        reference_price: float = 100.0,
    ):
        self.tick_size = tick_size
        self.reference_price = reference_price

        # Price → PriceLevel (sorted)
        self._bids: dict[float, PriceLevel] = {}  # price → level
        self._asks: dict[float, PriceLevel] = {}

        # Fast lookup
        self._orders: dict[str, Order] = {}

        # Audit trail
        self.trades: list[Trade] = []
        self.all_orders: list[Order] = []
        self._trade_counter = 0

        # Mid-price history
        self.mid_prices: list[float] = [reference_price]

    # ── Core Operations ───────────────────────────────────────────────

    def submit_order(self, order: Order) -> list[Trade]:
        """Submit an order. Returns any resulting trades."""
        self.all_orders.append(order)
        self._orders[order.order_id] = order

        if order.order_type == OrderType.CANCEL:
            return self._cancel_order(order)
        elif order.order_type == OrderType.MARKET:
            return self._match_market(order)
        else:  # LIMIT
            return self._process_limit(order)

    def _process_limit(self, order: Order) -> list[Trade]:
        """Process a limit order: match what crosses, rest goes on book."""
        trades = []

        if order.side == Side.BID:
            # Try to match against asks
            while order.remaining > 0 and self._asks:
                best_ask_price = min(self._asks.keys())
                if order.price >= best_ask_price:
                    new_trades = self._match_at_level(
                        order, self._asks[best_ask_price], Side.BID
                    )
                    trades.extend(new_trades)
                    # Clean empty level
                    if self._asks[best_ask_price].total_quantity == 0:
                        del self._asks[best_ask_price]
                else:
                    break
            # Place remainder on book
            if order.remaining > 0 and order.is_alive:
                self._add_to_book(order)
        else:  # ASK
            while order.remaining > 0 and self._bids:
                best_bid_price = max(self._bids.keys())
                if order.price <= best_bid_price:
                    new_trades = self._match_at_level(
                        order, self._bids[best_bid_price], Side.ASK
                    )
                    trades.extend(new_trades)
                    if self._bids[best_bid_price].total_quantity == 0:
                        del self._bids[best_bid_price]
                else:
                    break
            if order.remaining > 0 and order.is_alive:
                self._add_to_book(order)

        # Update mid-price
        self.mid_prices.append(self.mid_price)
        return trades

    def _match_market(self, order: Order) -> list[Trade]:
        """Match a market order immediately."""
        trades = []
        book = self._asks if order.side == Side.BID else self._bids
        price_fn = min if order.side == Side.BID else max

        while order.remaining > 0 and book:
            best_price = price_fn(book.keys())
            new_trades = self._match_at_level(
                order, book[best_price], order.side
            )
            trades.extend(new_trades)
            if book[best_price].total_quantity == 0:
                del book[best_price]

        self.mid_prices.append(self.mid_price)
        return trades

    def _match_at_level(
        self, aggressor: Order, level: PriceLevel, aggressor_side: Side
    ) -> list[Trade]:
        """Match aggressor against orders at a price level (FIFO)."""
        trades = []
        for passive in level.orders:
            if not passive.is_alive or passive.remaining == 0:
                continue
            if aggressor.remaining == 0:
                break

            fill_qty = min(aggressor.remaining, passive.remaining)
            aggressor.filled_quantity += fill_qty
            passive.filled_quantity += fill_qty

            if passive.is_filled:
                passive.is_alive = False

            self._trade_counter += 1
            trade = Trade(
                trade_id=f"T{self._trade_counter:06d}",
                timestamp=aggressor.timestamp,
                price=level.price,
                quantity=fill_qty,
                aggressor_id=aggressor.trader_id,
                passive_id=passive.trader_id,
                aggressor_side=aggressor_side,
            )
            trades.append(trade)
            self.trades.append(trade)

        level.clean()
        return trades

    def _cancel_order(self, cancel_order: Order) -> list[Trade]:
        """Cancel an existing order by ID (stored in cancel_order.order_id)."""
        # The cancel_order's trader_id is the target order_id to cancel
        target_id = cancel_order.trader_id  # Overloaded for cancel
        if target_id in self._orders:
            target = self._orders[target_id]
            target.is_alive = False
            target.cancel_timestamp = cancel_order.timestamp

            # Remove from book
            book = self._bids if target.side == Side.BID else self._asks
            if target.price in book:
                book[target.price].remove(target_id)
                if book[target.price].total_quantity == 0:
                    del book[target.price]

        return []

    def _add_to_book(self, order: Order):
        """Add order to the appropriate side of the book."""
        book = self._bids if order.side == Side.BID else self._asks
        if order.price not in book:
            book[order.price] = PriceLevel(price=order.price)
        book[order.price].add(order)

    # ── Cancellation by order_id (cleaner interface) ──────────────────

    def cancel_order_by_id(self, order_id: str, timestamp: int) -> bool:
        """Cancel an order by its ID. Returns True if successfully cancelled."""
        if order_id not in self._orders:
            return False
        target = self._orders[order_id]
        if not target.is_alive:
            return False

        target.is_alive = False
        target.cancel_timestamp = timestamp

        book = self._bids if target.side == Side.BID else self._asks
        if target.price in book:
            book[target.price].remove(order_id)
            if book[target.price].total_quantity == 0:
                del book[target.price]
        return True

    # ── Observability ─────────────────────────────────────────────────

    @property
    def best_bid(self) -> Optional[float]:
        return max(self._bids.keys()) if self._bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return min(self._asks.keys()) if self._asks else None

    @property
    def mid_price(self) -> float:
        bb, ba = self.best_bid, self.best_ask
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return self.mid_prices[-1] if self.mid_prices else self.reference_price

    @property
    def spread(self) -> float:
        bb, ba = self.best_bid, self.best_ask
        if bb is not None and ba is not None:
            return ba - bb
        return float("inf")

    @property
    def spread_ticks(self) -> float:
        return self.spread / self.tick_size if self.spread != float("inf") else float("inf")

    def depth(self, side: Side, n_levels: int = 5) -> list[tuple[float, int]]:
        """Return top N price levels as (price, total_qty)."""
        book = self._bids if side == Side.BID else self._asks
        prices = sorted(book.keys(), reverse=(side == Side.BID))
        result = []
        for p in prices[:n_levels]:
            result.append((p, book[p].total_quantity))
        return result

    def imbalance(self, n_levels: int = 3) -> float:
        """Order book imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol).
        Returns value in [-1, 1]. Positive = more buying pressure.
        """
        bid_vol = sum(qty for _, qty in self.depth(Side.BID, n_levels))
        ask_vol = sum(qty for _, qty in self.depth(Side.ASK, n_levels))
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    def snapshot(self, n_levels: int = 5) -> dict:
        """Full book snapshot for observation space."""
        return {
            "bids": self.depth(Side.BID, n_levels),
            "asks": self.depth(Side.ASK, n_levels),
            "mid_price": self.mid_price,
            "spread": self.spread,
            "spread_ticks": self.spread_ticks,
            "imbalance": self.imbalance(),
            "n_trades": len(self.trades),
        }

    # ── Trader-specific analytics (for surveillance) ──────────────────

    def trader_orders(self, trader_id: str) -> list[Order]:
        """All orders placed by a specific trader."""
        return [o for o in self.all_orders if o.trader_id == trader_id]

    def trader_cancel_rate(self, trader_id: str) -> float:
        """Fraction of a trader's orders that were cancelled."""
        orders = self.trader_orders(trader_id)
        if not orders:
            return 0.0
        cancelled = sum(
            1 for o in orders
            if o.cancel_timestamp is not None and o.order_type == OrderType.LIMIT
        )
        limit_orders = sum(1 for o in orders if o.order_type == OrderType.LIMIT)
        return cancelled / limit_orders if limit_orders > 0 else 0.0

    def trader_cancel_to_trade_ratio(self, trader_id: str) -> float:
        """Cancel-to-trade ratio — key FCA spoofing indicator."""
        orders = self.trader_orders(trader_id)
        cancels = sum(
            1 for o in orders
            if o.cancel_timestamp is not None and o.order_type == OrderType.LIMIT
        )
        trades = sum(1 for t in self.trades if t.aggressor_id == trader_id or t.passive_id == trader_id)
        return cancels / max(trades, 1)

    def trader_avg_order_lifetime(self, trader_id: str) -> float:
        """Average lifetime (in ticks) of cancelled orders."""
        lifetimes = [
            o.lifetime for o in self.trader_orders(trader_id)
            if o.lifetime is not None
        ]
        return sum(lifetimes) / len(lifetimes) if lifetimes else 0.0

    def reset(self):
        """Clear the book."""
        self._bids.clear()
        self._asks.clear()
        self._orders.clear()
        self.trades.clear()
        self.all_orders.clear()
        self._trade_counter = 0
        self.mid_prices = [self.reference_price]


# ─── Background Market Participant ─────────────────────────────────────

class BackgroundTrader:
    """
    Generates realistic background order flow using a Poisson process
    with mean-reverting prices.

    Calibrated to produce:
      - 2–8 tick spread
      - ~500 orders per 1000 steps
      - Realistic liquidity depth
      - Occasional large orders / cancellations
    """

    def __init__(
        self,
        trader_id: str = "BACKGROUND",
        arrival_rate: float = 0.5,
        cancel_rate: float = 0.15,
        mean_order_size: int = 100,
        spread_target_ticks: float = 4.0,
        mean_reversion_strength: float = 0.01,
        rng: Optional[np.random.Generator] = None,
    ):
        self.trader_id = trader_id
        self.arrival_rate = arrival_rate
        self.cancel_rate = cancel_rate
        self.mean_order_size = mean_order_size
        self.spread_target_ticks = spread_target_ticks
        self.mean_reversion = mean_reversion_strength
        self.rng = rng or np.random.default_rng(42)

        self._live_orders: list[str] = []
        self._order_counter = 0

    def generate_orders(
        self, book: LimitOrderBook, timestamp: int
    ) -> list[Order]:
        """Generate background orders for this timestep."""
        orders = []

        # Poisson arrival
        n_new = self.rng.poisson(self.arrival_rate)
        for _ in range(n_new):
            order = self._new_order(book, timestamp)
            orders.append(order)
            if order.order_type == OrderType.LIMIT:
                self._live_orders.append(order.order_id)

        # Random cancellations of existing orders
        if self._live_orders:
            n_cancel = self.rng.binomial(len(self._live_orders), self.cancel_rate)
            cancel_ids = self.rng.choice(
                self._live_orders,
                size=min(n_cancel, len(self._live_orders)),
                replace=False,
            ).tolist()
            for oid in cancel_ids:
                self._live_orders.remove(oid)
                # We'll handle cancel via book.cancel_order_by_id in the env

            # Return cancel IDs separately — env will process
            self._pending_cancels = cancel_ids
        else:
            self._pending_cancels = []

        return orders

    def _new_order(self, book: LimitOrderBook, timestamp: int) -> Order:
        """Generate a single background order."""
        self._order_counter += 1
        oid = f"BG_{self._order_counter:06d}"

        mid = book.mid_price

        # Side: slight mean-reversion bias
        if mid > book.reference_price * 1.02:
            p_bid = 0.4  # More selling when above ref
        elif mid < book.reference_price * 0.98:
            p_bid = 0.6  # More buying when below ref
        else:
            p_bid = 0.5
        side = Side.BID if self.rng.random() < p_bid else Side.ASK

        # Price: near the spread, with some depth
        spread = book.spread
        if spread == float("inf") or spread <= 0:
            spread = book.tick_size * self.spread_target_ticks
        half_spread = max(spread / 2, book.tick_size * 2)
        offset = self.rng.exponential(half_spread)

        if side == Side.BID:
            price = mid - offset
        else:
            price = mid + offset

        # Snap to tick
        price = round(price / book.tick_size) * book.tick_size
        price = max(price, book.tick_size)  # No zero/negative prices

        # Size: log-normal
        size = max(1, int(self.rng.lognormal(
            np.log(self.mean_order_size), 0.8
        )))

        # Occasionally generate a market order (5%)
        if self.rng.random() < 0.05:
            order_type = OrderType.MARKET
        else:
            order_type = OrderType.LIMIT

        return Order(
            order_id=oid,
            trader_id=self.trader_id,
            side=side,
            price=price,
            quantity=size,
            order_type=order_type,
            timestamp=timestamp,
        )
