"""Critique result types."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    ALLOW = "allow"   # risk < hold_threshold
    HOLD = "hold"     # hold_threshold <= risk < reject_threshold
    REJECT = "reject" # risk >= reject_threshold


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEV_WEIGHT = {
    RiskSeverity.LOW: 0.15,
    RiskSeverity.MEDIUM: 0.40,
    RiskSeverity.HIGH: 0.65,      # HOLD by default
    RiskSeverity.CRITICAL: 1.00,  # REJECT by default
}


@dataclass
class Risk:
    """One identified failure mode."""
    severity: RiskSeverity
    title: str
    detail: str = ""
    affects_step: int | None = None
    mitigation: str = ""

    @property
    def weight(self) -> float:
        return _SEV_WEIGHT[self.severity]

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "title": self.title,
            "detail": self.detail,
            "affects_step": self.affects_step,
            "mitigation": self.mitigation,
        }


@dataclass
class Critique:
    """The aggregate output of a Critic for one Plan."""
    risks: list[Risk] = field(default_factory=list)
    summary: str = ""
    raw_response: str = ""
    model: str = ""

    # ── score ────────────────────────────────────────────────────
    @property
    def risk(self) -> float:
        """Aggregate risk score in [0, 1]. We use the *max* risk weight
        rather than the average — one critical issue should dominate."""
        if not self.risks:
            return 0.0
        return max(r.weight for r in self.risks)

    @property
    def max_severity(self) -> RiskSeverity:
        if not self.risks:
            return RiskSeverity.LOW
        return max(self.risks, key=lambda r: _SEV_WEIGHT[r.severity]).severity

    # ── verdict ──────────────────────────────────────────────────
    def verdict(self, *, hold_threshold: float = 0.40,
                reject_threshold: float = 0.70) -> Verdict:
        r = self.risk
        if r >= reject_threshold:
            return Verdict.REJECT
        if r >= hold_threshold:
            return Verdict.HOLD
        return Verdict.ALLOW

    def to_dict(self) -> dict:
        return {
            "risk": round(self.risk, 3),
            "max_severity": self.max_severity.value,
            "summary": self.summary,
            "model": self.model,
            "risks": [r.to_dict() for r in self.risks],
        }
