"""Run the nail_monitor detector pack over stored fleet telemetry, per org/agent.

Fleet events carry detector-ready payloads in ``attrs`` (e.g. ``loaded_tools``,
``tool_manifest``, ``memory_writes``, ``task_goal``). This module bridges the
telemetry store to the nail_monitor control-plane detectors so the fleet layer
*detects* pathologies at scale instead of only aggregating counts.

For each agent (within an org scope) it replays that agent's events in time
order through a fresh detector pack — so stateful detectors (baselines, drift)
see a coherent per-agent stream — and returns the alerts, scoped by org.

nail_monitor is an **optional** dependency; :meth:`FleetPathologyScanner.scan`
raises a clear error if it is not installed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .store import Store


@dataclass
class PathologyFinding:
    """One detector alert raised against a stored fleet event."""

    org: str
    agent_id: str
    event_id: str
    ts: float
    detector: str
    pathology: str
    severity: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "org": self.org,
            "agent_id": self.agent_id,
            "event_id": self.event_id,
            "ts": self.ts,
            "detector": self.detector,
            "pathology": self.pathology,
            "severity": self.severity,
            "message": self.message,
            "metadata": self.metadata,
        }


class FleetPathologyScanner:
    """Replay stored telemetry through the nail_monitor detector pack, per org/agent.

    Parameters
    ----------
    store:
        The fleet telemetry :class:`~fleet.store.Store`.
    detector_factory:
        Optional ``() -> list`` returning a fresh detector pack per agent. Defaults
        to the v9 control-plane detectors (tool-manifest, tool-retrieval,
        memory-write, goal-drift). A factory is used (not a shared list) because
        detectors are stateful and must not bleed state across agents.
    """

    def __init__(
        self,
        store: Store,
        *,
        detector_factory: Optional[Callable[[], list]] = None,
    ) -> None:
        self.store = store
        self._detector_factory = detector_factory

    @staticmethod
    def _default_pack() -> list:
        from nail_monitor.detectors_v9 import (  # lazy: optional dependency
            GoalDriftMonitorDetector,
            MemoryWriteFirewallDetector,
            ToolManifestIntegrityDetector,
            ToolRetrievalIntegrityDetector,
        )
        return [
            ToolManifestIntegrityDetector(),
            ToolRetrievalIntegrityDetector(),
            MemoryWriteFirewallDetector(),
            GoalDriftMonitorDetector(),
        ]

    def scan(
        self,
        *,
        org: str | None = None,
        agent_id: str | None = None,
    ) -> list[PathologyFinding]:
        """Return detector findings over the (optionally org/agent-scoped) telemetry."""
        try:
            from nail_monitor.types import Observation
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                "FleetPathologyScanner requires nail-monitor. Install it, or pass a "
                "detector_factory backed by your own detectors."
            ) from exc

        factory = self._detector_factory or self._default_pack

        by_agent: dict[tuple[str, str], list] = defaultdict(list)
        for ev in self.store.query_events(org=org, agent_id=agent_id, order="asc"):
            by_agent[(ev.org, ev.agent_id)].append(ev)

        findings: list[PathologyFinding] = []
        for (ev_org, ev_agent), events in by_agent.items():
            detectors = factory()
            for ev in events:
                obs = Observation(
                    agent_name=ev_agent,
                    output=str(ev.attrs.get("output", "")),
                    metadata=dict(ev.attrs),
                )
                for detector in detectors:
                    if not getattr(detector, "enabled", True):
                        continue
                    alert = detector.observe(obs)
                    if alert is not None:
                        findings.append(PathologyFinding(
                            org=ev_org,
                            agent_id=ev_agent,
                            event_id=ev.event_id,
                            ts=ev.ts,
                            detector=alert.detector,
                            pathology=alert.pathology.value,
                            severity=alert.severity.value,
                            message=alert.message,
                            metadata=dict(alert.metadata),
                        ))
        findings.sort(key=lambda f: (f.org, f.ts, f.agent_id))
        return findings

    def summary(self, *, org: str | None = None) -> dict[str, dict[str, int]]:
        """Per-organisation pathology counts: ``{org: {pathology: count}}``."""
        out: dict[str, Counter] = defaultdict(Counter)
        for finding in self.scan(org=org):
            out[finding.org][finding.pathology] += 1
        return {o: dict(counter) for o, counter in out.items()}
