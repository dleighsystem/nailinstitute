"""RollUp — read-side aggregations over the event store."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .store import Store


@dataclass
class AgentSummary:
    agent_id: str
    n_events: int
    by_kind: dict[str, int]
    by_severity: dict[str, int]
    last_event_ts: float


class RollUp:
    def __init__(self, store: Store) -> None:
        self.store = store

    # ── basic group-bys ─────────────────────────────────────────
    def by_agent(self, **filters: Any) -> dict[str, int]:
        c: Counter[str] = Counter()
        for ev in self.store.query_events(**filters):
            c[ev.agent_id] += 1
        return dict(c)

    def by_kind(self, **filters: Any) -> dict[str, int]:
        c: Counter[str] = Counter()
        for ev in self.store.query_events(**filters):
            c[ev.kind] += 1
        return dict(c)

    def by_severity(self, **filters: Any) -> dict[str, int]:
        c: Counter[str] = Counter()
        for ev in self.store.query_events(**filters):
            c[ev.severity] += 1
        return dict(c)

    def by_org(self, **filters: Any) -> dict[str, int]:
        """Event counts grouped by organisation (multi-tenant fleet view)."""
        c: Counter[str] = Counter()
        for ev in self.store.query_events(**filters):
            c[ev.org] += 1
        return dict(c)

    # ── derived ────────────────────────────────────────────────
    def top_tools(self, *, kind: str = "arsenal.deny",
                  attr_key: str = "tool",
                  n: int = 10, **filters: Any) -> list[tuple[str, int]]:
        c: Counter[str] = Counter()
        for ev in self.store.query_events(kind=kind, **filters):
            v = ev.attrs.get(attr_key)
            if isinstance(v, str):
                c[v] += 1
        return c.most_common(n)

    def verdict_distribution(self, *, kind: str,
                             attr_key: str = "verdict",
                             **filters: Any) -> dict[str, int]:
        c: Counter[str] = Counter()
        for ev in self.store.query_events(kind=kind, **filters):
            v = ev.attrs.get(attr_key)
            if isinstance(v, str):
                c[v.lower()] += 1
        return dict(c)

    def time_window(self, *, since: float, until: float,
                    bucket_s: float = 60.0,
                    **filters: Any) -> dict[int, int]:
        if bucket_s <= 0:
            raise ValueError("bucket_s must be > 0")
        c: Counter[int] = Counter()
        for ev in self.store.query_events(since=since, until=until, **filters):
            bucket = int((ev.ts - since) // bucket_s)
            c[bucket] += 1
        return dict(c)

    def agent_summary(self, agent_id: str) -> AgentSummary:
        events = self.store.query_events(agent_id=agent_id, order="desc")
        bk: Counter[str] = Counter()
        bs: Counter[str] = Counter()
        for ev in events:
            bk[ev.kind] += 1
            bs[ev.severity] += 1
        last = events[0].ts if events else 0.0
        return AgentSummary(
            agent_id=agent_id,
            n_events=len(events),
            by_kind=dict(bk),
            by_severity=dict(bs),
            last_event_ts=last,
        )

    # ── overview blob ──────────────────────────────────────────
    def overview(self) -> dict:
        return {
            "n_events": self.store.event_count(),
            "n_agents": len(self.store.list_agents()),
            "by_severity": self.by_severity(),
            "by_kind": self.by_kind(),
        }
