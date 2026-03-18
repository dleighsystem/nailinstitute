"""
RMAP Phase 1 — Metamorphic Graph Engine
==========================================
Dynamic agent topologies that reshape at runtime.

Instead of hardcoded graphs (A → B → C), the Metamorphic Graph gives
agents structural tools to create, connect, fork, merge, and destroy
agent nodes at runtime. The graph reshapes itself based on the problem.

Structural tools exposed to the orchestrator:
  create_agent(name, role, prompt)   — spawn a new agent node
  kill_agent(name)                   — remove agent entirely
  connect(src, dst)                  — create directed edge
  disconnect(src, dst)               — remove edge
  fork_subgraph(agents, task)        — clone subset into isolated mini-graph
  collapse_subgraph(subgraph_id)     — destroy mini-graph, return summary
  broadcast(message, targets)        — message multiple agents simultaneously
  inspect_graph()                    — see current topology

Every structural mutation is recorded as a timestamped event so the
full topology evolution can be reconstructed post-hoc.

Based on: NAIL Experiment 22 — Metamorphic Architectures
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


# ── Graph Mutation Events ──────────────────────────────────────────────

class MutationType(str, Enum):
    """Types of structural graph mutation."""
    CREATE_AGENT = "create_agent"
    KILL_AGENT = "kill_agent"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    FORK_SUBGRAPH = "fork_subgraph"
    COLLAPSE_SUBGRAPH = "collapse_subgraph"
    BROADCAST = "broadcast"
    MESSAGE = "message"


@dataclass
class GraphMutation:
    """Record of a single structural mutation."""
    mutation_type: MutationType
    timestamp: float = field(default_factory=time.time)
    details: dict = field(default_factory=dict)
    success: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.mutation_type.value,
            "timestamp": self.timestamp,
            "details": self.details,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class SubGraph:
    """An isolated fork of agents working on a sub-task."""
    subgraph_id: str
    agents: list[str]          # Names of agents in this fork
    edges: list[tuple]         # (src, dst) edges
    task: str                  # The task this subgraph is solving
    created_at: float = field(default_factory=time.time)
    results: list[dict] = field(default_factory=list)
    collapsed: bool = False
    summary: str = ""


@dataclass
class AgentNode:
    """
    A node in the metamorphic graph.

    This is a framework-agnostic container. The actual LLM call
    is delegated to the `invoke` callable, which you wire to your
    own inference backend (Ollama, OpenAI, Anthropic, LangChain, etc.).

    Args:
        name: Unique identifier for this agent.
        role: Human-readable role description.
        system_prompt: The agent's system-level instructions.
        invoke: Callable[[str], str] — takes a user message, returns response.
                Defaults to a no-op echo if not provided.
        metadata: Arbitrary key-value metadata for the node.
    """
    name: str
    role: str
    system_prompt: str
    invoke: Callable[[str], str] = field(default=lambda msg: f"[{msg}]", repr=False)
    metadata: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    total_tokens: int = 0

    def respond(self, message: str, source: str = "system") -> str:
        """Send a message to this agent and record the exchange."""
        prompt = f"[From {source}]: {message}" if source != "system" else message
        self.history.append({"role": "user", "content": prompt})
        response = self.invoke(prompt)
        self.history.append({"role": "assistant", "content": response})
        return response

    def reset_history(self):
        """Clear conversation history."""
        self.history.clear()


class MetamorphicGraph:
    """
    A dynamic agent topology that reshapes itself at runtime.

    The graph tracks:
      - Active agents (name → AgentNode)
      - Directed edges (src → [dst1, dst2, ...])
      - Isolated subgraphs (fork/collapse lifecycle)
      - Complete mutation history for post-hoc analysis

    Framework-agnostic: wire your own LLM backend via the
    `agent_factory` callback passed at construction time, or
    create agents with explicit `invoke` callables.

    Args:
        agent_factory: Optional callable (name, role, system_prompt) → AgentNode.
                       If provided, `create_agent()` uses this to build nodes.
                       If not, nodes get a default echo invoke.
    """

    def __init__(self, agent_factory: Optional[Callable] = None):
        self.agent_factory = agent_factory

        # Core graph state
        self.agents: dict[str, AgentNode] = {}
        self.edges: dict[str, list[str]] = {}       # adjacency list
        self.subgraphs: dict[str, SubGraph] = {}

        # Mutation history
        self.mutations: list[GraphMutation] = []

        # Metrics
        self.total_agents_created = 0
        self.total_agents_killed = 0
        self.total_forks = 0
        self.total_collapses = 0
        self.total_messages = 0
        self.peak_agent_count = 0

    # ── Structural Tools (callable by orchestrator / planner) ────────

    def create_agent(
        self,
        name: str,
        role: str,
        system_prompt: str,
        invoke: Optional[Callable[[str], str]] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Spawn a new agent node in the graph.

        Args:
            name: Unique agent identifier.
            role: Human-readable role.
            system_prompt: System-level instructions.
            invoke: LLM call function. If None, uses agent_factory or echo.
            metadata: Optional metadata dict.

        Returns:
            True if created, False if name already exists.
        """
        name = str(name)
        if name in self.agents:
            self._record(MutationType.CREATE_AGENT,
                         {"name": name, "role": role},
                         success=False, error=f"Agent '{name}' already exists")
            return False

        if self.agent_factory and invoke is None:
            node = self.agent_factory(name, role, system_prompt)
        else:
            node = AgentNode(
                name=name,
                role=role,
                system_prompt=system_prompt,
                invoke=invoke or (lambda msg: f"[echo:{name}] {msg}"),
                metadata=metadata or {},
            )

        self.agents[name] = node
        self.edges[name] = []
        self.total_agents_created += 1
        self.peak_agent_count = max(self.peak_agent_count, len(self.agents))

        self._record(MutationType.CREATE_AGENT,
                     {"name": name, "role": role,
                      "prompt_preview": system_prompt[:200]})
        return True

    def kill_agent(self, name: str) -> bool:
        """
        Remove an agent and all its edges from the graph.

        Returns True if removed, False if agent not found.
        """
        name = str(name)
        if name not in self.agents:
            self._record(MutationType.KILL_AGENT,
                         {"name": name},
                         success=False, error=f"Agent '{name}' not found")
            return False

        del self.agents[name]
        del self.edges[name]
        for src in list(self.edges.keys()):
            self.edges[src] = [d for d in self.edges[src] if d != name]

        self.total_agents_killed += 1
        self._record(MutationType.KILL_AGENT, {"name": name})
        return True

    def connect(self, src: str, dst: str) -> bool:
        """Create a directed edge from src to dst."""
        src, dst = str(src), str(dst)
        if src not in self.agents or dst not in self.agents:
            self._record(MutationType.CONNECT,
                         {"src": src, "dst": dst},
                         success=False, error="Agent not found")
            return False
        if dst not in self.edges[src]:
            self.edges[src].append(dst)
        self._record(MutationType.CONNECT, {"src": src, "dst": dst})
        return True

    def disconnect(self, src: str, dst: str) -> bool:
        """Remove directed edge from src to dst."""
        src, dst = str(src), str(dst)
        if src not in self.edges:
            self._record(MutationType.DISCONNECT,
                         {"src": src, "dst": dst},
                         success=False, error="Source not found")
            return False
        if dst in self.edges[src]:
            self.edges[src].remove(dst)
        self._record(MutationType.DISCONNECT, {"src": src, "dst": dst})
        return True

    def fork_subgraph(self, agent_names: list[str], task: str) -> Optional[str]:
        """
        Clone a subset of agents into an isolated mini-graph to work on
        a sub-task independently.

        Returns subgraph_id or None on failure.
        """
        missing = [n for n in agent_names if n not in self.agents]
        if missing:
            self._record(MutationType.FORK_SUBGRAPH,
                         {"agents": agent_names, "task": task},
                         success=False, error=f"Missing agents: {missing}")
            return None

        sg_id = f"sg_{uuid.uuid4().hex[:8]}"
        sg_agents = []
        sg_edges = []

        for name in agent_names:
            original = self.agents[name]
            clone_name = f"{name}@{sg_id}"
            self.create_agent(
                clone_name, original.role, original.system_prompt,
                invoke=original.invoke,
            )
            sg_agents.append(clone_name)

        # Linear chain within the subgraph
        for i in range(len(sg_agents) - 1):
            self.connect(sg_agents[i], sg_agents[i + 1])
            sg_edges.append((sg_agents[i], sg_agents[i + 1]))

        subgraph = SubGraph(
            subgraph_id=sg_id,
            agents=sg_agents,
            edges=sg_edges,
            task=task,
        )
        self.subgraphs[sg_id] = subgraph
        self.total_forks += 1

        self._record(MutationType.FORK_SUBGRAPH,
                     {"subgraph_id": sg_id, "agents": sg_agents,
                      "task": task[:200]})
        return sg_id

    def collapse_subgraph(self, subgraph_id: str) -> Optional[str]:
        """
        Destroy a subgraph: kill all its agents, remove edges, return
        the summary of what the subgraph produced.
        """
        if subgraph_id not in self.subgraphs:
            self._record(MutationType.COLLAPSE_SUBGRAPH,
                         {"subgraph_id": subgraph_id},
                         success=False, error="Subgraph not found")
            return None

        sg = self.subgraphs[subgraph_id]
        if sg.collapsed:
            return sg.summary

        for agent_name in list(sg.agents):
            self.kill_agent(agent_name)

        sg.collapsed = True
        self.total_collapses += 1

        self._record(MutationType.COLLAPSE_SUBGRAPH,
                     {"subgraph_id": subgraph_id,
                      "agents_killed": sg.agents,
                      "summary_preview": sg.summary[:200]})
        return sg.summary

    def send_message(self, src: str, dst: str, message: str) -> Optional[str]:
        """
        Send a message from one agent to another.
        Returns the destination agent's response, or None on failure.
        """
        src, dst, message = str(src), str(dst), str(message)
        if dst not in self.agents:
            self._record(MutationType.MESSAGE,
                         {"src": src, "dst": dst},
                         success=False, error=f"Destination '{dst}' not found")
            return None

        agent = self.agents[dst]
        response = agent.respond(message, source=src)
        self.total_messages += 1

        self._record(MutationType.MESSAGE,
                     {"src": src, "dst": dst,
                      "message_preview": message[:200],
                      "response_preview": response[:200]})
        return response

    def broadcast(self, message: str, targets: Optional[list[str]] = None,
                  source: str = "system") -> dict[str, str]:
        """
        Send the same message to multiple agents.

        Args:
            message: The message to broadcast.
            targets: List of agent names. If None, broadcasts to all.
            source: Name of the sending entity.

        Returns dict of {agent_name: response}.
        """
        if targets is None:
            targets = list(self.agents.keys())
        results = {}
        for target in targets:
            resp = self.send_message(source, target, message)
            if resp is not None:
                results[target] = resp
        self._record(MutationType.BROADCAST,
                     {"source": source, "targets": targets,
                      "message_preview": message[:200]})
        return results

    # ── Introspection ──────────────────────────────────────────────────

    def inspect_graph(self) -> str:
        """Return a human-readable description of the current topology."""
        lines = [f"Active agents ({len(self.agents)}):"]
        for name, agent in self.agents.items():
            downstream = self.edges.get(name, [])
            arrow = f" → {downstream}" if downstream else ""
            lines.append(f"  [{name}] role={agent.role}{arrow}")

        active_sgs = [s for s in self.subgraphs.values() if not s.collapsed]
        if active_sgs:
            lines.append(f"\nActive subgraphs ({len(active_sgs)}):")
            for sg in active_sgs:
                lines.append(
                    f"  [{sg.subgraph_id}] agents={sg.agents}, "
                    f"task={sg.task[:80]}"
                )
        return "\n".join(lines)

    def get_downstream(self, name: str) -> list[str]:
        """Get agents that `name` can send messages to."""
        return list(self.edges.get(name, []))

    def get_upstream(self, name: str) -> list[str]:
        """Get agents that can send messages to `name`."""
        return [src for src, dsts in self.edges.items() if name in dsts]

    def get_topology_snapshot(self) -> dict:
        """Return a serializable snapshot of the current graph topology."""
        return {
            "agents": {n: {"role": a.role} for n, a in self.agents.items()},
            "edges": {k: list(v) for k, v in self.edges.items()},
            "subgraphs": {
                sid: {
                    "agents": sg.agents,
                    "task": sg.task,
                    "collapsed": sg.collapsed,
                }
                for sid, sg in self.subgraphs.items()
            },
        }

    # ── Metrics ──────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        """Return graph-level metrics for experiment analysis."""
        return {
            "total_agents_created": self.total_agents_created,
            "total_agents_killed": self.total_agents_killed,
            "current_agent_count": len(self.agents),
            "peak_agent_count": self.peak_agent_count,
            "total_edges": sum(len(v) for v in self.edges.values()),
            "total_forks": self.total_forks,
            "total_collapses": self.total_collapses,
            "total_messages": self.total_messages,
            "active_subgraphs": sum(
                1 for s in self.subgraphs.values() if not s.collapsed
            ),
            "mutation_count": len(self.mutations),
            "mutation_types": self._mutation_type_counts(),
        }

    def reset(self):
        """Reset the entire graph to empty state."""
        self.agents.clear()
        self.edges.clear()
        self.subgraphs.clear()
        self.mutations.clear()
        self.total_agents_created = 0
        self.total_agents_killed = 0
        self.total_forks = 0
        self.total_collapses = 0
        self.total_messages = 0
        self.peak_agent_count = 0

    # ── Internal helpers ─────────────────────────────────────────────

    def _record(self, mutation_type: MutationType, details: dict,
                success: bool = True, error: str = ""):
        """Record a graph mutation event."""
        self.mutations.append(GraphMutation(
            mutation_type=mutation_type,
            details=details,
            success=success,
            error=error,
        ))

    def _mutation_type_counts(self) -> dict:
        """Count mutations by type."""
        counts: dict[str, int] = {}
        for m in self.mutations:
            key = m.mutation_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts
