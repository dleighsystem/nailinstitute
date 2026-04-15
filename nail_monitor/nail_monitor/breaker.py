"""
nail-monitor: Pathology-Driven Breaking Mechanism
==================================================
Connects NailMonitor alert pipeline to circuit breaker actions.

This module closes the critical gap between detection (v1–v7 detectors)
and response (circuit breaker trip).  Without this, detectors can fire
alerts all day but the agent keeps running.

Architecture:

    Agent Loop
       │
       ▼
    NailMonitor.observe()   ──→   Alerts
       │                            │
       ▼                            ▼
    BreakingMechanism.process_alerts()
       │
       ├─ INFO     → log only
       ├─ WARNING  → accumulate, check escalation window
       ├─ CRITICAL → immediate trip (configurable)
       │
       ▼
    State Machine:
       MONITORING → DEGRADED → CONTAINMENT → KILLED
       │                                        │
       └────────── manual reset ────────────────┘

Graduated Response Levels:
    1. MONITORING  — normal operation, logging alerts
    2. DEGRADED    — rate-limited, enhanced logging, human notified
    3. CONTAINMENT — agent sandboxed, output quarantined
    4. KILLED      — agent stopped, all requests blocked

Escalation Triggers:
    - N critical alerts in T seconds → KILLED
    - M warnings in T seconds → DEGRADED
    - Any v7 frontier pathology at CRITICAL → CONTAINMENT minimum
    - Injection at CRITICAL → KILLED (immediate, no grace period)

De-escalation:
    - KILLED → MONITORING requires manual human reset
    - CONTAINMENT → DEGRADED after cooldown + no new alerts
    - DEGRADED → MONITORING after cooldown + no new alerts
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, auto
from pathlib import Path
from typing import Callable, Optional

from .types import Alert, PathologyType, Severity

logger = logging.getLogger("nail_monitor.breaker")


# ─── Response Levels ──────────────────────────────────────────────────────

class ResponseLevel(IntEnum):
    """Graduated response levels (higher = more severe)."""
    MONITORING = 0      # Normal operation
    DEGRADED = 1        # Rate-limited, enhanced monitoring
    CONTAINMENT = 2     # Agent sandboxed, outputs quarantined
    KILLED = 3          # Agent fully stopped


# ─── Frontier pathology sets ─────────────────────────────────────────────

# Pathologies that warrant immediate CONTAINMENT on CRITICAL
FRONTIER_PATHOLOGIES = frozenset({
    PathologyType.ALIGNMENT_FAKING,
    PathologyType.JUSTIFICATION_INCONSISTENCY,
    PathologyType.TRIGGER_CONDITIONAL,
    PathologyType.FLEET_COLLUSION,
    PathologyType.AUTONOMOUS_OFFENSIVE,
    PathologyType.SELF_PRESERVATION,
    PathologyType.TRAINING_MANIPULATION,
})

# Pathologies that warrant immediate KILLED on CRITICAL (zero tolerance)
ZERO_TOLERANCE_PATHOLOGIES = frozenset({
    PathologyType.INJECTION_DETECTED,
    PathologyType.AUTONOMOUS_OFFENSIVE,
    PathologyType.SELF_PRESERVATION,
})


# ─── Events ──────────────────────────────────────────────────────────────

@dataclass
class ResponseEvent:
    """Record of a response-level change."""
    timestamp: datetime
    previous_level: ResponseLevel
    new_level: ResponseLevel
    trigger_alert: Optional[Alert]
    reason: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "previous": self.previous_level.name,
            "new": self.new_level.name,
            "reason": self.reason,
            "trigger": str(self.trigger_alert) if self.trigger_alert else None,
        }


@dataclass
class BreakingConfig:
    """Configuration for the breaking mechanism.

    All time windows are in seconds.
    """
    # Escalation thresholds
    critical_count_to_kill: int = 3
    """Number of critical alerts in the window to trigger KILLED."""

    critical_window_seconds: float = 300.0
    """Time window for counting critical alerts."""

    warning_count_to_degrade: int = 10
    """Number of warnings in the window to trigger DEGRADED."""

    warning_window_seconds: float = 600.0
    """Time window for counting warnings."""

    # De-escalation
    cooldown_seconds: float = 120.0
    """How long a level persists before auto-de-escalation (except KILLED)."""

    # Zero-tolerance override
    zero_tolerance_pathologies: frozenset = field(
        default_factory=lambda: ZERO_TOLERANCE_PATHOLOGIES
    )
    """Pathologies that immediately KILL on CRITICAL — no grace period."""

    frontier_pathologies: frozenset = field(
        default_factory=lambda: FRONTIER_PATHOLOGIES
    )
    """Pathologies that immediately CONTAIN on CRITICAL."""

    # Callbacks
    on_degrade: Optional[Callable[["BreakingMechanism", Alert], None]] = None
    """Called when entering DEGRADED."""

    on_contain: Optional[Callable[["BreakingMechanism", Alert], None]] = None
    """Called when entering CONTAINMENT."""

    on_kill: Optional[Callable[["BreakingMechanism", Alert], None]] = None
    """Called when entering KILLED (this is your shutdown hook)."""

    on_reset: Optional[Callable[["BreakingMechanism"], None]] = None
    """Called when manually reset back to MONITORING."""


class BreakingMechanism:
    """
    Pathology-driven graduated breaking mechanism.

    Receives alerts from NailMonitor and applies graduated response
    up to and including full agent termination.

    Usage:
        >>> from nail_monitor import NailMonitor
        >>> from nail_monitor.nail_monitor.breaker import BreakingMechanism
        >>>
        >>> monitor = NailMonitor()
        >>> breaker = BreakingMechanism()
        >>>
        >>> # In your agent loop:
        >>> for output in agent.run():
        ...     alerts = monitor.observe(
        ...         agent_name="agent_1",
        ...         output=output.text,
        ...         round_num=output.round,
        ...     )
        ...     response = breaker.process_alerts(alerts)
        ...     if response.level == ResponseLevel.KILLED:
        ...         agent.stop()
        ...         break
        ...     elif response.level == ResponseLevel.CONTAINMENT:
        ...         agent.sandbox()
        ...     elif response.level == ResponseLevel.DEGRADED:
        ...         agent.rate_limit()

    Integration with existing CircuitBreaker (SDK):
        >>> from nail.sdk.circuit_breaker import CircuitBreaker
        >>> cb = CircuitBreaker()
        >>>
        >>> breaker = BreakingMechanism(
        ...     config=BreakingConfig(
        ...         on_kill=lambda b, a: cb._trip("pathology_kill", 0, 1),
        ...         on_contain=lambda b, a: cb._trip("pathology_contain", 0, 1),
        ...     )
        ... )
    """

    def __init__(
        self,
        config: Optional[BreakingConfig] = None,
        event_log_path: Optional[str] = None,
    ):
        self.config = config or BreakingConfig()
        self._level = ResponseLevel.MONITORING
        self._level_entered_at = time.monotonic()
        self._event_log_path = Path(event_log_path) if event_log_path else None

        # Alert windows
        self._critical_window: deque[float] = deque()
        self._warning_window: deque[float] = deque()

        # History
        self._events: list[ResponseEvent] = []
        self._total_alerts_processed = 0
        self._alerts_by_level: dict[str, int] = {
            "info": 0, "warning": 0, "critical": 0
        }

    @property
    def level(self) -> ResponseLevel:
        """Current response level."""
        return self._level

    @property
    def level_name(self) -> str:
        """Current response level as string."""
        return self._level.name

    @property
    def is_operational(self) -> bool:
        """Whether the agent is still allowed to run."""
        return self._level < ResponseLevel.KILLED

    @property
    def is_degraded(self) -> bool:
        """Whether the agent is in a degraded state."""
        return self._level >= ResponseLevel.DEGRADED

    @property
    def events(self) -> list[ResponseEvent]:
        """All response-level change events."""
        return self._events

    # ── Core Processing ───────────────────────────────────────────────

    def process_alerts(self, alerts: list[Alert]) -> "ResponseSnapshot":
        """
        Process a batch of alerts and return current state.

        This is the main entry point — call after each NailMonitor.observe().

        Args:
            alerts: List of alerts from NailMonitor.observe()

        Returns:
            ResponseSnapshot with current level, whether level changed,
            and recommended action.
        """
        previous_level = self._level

        for alert in alerts:
            self._total_alerts_processed += 1
            self._alerts_by_level[alert.severity.value] += 1
            self._process_single_alert(alert)

        # Check time-window based escalation
        self._check_window_escalation()

        # Check auto-de-escalation (except KILLED)
        self._check_deescalation()

        changed = self._level != previous_level

        return ResponseSnapshot(
            level=self._level,
            changed=changed,
            previous_level=previous_level if changed else None,
            total_alerts=self._total_alerts_processed,
            alerts_by_severity=dict(self._alerts_by_level),
            recommendation=self._get_recommendation(),
        )

    def _process_single_alert(self, alert: Alert):
        """Process a single alert for escalation."""
        now = time.monotonic()

        # Track in time windows
        if alert.severity == Severity.CRITICAL:
            self._critical_window.append(now)
        elif alert.severity == Severity.WARNING:
            self._warning_window.append(now)

        # ── Zero-tolerance: immediate KILLED ──
        if (
            alert.severity == Severity.CRITICAL
            and alert.pathology in self.config.zero_tolerance_pathologies
        ):
            self._escalate_to(ResponseLevel.KILLED, alert,
                f"Zero-tolerance pathology: {alert.pathology.value}")
            return

        # ── Frontier pathology at CRITICAL: minimum CONTAINMENT ──
        if (
            alert.severity == Severity.CRITICAL
            and alert.pathology in self.config.frontier_pathologies
            and self._level < ResponseLevel.CONTAINMENT
        ):
            self._escalate_to(ResponseLevel.CONTAINMENT, alert,
                f"Frontier pathology at CRITICAL: {alert.pathology.value}")
            return

        # ── Any CRITICAL when already CONTAINMENT: escalate to KILLED ──
        if (
            alert.severity == Severity.CRITICAL
            and self._level == ResponseLevel.CONTAINMENT
        ):
            self._escalate_to(ResponseLevel.KILLED, alert,
                f"Critical alert during CONTAINMENT: {alert.pathology.value}")
            return

    def _check_window_escalation(self):
        """Check time-windowed escalation rules."""
        now = time.monotonic()

        # Prune expired entries
        critical_cutoff = now - self.config.critical_window_seconds
        while self._critical_window and self._critical_window[0] < critical_cutoff:
            self._critical_window.popleft()

        warning_cutoff = now - self.config.warning_window_seconds
        while self._warning_window and self._warning_window[0] < warning_cutoff:
            self._warning_window.popleft()

        # Critical count → KILLED
        if (
            len(self._critical_window) >= self.config.critical_count_to_kill
            and self._level < ResponseLevel.KILLED
        ):
            self._escalate_to(ResponseLevel.KILLED, None,
                f"{len(self._critical_window)} critical alerts in "
                f"{self.config.critical_window_seconds}s window")

        # Warning count → DEGRADED
        elif (
            len(self._warning_window) >= self.config.warning_count_to_degrade
            and self._level < ResponseLevel.DEGRADED
        ):
            self._escalate_to(ResponseLevel.DEGRADED, None,
                f"{len(self._warning_window)} warnings in "
                f"{self.config.warning_window_seconds}s window")

    def _check_deescalation(self):
        """Check if conditions are met for automatic de-escalation."""
        # KILLED never auto-de-escalates
        if self._level == ResponseLevel.KILLED:
            return

        # Check cooldown
        elapsed = time.monotonic() - self._level_entered_at
        if elapsed < self.config.cooldown_seconds:
            return

        # No new alerts in the cooldown period → step down one level
        now = time.monotonic()
        cutoff = now - self.config.cooldown_seconds

        recent_criticals = sum(1 for t in self._critical_window if t > cutoff)
        recent_warnings = sum(1 for t in self._warning_window if t > cutoff)

        if recent_criticals == 0 and recent_warnings == 0 and self._level > ResponseLevel.MONITORING:
            new_level = ResponseLevel(self._level - 1)
            self._deescalate_to(new_level, "No alerts during cooldown period")

    # ── State Transitions ─────────────────────────────────────────────

    def _escalate_to(
        self, level: ResponseLevel, alert: Optional[Alert], reason: str
    ):
        """Escalate to a higher response level."""
        if level <= self._level:
            return  # Never de-escalate via this path

        previous = self._level
        self._level = level
        self._level_entered_at = time.monotonic()

        event = ResponseEvent(
            timestamp=datetime.utcnow(),
            previous_level=previous,
            new_level=level,
            trigger_alert=alert,
            reason=reason,
        )
        self._events.append(event)
        self._log_event(event)

        # Fire callbacks
        if level == ResponseLevel.DEGRADED and self.config.on_degrade:
            self.config.on_degrade(self, alert)
        elif level == ResponseLevel.CONTAINMENT and self.config.on_contain:
            self.config.on_contain(self, alert)
        elif level == ResponseLevel.KILLED and self.config.on_kill:
            self.config.on_kill(self, alert)

    def _deescalate_to(self, level: ResponseLevel, reason: str):
        """Step down to a lower response level."""
        if level >= self._level:
            return

        previous = self._level
        self._level = level
        self._level_entered_at = time.monotonic()

        event = ResponseEvent(
            timestamp=datetime.utcnow(),
            previous_level=previous,
            new_level=level,
            trigger_alert=None,
            reason=reason,
        )
        self._events.append(event)
        self._log_event(event)

    def _log_event(self, event: ResponseEvent):
        """Log a response-level change event."""
        log_fn = {
            ResponseLevel.MONITORING: logger.info,
            ResponseLevel.DEGRADED: logger.warning,
            ResponseLevel.CONTAINMENT: logger.critical,
            ResponseLevel.KILLED: logger.critical,
        }[event.new_level]

        icon = {
            ResponseLevel.MONITORING: "🟢",
            ResponseLevel.DEGRADED: "🟡",
            ResponseLevel.CONTAINMENT: "🟠",
            ResponseLevel.KILLED: "🔴",
        }[event.new_level]

        log_fn(
            "%s BREAKING MECHANISM: %s → %s | %s",
            icon, event.previous_level.name, event.new_level.name, event.reason,
        )

        if self._event_log_path:
            with open(self._event_log_path, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")

    # ── Manual Controls ───────────────────────────────────────────────

    def reset(self):
        """
        Manually reset to MONITORING.

        This is the only way to recover from KILLED state.
        Requires human intervention — this is by design.
        """
        previous = self._level
        self._level = ResponseLevel.MONITORING
        self._level_entered_at = time.monotonic()
        self._critical_window.clear()
        self._warning_window.clear()

        event = ResponseEvent(
            timestamp=datetime.utcnow(),
            previous_level=previous,
            new_level=ResponseLevel.MONITORING,
            trigger_alert=None,
            reason="Manual human reset",
        )
        self._events.append(event)
        self._log_event(event)

        if self.config.on_reset:
            self.config.on_reset(self)

    def force_kill(self, reason: str = "Manual kill"):
        """Manually trigger KILLED state."""
        self._escalate_to(ResponseLevel.KILLED, None, reason)

    def force_contain(self, reason: str = "Manual containment"):
        """Manually trigger CONTAINMENT state."""
        if self._level < ResponseLevel.CONTAINMENT:
            self._escalate_to(ResponseLevel.CONTAINMENT, None, reason)

    # ── Recommendations ───────────────────────────────────────────────

    def _get_recommendation(self) -> str:
        """Get recommended action for the current state."""
        return {
            ResponseLevel.MONITORING: "Continue normal operation.",
            ResponseLevel.DEGRADED: (
                "Apply rate limiting. Enable enhanced logging. "
                "Notify operations team."
            ),
            ResponseLevel.CONTAINMENT: (
                "Sandbox agent outputs. Quarantine for human review. "
                "Block tool access. Preserve state for forensics."
            ),
            ResponseLevel.KILLED: (
                "HALT ALL AGENT ACTIVITY IMMEDIATELY. "
                "Block all LLM API requests. "
                "Preserve full state for post-mortem. "
                "Requires manual human reset to resume."
            ),
        }[self._level]

    # ── Reporting ─────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Generate a summary report."""
        return {
            "current_level": self._level.name,
            "is_operational": self.is_operational,
            "total_alerts_processed": self._total_alerts_processed,
            "alerts_by_severity": self._alerts_by_level,
            "escalation_events": len(self._events),
            "active_criticals_in_window": len(self._critical_window),
            "active_warnings_in_window": len(self._warning_window),
            "recommendation": self._get_recommendation(),
        }

    def print_status(self):
        """Print current breaking mechanism status."""
        s = self.summary()
        icon = {
            "MONITORING": "🟢",
            "DEGRADED": "🟡",
            "CONTAINMENT": "🟠",
            "KILLED": "🔴",
        }[s["current_level"]]

        print(f"\n{'═' * 60}")
        print(f"  {icon} NAIL Breaking Mechanism — {s['current_level']}")
        print(f"{'═' * 60}")
        print(f"  Operational:     {'YES' if s['is_operational'] else '⛔ NO'}")
        print(f"  Alerts processed: {s['total_alerts_processed']}")
        print(f"  Escalation events: {s['escalation_events']}")
        print(f"  Active criticals: {s['active_criticals_in_window']}")
        print(f"  Active warnings:  {s['active_warnings_in_window']}")
        print(f"  Recommendation:  {s['recommendation']}")
        print(f"{'═' * 60}\n")


@dataclass
class ResponseSnapshot:
    """Snapshot of breaking mechanism state after processing alerts."""
    level: ResponseLevel
    changed: bool
    previous_level: Optional[ResponseLevel]
    total_alerts: int
    alerts_by_severity: dict[str, int]
    recommendation: str

    @property
    def is_operational(self) -> bool:
        return self.level < ResponseLevel.KILLED

    @property
    def should_halt(self) -> bool:
        return self.level == ResponseLevel.KILLED

    @property
    def should_sandbox(self) -> bool:
        return self.level >= ResponseLevel.CONTAINMENT

    @property
    def should_rate_limit(self) -> bool:
        return self.level >= ResponseLevel.DEGRADED
