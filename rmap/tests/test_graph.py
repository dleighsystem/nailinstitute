"""Tests for rmap.graph — Phase 1: Metamorphic Graph Engine."""

import pytest
from rmap.graph import (
    AgentNode, MetamorphicGraph, MutationType, GraphMutation, SubGraph,
)


# ── AgentNode ──────────────────────────────────────────────────────────────

class TestAgentNode:
    def test_default_invoke(self):
        node = AgentNode(name="a1", role="test", system_prompt="be helpful")
        result = node.respond("hello")
        assert "hello" in result  # default echo wraps the message

    def test_custom_invoke(self):
        node = AgentNode(
            name="a1", role="reverser", system_prompt="",
            invoke=lambda s: s[::-1],
        )
        result = node.respond("abc")
        assert isinstance(result, str)

    def test_history_tracking(self):
        node = AgentNode(name="a1", role="test", system_prompt="")
        node.respond("one")
        node.respond("two")
        # Each respond adds 2 entries (user + assistant)
        assert len(node.history) == 4

    def test_reset_history(self):
        node = AgentNode(name="a1", role="test", system_prompt="")
        node.respond("one")
        node.respond("two")
        node.reset_history()
        assert len(node.history) == 0


# ── MetamorphicGraph ──────────────────────────────────────────────────────

class TestMetamorphicGraph:
    def test_create_and_kill_agent(self):
        g = MetamorphicGraph()
        result = g.create_agent("worker", role="calc", system_prompt="do math")
        assert result is True
        assert "worker" in g.agents

        kill_result = g.kill_agent("worker")
        assert kill_result is True
        assert "worker" not in g.agents

    def test_create_with_factory(self):
        def factory(name: str, role: str, system_prompt: str) -> AgentNode:
            return AgentNode(
                name=name, role=role, system_prompt=system_prompt,
                invoke=lambda s: f"[{role}] {s}",
            )

        g = MetamorphicGraph(agent_factory=factory)
        result = g.create_agent("bot", role="greeter", system_prompt="greet people")
        assert result is True
        node = g.agents["bot"]
        resp = node.respond("hi")
        assert "[greeter]" in resp

    def test_create_duplicate_returns_false(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        result = g.create_agent("a", "r2", "p2")
        assert result is False

    def test_connect_and_disconnect(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r1", "p1")
        g.create_agent("b", "r2", "p2")
        assert g.connect("a", "b") is True
        assert "b" in g.edges["a"]

        assert g.disconnect("a", "b") is True
        assert "b" not in g.edges["a"]

    def test_connect_is_directed(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r1", "p1")
        g.create_agent("b", "r2", "p2")
        g.connect("a", "b")
        assert "b" in g.edges["a"]
        assert "a" not in g.edges["b"]

    def test_send_message(self):
        replies = []

        def capture(s):
            replies.append(s)
            return f"re:{s}"

        g = MetamorphicGraph()
        g.create_agent("sender", "s", "sp")
        g.create_agent("receiver", "r", "rp", invoke=capture)

        result = g.send_message("sender", "receiver", "hello")
        assert result is not None
        assert result.startswith("re:")
        assert len(replies) == 1

    def test_send_message_nonexistent_returns_none(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        result = g.send_message("a", "nonexistent", "test")
        assert result is None

    def test_broadcast(self):
        g = MetamorphicGraph()
        g.create_agent("hub", "h", "p")
        g.create_agent("spoke1", "s", "p", invoke=lambda s: s.upper())
        g.create_agent("spoke2", "s", "p", invoke=lambda s: s.upper())

        results = g.broadcast("ping", targets=["spoke1", "spoke2"], source="hub")
        assert "spoke1" in results
        assert "spoke2" in results

    def test_broadcast_all(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p", invoke=lambda s: "ok")
        g.create_agent("b", "r", "p", invoke=lambda s: "ok")

        results = g.broadcast("hello")
        assert len(results) == 2

    def test_mutation_log(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        g.create_agent("b", "r", "p")
        g.connect("a", "b")
        g.kill_agent("b")

        assert len(g.mutations) == 4
        assert g.mutations[0].mutation_type == MutationType.CREATE_AGENT
        assert g.mutations[2].mutation_type == MutationType.CONNECT
        assert g.mutations[3].mutation_type == MutationType.KILL_AGENT

    def test_fork_and_collapse_subgraph(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p", invoke=lambda s: "A")
        g.create_agent("b", "r", "p", invoke=lambda s: "B")
        g.connect("a", "b")

        sg_id = g.fork_subgraph(["a", "b"], task="solve subtask")
        assert sg_id is not None
        assert sg_id in g.subgraphs

        summary = g.collapse_subgraph(sg_id)
        assert summary is not None
        sg = g.subgraphs[sg_id]
        assert sg.collapsed is True

    def test_fork_missing_agent_returns_none(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        result = g.fork_subgraph(["a", "ghost"], task="t")
        assert result is None

    def test_inspect_graph(self):
        g = MetamorphicGraph()
        g.create_agent("x", "analyst", "p")
        g.create_agent("y", "writer", "p")
        g.connect("x", "y")

        info = g.inspect_graph()
        assert isinstance(info, str)
        assert "x" in info
        assert "y" in info
        assert "analyst" in info

    def test_get_metrics(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        g.create_agent("b", "r", "p")
        g.connect("a", "b")

        m = g.get_metrics()
        assert m["total_agents_created"] == 2
        assert m["current_agent_count"] == 2
        assert m["total_edges"] == 1
        assert m["mutation_count"] >= 3

    def test_get_downstream_and_upstream(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        g.create_agent("b", "r", "p")
        g.connect("a", "b")

        assert g.get_downstream("a") == ["b"]
        assert g.get_upstream("b") == ["a"]

    def test_get_topology_snapshot(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        snap = g.get_topology_snapshot()
        assert "agents" in snap
        assert "a" in snap["agents"]


# ── Edge cases ────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_kill_nonexistent_returns_false(self):
        g = MetamorphicGraph()
        result = g.kill_agent("ghost")
        assert result is False

    def test_connect_nonexistent_returns_false(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        result = g.connect("a", "nope")
        assert result is False

    def test_reset(self):
        g = MetamorphicGraph()
        g.create_agent("a", "r", "p")
        g.create_agent("b", "r", "p")
        g.connect("a", "b")
        g.reset()
        assert len(g.agents) == 0
        assert len(g.edges) == 0
        assert len(g.mutations) == 0
