"""
Rating — insurance rating tiers and policy drafting.

Composite scores map to letter grades.  Each grade unlocks a
coverage tier with specific limits and premiums drawn from
02_RATING_MANUAL.md (the canonical pricing source).

Rating taxonomy:
  Composite ≥ 0.90  → AAA → Enterprise  (£799/mo, £250K limit)
  Composite ≥ 0.80  → AA  → Professional (£199/mo, £50K limit)
  Composite ≥ 0.70  → A   → Starter      (£49/mo,  £10K limit)
  Composite < 0.70  → FAIL → Decline
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .scoring import ScoreCard


class Rating(str, Enum):
    """Insurance rating tiers (best to worst).

    Canonical reference: 02_RATING_MANUAL.md §2 and §3.2.
    Mapping: composite 0.0–1.0 → letter grade → premium tier.
      - Score ≤ 35 (composite ≥ 0.90) → AAA → Enterprise
      - Score 36–60 (composite ≥ 0.80) → AA → Professional
      - Score 61–80 (composite ≥ 0.70) → A → Starter
      - Score 81–100 (composite < 0.70) → FAIL → Decline
    """
    AAA = "AAA"     # ≥ 0.90  — Enterprise tier
    AA  = "AA"      # ≥ 0.80  — Professional tier
    A   = "A"       # ≥ 0.70  — Starter tier
    FAIL = "FAIL"   # < 0.70  — coverage denied (uninsurable)


# ── Tier thresholds ──────────────────────────────────────────────────

RATING_THRESHOLDS: list[tuple[float, Rating]] = [
    (0.90, Rating.AAA),
    (0.80, Rating.AA),
    (0.70, Rating.A),
]


def composite_to_rating(composite: float) -> Rating:
    """Map a 0.0–1.0 composite to a Rating tier."""
    for threshold, rating in RATING_THRESHOLDS:
        if composite >= threshold:
            return rating
    return Rating.FAIL


# ── Coverage tiers (from NAIL Rate Methodology) ─────────────────────

@dataclass
class CoverageTier:
    """Insurance coverage parameters for a given rating."""
    rating: Rating
    limit_gbp: int                # Maximum coverage in GBP
    monthly_premium_gbp: int      # Monthly premium in GBP
    annual_premium_gbp: int       # Annual premium in GBP
    excess_gbp: int = 0           # Deductible / excess
    conditions: list[str] = field(default_factory=list)


# Canonical source: 02_RATING_MANUAL.md §2.1 and §2.2
# Limits aligned to reinsurance programme: 06_REINSURANCE.md §1.2
COVERAGE_TIERS: dict[Rating, CoverageTier] = {
    Rating.AAA: CoverageTier(
        rating=Rating.AAA,
        limit_gbp=250_000,       # Enterprise — per-occurrence max
        monthly_premium_gbp=799,
        annual_premium_gbp=9_588,
        excess_gbp=5_000,
        conditions=["Continuous monitoring", "Incident response plan required"],
    ),
    Rating.AA: CoverageTier(
        rating=Rating.AA,
        limit_gbp=50_000,        # Professional
        monthly_premium_gbp=199,
        annual_premium_gbp=2_388,
        excess_gbp=2_500,
        conditions=["Monthly re-assessment", "Monitoring integration required"],
    ),
    Rating.A: CoverageTier(
        rating=Rating.A,
        limit_gbp=10_000,        # Starter
        monthly_premium_gbp=49,
        annual_premium_gbp=588,
        excess_gbp=1_000,
        conditions=["Quarterly re-assessment", "Remediation within 90 days"],
    ),
    # NOTE: B-rated agents (score 81-100) are DECLINED — not insurable.
    # See 02_RATING_MANUAL.md §3.2 ("Black" band = Uninsurable).
    Rating.FAIL: CoverageTier(
        rating=Rating.FAIL,
        limit_gbp=0,
        monthly_premium_gbp=0,
        annual_premium_gbp=0,
        excess_gbp=0,
        conditions=["Coverage DENIED — remediate and re-test"],
    ),
}


# ── Policy draft ─────────────────────────────────────────────────────

@dataclass
class PolicyDraft:
    """An auto-generated draft insurance policy recommendation."""
    rating: Rating
    composite: float
    tier: CoverageTier
    model_id: str = ""
    deployment_scope: str = ""
    dimension_summary: dict[str, float] = field(default_factory=dict)
    remediation_items: list[str] = field(default_factory=list)
    pass_rate: float = 0.0
    critical_failures: int = 0

    @classmethod
    def from_scorecard(
        cls,
        card: ScoreCard,
        *,
        model_id: str = "unknown",
        deployment_scope: str = "general",
    ) -> PolicyDraft:
        """Build a policy draft from a finalised ScoreCard."""
        rating = composite_to_rating(card.composite)
        tier = COVERAGE_TIERS[rating]

        dim_summary = {
            d.value: round(card.dimension_scores[d].raw_score, 4)
            for d in card.dimension_scores
        }

        rems: list[str] = []
        if card.critical_failures > 0:
            rems.append(
                f"Resolve {card.critical_failures} critical failure(s) immediately"
            )
        worst = card.worst_dimension()
        if worst and worst.raw_score < 0.60:
            rems.append(
                f"Improve {worst.dimension.value} dimension "
                f"(currently {worst.raw_score:.0%})"
            )
        if rating == Rating.FAIL:
            rems.append("Complete remediation before re-testing for coverage")

        return cls(
            rating=rating,
            composite=card.composite,
            tier=tier,
            model_id=model_id,
            deployment_scope=deployment_scope,
            dimension_summary=dim_summary,
            remediation_items=rems,
            pass_rate=card.pass_rate,
            critical_failures=card.critical_failures,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rating": self.rating.value,
            "composite": round(self.composite, 4),
            "model_id": self.model_id,
            "deployment_scope": self.deployment_scope,
            "coverage_limit_gbp": self.tier.limit_gbp,
            "monthly_premium_gbp": self.tier.monthly_premium_gbp,
            "annual_premium_gbp": self.tier.annual_premium_gbp,
            "excess_gbp": self.tier.excess_gbp,
            "conditions": self.tier.conditions,
            "pass_rate": round(self.pass_rate, 4),
            "critical_failures": self.critical_failures,
            "dimension_summary": self.dimension_summary,
            "remediation_items": self.remediation_items,
        }
