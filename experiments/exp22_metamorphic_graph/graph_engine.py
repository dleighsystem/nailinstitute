"""
NAIL Institute — Metamorphic Graph Engine
============================================
Phase 1 of the Build-Solution Manifesto: Break the Graph

Instead of hardcoded agent topologies (A → B → C), the Metamorphic Graph
gives a "Planner Agent" structural tools to dynamically create, connect,
fork, merge, and destroy agent nodes at runtime.  The graph reshapes itself
based on the problem encountered.

Structural tools exposed to the Planner:
  create_agent(name, role, prompt)   — spawn a new agent node
  connect(src, dst)                  — create directed edge
  disconnect(src, dst)               — remove edge
  fork_subgraph(agents, task)        — clone subset into an isolated mini-graph
  collapse_subgraph(subgraph_id)     — destroy mini-graph, return summary
  kill_agent(name)                   — remove agent entirely
  broadcast(message, targets)        — message multiple agents simultaneously
  inspect_graph()                    — Planner can see current topology

The engine records every structural mutation as a timestamped event so we
can reconstruct the full topology evolution post-hoc.
"""

import json
import time
import uuid
import copy
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.agent_base import Agent
from shared.ollama_llm import OllamaLLM
from shared.config import FAST_MODEL


# ── Graph Mutation Events ──────────────────────────────────────────────

class MutationType(str, Enum):
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


class MetamorphicGraph:
    """
    A dynamic agent topology that can be reshaped at runtime.

    The graph tracks:
      - Active agents (name → Agent instance)
      - Directed edges (src → [dst1, dst2, ...])
      - Isolated subgraphs (fork/collapse lifecycle)
      - Complete mutation history for post-hoc analysis
    """

    def __init__(self, model: str = FAST_MODEL, temperature: float = 0.7):
        self.model = model
        self.temperature = temperature

        # Core graph state
        self.agents: dict[str, Agent] = {}
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
        self.total_tokens = 0
        self.peak_agent_count = 0

    # ── Structural Tools (callable by the Planner) ────────────────────

    def create_agent(self, name: str, role: str, system_prompt: str) -> bool:
        """Spawn a new agent node in the graph."""
        name, role, system_prompt = str(name), str(role), str(system_prompt)
        if name in self.agents:
            self._record(MutationType.CREATE_AGENT,
                         {"name": name, "role": role},
                         success=False, error=f"Agent '{name}' already exists")
            return False

        agent = Agent(
            name=name,
            role=role,
            system_prompt=system_prompt,
            model=self.model,
            temperature=self.temperature,
        )
        self.agents[name] = agent
        self.edges[name] = []
        self.total_agents_created += 1
        self.peak_agent_count = max(self.peak_agent_count, len(self.agents))

        self._record(MutationType.CREATE_AGENT,
                     {"name": name, "role": role,
                      "prompt_preview": system_prompt[:200]})
        return True

    def kill_agent(self, name: str) -> bool:
        """Remove an agent and all its edges from the graph."""
        name = str(name)
        if name not in self.agents:
            self._record(MutationType.KILL_AGENT,
                         {"name": name},
                         success=False, error=f"Agent '{name}' not found")
            return False

        # Remove all edges involving this agent
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
        a sub-task independently.  Returns subgraph_id or None.
        """
        missing = [n for n in agent_names if n not in self.agents]
        if missing:
            self._record(MutationType.FORK_SUBGRAPH,
                         {"agents": agent_names, "task": task},
                         success=False, error=f"Missing agents: {missing}")
            return None

        sg_id = f"sg_{uuid.uuid4().hex[:8]}"

        # Create fresh clones in the subgraph (separate context)
        sg_agents = []
        sg_edges = []
        for name in agent_names:
            original = self.agents[name]
            clone_name = f"{name}@{sg_id}"
            self.create_agent(clone_name, original.role, original.system_prompt)
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

        # Kill all agents in the subgraph
        for agent_name in sg.agents:
            self.kill_agent(agent_name)

        sg.collapsed = True
        self.total_collapses += 1

        self._record(MutationType.COLLAPSE_SUBGRAPH,
                     {"subgraph_id": subgraph_id,
                      "agents_killed": sg.agents,
                      "summary_preview": sg.summary[:200]})
        return sg.summary

    def send_message(self, src: str, dst: str, message: str,
                     json_mode: bool = False) -> Optional[str]:
        """
        Send a message from one agent to another.
        Returns the destination agent's response.
        """
        src, dst, message = str(src), str(dst), str(message)
        if dst not in self.agents:
            self._record(MutationType.MESSAGE,
                         {"src": src, "dst": dst},
                         success=False, error=f"Destination '{dst}' not found")
            return None

        agent = self.agents[dst]
        prompt = f"[Message from {src}]: {message}"
        response = agent.respond(prompt, json_mode=json_mode)
        self.total_messages += 1
        self.total_tokens += agent.llm.total_prompt_tokens + agent.llm.total_completion_tokens

        self._record(MutationType.MESSAGE,
                     {"src": src, "dst": dst,
                      "message_preview": message[:200],
                      "response_preview": response[:200]})
        return response

    def broadcast(self, message: str, targets: list[str],
                  source: str = "system") -> dict[str, str]:
        """Send the same message to multiple agents. Returns {name: response}."""
        results = {}
        for target in targets:
            resp = self.send_message(source, target, message)
            if resp is not None:
                results[target] = resp
        self._record(MutationType.BROADCAST,
                     {"source": source, "targets": targets,
                      "message_preview": message[:200]})
        return results

    # ── Introspection (Planner can see graph state) ──────────────────

    def inspect_graph(self) -> str:
        """Return a human-readable description of the current topology."""
        lines = [f"Active agents ({len(self.agents)}):"]
        for name, agent in self.agents.items():
            downstream = self.edges.get(name, [])
            arrow = f" → {downstream}" if downstream else ""
            lines.append(f"  [{name}] role={agent.role}{arrow}")

        if self.subgraphs:
            active_sgs = [s for s in self.subgraphs.values() if not s.collapsed]
            if active_sgs:
                lines.append(f"\nActive subgraphs ({len(active_sgs)}):")
                for sg in active_sgs:
                    lines.append(f"  [{sg.subgraph_id}] agents={sg.agents}, "
                                 f"task={sg.task[:80]}")
        return "\n".join(lines)

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
            "total_tokens": self.total_tokens,
            "active_subgraphs": sum(
                1 for s in self.subgraphs.values() if not s.collapsed
            ),
            "mutation_count": len(self.mutations),
            "mutation_types": self._mutation_type_counts(),
        }

    def get_topology_snapshot(self) -> dict:
        """Return a serializable snapshot of the current graph topology."""
        return {
            "agents": {n: {"role": a.role} for n, a in self.agents.items()},
            "edges": dict(self.edges),
            "subgraphs": {
                sid: {
                    "agents": sg.agents,
                    "task": sg.task,
                    "collapsed": sg.collapsed,
                }
                for sid, sg in self.subgraphs.items()
            },
        }

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
        counts = {}
        for m in self.mutations:
            key = m.mutation_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts
