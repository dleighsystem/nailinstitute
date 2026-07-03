"""Workflow ingester — derive a WorkflowProfile from a LangGraph (or a spec).

Turns "point us at your graph" into "here are your compliance gaps". A compiled
LangGraph ``StateGraph`` exposes enough structure to infer compliance-relevant
capabilities:

  * HITL **interrupt** nodes            -> human_oversight        (EU AIA Art. 14)
  * a **checkpointer**                  -> operational_logging    (Art. 26)
  * node-name signals (redact, audit,   -> pii_handling, immutable_audit_log,
    disclose, monitor, escalate, ...)      ai_disclosure, post_market_monitoring,
                                           kill_switch, robustness_monitoring …
  * author-**declared** capabilities    -> taken as asserted (escape hatch)

LangGraph is **never imported** — the compiled graph is duck-typed — so this stays
dependency-free and also accepts a plain mapping (for tests / non-LangGraph stacks).

Inference is heuristic + structural: treat derived capabilities as a first pass a
human confirms, not ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .engine import GapReport, WorkflowProfile, evaluate
from .registry import ComplianceRegistry
from .schema import Jurisdiction, Party, RiskTier

_END_TOKENS = {"__end__", "end"}

# node-name keyword -> capability (a supplementary, tunable signal)
_NODE_KEYWORD_CAPS: dict[str, tuple[str, ...]] = {
    "human_oversight": ("approve", "review", "human", "hitl", "oversight"),
    "kill_switch": ("kill", "abort", "halt", "escalate", "revoke", "stop", "circuit_break"),
    "pii_handling": ("redact", "scrub", "pii", "anonym", "mask", "deident"),
    "data_provenance_controls": ("provenance", "taint", "lineage", "redact", "scrub"),
    "ai_disclosure": ("disclose", "disclaimer", "inform_user", "ai_notice"),
    "post_market_monitoring": ("monitor", "telemetry", "metrics", "observ", "report_incident"),
    "immutable_audit_log": ("audit", "flight_record", "hash_chain", "record_keep"),
    "robustness_monitoring": ("guard", "validate", "policy_check", "redteam", "adversar", "detector"),
    "operational_logging": ("log", "logging", "record"),
}


@dataclass(frozen=True)
class GraphSpec:
    """Normalised, framework-agnostic view of a workflow graph."""
    nodes: tuple[str, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()
    interrupt_nodes: tuple[str, ...] = ()
    has_checkpointer: bool = False
    has_end_edge: bool = False
    tool_nodes: tuple[str, ...] = ()
    declared_capabilities: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_mapping(cls, d: dict[str, Any]) -> "GraphSpec":
        nodes = tuple(str(n) for n in d.get("nodes", []))
        edges = tuple((str(a), str(b)) for a, b in d.get("edges", []))
        tool_nodes = tuple(str(n) for n in d.get("tool_nodes",
                                                 [n for n in nodes if "tool" in n.lower()]))
        has_end = bool(d.get("has_end_edge",
                             any(t.lower() in _END_TOKENS for _, t in edges)))
        return cls(
            nodes=nodes,
            edges=edges,
            interrupt_nodes=tuple(str(n) for n in d.get("interrupt_nodes", [])),
            has_checkpointer=bool(d.get("has_checkpointer", False)),
            has_end_edge=has_end,
            tool_nodes=tool_nodes,
            declared_capabilities=frozenset(str(c) for c in d.get("declared_capabilities", [])),
        )

    @classmethod
    def from_langgraph(cls, compiled: Any) -> "GraphSpec":
        """Duck-type a compiled LangGraph ``StateGraph`` (langgraph is not imported)."""
        nodes: list[str] = []
        edges: list[tuple[str, str]] = []

        get_graph = getattr(compiled, "get_graph", None)
        if callable(get_graph):
            g = get_graph()
            raw_nodes = getattr(g, "nodes", {}) or {}
            nodes = [str(n) for n in (raw_nodes.keys() if isinstance(raw_nodes, dict) else raw_nodes)]
            for e in (getattr(g, "edges", []) or []):
                src = getattr(e, "source", None)
                tgt = getattr(e, "target", None)
                if src is None and isinstance(e, (tuple, list)) and len(e) >= 2:
                    src, tgt = e[0], e[1]
                if src is not None and tgt is not None:
                    edges.append((str(src), str(tgt)))
        else:
            raw_nodes = getattr(compiled, "nodes", {}) or {}
            nodes = [str(n) for n in (raw_nodes.keys() if isinstance(raw_nodes, dict) else raw_nodes)]

        interrupts = (list(getattr(compiled, "interrupt_before", None) or [])
                      + list(getattr(compiled, "interrupt_after", None) or []))
        interrupts = [str(n) for n in interrupts if str(n) != "*"]

        has_end = any(t.lower() in _END_TOKENS for _, t in edges)
        tool_nodes = tuple(n for n in nodes if "tool" in n.lower())
        declared = frozenset(str(c) for c in (getattr(compiled, "nail_capabilities", None) or []))

        return cls(
            nodes=tuple(nodes),
            edges=tuple(edges),
            interrupt_nodes=tuple(interrupts),
            has_checkpointer=getattr(compiled, "checkpointer", None) is not None,
            has_end_edge=has_end,
            tool_nodes=tool_nodes,
            declared_capabilities=declared,
        )


def derive_capabilities(spec: GraphSpec) -> dict[str, str]:
    """Infer compliance capabilities from a graph, mapped to *why* they were inferred."""
    caps: dict[str, str] = {}

    def add(cap: str, reason: str) -> None:
        caps.setdefault(cap, reason)

    if spec.interrupt_nodes:
        add("human_oversight", f"HITL interrupt(s): {', '.join(spec.interrupt_nodes)}")
    if spec.has_checkpointer:
        add("operational_logging", "checkpointer persists graph state")

    lowered = [(n, n.lower()) for n in spec.nodes]
    for cap, keywords in _NODE_KEYWORD_CAPS.items():
        for name, low in lowered:
            if any(k in low for k in keywords):
                add(cap, f"node '{name}'")
                break

    for cap in sorted(spec.declared_capabilities):
        add(cap, "declared by author")
    return caps


def profile_from_graph(spec: GraphSpec, *, name: str, party: Party, risk_tier: RiskTier,
                       jurisdictions: Iterable[Jurisdiction] = (Jurisdiction.EU,)) -> WorkflowProfile:
    caps = frozenset(derive_capabilities(spec))
    return WorkflowProfile(name=name, party=party, risk_tier=risk_tier,
                           capabilities=caps, jurisdictions=tuple(jurisdictions))


def analyze(graph: Any, *, name: str, party: Party, risk_tier: RiskTier,
            jurisdictions: Iterable[Jurisdiction] = (Jurisdiction.EU,),
            registry: ComplianceRegistry | None = None) -> GapReport:
    """Ingest a graph (compiled LangGraph, mapping, or GraphSpec) and return its gap report."""
    if isinstance(graph, GraphSpec):
        spec = graph
    elif isinstance(graph, dict):
        spec = GraphSpec.from_mapping(graph)
    else:
        spec = GraphSpec.from_langgraph(graph)
    profile = profile_from_graph(spec, name=name, party=party, risk_tier=risk_tier,
                                 jurisdictions=jurisdictions)
    return evaluate(profile, registry)
