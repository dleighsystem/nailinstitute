"""
DESE — Deterministic Entropy Simulation Engine
===============================================

A new category of entropy primitive that generates reproducible,
platform-independent entropy through deterministic simulation of
chaotic dynamical systems.

DESE combines deterministic execution with chaotic system dynamics,
producing entropy that is both operationally unpredictable and
bit-exact replayable via manifest-based reconstruction.

Core guarantees:
    1. Determinism  — identical manifest → byte-identical output
    2. Chaos        — exponential sensitivity to initial conditions
    3. Uniformity   — extracted bits pass NIST SP 800-22 suite
    4. Portability  — IEEE 754 arithmetic, no platform-specific ops
    5. Auditability — every byte traceable to a manifest + step count

Copyright © 2026 Neuravant AI Limited / NAIL Institute.
"""

__version__ = "0.1.0"
__author__ = "NAIL Institute — Neuravant AI Limited"

from dese.manifest import Manifest
from dese.engine import DESEEngine
from dese.extractors import EntropyExtractor

__all__ = ["Manifest", "DESEEngine", "EntropyExtractor", "__version__"]
