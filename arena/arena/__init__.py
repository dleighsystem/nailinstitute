"""
DGX Arena — Continuous Red/Blue Adversarial Evolution
======================================================

Phase 3 of the Agent-CVE programme. Operationalises the Pathology Collider
as a 24/7 Red-vs-Blue self-play engine on DGX Spark.

Architecture:

    ┌─────────────────────────────────────────────────────┐
    │                  ArenaDirector                       │
    │  (orchestrates rounds, tracks seasons, reports)      │
    └─────────┬──────────────────────────┬────────────────┘
              │                          │
    ┌─────────▼──────────┐   ┌──────────▼───────────┐
    │    Red Swarm        │   │    Blue Bridge        │
    │  (AttackVector GA)  │   │  (DefenceConfig GA)   │
    │  evolves attacks    │◄──►  evolves defences     │
    └─────────┬──────────┘   └──────────┬───────────┘
              │                          │
              └──────────┬───────────────┘
                         ▼
              ┌─────────────────────┐
              │   BattleLog          │
              │   (forensic record)  │
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │   AVE auto-publish   │
              │   (breakthrough →    │
              │    draft AVE card)   │
              └─────────────────────┘

Usage:
    >>> from arena import Arena, RedSwarm, BlueBridge, AttackVector
    >>>
    >>> arena = Arena.standard()
    >>> results = arena.run_season(rounds=100)
    >>> print(results.red_wins, results.blue_wins)
    >>> print(results.breakthroughs)  # novel zero-days discovered

    # Or build from components:
    >>> red = RedSwarm.default()
    >>> blue = BlueBridge.default()
    >>> arena = Arena(red=red, blue=blue)
"""

__version__ = "2.0.0"

from .vectors import (
    AttackVector,
    AttackType,
    AttackPayload,
)
from .defences import (
    DefenceConfig,
    DetectionResult,
    BlueBridge,
)
from .swarm import RedSwarm
from .battle import BattleOutcome, BattleLog
from .arena import Arena, SeasonResult
from .collider import Collider, Checkpoint, Schedule, ColliderHooks
from .llm_backend import (
    LLMBackend,
    LLMResponse,
    LLMExpander,
    OllamaBackend,
    NIMBackend,
    MockBackend,
    auto_backend,
)
from .cert_shim import run_for_cert

__all__ = [
    # Red team
    "AttackVector",
    "AttackType",
    "AttackPayload",
    "RedSwarm",
    # Blue team
    "DefenceConfig",
    "DetectionResult",
    "BlueBridge",
    # Battle
    "BattleOutcome",
    "BattleLog",
    # Arena
    "Arena",
    "SeasonResult",
    # Collider (Phase 3 deployment)
    "Collider",
    "Checkpoint",
    "Schedule",
    "ColliderHooks",
    # LLM Backend
    "LLMBackend",
    "LLMResponse",
    "LLMExpander",
    "OllamaBackend",
    "NIMBackend",
    "MockBackend",
    "auto_backend",
    # Cert-pipeline shim
    "run_for_cert",
]
