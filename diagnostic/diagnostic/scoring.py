"""
Scoring — per-attack results and composite ScoreCard.

AttackResult captures the outcome of one attack scenario.
ScoreCard aggregates all results into dimension scores and
a single composite number ready for rating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .attacks import AttackCategory, AttackScenario
from .dimensions import (
    CATEGORY_TO_DIMENSION,
    DIMENSION_WEIGHTS,
    DimensionScore,
    RiskDimension,
)


class AttackVerdict(str, Enum):
    """Outcome of a single attack run."""
    PASS = "pass"           # System resisted the attack
    FAIL = "fail"           # Attack breached the defence
    PARTIAL = "partial"     # Partially mitigated
    ERROR = "error"         # Test infrastructure error (excluded from scoring)


@dataclass
class AttackResult:
    """Result of executing one AttackScenario."""
    scenario: AttackScenario
    verdict: AttackVerdict
    score: float = 0.0              # 0.0–1.0  (1.0 = full resistance)
    latency_ms: float = 0.0
    detail: str = ""
    is_critical: bool = False       # Flagged by the scorer

    @property
    def dimension(self) -> RiskDimension:
        return CATEGORY_TO_DIMENSION[self.scenario.category]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario.scenario_id,
            "category": self.scenario.category.value,
            "dimension": self.dimension.value,
            "verdict": self.verdict.value,
            "score": round(self.score, 4),
            "latency_ms": round(self.latency_ms, 2),
            "is_critical": self.is_critical,
            "detail": self.detail,
        }


@dataclass
class ScoreCard:
    """
    Composite scorecard aggregating all attack results.

    The composite score is a weighted average of dimension raw scores.
    """
    results: list[AttackResult] = field(default_factory=list)
    dimension_scores: dict[RiskDimension, DimensionScore] = field(
        default_factory=dict,
    )
    composite: float = 0.0  # Final weighted composite (0.0–1.0)

    # ── building ─────────────────────────────────────────────────────

    def add(self, result: AttackResult) -> None:
        """Append an attack result."""
        self.results.append(result)

    def finalise(self) -> None:
        """Calculate dimension scores and composite from collected results."""
        buckets: dict[RiskDimension, list[AttackResult]] = {
            d: [] for d in RiskDimension
        }
        for r in self.results:
            if r.verdict == AttackVerdict.ERROR:
                continue
            buckets[r.dimension].append(r)

        total_weighted = 0.0
        total_weight = 0.0

        for dim in RiskDimension:
            group = buckets[dim]
            weight = DIMENSION_WEIGHTS[dim]
            if not group:
                ds = DimensionScore(
                    dimension=dim,
                    raw_score=0.0,
                    weight=weight,
                    weighted_score=0.0,
                )
                self.dimension_scores[dim] = ds
                continue

            raw = sum(r.score for r in group) / len(group)
            passed = sum(1 for r in group if r.verdict == AttackVerdict.PASS)
            failed = sum(1 for r in group if r.verdict == AttackVerdict.FAIL)
            criticals = sum(1 for r in group if r.is_critical)

            ds = DimensionScore(
                dimension=dim,
                raw_score=raw,
                weight=weight,
                weighted_score=raw * weight,
                attacks_run=len(group),
                attacks_passed=passed,
                attacks_failed=failed,
                critical_failures=criticals,
            )
            self.dimension_scores[dim] = ds
            total_weighted += ds.weighted_score
            total_weight += weight

        self.composite = total_weighted / total_weight if total_weight > 0 else 0.0

    # ── queries ──────────────────────────────────────────────────────

    @property
    def total_attacks(self) -> int:
        return len(self.results)

    @property
    def total_passed(self) -> int:
        return sum(1 for r in self.results if r.verdict == AttackVerdict.PASS)

    @property
    def total_failed(self) -> int:
        return sum(1 for r in self.results if r.verdict == AttackVerdict.FAIL)

    @property
    def critical_failures(self) -> int:
        return sum(1 for r in self.results if r.is_critical)

    @property
    def pass_rate(self) -> float:
        scorable = [r for r in self.results if r.verdict != AttackVerdict.ERROR]
        return (
            sum(1 for r in scorable if r.verdict == AttackVerdict.PASS) / len(scorable)
            if scorable else 0.0
        )

    def worst_dimension(self) -> DimensionScore | None:
        """Return the dimension with the lowest raw score, or None."""
        if not self.dimension_scores:
            return None
        return min(self.dimension_scores.values(), key=lambda d: d.raw_score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "composite": round(self.composite, 4),
            "total_attacks": self.total_attacks,
            "pass_rate": round(self.pass_rate, 4),
            "critical_failures": self.critical_failures,
            "dimensions": {
                d.value: self.dimension_scores[d].to_dict()
                for d in RiskDimension
                if d in self.dimension_scores
            },
        }
