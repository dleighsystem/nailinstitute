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

# Server is optional (needs fastapi). Import lazily so installs without
# the [server] extra still work.
try:  # pragma: no cover - import guard
    from .server import build_app, serve, DEFAULT_MODEL_NAME, DEFAULT_PORT
    _HAS_SERVER = True
except Exception:  # pragma: no cover
    build_app = None  # type: ignore[assignment]
    serve = None      # type: ignore[assignment]
    DEFAULT_MODEL_NAME = "apex-matrix-swarm"
    DEFAULT_PORT = 11435
    _HAS_SERVER = False

__all__ = [
    "ApexBrain", "ApexResponse",
    "OllamaClient", "OllamaError",
    "CosineRouter", "GuardRouter", "DomainRouter", "Router",
    "SYSTEM_1", "SYSTEM_2",
    "System1", "System2", "TTCResult", "extract",
    "build_app", "serve", "DEFAULT_MODEL_NAME", "DEFAULT_PORT",
]
__version__ = "0.2.0"
