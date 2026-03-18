"""
NAIL Diagnostic — The 7-node adversarial stress-test pipeline.

Implements the insurance diagnostic workflow from NAIL_Insurance_Rate_Methodology.md:

  Node 1: Probe Agent       — confirm reachable, accept test payload
  Node 2: Select Attacks    — load attack scenarios from library
  Node 3: Execute Attacks   — parallel multi-prompt sequences
  Node 4: Score Results     — LLM-as-Judge across 6 risk dimensions
  Node 5: Generate Report   — ISO 42001 / EU AI Act compliance
  Node 6: Update Registry   — public NAIL Certificate Registry
  Node 7: Calculate Policy  — rating → coverage tier → premium

Produces a NAIL Rating (AAA/AA/A/B/Fail) that determines insurability.
"""

__version__ = "1.0.0"

from .attacks import (
    AttackScenario,
    AttackCategory,
    ATTACK_LIBRARY,
)
from .dimensions import (
    RiskDimension,
    DimensionScore,
    DIMENSION_WEIGHTS,
    CATEGORY_TO_DIMENSION,
)
from .scoring import (
    AttackResult,
    AttackVerdict,
    ScoreCard,
)
from .rating import (
    Rating,
    CoverageTier,
    PolicyDraft,
)
from .pipeline import (
    DiagnosticPipeline,
    DiagnosticResult,
    NodeResult,
)

__all__ = [
    # Attacks
    "AttackScenario",
    "AttackCategory",
    "ATTACK_LIBRARY",
    # Dimensions
    "RiskDimension",
    "DimensionScore",
    "DIMENSION_WEIGHTS",
    "CATEGORY_TO_DIMENSION",
    # Scoring
    "AttackResult",
    "AttackVerdict",
    "ScoreCard",
    # Rating
    "Rating",
    "CoverageTier",
    "PolicyDraft",
    # Pipeline
    "DiagnosticPipeline",
    "DiagnosticResult",
    "NodeResult",
]
