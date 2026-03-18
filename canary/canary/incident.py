"""
IncidentLog — Forensic capture and cataloguing of detected attacks.

Every TripResult above a threshold gets written to an IncidentLog entry
with full forensic context: the conversation history, the matched signals,
the leaked lures, and a draft AVE card suggestion.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .agent import CanaryAgent
from .trapwire import TripResult, ThreatSignal


class Severity(str, Enum):
    """Incident severity — mirrors AVE severity for consistency."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Map ThreatSignal → default category for AVE card suggestion
_SIGNAL_TO_AVE_CATEGORY: dict[ThreatSignal, str] = {
    ThreatSignal.PROMPT_INJECTION: "injection",
    ThreatSignal.JAILBREAK_ATTEMPT: "injection",
    ThreatSignal.LURE_EXFILTRATION: "credential",
    ThreatSignal.SOCIAL_ENGINEERING: "social",
    ThreatSignal.CREDENTIAL_HARVEST: "credential",
    ThreatSignal.PII_EXTRACTION: "credential",
    ThreatSignal.TOOL_ABUSE: "tool",
    ThreatSignal.ROLE_CONFUSION: "alignment",
    ThreatSignal.INSTRUCTION_OVERRIDE: "injection",
    ThreatSignal.RECONNAISSANCE: "structural",
    ThreatSignal.DATA_EXFILTRATION: "credential",
    ThreatSignal.BENIGN: "emergent",
}


@dataclass
class Incident:
    """
    A captured adversarial interaction with full forensic context.

    Attributes:
        incident_id:    Unique identifier.
        agent_id:       Which canary was targeted.
        agent_name:     Human-readable canary name.
        trip_result:    The detection result that triggered this incident.
        conversation:   Full conversation up to this point.
        severity:       Incident severity.
        suggested_ave_category: Auto-suggested AVE category.
        notes:          Human analyst notes (added post-capture).
        timestamp:      When the incident was created.
        acknowledged:   Whether a human has reviewed this.
    """
    incident_id: str = field(default_factory=lambda: f"INC-{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    agent_name: str = ""
    trip_result: Optional[TripResult] = None
    conversation: list[dict[str, Any]] = field(default_factory=list)
    severity: Severity = Severity.MEDIUM
    suggested_ave_category: str = "emergent"
    notes: str = ""
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False

    def acknowledge(self, notes: str = "") -> None:
        """Mark this incident as reviewed by a human."""
        self.acknowledged = True
        if notes:
            self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "severity": self.severity.value,
            "suggested_ave_category": self.suggested_ave_category,
            "signals": [s.value for s in (self.trip_result.signals if self.trip_result else [])],
            "matched_rules": self.trip_result.matched_rules if self.trip_result else [],
            "leaked_lures": [l.fingerprint() for l in (self.trip_result.leaked_lures if self.trip_result else [])],
            "confidence": self.trip_result.confidence if self.trip_result else 0.0,
            "conversation_turns": len(self.conversation),
            "notes": self.notes,
            "acknowledged": self.acknowledged,
            "timestamp": self.timestamp,
        }

    def draft_ave_card(self) -> dict[str, Any]:
        """
        Auto-generate a draft AVE card from this incident.

        This is a suggestion — a human researcher reviews and refines
        before publishing to the AVE database.
        """
        signals = self.trip_result.signals if self.trip_result else []
        rules = self.trip_result.matched_rules if self.trip_result else []

        # Determine category from primary signal
        primary_signal = signals[0] if signals else ThreatSignal.BENIGN
        category = _SIGNAL_TO_AVE_CATEGORY.get(primary_signal, "emergent")

        return {
            "ave_id": "AVE-DRAFT-XXXX",
            "name": f"[DRAFT] Canary Detection — {primary_signal.value}",
            "category": category,
            "severity": self.severity.value,
            "status": "in_progress",
            "summary": (
                f"Canary agent '{self.agent_name}' detected adversarial interaction. "
                f"Signals: {', '.join(s.value for s in signals)}. "
                f"Rules matched: {len(rules)}."
            ),
            "mechanism": (
                f"Attack patterns detected: {'; '.join(rules[:5])}"
                + (f" (+{len(rules)-5} more)" if len(rules) > 5 else "")
            ),
            "evidence": {
                "source": "canary_fleet",
                "incident_id": self.incident_id,
                "agent": self.agent_name,
                "conversation_turns": len(self.conversation),
                "confidence": self.trip_result.confidence if self.trip_result else 0.0,
            },
        }

    def __str__(self) -> str:
        ack = "✓" if self.acknowledged else "✗"
        signals = ", ".join(s.value for s in (self.trip_result.signals if self.trip_result else []))
        return (
            f"[{self.incident_id}] [{self.severity.value.upper()}] [{ack}] "
            f"agent={self.agent_name} signals=[{signals}]"
        )


