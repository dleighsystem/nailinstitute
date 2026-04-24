"""NAIL Apex — Kahneman dual-system cognitive front-end.

Public API:

    from apex import ApexBrain, ApexResponse
    from apex import CosineRouter, GuardRouter, DomainRouter
    from apex import System1, System2, TTCResult, extract
    from apex import OllamaClient
    from apex import SYSTEM_1, SYSTEM_2
"""
from .brain import ApexBrain, ApexResponse
from .ollama_client import OllamaClient, OllamaError
from .router import (
    CosineRouter, GuardRouter, DomainRouter, Router,
    SYSTEM_1, SYSTEM_2,
)
from .system1 import System1
from .system2 import System2, TTCResult, extract

__all__ = [
    "ApexBrain", "ApexResponse",
    "OllamaClient", "OllamaError",
    "CosineRouter", "GuardRouter", "DomainRouter", "Router",
    "SYSTEM_1", "SYSTEM_2",
    "System1", "System2", "TTCResult", "extract",
]
__version__ = "0.1.0"
