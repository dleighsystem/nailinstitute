"""Heartbeat — explicit agent registration + liveness."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .store import Store


@dataclass
class AgentStatus:
    agent_id: str
    first_seen: float
    last_seen: float
    age_s: float
    is_live: bool
    meta: dict


class Heartbeat:
    def __init__(self, store: Store, *,
                 live_window_s: float = 300.0) -> None:
        self.store = store
        self.live_window_s = live_window_s

    def beat(self, agent_id: str, *, meta: dict | None = None,
             ts: float | None = None) -> None:
        self.store.upsert_agent(agent_id, ts if ts is not None else time.time(),
                                meta=meta)

    def status(self, *, now: float | None = None) -> list[AgentStatus]:
        now = now if now is not None else time.time()
        out: list[AgentStatus] = []
        for a in self.store.list_agents():
            age = now - a["last_seen"]
            out.append(AgentStatus(
                agent_id=a["agent_id"],
                first_seen=a["first_seen"],
                last_seen=a["last_seen"],
                age_s=age,
                is_live=age <= self.live_window_s,
                meta=a["meta"],
            ))
        return out
