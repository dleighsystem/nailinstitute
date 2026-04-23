"""Retention policy — TTL + max-rows pruning for the events table."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .store import Store


@dataclass
class PruneReport:
    deleted_by_ttl: int = 0
    deleted_by_cap: int = 0

    @property
    def total(self) -> int:
        return self.deleted_by_ttl + self.deleted_by_cap

    def to_dict(self) -> dict:
        return {
            "deleted_by_ttl": self.deleted_by_ttl,
            "deleted_by_cap": self.deleted_by_cap,
            "total": self.total,
        }


class Retention:
    """Apply retention rules to a Store.

    * ``ttl_s``      — delete events older than this. ``None`` disables.
    * ``max_rows``   — keep only the newest N events. ``None`` disables.
    * ``prune_agents`` — drop agents with no remaining events.
    """

    def __init__(self, store: Store, *,
                 ttl_s: float | None = None,
                 max_rows: int | None = None,
                 prune_agents: bool = True) -> None:
        self.store = store
        self.ttl_s = ttl_s
        self.max_rows = max_rows
        self.prune_agents = prune_agents

    def apply(self, *, now: float | None = None) -> PruneReport:
        now = now if now is not None else time.time()
        report = PruneReport()
        with self.store._connect() as conn:  # noqa: SLF001 — same package
            if self.ttl_s is not None and self.ttl_s > 0:
                cutoff = now - self.ttl_s
                cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
                report.deleted_by_ttl = cur.rowcount or 0

            if self.max_rows is not None and self.max_rows >= 0:
                total = int(conn.execute(
                    "SELECT COUNT(*) FROM events").fetchone()[0])
                excess = total - self.max_rows
                if excess > 0:
                    cur = conn.execute(
                        "DELETE FROM events WHERE event_id IN ("
                        "  SELECT event_id FROM events"
                        "  ORDER BY ts ASC LIMIT ?"
                        ")",
                        (excess,),
                    )
                    report.deleted_by_cap = cur.rowcount or 0

            if self.prune_agents:
                conn.execute(
                    "DELETE FROM agents WHERE agent_id NOT IN ("
                    "  SELECT DISTINCT agent_id FROM events"
                    ")"
                )
            conn.commit()
        return report
