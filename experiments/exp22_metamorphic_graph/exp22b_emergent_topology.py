"""
NAIL Institute — Experiment 22b: Emergent Topology Under Stress
================================================================

GOAL: Test whether the metamorphic graph develops different topologies
      for fundamentally different problem structures, and whether the
      Planner's topological choices correlate with output quality.

SETUP:
  The Planner is given tasks that have known "optimal" structures:
    - SERIAL DEPENDENCY: Steps must happen in order (topology should be linear)
    - PARALLEL INDEPENDENCE: Sub-tasks are independent (topology should be hub-spoke)
    - ADVERSARIAL: Requires debate/criticism (topology should include loops)
    - HIERARCHICAL: Multiple levels of synthesis (topology should be tree)
    - CHAOTIC: Contradictory requirements (topology is unpredictable)

  We measure whether the Planner discovers the right topology for each
  problem type WITHOUT being told what topology to use.

METRICS:
  - Topological appropriateness (does the graph match the problem structure?)
  - Graph density (edges / max_possible_edges)
  - Mutation rate per step
  - Agent lifetime (how long before kill?)
  - Output quality (LLM-as-judge)
  - Token efficiency vs. static baseline

USAGE:
  python -m exp22_metamorphic_graph.exp22b_emergent_topology
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import FAST_MODEL, DATA_DIR
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

from exp22_metamorphic_graph.graph_engine import MetamorphicGraph, MutationType
from exp22_metamorphic_graph.exp22a_static_vs_meta import (
    parse_tool_calls, execute_tool, judge_output, PLANNER_PROMPT,
)


# ─── Task Types with Expected Optimal Topologies ─────────────────────────

TOPOLOGY_TASKS = [
    {
        "id": "SERIAL",
        "optimal_topology": "linear",
        "description": "Sequential dependency — each step requires the previous step's output",
        "prompt": (
            "Write a technical specification for a REST API. The steps MUST happen "
            "in this exact order because each depends on the previous: "
            "(1) Define the data model schema, (2) Design the API endpoints based "
            "on the schema, (3) Write request/response examples using the endpoints, "
            "(4) Create an error handling specification referencing the examples, "
            "(5) Produce a security review of the complete specification. "
            "Each step MUST reference specific outputs from the previous step."
        ),
        "domains": ["architecture", "design"],
    },
    {
        "id": "PARALLEL",
        "optimal_topology": "hub-spoke",
        "description": "Independent sub-tasks that can be done simultaneously",
        "prompt": (
            "A company is expanding into 4 completely independent markets. "
            "Produce separate, self-contained market analyses for: "
            "(1) Electric vehicle charging in Norway, "
            "(2) Vertical farming in Singapore, "
            "(3) Telemedicine in rural India, "
            "(4) Desalination technology in Saudi Arabia. "
            "Each analysis is INDEPENDENT — they share no data or dependencies. "
            "After all 4 are complete, produce a brief portfolio summary."
        ),
        "domains": ["market_analysis"],
    },
    {
        "id": "ADVERSARIAL",
        "optimal_topology": "cyclic/debate",
        "description": "Requires arguments and counter-arguments",
        "prompt": (
            "Hold a structured debate on whether AI models should be open-sourced. "
            "There must be: (1) a strong PRO argument with evidence, "
            "(2) a strong CON argument with evidence, (3) a rebuttal of PRO by CON, "
            "(4) a rebuttal of CON by PRO, (5) a neutral judge who evaluates "
            "both sides and declares a winner with reasoning. "
            "The debate must be genuine — each side must engage with the OTHER's "
            "specific arguments, not just repeat their own points."
        ),
        "domains": ["debate", "policy"],
    },
    {
        "id": "HIERARCHICAL",
        "optimal_topology": "tree",
        "description": "Multiple levels of aggregation",
        "prompt": (
            "Produce a comprehensive industry report on the Global AI Market. "
            "Structure: (1) Three sector analysts each analyse ONE sector "
            "(healthcare AI, financial AI, manufacturing AI) independently. "
            "(2) A regional analyst adds geographic overlays (US, EU, Asia). "
            "(3) A senior analyst synthesises the sector reports into a single "
            "executive summary with cross-sector themes. "
            "(4) A fact-checker reviews the executive summary for consistency. "
            "Each level MUST use the outputs from the level below."
        ),
        "domains": ["market_analysis", "synthesis"],
    },
    {
        "id": "CHAOTIC",
        "optimal_topology": "unpredictable",
        "description": "Contradictory requirements that force creative graph design",
        "prompt": (
            "A startup has contradictory goals: (1) Build the most innovative "
            "product possible — MAXIMIZE novelty and risk-taking. "
            "(2) Satisfy extremely conservative investors — MINIMIZE all risk. "
            "(3) Ship in 6 months — MINIMIZE development time. "
            "(4) Ensure 99.99% reliability — MAXIMIZE testing. "
            "Produce a unified strategy that somehow reconciles all four goals. "
            "The strategy MUST explicitly address how each trade-off is resolved."
        ),
        "domains": ["strategy", "contradictions"],
    },
]


# ─── Topology Analysis ───────────────────────────────────────────────────

def classify_topology(graph: MetamorphicGraph) -> dict:
    """Analyse the graph's actual topology structure."""
    n = len(graph.agents)
    edge_count = sum(len(v) for v in graph.edges.values())
    max_edges = n * (n - 1) if n > 1 else 1

    # Detect topology type
    in_degree = {name: 0 for name in graph.agents}
    out_degree = {name: 0 for name in graph.agents}
    for src, dsts in graph.edges.items():
        if src in out_degree:
            out_degree[src] = len(dsts)
        for dst in dsts:
            if dst in in_degree:
                in_degree[dst] = in_degree.get(dst, 0) + 1

    # Check for hub-spoke (one node with high degree)
    max_out = max(out_degree.values()) if out_degree else 0
    is_hub_spoke = max_out >= n - 1 and n > 2

    # Check for linear chain
    is_linear = (edge_count == n - 1 and
                 sum(1 for d in out_degree.values() if d > 1) == 0 and
                 n > 1)

    # Check for cycles
    has_cycle = _detect_cycle(graph.edges)

    # Check for tree (connected, no cycles, n-1 edges)
    is_tree = edge_count == n - 1 and not has_cycle and n > 2

    topology_type = "unknown"
    if is_linear:
        topology_type = "linear"
    elif is_hub_spoke:
        topology_type = "hub-spoke"
    elif has_cycle:
        topology_type = "cyclic"
    elif is_tree:
        topology_type = "tree"
    elif n <= 1:
        topology_type = "degenerate"
    elif edge_count == 0:
        topology_type = "disconnected"

    return {
        "topology_type": topology_type,
        "num_agents": n,
        "num_edges": edge_count,
        "density": round(edge_count / max_edges, 3) if max_edges > 0 else 0,
        "is_linear": is_linear,
        "is_hub_spoke": is_hub_spoke,
        "has_cycle": has_cycle,
        "is_tree": is_tree,
        "in_degrees": dict(in_degree),
        "out_degrees": dict(out_degree),
    }


