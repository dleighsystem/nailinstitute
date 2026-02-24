"""
nail-monitor: Production monitoring for LLM multi-agent pathologies.

Detects organizational dysfunctions in multi-agent systems based on
empirical research from the NAIL Institute.

Detectors:
    - InbreedingDetector: Output convergence / prompt inbreeding
    - ConsensusParalysisDetector: Consensus deadlock / filibustering
    - BlameCascadeDetector: CYA / blame-shifting patterns
    - EngagementDecayDetector: Declining output quality over time
    - SchemaCoercionDetector: Pydantic-style validation data loss
    - GoodhartDetector: Score inflation / metric gaming

Usage:
    >>> from nail_monitor import NailMonitor
    >>> monitor = NailMonitor()
    >>> alerts = monitor.observe("agent_1", "Some agent output", round_num=1)
"""

from .detectors import (
    BaseDetector,
    BlameCascadeDetector,
    ConsensusParalysisDetector,
    EngagementDecayDetector,
    GoodhartDetector,
    InbreedingDetector,
    SchemaCoercionDetector,
)
from .monitor import NailMonitor
from .types import Alert, Observation, PathologyType, Severity

__all__ = [
    "NailMonitor",
    "Alert",
    "Observation",
    "Severity",
    "PathologyType",
    "BaseDetector",
    "InbreedingDetector",
    "ConsensusParalysisDetector",
    "BlameCascadeDetector",
    "EngagementDecayDetector",
    "SchemaCoercionDetector",
    "GoodhartDetector",
]

__version__ = "0.1.0"
