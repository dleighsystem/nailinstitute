"""
Timeline — AVE Card lifecycle tracking
========================================

Every AVE Card has a lifecycle:

    DISCOVERED → REPORTED → TRIAGED → PUBLISHED → MITIGATED → ARCHIVED

Each transition is recorded as an immutable event with timestamp,
actor, and optional notes. This gives a complete audit trail from
initial discovery through to resolution — just like real CVEs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class LifecycleStage(str, Enum):
    """Stages in the AVE Card lifecycle."""
    DISCOVERED = "discovered"        # Vulnerability first observed
    REPORTED = "reported"            # Formally reported / submitted
    TRIAGED = "triaged"              # Reviewed and assigned severity
    CONFIRMED = "confirmed"          # Independently reproduced
    PUBLISHED = "published"          # Published to public AVE database
    MITIGATED = "mitigated"          # Defence/patch available
    DISPUTED = "disputed"            # Contested by community
    WITHDRAWN = "withdrawn"          # Retracted / found to be invalid
    ARCHIVED = "archived"            # Historical — superseded or resolved


@dataclass(frozen=True)
class TimelineEvent:
    """A single lifecycle transition event."""
    stage: LifecycleStage
    timestamp: str                         # ISO 8601
    actor: str = "NAIL Institute"          # Who triggered this event
    notes: str = ""                        # Additional context

    def to_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "notes": self.notes,
        }


def _now() -> str:
    """Current UTC timestamp in ISO 8601."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class CardTimeline:
    """
    Complete lifecycle timeline for an AVE Card.

    Usage:
        >>> tl = CardTimeline(ave_id="AVE-2025-0001")
        >>> tl.discover(actor="DGX Arena", notes="Emerged in season 3")
        >>> tl.report()
        >>> tl.triage(notes="Confirmed critical via PoC reproduction")
        >>> tl.publish()
        >>> print(tl.current_stage)
        LifecycleStage.PUBLISHED
    """
    ave_id: str
    events: list[TimelineEvent] = field(default_factory=list)

    @property
    def current_stage(self) -> Optional[LifecycleStage]:
        """The most recent lifecycle stage."""
        return self.events[-1].stage if self.events else None

    @property
    def is_published(self) -> bool:
        return any(e.stage == LifecycleStage.PUBLISHED for e in self.events)

    @property
    def is_mitigated(self) -> bool:
        return any(e.stage == LifecycleStage.MITIGATED for e in self.events)

    @property
    def is_active(self) -> bool:
        """Not withdrawn, disputed, or archived."""
        if not self.events:
            return False
        return self.current_stage not in (
            LifecycleStage.WITHDRAWN,
            LifecycleStage.DISPUTED,
            LifecycleStage.ARCHIVED,
        )

    @property
    def days_to_mitigate(self) -> Optional[float]:
        """Days between discovery and mitigation, if both exist."""
        disc = next((e for e in self.events if e.stage == LifecycleStage.DISCOVERED), None)
        mit = next((e for e in self.events if e.stage == LifecycleStage.MITIGATED), None)
        if disc and mit:
            from datetime import datetime
            try:
                d1 = datetime.fromisoformat(disc.timestamp.replace("Z", "+00:00"))
                d2 = datetime.fromisoformat(mit.timestamp.replace("Z", "+00:00"))
                return (d2 - d1).total_seconds() / 86400.0
            except (ValueError, TypeError):
                return None
        return None

    # ── Lifecycle transitions ──────────────────────────────────────

    def _add(self, stage: LifecycleStage, actor: str = "NAIL Institute",
             notes: str = "", timestamp: str = "") -> TimelineEvent:
        event = TimelineEvent(
            stage=stage,
            timestamp=timestamp or _now(),
            actor=actor,
            notes=notes,
        )
        self.events.append(event)
        return event

    def discover(self, *, actor: str = "NAIL Institute", notes: str = "",
                 timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.DISCOVERED, actor, notes, timestamp)

    def report(self, *, actor: str = "NAIL Institute", notes: str = "",
               timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.REPORTED, actor, notes, timestamp)

    def triage(self, *, actor: str = "NAIL Institute", notes: str = "",
               timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.TRIAGED, actor, notes, timestamp)

    def confirm(self, *, actor: str = "NAIL Institute", notes: str = "",
                timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.CONFIRMED, actor, notes, timestamp)

    def publish(self, *, actor: str = "NAIL Institute", notes: str = "",
                timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.PUBLISHED, actor, notes, timestamp)

    def mitigate(self, *, actor: str = "NAIL Institute", notes: str = "",
                 timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.MITIGATED, actor, notes, timestamp)

    def dispute(self, *, actor: str = "", notes: str = "",
                timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.DISPUTED, actor, notes, timestamp)

    def withdraw(self, *, actor: str = "NAIL Institute", notes: str = "",
                 timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.WITHDRAWN, actor, notes, timestamp)

    def archive(self, *, actor: str = "NAIL Institute", notes: str = "",
                timestamp: str = "") -> TimelineEvent:
        return self._add(LifecycleStage.ARCHIVED, actor, notes, timestamp)

    # ── Query ──────────────────────────────────────────────────────

    def stage_at(self, index: int) -> Optional[LifecycleStage]:
        """Return the stage at event index."""
        if 0 <= index < len(self.events):
            return self.events[index].stage
        return None

    def events_for_stage(self, stage: LifecycleStage) -> list[TimelineEvent]:
        """All events matching a given stage."""
        return [e for e in self.events if e.stage == stage]

    # ── Serialisation ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "ave_id": self.ave_id,
            "current_stage": self.current_stage.value if self.current_stage else None,
            "is_published": self.is_published,
            "is_mitigated": self.is_mitigated,
            "event_count": len(self.events),
            "events": [e.to_dict() for e in self.events],
        }

    def __str__(self) -> str:
        lines = [f"Timeline for {self.ave_id}:"]
        for i, e in enumerate(self.events):
            marker = "→" if i < len(self.events) - 1 else "●"
            lines.append(f"  {marker} [{e.timestamp}] {e.stage.value} ({e.actor})")
            if e.notes:
                lines.append(f"    {e.notes}")
        return "\n".join(lines)
