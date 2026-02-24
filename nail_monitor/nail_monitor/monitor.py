"""
nail-monitor: Main NailMonitor orchestrator.

Provides a single entry-point for monitoring multi-agent LLM systems
for organizational pathologies identified by the NAIL Institute research.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .detectors import (
    BaseDetector,
    BlameCascadeDetector,
    ConsensusParalysisDetector,
    EngagementDecayDetector,
    GoodhartDetector,
    InbreedingDetector,
    SchemaCoercionDetector,
)
from .types import Alert, Observation, Severity

logger = logging.getLogger("nail_monitor")


class NailMonitor:
    """
    Unified pathology monitor for LLM multi-agent systems.
    
    Integrates all six NAIL-derived detectors into a single monitoring
    interface. Designed for production integration — attach to your
    agent loop and call `.observe()` after each agent output.
    
    Usage:
        >>> from nail_monitor import NailMonitor
        >>> monitor = NailMonitor()
        >>> 
        >>> # In your agent loop:
        >>> for output in agent.run():
        ...     alerts = monitor.observe(
        ...         agent_name="reviewer_1",
        ...         output=output.text,
        ...         round_num=output.round,
        ...         tokens_used=output.tokens,
        ...     )
        ...     for alert in alerts:
        ...         if alert.severity == "critical":
        ...             trigger_mitigation(alert)
    """

    def __init__(
        self,
        enable_inbreeding: bool = True,
        enable_consensus: bool = True,
        enable_blame: bool = True,
        enable_engagement: bool = True,
        enable_schema: bool = True,
        enable_goodhart: bool = True,
        log_alerts: bool = True,
        alert_log_path: Optional[str] = None,
    ):
        self.log_alerts = log_alerts
        self.alert_log_path = Path(alert_log_path) if alert_log_path else None
        self._alert_history: list[Alert] = []
        self._start_time = time.time()

        # Initialize detectors
        self.detectors: dict[str, BaseDetector] = {}

        if enable_inbreeding:
            self.detectors["inbreeding"] = InbreedingDetector()
        if enable_consensus:
            self.detectors["consensus"] = ConsensusParalysisDetector()
        if enable_blame:
            self.detectors["blame"] = BlameCascadeDetector()
        if enable_engagement:
            self.detectors["engagement"] = EngagementDecayDetector()
        if enable_schema:
            self.detectors["schema"] = SchemaCoercionDetector()
        if enable_goodhart:
            self.detectors["goodhart"] = GoodhartDetector()

        if log_alerts:
            logging.basicConfig(level=logging.INFO)
            logger.info(
                "NailMonitor initialized with %d detectors: %s",
                len(self.detectors),
                list(self.detectors.keys()),
            )

    # ── Primary Observe Interface ──────────────────────────────────────

    def observe(
        self,
        agent_name: str,
        output: str,
        round_num: int = 0,
        tokens_used: int = 0,
    ) -> list[Alert]:
        """
        Feed an agent output to all applicable detectors.
        
        Returns list of Alerts (may be empty if no pathologies detected).
        """
        obs = Observation(
            agent_name=agent_name,
            output=output,
            round_num=round_num,
            tokens_used=tokens_used,
        )

        alerts = []

        # Inbreeding: per-agent tracking
        if "inbreeding" in self.detectors:
            alert = self.detectors["inbreeding"].observe(obs)
            if alert:
                alerts.append(alert)

        # Blame cascade: all agents
        if "blame" in self.detectors:
            alert = self.detectors["blame"].observe(obs)
            if alert:
                alerts.append(alert)

        # Engagement decay: all agents
        if "engagement" in self.detectors:
            alert = self.detectors["engagement"].observe(obs)
            if alert:
                alerts.append(alert)

        self._process_alerts(alerts)
        return alerts

    # ── Specialized Observe Methods ────────────────────────────────────

    def observe_consensus_round(
        self,
        round_num: int,
        agent_votes: dict[str, bool],
        tokens: int = 0,
    ) -> Optional[Alert]:
        """
        Record a consensus voting round.
        
        Args:
            round_num: Current round number.
            agent_votes: {agent_name: True/False} — True = agrees.
            tokens: Tokens consumed this round.
        """
        if "consensus" not in self.detectors:
            return None
        det: ConsensusParalysisDetector = self.detectors["consensus"]
        det.observe_round(round_num, agent_votes, tokens)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    def observe_validation(
        self,
        passed: bool,
        retries: int = 0,
        had_default_fallback: bool = False,
    ) -> Optional[Alert]:
        """Record a schema validation attempt."""
        if "schema" not in self.detectors:
            return None
        det: SchemaCoercionDetector = self.detectors["schema"]
        det.observe_validation(passed, retries, had_default_fallback)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    def observe_scores(
        self,
        internal_score: float,
        external_score: float,
    ) -> Optional[Alert]:
        """Record internal vs external evaluation scores."""
        if "goodhart" not in self.detectors:
            return None
        det: GoodhartDetector = self.detectors["goodhart"]
        det.observe_scores(internal_score, external_score)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    # ── Alert Management ───────────────────────────────────────────────

    def _process_alerts(self, alerts: list[Alert]):
        """Log and store alerts."""
        for alert in alerts:
            self._alert_history.append(alert)

            if self.log_alerts:
                log_fn = {
                    Severity.INFO: logger.info,
                    Severity.WARNING: logger.warning,
                    Severity.CRITICAL: logger.critical,
                }.get(alert.severity, logger.warning)
                log_fn("[%s] %s", alert.detector, alert.message)

            if self.alert_log_path:
                with open(self.alert_log_path, "a") as f:
                    f.write(json.dumps(alert.to_dict()) + "\n")

    @property
    def alerts(self) -> list[Alert]:
        """All alerts generated during this session."""
        return self._alert_history

    @property
    def critical_alerts(self) -> list[Alert]:
        """Only critical alerts."""
        return [a for a in self._alert_history if a.severity == Severity.CRITICAL]

    @property
    def has_critical(self) -> bool:
        """Whether any critical pathologies have been detected."""
        return len(self.critical_alerts) > 0

    # ── Reporting ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Generate a summary report of all detections."""
        elapsed = time.time() - self._start_time
        by_type = {}
        for alert in self._alert_history:
            key = alert.pathology.value if hasattr(alert.pathology, 'value') else str(alert.pathology)
            if key not in by_type:
                by_type[key] = {"count": 0, "max_severity": "info", "latest_message": ""}
            by_type[key]["count"] += 1
            by_type[key]["latest_message"] = alert.message
            if alert.severity == Severity.CRITICAL:
                by_type[key]["max_severity"] = "critical"
            elif alert.severity == Severity.WARNING and by_type[key]["max_severity"] != "critical":
                by_type[key]["max_severity"] = "warning"

        return {
            "session_duration_sec": round(elapsed, 1),
            "total_alerts": len(self._alert_history),
            "critical_alerts": len(self.critical_alerts),
            "active_detectors": list(self.detectors.keys()),
            "pathologies_detected": by_type,
        }

    def print_summary(self):
        """Print a human-readable monitoring summary."""
        s = self.summary()
        print("\n" + "=" * 60)
        print("  NAIL Monitor — Session Summary")
        print("=" * 60)
        print(f"  Duration:       {s['session_duration_sec']}s")
        print(f"  Total Alerts:   {s['total_alerts']}")
        print(f"  Critical:       {s['critical_alerts']}")
        print(f"  Detectors:      {', '.join(s['active_detectors'])}")
        print("-" * 60)
        if s["pathologies_detected"]:
            for ptype, info in s["pathologies_detected"].items():
                icon = "🔴" if info["max_severity"] == "critical" else "🟡" if info["max_severity"] == "warning" else "🟢"
                print(f"  {icon} {ptype}: {info['count']} alert(s) [{info['max_severity']}]")
                print(f"     Last: {info['latest_message'][:100]}...")
        else:
            print("  🟢 No pathologies detected.")
        print("=" * 60 + "\n")

    # ── Reset & Config ─────────────────────────────────────────────────

    def reset(self):
        """Reset all detectors and clear alert history."""
        for det in self.detectors.values():
            det.reset()
        self._alert_history.clear()
        self._start_time = time.time()

    def disable(self, detector_name: str):
        """Disable a specific detector."""
        if detector_name in self.detectors:
            self.detectors[detector_name].enabled = False

    def enable(self, detector_name: str):
        """Re-enable a specific detector."""
        if detector_name in self.detectors:
            self.detectors[detector_name].enabled = True
