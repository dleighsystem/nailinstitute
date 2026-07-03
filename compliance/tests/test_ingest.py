"""Tests for the LangGraph workflow ingester (duck-typed; langgraph not required)."""

from compliance import (
    GraphSpec,
    Jurisdiction,
    Party,
    RiskTier,
    Status,
    analyze,
    derive_capabilities,
    profile_from_graph,
)


# ── A fake compiled LangGraph (duck-typed — no langgraph dependency) ──
class _Edge:
    def __init__(self, source, target):
        self.source, self.target = source, target


class _Graph:
    def __init__(self, nodes, edges):
        self.nodes = {n: None for n in nodes}
        self.edges = [_Edge(a, b) for a, b in edges]


class _Compiled:
    def __init__(self, nodes, edges, *, interrupt_before=None,
                 checkpointer=None, nail_capabilities=None):
        self._g = _Graph(nodes, edges)
        self.interrupt_before = interrupt_before or []
        self.checkpointer = checkpointer
        self.nail_capabilities = nail_capabilities or []

    def get_graph(self):
        return self._g


# ── Structural signals ────────────────────────────────────────────
def test_interrupt_implies_human_oversight():
    spec = GraphSpec.from_mapping({"nodes": ["plan", "act"], "interrupt_nodes": ["act"]})
    caps = derive_capabilities(spec)
    assert "human_oversight" in caps
    assert "act" in caps["human_oversight"]


def test_checkpointer_implies_operational_logging():
    spec = GraphSpec.from_mapping({"nodes": ["a"], "has_checkpointer": True})
    assert "operational_logging" in derive_capabilities(spec)


def test_node_name_heuristics():
    spec = GraphSpec.from_mapping({"nodes": [
        "redact_pii", "disclose_ai", "monitor_metrics", "escalate_to_human", "audit_log"]})
    caps = derive_capabilities(spec)
    assert "pii_handling" in caps
    assert "ai_disclosure" in caps
    assert "post_market_monitoring" in caps
    assert "kill_switch" in caps
    assert "immutable_audit_log" in caps


def test_declared_capabilities_are_taken_as_asserted():
    spec = GraphSpec.from_mapping({"nodes": ["a"], "declared_capabilities": ["technical_documentation"]})
    caps = derive_capabilities(spec)
    assert caps["technical_documentation"] == "declared by author"


# ── Duck-typed compiled-graph extraction ──────────────────────────
def test_from_langgraph_duck_types_a_compiled_graph():
    compiled = _Compiled(
        nodes=["retrieve", "human_review", "tools", "END"],
        edges=[("retrieve", "human_review"), ("human_review", "END")],
        interrupt_before=["human_review"],
        checkpointer=object(),
        nail_capabilities=["technical_documentation"],
    )
    spec = GraphSpec.from_langgraph(compiled)
    assert "human_review" in spec.nodes
    assert spec.interrupt_nodes == ("human_review",)
    assert spec.has_checkpointer is True
    assert spec.has_end_edge is True
    assert spec.tool_nodes == ("tools",)
    assert "technical_documentation" in spec.declared_capabilities


# ── End to end: ingest -> profile -> gap report ────────────────────
def test_analyze_maps_graph_to_gap_report():
    compiled = _Compiled(
        nodes=["retrieve", "human_review", "monitor", "log"],
        edges=[("retrieve", "human_review"), ("human_review", "monitor")],
        interrupt_before=["human_review"],
        checkpointer=object(),
    )
    report = analyze(compiled, name="refund-agent", party=Party.DEPLOYER, risk_tier=RiskTier.HIGH)

    art26 = next(f for f in report.findings if f.control.control_id == "EU-AIA-ART26")
    # human_oversight (interrupt), operational_logging (checkpointer/log),
    # post_market_monitoring (monitor node) => Art.26 fully satisfied
    assert art26.status == Status.SATISFIED


def test_analyze_flags_gaps_for_bare_graph():
    report = analyze({"nodes": ["plan", "act"]},
                     name="bare", party=Party.DEPLOYER, risk_tier=RiskTier.HIGH)
    assert not report.compliant
    art14 = next(f for f in report.findings if f.control.control_id == "EU-AIA-ART14")
    assert art14.status == Status.GAP
    assert "human_oversight" in art14.missing_capabilities


def test_profile_from_graph_returns_capabilities():
    spec = GraphSpec.from_mapping({"nodes": ["monitor"], "interrupt_nodes": ["x"]})
    profile = profile_from_graph(spec, name="w", party=Party.DEPLOYER, risk_tier=RiskTier.HIGH,
                                 jurisdictions=[Jurisdiction.EU])
    assert "human_oversight" in profile.capabilities
    assert "post_market_monitoring" in profile.capabilities
