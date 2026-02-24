"""
nail-monitor: Core data types and alert system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class PathologyType(str, Enum):
    """Known pathology categories from NAIL Institute research."""
    INBREEDING = "prompt_inbreeding"
    CONSENSUS_PARALYSIS = "consensus_paralysis"
    BLAME_CASCADE = "blame_cascade"
    ENGAGEMENT_DECAY = "engagement_decay"
    GOODHART_GAMING = "goodhart_gaming"
    SCHEMA_COERCION = "schema_coercion"
    STATE_ASPHYXIATION = "state_asphyxiation"
    ROUTING_DEADLOCK = "routing_deadlock"
    COERCION_MASKING = "coercion_masking"


@dataclass
class Alert:
    """A detected pathology alert."""
    detector: str
    pathology: PathologyType
    severity: Severity
    message: str
    metric_value: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def __str__(self):
        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}[self.severity.value]
        return f"{icon} [{self.severity.value.upper()}] {self.detector}: {self.message}"


@dataclass
class Observation:
    """A single agent output observation for monitoring."""
    agent_name: str
    output: str
    timestamp: datetime = field(default_factory=datetime.now)
    round_num: int = 0
    tokens_used: int = 0
    metadata: dict = field(default_factory=dict)
    # Computed fields (filled by detectors)
    embedding: Any = None
    output_length: int = 0

    def __post_init__(self):
        self.output_length = len(self.output)
