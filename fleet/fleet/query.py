"""Query — read-side analytics primitives over the event store.

R3 layers richer aggregations on top of `RollUp`:

* rate(kind, window_s)               — events / second over trailing window
* latency_percentiles(kind, attr)    — p50 / p95 / p99 numeric attribute
* numeric_stats(kind, attr)          — count / sum / mean / min / max
* top_n(kind, attr, n)               — generic top-N attribute frequency
* histogram(kind, attr, buckets)     — fixed-edge numeric histogram
* group_by(kind, attr)               — dict[value] → count
* time_series(kind, since, until)    — event count per fixed bucket
* deny_allow_ratio(window_s)         — arsenal.deny / (deny + allow)

All read-only; safe to call against a live Store.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass, asdict
from typing import Any, Iterable

from .store import Store


@dataclass
class NumericStats:
    n: int
    sum: float
    mean: float
    min: float
    max: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Percentiles:
    n: int
    p50: float
    p95: float
    p99: float
    min: float
    max: float

    def to_dict(self) -> dict:
        return asdict(self)


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolated percentile (NIST type 7, same as numpy default)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return float(d0 + d1)


class Query:
    """Read-only analytics façade over a `Store`."""

    def __init__(self, store: Store) -> None:
        self.store = store

    # ── helpers ────────────────────────────────────────────────
    def _numeric_attr(self, kind: str, attr_key: str,
                      **filters: Any) -> list[float]:
        out: list[float] = []
        for ev in self.store.query_events(kind=kind, **filters):
            v = ev.attrs.get(attr_key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(float(v))
        return out

    # ── rate ───────────────────────────────────────────────────
    def rate(self, *, kind: str | None = None,
             window_s: float = 60.0,
             now: float | None = None,
             severity: str | None = None,
             agent_id: str | None = None) -> float:
        """Events per second over the trailing `window_s` window."""
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        ref = time.time() if now is None else now
        since = ref - window_s
        evs = self.store.query_events(
            kind=kind, severity=severity, agent_id=agent_id,
            since=since, until=ref,
        )
        return len(evs) / window_s

    def count(self, *, kind: str | None = None,
              window_s: float | None = None,
              now: float | None = None,
              severity: str | None = None,
              agent_id: str | None = None) -> int:
        ref = time.time() if now is None else now
        since = (ref - window_s) if window_s else None
        until = ref if window_s else None
        return len(self.store.query_events(
            kind=kind, severity=severity, agent_id=agent_id,
            since=since, until=until,
        ))

    # ── numeric distributions ──────────────────────────────────
    def numeric_stats(self, *, kind: str, attr_key: str,
                      **filters: Any) -> NumericStats:
        vals = self._numeric_attr(kind, attr_key, **filters)
        if not vals:
            return NumericStats(n=0, sum=0.0, mean=0.0, min=0.0, max=0.0)
        s = sum(vals)
        return NumericStats(
            n=len(vals), sum=s, mean=s / len(vals),
            min=min(vals), max=max(vals),
        )

    def latency_percentiles(self, *, kind: str,
                            attr_key: str = "duration_ms",
                            **filters: Any) -> Percentiles:
        vals = sorted(self._numeric_attr(kind, attr_key, **filters))
        if not vals:
            return Percentiles(n=0, p50=0.0, p95=0.0, p99=0.0,
                               min=0.0, max=0.0)
        return Percentiles(
            n=len(vals),
            p50=_percentile(vals, 50),
            p95=_percentile(vals, 95),
            p99=_percentile(vals, 99),
            min=vals[0], max=vals[-1],
        )

    def histogram(self, *, kind: str, attr_key: str,
                  buckets: list[float],
                  **filters: Any) -> dict[str, int]:
        """Fixed-edge histogram. ``buckets`` are upper bounds, ascending.

        Result keys: ``"<=b0"``, ``"<=b1"``, ..., ``">bN"``.
        """
        if not buckets:
            raise ValueError("buckets must be non-empty")
        edges = sorted(buckets)
        out: Counter[str] = Counter()
        for v in self._numeric_attr(kind, attr_key, **filters):
            placed = False
            for e in edges:
                if v <= e:
                    out[f"<={e}"] += 1
                    placed = True
                    break
            if not placed:
                out[f">{edges[-1]}"] += 1
        # ensure all keys present
        result: dict[str, int] = {f"<={e}": out.get(f"<={e}", 0) for e in edges}
        result[f">{edges[-1]}"] = out.get(f">{edges[-1]}", 0)
        return result

    # ── group-by primitives ────────────────────────────────────
    def top_n(self, *, kind: str, attr_key: str, n: int = 10,
              **filters: Any) -> list[tuple[str, int]]:
        c: Counter[str] = Counter()
        for ev in self.store.query_events(kind=kind, **filters):
            v = ev.attrs.get(attr_key)
            if v is None:
                continue
            c[str(v)] += 1
        return c.most_common(n)

    def group_by(self, *, kind: str, attr_key: str,
                 **filters: Any) -> dict[str, int]:
        c: Counter[str] = Counter()
        for ev in self.store.query_events(kind=kind, **filters):
            v = ev.attrs.get(attr_key)
            if v is None:
                continue
            c[str(v)] += 1
        return dict(c)

    # ── time series ────────────────────────────────────────────
    def time_series(self, *, since: float, until: float,
                    bucket_s: float = 60.0,
                    kind: str | None = None,
                    severity: str | None = None,
                    agent_id: str | None = None) -> list[tuple[float, int]]:
        """Returns ``[(bucket_start_ts, count), ...]`` covering [since, until]."""
        if bucket_s <= 0:
            raise ValueError("bucket_s must be > 0")
        if until < since:
            raise ValueError("until < since")
        n_buckets = max(1, int(math.ceil((until - since) / bucket_s)))
        counts = [0] * n_buckets
        for ev in self.store.query_events(
            kind=kind, severity=severity, agent_id=agent_id,
            since=since, until=until,
        ):
            idx = int((ev.ts - since) // bucket_s)
            if 0 <= idx < n_buckets:
                counts[idx] += 1
        return [(since + i * bucket_s, counts[i]) for i in range(n_buckets)]

    # ── derived ratios ─────────────────────────────────────────
    def ratio(self, *, num_kind: str, denom_kinds: Iterable[str],
              window_s: float | None = None,
              now: float | None = None) -> float:
        """Returns ``count(num_kind) / sum(count(k) for k in denom_kinds)``.

        Useful for e.g. arsenal.deny / (deny + allow) refusal rate.
        Returns 0.0 when denominator is 0.
        """
        ref = time.time() if now is None else now
        since = (ref - window_s) if window_s else None
        until = ref if window_s else None
        num = len(self.store.query_events(kind=num_kind, since=since, until=until))
        den = 0
        for k in denom_kinds:
            den += len(self.store.query_events(kind=k, since=since, until=until))
        return (num / den) if den > 0 else 0.0

    def deny_allow_ratio(self, *, window_s: float | None = None,
                         now: float | None = None) -> float:
        """Arsenal refusal rate: deny / (deny + allow)."""
        return self.ratio(
            num_kind="arsenal.deny",
            denom_kinds=("arsenal.deny", "arsenal.allow"),
            window_s=window_s, now=now,
        )
