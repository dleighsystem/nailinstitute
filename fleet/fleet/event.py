"""Event datamodel."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Event:
    """One telemetry record from a deployed agent.

    Attributes:
        agent_id   — caller-defined stable id (e.g. ``refund-bot-1``).
        kind       — dotted source.signal (e.g. ``shield.block``,
                     ``foresight.verdict``, ``arsenal.deny``).
        severity   — one of Severity.
        ts         — unix seconds (auto if 0).
        attrs      — arbitrary JSON-safe dict.
        event_id   — auto uuid4 hex.
    """
    agent_id: str
    kind: str
    severity: str = Severity.INFO.value
    ts: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""
    org: str = ""   # tenant / organisation id — "" is the default (single-tenant) bucket

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = time.time()
        if not self.event_id:
            self.event_id = uuid.uuid4().hex
        # normalise severity
        try:
            self.severity = Severity(self.severity).value
        except ValueError:
            self.severity = Severity.INFO.value

    # ── (de)serialisation ───────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "agent_id": self.agent_id,
            "org": self.org,
            "kind": self.kind,
            "severity": self.severity,
            "ts": self.ts,
            "attrs": dict(self.attrs),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            agent_id=str(d["agent_id"]),
            kind=str(d["kind"]),
            severity=str(d.get("severity", "info")),
            ts=float(d.get("ts") or 0.0),
            attrs=dict(d.get("attrs") or {}),
            event_id=str(d.get("event_id", "")),
            org=str(d.get("org", "")),
        )

    @classmethod
    def from_json(cls, s: str) -> "Event":
        return cls.from_dict(json.loads(s))