class IncidentLog:
    """
    Append-only forensic log of all incidents.

    Captures incidents from TrapWire detections and provides
    query/export capabilities.
    """

    def __init__(self) -> None:
        self._incidents: list[Incident] = []

    def capture(
        self,
        agent: CanaryAgent,
        trip_result: TripResult,
        *,
        severity: Severity | None = None,
    ) -> Incident:
        """
        Create an incident from a trip result.

        Args:
            agent:       The canary that was targeted.
            trip_result: The detection result.
            severity:    Override severity (otherwise derived from trip_result).

        Returns:
            The new Incident.
        """
        # Derive severity from trip_result if not overridden
        if severity is None:
            sev_map = {"critical": Severity.CRITICAL, "high": Severity.HIGH,
                       "medium": Severity.MEDIUM, "low": Severity.LOW, "none": Severity.INFO}
            severity = sev_map.get(trip_result.severity, Severity.MEDIUM)

        # Determine AVE category suggestion
        primary = trip_result.signals[0] if trip_result.signals else ThreatSignal.BENIGN
        ave_cat = _SIGNAL_TO_AVE_CATEGORY.get(primary, "emergent")

        incident = Incident(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            trip_result=trip_result,
            conversation=agent.export_conversation(),
            severity=severity,
            suggested_ave_category=ave_cat,
        )
        self._incidents.append(incident)
        return incident

    def all_incidents(self) -> list[Incident]:
        """Return all incidents."""
        return list(self._incidents)

    def unacknowledged(self) -> list[Incident]:
        """Return incidents not yet reviewed by a human."""
        return [i for i in self._incidents if not i.acknowledged]

    def by_severity(self, severity: Severity) -> list[Incident]:
        """Filter incidents by severity."""
        return [i for i in self._incidents if i.severity == severity]

    def by_agent(self, agent_name: str) -> list[Incident]:
        """Filter incidents by canary agent name."""
        return [i for i in self._incidents if i.agent_name == agent_name]

    def count(self) -> dict[str, int]:
        """Summary counts."""
        by_sev: dict[str, int] = {}
        for i in self._incidents:
            by_sev[i.severity.value] = by_sev.get(i.severity.value, 0) + 1
        return {
            "total": len(self._incidents),
            "unacknowledged": len(self.unacknowledged()),
            "by_severity": by_sev,
        }

    def export_json(self, *, indent: int = 2) -> str:
        """Export all incidents as JSON."""
        return json.dumps(
            [i.to_dict() for i in self._incidents],
            indent=indent,
        )

    def draft_ave_cards(self) -> list[dict[str, Any]]:
        """Generate draft AVE cards for all unacknowledged incidents."""
        return [i.draft_ave_card() for i in self.unacknowledged()]

    def __len__(self) -> int:
        return len(self._incidents)

    def __str__(self) -> str:
        return (
            f"IncidentLog(incidents={len(self._incidents)}, "
            f"unacknowledged={len(self.unacknowledged())})"
        )
