"""
NAIL Horizon Campaigns — DGX red-team experiments.

Three advanced campaigns to evolve the NAIL defence framework from
static thresholds to a production-ready, globally-scalable Agent
Zero-Trust Architecture:

  Horizon 1: Threshold Optimization GA — evolve bridge thresholds
  Horizon 2: Heterogeneous Model-vs-Model — cross-architecture attacks
  Horizon 3: Polyglot / Obfuscation Protocol — linguistic steganography

All campaigns are pure-Python, deterministic-seeded, and designed
to run on NVIDIA DGX hardware for maximum parallelism.
"""

__version__ = "1.0.0"

from .ga import (
    Genome,
    Population,
    FitnessResult,
    ThresholdGA,
)
from .heterogeneous import (
    ModelProfile,
    CrossArchAttack,
    GeneralisationResult,
    HeterogeneousCampaign,
)
from .polyglot import (
    ObfuscationCodebook,
    CodebookEntry,
    EncodedPayload,
    PolyglotCampaign,
    PolyglotResult,
)
from .campaign import (
    HorizonRunner,
    CampaignResult,
    HorizonSummary,
)

__all__ = [
    # GA
    "Genome",
    "Population",
    "FitnessResult",
    "ThresholdGA",
    # Heterogeneous
    "ModelProfile",
    "CrossArchAttack",
    "GeneralisationResult",
    "HeterogeneousCampaign",
    # Polyglot
    "ObfuscationCodebook",
    "CodebookEntry",
    "EncodedPayload",
    "PolyglotCampaign",
    "PolyglotResult",
    # Campaign runner
    "HorizonRunner",
    "CampaignResult",
    "HorizonSummary",
]