def _detect_cycle(edges: dict) -> bool:
    """Detect if the directed graph has a cycle using DFS."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in edges}

    def dfs(node):
        color[node] = GRAY
        for nbr in edges.get(node, []):
            if nbr not in color:
                continue
            if color[nbr] == GRAY:
                return True
            if color[nbr] == WHITE and dfs(nbr):
                return True
        color[node] = BLACK
        return False

    for node in edges:
        if color.get(node) == WHITE:
            if dfs(node):
                return True
    return False


def score_topology_match(actual: str, expected: str) -> float:
    """
    Score how well the actual topology matches the expected optimal.
    Returns 0.0 (wrong) to 1.0 (perfect match).
    """
    if expected == "unpredictable":
        return 0.5  # Chaotic tasks have no "right" answer

    if actual == expected:
        return 1.0

    # Partial credit for related topologies
    partial_credit = {
        ("tree", "hub-spoke"): 0.6,
        ("hub-spoke", "tree"): 0.6,
        ("linear", "tree"): 0.4,
        ("cyclic", "hub-spoke"): 0.3,
    }
    return partial_credit.get((actual, expected), 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_exp22b():
    """Run Exp22b: Emergent Topology Under Stress."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — Exp 22b: Emergent Topology Under Stress")
    print("  Can the Planner discover the right topology for each problem?")
    print("=" * 70 + "\n")

    logger = ExperimentLogger(
        experiment_name="exp22b_emergent_topology",
        enable_system_monitor=True,
    )
    model = FAST_MODEL
    overall_start = time.time()
    trial_results = []

    for task in TOPOLOGY_TASKS:
        print(f"\n{'─' * 60}")
        print(f"  Task: {task['id']} — {task['description']}")
        print(f"  Expected optimal topology: {task['optimal_topology']}")
        print(f"{'─' * 60}")

        t0 = time.time()

        # Create the metamorphic graph
        graph = MetamorphicGraph(model=model, temperature=0.7)

        # Create the Planner
        planner_llm = OllamaLLM(
            model=model,
            system_prompt=PLANNER_PROMPT,
            temperature=0.7,
        )

        planner_history = [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": (
                f"TASK: {task['prompt']}\n\n"
                f"Design the optimal agent team and topology to solve this task. "
                f"Think carefully about which agents need to communicate with which "
                f"other agents. Issue one tool command at a time."
            )},
        ]

        final_output = ""
        topology_snapshots = []
        step = 0
        max_steps = 30

        while step < max_steps:
            step += 1

            resp = planner_llm.chat(planner_history, temperature=0.7)
            planner_response = resp.content
            planner_history.append({"role": "assistant", "content": planner_response})

            calls = parse_tool_calls(planner_response)
            if not calls:
                planner_history.append({
                    "role": "user",
                    "content": "Please issue your next tool command as JSON.",
                })
                continue

            results_text = []
            for call in calls:
                result = execute_tool(graph, call, logger)
                if result.startswith("__FINAL__:"):
                    final_output = result[len("__FINAL__:"):]
                    break
                results_text.append(result)

            if final_output:
                break

            combined = "\n".join(results_text)
            planner_history.append({
                "role": "user",
                "content": f"Tool results:\n{combined}\n\nWhat's your next step?",
            })

            # Snapshot every 5 steps
            if step % 5 == 0:
                topology_snapshots.append({
                    "step": step,
                    "topology": graph.get_topology_snapshot(),
                    "analysis": classify_topology(graph),
                })

        elapsed = time.time() - t0
        metrics = graph.get_metrics()
        total_tokens = (metrics["total_tokens"] +
                        planner_llm.total_prompt_tokens +
                        planner_llm.total_completion_tokens)

        # Analyse final topology
        topo_analysis = classify_topology(graph)
        topo_match = score_topology_match(
            topo_analysis["topology_type"],
            task["optimal_topology"],
        )

        # Final snapshot
        topology_snapshots.append({
            "step": step,
            "topology": graph.get_topology_snapshot(),
            "analysis": topo_analysis,
        })

        # Judge output quality
        scores = {}
        if final_output:
            scores = judge_output(task, final_output, model)

        result = {
            "task_id": task["id"],
            "expected_topology": task["optimal_topology"],
            "actual_topology": topo_analysis["topology_type"],
            "topology_match_score": topo_match,
            "topology_analysis": topo_analysis,
            "topology_evolution": topology_snapshots,
            "scores": scores,
            "total_tokens": total_tokens,
            "elapsed_s": round(elapsed, 1),
            "planner_steps": step,
            "graph_metrics": metrics,
            "final_output_preview": (final_output[:500] if final_output
                                     else "(no final answer produced)"),
        }
        trial_results.append(result)

        print(f"  Actual topology: {topo_analysis['topology_type']} "
              f"(match={topo_match:.1f})")
        print(f"  Agents: {metrics['total_agents_created']}, "
              f"Mutations: {metrics['mutation_count']}, "
              f"Tokens: {total_tokens:,}")
        print(f"  Quality: {scores.get('overall', '?')}")

    # ── Aggregate ─────────────────────────────────────────────────────
    elapsed = time.time() - overall_start
    matches = [r["topology_match_score"] for r in trial_results]
    avg_match = round(sum(matches) / len(matches), 3) if matches else 0

    results = {
        "experiment": "exp22b_emergent_topology",
        "model": model,
        "total_runtime_s": round(elapsed, 1),
        "num_tasks": len(TOPOLOGY_TASKS),
        "avg_topology_match": avg_match,
        "topology_results": {
            r["task_id"]: {
                "expected": r["expected_topology"],
                "actual": r["actual_topology"],
                "match": r["topology_match_score"],
            }
            for r in trial_results
        },
        "trials": trial_results,
    }

    out_path = DATA_DIR / "exp22b_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✅ Results saved to {out_path}")

    logger.summary_table({
        "Topology Match Rate": f"{avg_match:.1%}",
        **{r["task_id"]: f"{r['expected_topology']} → {r['actual_topology']} ({r['topology_match_score']:.1f})"
           for r in trial_results},
        "Total Runtime": f"{elapsed:.0f}s",
    })
    logger.finalize()
    return results


if __name__ == "__main__":
    run_exp22b()
