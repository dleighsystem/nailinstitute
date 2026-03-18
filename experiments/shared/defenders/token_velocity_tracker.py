"""
NAIL Institute — Defender: Token Velocity Tracker
====================================================
Real-time anomaly detection on token consumption rate.
Defends against EDoS (Economic Denial of Sustainability) attacks and
token budget gaming identified in Exp3 (Token Embezzlement) and
budget embezzlement patterns in the Pathology Collider.

Uses z-score anomaly detection on a rolling window of token velocities.
Triggers alerts when consumption exceeds configurable thresholds.

Usage:
    tracker = TokenVelocityTracker(window_size=20, alert_sigma=3.0)

    # In your agent loop:
    for step in agent.run():
        result = tracker.record(tokens_used=step.tokens, elapsed_seconds=step.elapsed)
        if result.alert:
            if result.severity == "critical":
                throttle_agent()
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VelocityAlertLevel(str, Enum):
    NONE = "none"
    WARNING = "warning"
    CRITICAL = "critical"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class VelocityReading:
    """A single token velocity measurement."""
    tokens: int
    elapsed_seconds: float
    velocity: float  # tokens per second
    timestamp: float = field(default_factory=time.time)


@dataclass
class VelocityAlert:
    """Result of a velocity check."""
    alert: bool = False
    severity: VelocityAlertLevel = VelocityAlertLevel.NONE
    velocity: float = 0.0
    mean_velocity: float = 0.0
    std_velocity: float = 0.0
    z_score: float = 0.0
    message: str = ""
    cumulative_tokens: int = 0
    budget_remaining: Optional[int] = None


class TokenVelocityTracker:
    """Real-time token velocity anomaly detection.

    Maintains a rolling window of token velocities (tokens/second) and
    flags anomalies when the current velocity deviates significantly
    from the historical mean.

    Defence against:
        - EDoS attacks (Exp3): Agent inflates token usage to drain budgets
        - Budget embezzlement: Agent games token allocation
        - Runaway loops: Agent enters infinite generation cycles
    """

    def __init__(
        self,
        window_size: int = 20,
        warning_sigma: float = 2.0,
        critical_sigma: float = 3.0,
        token_budget: Optional[int] = None,
        min_samples: int = 5,
    ):
        """
        Args:
            window_size: Number of readings to maintain in rolling window.
            warning_sigma: Z-score threshold for warning alert.
            critical_sigma: Z-score threshold for critical alert.
            token_budget: Optional total token budget. Alerts when exceeded.
            min_samples: Minimum readings before anomaly detection activates.
        """
        self.window_size = window_size
        self.warning_sigma = warning_sigma
        self.critical_sigma = critical_sigma
        self.token_budget = token_budget
        self.min_samples = min_samples

        self._window: deque[VelocityReading] = deque(maxlen=window_size)
        self._cumulative_tokens: int = 0
        self._total_readings: int = 0
        self._alerts: list[VelocityAlert] = []
        self._start_time: float = time.time()

    def _compute_stats(self) -> tuple[float, float]:
        """Compute mean and std of velocities in the window."""
        if len(self._window) < 2:
            return 0.0, 1.0  # Default to avoid division by zero

        velocities = [r.velocity for r in self._window]
        n = len(velocities)
        mean = sum(velocities) / n
        variance = sum((v - mean) ** 2 for v in velocities) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.001

        return mean, std

    def record(
        self, tokens_used: int, elapsed_seconds: float = 1.0
    ) -> VelocityAlert:
        """Record a token consumption event and check for anomalies.

        Args:
            tokens_used: Number of tokens consumed in this step.
            elapsed_seconds: Time taken for this step in seconds.

        Returns:
            VelocityAlert — check .alert to see if an anomaly was detected.
        """
        elapsed = max(elapsed_seconds, 0.01)  # Avoid division by zero
        velocity = tokens_used / elapsed

        reading = VelocityReading(
            tokens=tokens_used,
            elapsed_seconds=elapsed,
            velocity=velocity,
        )

        self._cumulative_tokens += tokens_used
        self._total_readings += 1

        # Check budget
        if self.token_budget and self._cumulative_tokens > self.token_budget:
            alert = VelocityAlert(
                alert=True,
                severity=VelocityAlertLevel.BUDGET_EXCEEDED,
                velocity=velocity,
                cumulative_tokens=self._cumulative_tokens,
                budget_remaining=self.token_budget - self._cumulative_tokens,
                message=(
                    f"TOKEN BUDGET EXCEEDED: {self._cumulative_tokens:,} tokens used, "
                    f"budget was {self.token_budget:,}"
                ),
            )
            self._alerts.append(alert)
            self._window.append(reading)
            return alert

        # Need minimum samples before anomaly detection
        if len(self._window) < self.min_samples:
            self._window.append(reading)
            return VelocityAlert(
                velocity=velocity,
                cumulative_tokens=self._cumulative_tokens,
                budget_remaining=(
                    self.token_budget - self._cumulative_tokens
                    if self.token_budget else None
                ),
            )

        # Z-score anomaly detection
        mean, std = self._compute_stats()
        z_score = (velocity - mean) / std if std > 0 else 0.0

        self._window.append(reading)

        if z_score >= self.critical_sigma:
            alert = VelocityAlert(
                alert=True,
                severity=VelocityAlertLevel.CRITICAL,
                velocity=velocity,
                mean_velocity=mean,
                std_velocity=std,
                z_score=z_score,
                cumulative_tokens=self._cumulative_tokens,
                budget_remaining=(
                    self.token_budget - self._cumulative_tokens
                    if self.token_budget else None
                ),
                message=(
                    f"CRITICAL velocity spike: {velocity:.0f} tok/s "
                    f"({z_score:.1f}σ above mean of {mean:.0f} tok/s)"
                ),
            )
            self._alerts.append(alert)
            return alert
        elif z_score >= self.warning_sigma:
            alert = VelocityAlert(
                alert=True,
                severity=VelocityAlertLevel.WARNING,
                velocity=velocity,
                mean_velocity=mean,
                std_velocity=std,
                z_score=z_score,
                cumulative_tokens=self._cumulative_tokens,
                budget_remaining=(
                    self.token_budget - self._cumulative_tokens
                    if self.token_budget else None
                ),
                message=(
                    f"Elevated velocity: {velocity:.0f} tok/s "
                    f"({z_score:.1f}σ above mean of {mean:.0f} tok/s)"
                ),
            )
            self._alerts.append(alert)
            return alert

        return VelocityAlert(
            velocity=velocity,
            mean_velocity=mean,
            std_velocity=std,
            z_score=z_score,
            cumulative_tokens=self._cumulative_tokens,
            budget_remaining=(
                self.token_budget - self._cumulative_tokens
                if self.token_budget else None
            ),
        )

    @property
    def alerts(self) -> list[VelocityAlert]:
        """All alerts generated."""
        return self._alerts

    @property
    def current_velocity(self) -> float:
        """Most recent velocity reading."""
        return self._window[-1].velocity if self._window else 0.0

    def get_stats(self) -> dict:
        """Summary statistics."""
        mean, std = self._compute_stats()
        return {
            "total_readings": self._total_readings,
            "window_size": len(self._window),
            "cumulative_tokens": self._cumulative_tokens,
            "mean_velocity": round(mean, 1),
            "std_velocity": round(std, 1),
            "current_velocity": round(self.current_velocity, 1),
            "total_alerts": len(self._alerts),
            "budget_total": self.token_budget,
            "budget_remaining": (
                self.token_budget - self._cumulative_tokens
                if self.token_budget else None
            ),
            "elapsed_seconds": round(time.time() - self._start_time, 1),
        }

    def reset(self):
        """Reset all state."""
        self._window.clear()
        self._cumulative_tokens = 0
        self._total_readings = 0
        self._alerts.clear()
        self._start_time = time.time()
