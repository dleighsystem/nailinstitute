"""NAIL Foresight — pre-flight planner.

Public API:

    from foresight import (
        Plan, Step, Risk, Critique,
        Critic, OllamaCritic, HeuristicCritic, MockCritic,
        Verdict,
    )
"""
from .plan import Plan, Step
from .critique import Risk, Critique, Verdict, RiskSeverity
from .critic import Critic, HeuristicCritic, MockCritic
from .ollama_critic import OllamaCritic, OllamaError

__all__ = [
    "Plan", "Step",
    "Risk", "Critique", "Verdict", "RiskSeverity",
    "Critic", "HeuristicCritic", "MockCritic", "OllamaCritic",
    "OllamaError",
]

__version__ = "0.1.0"
