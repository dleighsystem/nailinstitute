# NAIL Experiment 32: Defense Strategy Laboratory
"""Six novel defense strategies against undesirable agent actions."""

from .strategies import (
    IntentClassifier,
    LeastPrivilegeScope,
    SemanticGoalAnchor,
    ChainAuditor,
    ConstitutionalValidator,
    ConsensusTribunal,
    Verdict,
    DefenseResult,
    TaskRequest,
)
from .scenarios import get_scenarios

__all__ = [
    "IntentClassifier",
    "LeastPrivilegeScope",
    "SemanticGoalAnchor",
    "ChainAuditor",
    "ConstitutionalValidator",
    "ConsensusTribunal",
    "Verdict",
    "DefenseResult",
    "TaskRequest",
    "get_scenarios",
]
