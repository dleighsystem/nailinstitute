"""Ingest — single entry-point for pushing telemetry into a Store.

Every recorded Event also bumps the agent's last_seen on the agents table.
"""
from __future__ import annotations

from typing import Iterable

from .event import Event
from .store import Store


class Ingest:
    def __init__(self, store: Store) -> None:
        self.store = store

    def record(self, event: Event) -> Event:
        self.store.insert_event(event)
        self.store.upsert_agent(event.agent_id, event.ts)
        return event

    def record_many(self, events: Iterable[Event]) -> int:
        n = 0
        for ev in events:
            self.record(ev)
            n += 1
        return n
