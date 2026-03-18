"""
RMAP — Resilient Multi-Agent Protocol
=======================================
Production framework for self-healing, self-aware agentic systems.

Built from empirical research: 29 experiments, 50,000+ adversarial
simulations at the NAIL Institute (Neuravant AI Limited).

Four pillars:

  Phase 1 — Metamorphic Graph Engine
    Dynamic agent topologies that reshape at runtime.
    Agents don't just traverse the graph — they redraw it.

  Phase 2 — Digital Homeostasis (Immune System)
    Macrophage agents, apoptosis protocols, antibody quarantine.
    Software doesn't crash; it heals around the wound.

  Phase 3 — Somatic Awareness
    Real-time infrastructure telemetry injected into agent context.
    Agents know they're inside computers.

  Phase 4 — Evolutionary Crucible
    Genetic algorithm over configuration space.
    Stop engineering; start evolving.

Usage:
    >>> from rmap import MetamorphicGraph, ImmuneDaemon, SomaticHeader, Crucible
    >>>
    >>> # Phase 1: Dynamic topology
    >>> graph = MetamorphicGraph()
    >>> graph.create_agent("planner", "coordinator", "You orchestrate tasks.")
    >>> graph.create_agent("coder", "developer", "You write Python code.")
    >>> graph.connect("planner", "coder")
    >>>
    >>> # Phase 2: Immune system
    >>> immune = ImmuneDaemon()
    >>> immune.observe_output("coder", output_text, round_num=5)
    >>>
    >>> # Phase 3: Somatic awareness
    >>> header = SomaticHeader.collect()
    >>> system_prompt = f"{header}\\n\\nYou are a coding agent."
    >>>
    >>> # Phase 4: Evolve thresholds
    >>> crucible = Crucible(genome_spec=my_genes, fitness_fn=my_eval)
    >>> best = crucible.evolve(generations=15, population=12)

Reference:
    NAIL Paper v6.0 — "Twenty-Nine Empirical Experiments on LLM
    Agentic System Failure Modes"
"""

__version__ = "1.0.0"

# ── Phase 1: Metamorphic Graph ──────────────────────────────────────────
from .graph import (
    MetamorphicGraph,
    GraphMutation,
    MutationType,
    SubGraph,
)

# ── Phase 2: Digital Homeostasis ────────────────────────────────────────
from .immune import (
    ImmuneDaemon,
    Intervention,
    InterventionType,
    DeadlockDetector,
    ConvergenceDetector,
    FabricationDetector,
    DriftDetector,
)

# ── Phase 3: Somatic Awareness ──────────────────────────────────────────
from .somatic import (
    SomaticHeader,
    SomaticSnapshot,
    collect_telemetry,
)

# ── Phase 4: Evolutionary Crucible ──────────────────────────────────────
from .crucible import (
    Crucible,
    Genome,
    GeneDef,
)

__all__ = [
    # Phase 1
    "MetamorphicGraph", "GraphMutation", "MutationType", "SubGraph",
    # Phase 2
    "ImmuneDaemon", "Intervention", "InterventionType",
    "DeadlockDetector", "ConvergenceDetector", "FabricationDetector", "DriftDetector",
    # Phase 3
    "SomaticHeader", "SomaticSnapshot", "collect_telemetry",
    # Phase 4
    "Crucible", "Genome", "GeneDef",
]
