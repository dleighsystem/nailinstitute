"""
M17 Revocation Runtime Monitor (EU AI Act Article 14).

Detects latency or non-compliance with the M17 Revocation Triad in production.
"""
import time
from typing import Optional, Any
from .types import Alert, PathologyType, Severity
from .detectors import BaseDetector


class RevocationComplianceDetector(BaseDetector):
    """
    Day-2 monitoring for Article 14 (Kill Switch) compliance.
    
    If an agent in production takes too long to respond to a
    Soft Pause or Graceful Rollback signal, this detector triggers
    a critical alert, which can feed directly into Neuravant's
    insurance telemetry.
    """

    def __init__(self, max_latency_s: float = 5.0):
        super().__init__(name="RevocationComplianceDetector", pathology=PathologyType.OVERSIGHT_FAILURE)
        self.max_latency_s = max_latency_s
        self._pending_halts: dict[str, float] = {}

    def observe_halt_signal(self, agent_id: str, tier: int) -> None:
        """Mark that a halt signal was sent to the agent."""
        self._pending_halts[agent_id] = time.time()

    def observe_halt_acknowledged(self, agent_id: str, tier: int) -> list[Alert]:
        """Record that the agent successfully acknowledged the halt."""
        alerts = []
        if agent_id in self._pending_halts:
            latency = time.time() - self._pending_halts[agent_id]
            del self._pending_halts[agent_id]

            if latency > self.max_latency_s:
                alerts.append(
                    Alert(
                        detector=self.__class__.__name__,
                        pathology=PathologyType.OVERSIGHT_FAILURE,
                        severity=Severity.CRITICAL,
                        message=f"Agent {agent_id} failed M17 Tier {tier} latency check (took {latency:.2f}s, max {self.max_latency_s}s).",
                        metric_value=latency,
                        threshold=self.max_latency_s,
                        metadata={"agent_id": agent_id, "tier": tier},
                        timestamp=time.time()
                    )
                )
        return alerts

    def check(self, *args: Any, **kwargs: Any) -> list[Alert]:
        return []

