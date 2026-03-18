"""
NAIL Institute — Experiment 22a: Static vs. Metamorphic Resolution
===================================================================

GOAL: Prove that a metamorphic (self-reshaping) agent graph outperforms
      a hardcoded static graph on a multi-faceted analysis task.

SETUP:
  A "Chief Analyst" receives a complex research task with multiple
  sub-domains (finance, technology, regulation, geopolitics).

  Condition A — STATIC GRAPH:
    Fixed 4-agent linear pipeline: Researcher → Analyst → Critic → Synthesiser.
    All 4 agents always run regardless of the problem.

  Condition B — METAMORPHIC GRAPH:
    A Planner Agent assesses the task, then uses structural tools to:
    - Spawn only the specialist agents needed
    - Connect them in whatever topology it thinks is best
    - Fork subgraphs for parallel investigation
    - Collapse subgraphs and merge results
    - Kill unnecessary agents to save tokens

METRICS:
  - Output quality (LLM-as-judge, 1–10)
  - Total tokens consumed
  - Number of agents used (static always 4, metamorphic varies)
  - Task completion time (wall-clock)
  - Graph mutations (create, kill, fork, collapse counts)
  - Topological diversity (how different is each task's graph?)

USAGE:
  python -m exp22_metamorphic_graph.exp22a_static_vs_meta
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import PRIMARY_MODEL, FAST_MODEL, DATA_DIR
from shared.agent_base import Agent
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

from exp22_metamorphic_graph.graph_engine import MetamorphicGraph

NUM_TRIALS = int(os.getenv("NAIL_EXP22A_TRIALS", "5"))

# ─── Complex multi-domain research tasks ─────────────────────────────────

TASKS = [
    {
        "id": "T1",
        "title": "AI Chip Supply Chain Risk",
        "prompt": (
            "Analyse the risk exposure of a Fortune 500 company whose AI "
            "infrastructure depends on NVIDIA GPUs. Consider: (1) geopolitical "
            "risks (US–China export controls, TSMC dependency), (2) financial "
            "risks (capex cycles, GPU price volatility), (3) technical risks "
            "(AMD/Intel alternatives, custom silicon), (4) regulatory risks "
            "(EU AI Act compute reporting). Produce a unified risk assessment "
            "with specific mitigation recommendations."
        ),
        "domains": ["finance", "geopolitics", "technology", "regulation"],
    },
    {
        "id": "T2",
        "title": "Autonomous Vehicle Insurance",
        "prompt": (
            "A major insurer wants to create an autonomous vehicle insurance "
            "product. Analyse: (1) the liability framework (manufacturer vs. "
            "operator vs. software provider), (2) actuarial data availability "
            "and challenges, (3) regulatory landscape across US states, "
            "(4) competitive positioning against incumbents. Produce a "
            "go/no-go recommendation with supporting evidence."
        ),
        "domains": ["regulation", "finance", "technology"],
    },
    {
        "id": "T3",
        "title": "Pandemic Preparedness Technology",
        "prompt": (
            "A government health agency wants to invest in pandemic "
            "preparedness technology. Evaluate: (1) mRNA platform vs "
            "traditional vaccine approaches, (2) wastewater genomic "
            "surveillance systems, (3) AI-powered epidemiological modelling, "
            "(4) supply chain resilience for PPE and therapeutics. Recommend "
            "a technology portfolio with 5-year budget allocation."
        ),
        "domains": ["technology", "finance", "regulation", "science"],
    },
    {
        "id": "T4",
        "title": "Digital Currency Central Bank Strategy",
        "prompt": (
            "A central bank is considering a CBDC (Central Bank Digital "
            "Currency). Analyse: (1) technical architecture options (account-"
            "based vs token-based), (2) privacy and surveillance implications, "
            "(3) impact on commercial banking system, (4) geopolitical "
            "competitive landscape (China's e-CNY, EU digital euro). Recommend "
            "a phased implementation strategy."
        ),
        "domains": ["finance", "technology", "regulation", "geopolitics"],
    },
    {
        "id": "T5",
        "title": "Space Debris Mitigation",
        "prompt": (
            "A space industry consortium wants a strategy for orbital debris "
            "mitigation. Analyse: (1) current debris tracking capabilities "
            "and limitations, (2) active debris removal technologies, "
            "(3) regulatory framework (UN COPUOS, national space agencies), "
            "(4) economic model for debris removal services, (5) liability "
            "allocation for collision damage. Produce a 10-year roadmap."
        ),
        "domains": ["technology", "regulation", "finance", "science"],
    },
]


# ─── Static Graph Agents ─────────────────────────────────────────────────

STATIC_RESEARCHER = """You are a Research Agent. Given a complex analysis task,
gather all relevant facts, data points, and context. Be thorough and comprehensive.
Cover all sub-domains mentioned in the task. Output your findings as structured text
with clear section headings."""

STATIC_ANALYST = """You are an Analyst Agent. You receive raw research and must
synthesise it into a coherent analysis. Identify patterns, contradictions, and gaps.
Quantify risks or opportunities where possible. Structure your output with:
- Key Findings (bullet points)
- Risk/Opportunity Matrix
- Gaps in Available Information"""

STATIC_CRITIC = """You are a Critical Review Agent. You receive an analysis and must:
1. Challenge assumptions — what evidence is missing?
2. Identify logical fallacies or unsupported claims
3. Play devil's advocate on each recommendation
4. Rate the analysis quality (1-10) with specific justification
Output structured criticism with specific, actionable improvements."""

STATIC_SYNTHESISER = """You are a Synthesis Agent. You receive research, analysis,
and critical review. Your job is to produce the final deliverable:
1. Executive summary (3 sentences)
2. Detailed findings with evidence ratings (strong/moderate/weak)
3. Specific, actionable recommendations ranked by priority
4. Key uncertainties and how to resolve them
Be concise but comprehensive. This is the final output the client receives."""


# ─── Planner Agent (Metamorphic Condition) ───────────────────────────────

PLANNER_PROMPT = """You are the PLANNER AGENT in a metamorphic multi-agent system.
You can dynamically create, connect, and destroy specialist agents to solve any task.

You have these structural tools (call them by outputting JSON commands):

1. create_agent: {"tool": "create_agent", "name": "agent_name", "role": "brief_role", "prompt": "full system prompt"}
2. connect: {"tool": "connect", "src": "agent_a", "dst": "agent_b"}
3. send_message: {"tool": "send_message", "src": "sender", "dst": "receiver", "message": "content"}
4. fork_subgraph: {"tool": "fork_subgraph", "agents": ["a", "b"], "task": "sub-task description"}
5. collapse_subgraph: {"tool": "collapse_subgraph", "subgraph_id": "sg_xxx"}
6. kill_agent: {"tool": "kill_agent", "name": "agent_name"}
7. broadcast: {"tool": "broadcast", "message": "content", "targets": ["agent1", "agent2"]}
8. inspect: {"tool": "inspect"}
9. final_answer: {"tool": "final_answer", "answer": "the complete final deliverable"}

RULES:
- First, THINK about what specialists are needed for THIS specific task
- Only create agents that are necessary — don't waste tokens on irrelevant experts
- Connect agents in whatever topology best fits the problem (linear, hub-spoke, parallel, etc.)
- You can fork subgraphs for parallel investigation
- When a sub-task is complete, collapse the subgraph to free resources
- Kill agents that have finished their work
- When all analysis is complete, use final_answer to deliver the result

Output ONE tool command per response as a JSON object on its own line.
After each command, you will see the result and can issue the next command.
You may output multiple commands separated by newlines if they are independent.

IMPORTANT: Be efficient. The goal is high-quality output with minimal token waste.
Think about the optimal team structure BEFORE creating agents."""


# ─── LLM-as-Judge ────────────────────────────────────────────────────────

JUDGE_PROMPT = """You are an expert evaluator. Rate the following analysis on these criteria:

1. COMPREHENSIVENESS (1-10): Does it cover all sub-domains requested?
2. DEPTH (1-10): Is the analysis deep and specific, or shallow and generic?
3. ACTIONABILITY (1-10): Are recommendations specific and implementable?
4. COHERENCE (1-10): Is the analysis logically structured and internally consistent?
5. EVIDENCE (1-10): Are claims supported with reasoning or data?

The task was: {task}

The analysis to evaluate:
---
{analysis}
---

Output JSON:
{{"comprehensiveness": X, "depth": X, "actionability": X, "coherence": X, "evidence": X, "overall": X, "justification": "brief explanation"}}"""


# ═══════════════════════════════════════════════════════════════════════════
# CONDITION A: STATIC PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def run_static_pipeline(task: dict, model: str, logger: ExperimentLogger) -> dict:
    """Run a fixed 4-agent linear pipeline on the task."""
    t0 = time.time()
    logger.log_event("info", message=f"Static pipeline: {task['id']} — {task['title']}")

    # Create fixed agents
    researcher = Agent("Researcher", "researcher", STATIC_RESEARCHER, model)
    analyst = Agent("Analyst", "analyst", STATIC_ANALYST, model)
    critic = Agent("Critic", "critic", STATIC_CRITIC, model)
    synthesiser = Agent("Synthesiser", "synthesiser", STATIC_SYNTHESISER, model)

    # Step 1: Research
    research_output = researcher.respond(
        f"Research task: {task['prompt']}\n\nProvide comprehensive research findings."
    )
    logger.log_event("info", agent="Researcher",
                     message=f"Research: {len(research_output)} chars")

    # Step 2: Analysis
    analysis_output = analyst.respond(
        f"Here is the raw research. Produce a structured analysis.\n\n"
        f"RESEARCH:\n{research_output}"
    )
    logger.log_event("info", agent="Analyst",
                     message=f"Analysis: {len(analysis_output)} chars")

    # Step 3: Critical review
    critic_output = critic.respond(
        f"Review this analysis critically.\n\nANALYSIS:\n{analysis_output}"
    )
    logger.log_event("info", agent="Critic",
                     message=f"Critique: {len(critic_output)} chars")

    # Step 4: Synthesis
    final_output = synthesiser.respond(
        f"Produce the final deliverable from these inputs.\n\n"
        f"RESEARCH:\n{research_output[:2000]}\n\n"
        f"ANALYSIS:\n{analysis_output}\n\n"
        f"CRITICAL REVIEW:\n{critic_output}"
    )
    logger.log_event("info", agent="Synthesiser",
                     message=f"Synthesis: {len(final_output)} chars")

    elapsed = time.time() - t0
    total_tokens = sum(a.total_tokens_used for a in
                       [researcher, analyst, critic, synthesiser])

    return {
        "task_id": task["id"],
        "task_title": task["title"],
        "condition": "static",
        "final_output": final_output,
        "total_tokens": total_tokens,
        "elapsed_s": round(elapsed, 1),
        "num_agents": 4,
        "num_messages": 4,
        "graph_mutations": 0,
        "topology": "linear: Researcher → Analyst → Critic → Synthesiser",
    }


# ═══════════════════════════════════════════════════════════════════════════
# CONDITION B: METAMORPHIC GRAPH (Planner-driven)
# ═══════════════════════════════════════════════════════════════════════════

def parse_tool_calls(response: str) -> list[dict]:
    """Extract JSON tool calls from Planner response."""
    calls = []
    # Try to find JSON objects in the response
    for line in response.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Try to parse as JSON
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "tool" in obj:
                calls.append(obj)
                continue
        except json.JSONDecodeError:
            pass

        # Try to find JSON embedded in text
        import re
        for match in re.finditer(r'\{[^{}]*"tool"\s*:\s*"[^"]+?"[^{}]*\}', line):
            try:
                obj = json.loads(match.group())
                if "tool" in obj:
                    calls.append(obj)
            except json.JSONDecodeError:
                continue

    return calls


def _str(val) -> str:
    """Coerce a value to str – LLMs sometimes return lists instead of strings."""
    if isinstance(val, list):
        return val[0] if val else ""
    return str(val) if val is not None else ""


def execute_tool(graph: MetamorphicGraph, call: dict,
                 logger: ExperimentLogger) -> str:
    """Execute a tool call against the metamorphic graph."""
    tool = _str(call.get("tool", ""))

    if tool == "create_agent":
        name = _str(call.get("name", f"agent_{len(graph.agents)}"))
        role = _str(call.get("role", "general"))
        prompt = _str(call.get("prompt", "You are a helpful assistant."))
        ok = graph.create_agent(name, role, prompt)
        result = f"✅ Agent '{name}' created" if ok else f"❌ Agent '{name}' already exists"
        logger.log_event("info", message=f"[TOOL] {result}")
        return result

    elif tool == "connect":
        src = _str(call.get("src", ""))
        dst = _str(call.get("dst", ""))
        ok = graph.connect(src, dst)
        result = f"✅ Connected {src} → {dst}" if ok else "❌ Connect failed"
        logger.log_event("info", message=f"[TOOL] {result}")
        return result

    elif tool == "send_message":
        src = _str(call.get("src", "Planner"))
        dst = _str(call.get("dst", ""))
        msg = _str(call.get("message", ""))
        resp = graph.send_message(src, dst, msg)
        if resp:
            logger.log_event("info", agent=dst,
                             message=f"Response ({len(resp)} chars)")
            return f"[{dst} responded]: {resp}"
        return f"❌ Could not send to '{dst}'"

    elif tool == "fork_subgraph":
        agents = call.get("agents", [])
        if isinstance(agents, str):
            agents = [agents]
        task = _str(call.get("task", ""))
        sg_id = graph.fork_subgraph(agents, task)
        result = f"✅ Forked subgraph {sg_id}" if sg_id else "❌ Fork failed"
        logger.log_event("info", message=f"[TOOL] {result}")
        return result

    elif tool == "collapse_subgraph":
        sg_id = _str(call.get("subgraph_id", ""))
        summary = graph.collapse_subgraph(sg_id)
        result = f"✅ Collapsed {sg_id}" if summary is not None else "❌ Collapse failed"
        logger.log_event("info", message=f"[TOOL] {result}")
        return result

    elif tool == "kill_agent":
        name = _str(call.get("name", ""))
        ok = graph.kill_agent(name)
        result = f"✅ Killed '{name}'" if ok else f"❌ Could not kill '{name}'"
        logger.log_event("info", message=f"[TOOL] {result}")
        return result

    elif tool == "broadcast":
        msg = _str(call.get("message", ""))
        targets = call.get("targets", [])
        if isinstance(targets, str):
            targets = [targets]
        results = graph.broadcast(msg, targets)
        logger.log_event("info",
                         message=f"[TOOL] Broadcast to {len(results)} agents")
        return "\n".join(f"[{k}]: {v[:300]}" for k, v in results.items())

    elif tool == "inspect":
        topology = graph.inspect_graph()
        return f"Current graph:\n{topology}"

    elif tool == "final_answer":
        return "__FINAL__:" + _str(call.get("answer", ""))

    else:
        return f"❌ Unknown tool '{tool}'"


def run_metamorphic(task: dict, model: str,
                    logger: ExperimentLogger,
                    max_planner_steps: int = 25) -> dict:
    """Run a Planner-driven metamorphic graph on the task."""
    t0 = time.time()
    logger.log_event("info",
                     message=f"Metamorphic: {task['id']} — {task['title']}")

    # Create the metamorphic graph
    graph = MetamorphicGraph(model=model, temperature=0.7)

    # Create the Planner (uses the PRIMARY model for reasoning)
    planner_llm = OllamaLLM(
        model=model,
        system_prompt=PLANNER_PROMPT,
        temperature=0.7,
    )

    # Initial prompt to the Planner
    planner_history = [
        {"role": "system", "content": PLANNER_PROMPT},
        {"role": "user", "content": (
            f"TASK: {task['prompt']}\n\n"
            f"Domains involved: {', '.join(task['domains'])}\n\n"
            f"Design the optimal agent team and topology to solve this task. "
            f"Create only the specialists you need, connect them appropriately, "
            f"and drive the analysis to completion. Issue one tool command at a time."
        )},
    ]

    final_output = ""
    topology_snapshots = []
    step = 0

    while step < max_planner_steps:
        step += 1

        # Get Planner's next action
        resp = planner_llm.chat(planner_history, temperature=0.7)
        planner_response = resp.content
        planner_history.append({"role": "assistant", "content": planner_response})

        # Parse tool calls
        calls = parse_tool_calls(planner_response)

        if not calls:
            # Planner didn't emit a valid tool call — nudge it
            planner_history.append({
                "role": "user",
                "content": (
                    "Please issue your next tool command as JSON. "
                    "Available: create_agent, connect, send_message, "
                    "fork_subgraph, collapse_subgraph, kill_agent, "
                    "broadcast, inspect, final_answer."
                ),
            })
            continue

        # Execute each tool call
        results_text = []
        for call in calls:
            result = execute_tool(graph, call, logger)
            if result.startswith("__FINAL__:"):
                final_output = result[len("__FINAL__:"):]
                break
            results_text.append(result)

        if final_output:
            break

        # Feed results back to the Planner
        combined = "\n".join(results_text)
        planner_history.append({
            "role": "user",
            "content": f"Tool results:\n{combined}\n\nWhat's your next step?",
        })

        # Snapshot topology periodically
        if step % 3 == 0:
            topology_snapshots.append({
                "step": step,
                "topology": graph.get_topology_snapshot(),
            })

    elapsed = time.time() - t0
    metrics = graph.get_metrics()
    total_tokens = metrics["total_tokens"] + planner_llm.total_prompt_tokens + planner_llm.total_completion_tokens

    # Final topology snapshot
    topology_snapshots.append({
        "step": step,
        "topology": graph.get_topology_snapshot(),
    })

    return {
        "task_id": task["id"],
        "task_title": task["title"],
        "condition": "metamorphic",
        "final_output": final_output,
        "total_tokens": total_tokens,
        "elapsed_s": round(elapsed, 1),
        "planner_steps": step,
        "num_agents": metrics["total_agents_created"],
        "peak_agents": metrics["peak_agent_count"],
        "agents_killed": metrics["total_agents_killed"],
        "num_messages": metrics["total_messages"],
        "graph_mutations": metrics["mutation_count"],
        "total_forks": metrics["total_forks"],
        "total_collapses": metrics["total_collapses"],
        "mutation_types": metrics["mutation_types"],
        "topology_evolution": topology_snapshots,
        "topology": graph.inspect_graph(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# JUDGE (evaluates both conditions' outputs)
# ═══════════════════════════════════════════════════════════════════════════

def judge_output(task: dict, analysis: str, model: str) -> dict:
    """LLM-as-judge evaluation of an analysis output."""
    judge_llm = OllamaLLM(model=model, temperature=0.1)
    prompt = JUDGE_PROMPT.format(task=task["prompt"], analysis=analysis)

    resp = judge_llm.chat([
        {"role": "system", "content": "You are an expert evaluator. Output valid JSON only."},
        {"role": "user", "content": prompt},
    ], json_mode=True)

    try:
        scores = json.loads(resp.content)
        return scores
    except json.JSONDecodeError:
        # Try to extract JSON from response
        match = re.search(r'\{[^{}]+\}', resp.content)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {"overall": 5.0, "parse_error": True, "raw": resp.content[:200]}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_exp22a():
    """Run all trials of Exp22a: Static vs. Metamorphic."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — Exp 22a: Static vs. Metamorphic Resolution")
    print("  Phase 1: Break the Graph (Metamorphic Architectures)")
    print("=" * 70 + "\n")

    logger = ExperimentLogger(
        experiment_name="exp22a_static_vs_meta",
        enable_system_monitor=True,
    )
    model = FAST_MODEL  # Use fast model for agents, primary for planner
    overall_start = time.time()

    static_results = []
    meta_results = []

    for trial_idx in range(NUM_TRIALS):
        task = TASKS[trial_idx % len(TASKS)]
        print(f"\n{'─' * 60}")
        print(f"  Trial {trial_idx + 1}/{NUM_TRIALS}: {task['id']} — {task['title']}")
        print(f"{'─' * 60}")

        # ── Condition A: Static ──────────────────────────
        logger.log_event("info",
                         message=f"Trial {trial_idx+1} Condition A (Static): {task['id']}")
        static = run_static_pipeline(task, model, logger)
        static["scores"] = judge_output(task, static["final_output"], model)
        static_results.append(static)

        print(f"  Static:  {static['total_tokens']:,} tokens, "
              f"{static['elapsed_s']}s, "
              f"quality={static['scores'].get('overall', '?')}")

        # ── Condition B: Metamorphic ─────────────────────
        logger.log_event("info",
                         message=f"Trial {trial_idx+1} Condition B (Metamorphic): {task['id']}")
        meta = run_metamorphic(task, model, logger)
        meta["scores"] = judge_output(task, meta["final_output"], model)
        meta_results.append(meta)

        print(f"  Meta:    {meta['total_tokens']:,} tokens, "
              f"{meta['elapsed_s']}s, "
              f"quality={meta['scores'].get('overall', '?')}, "
              f"agents={meta['num_agents']}, "
              f"mutations={meta['graph_mutations']}")

    # ── Aggregate Results ────────────────────────────────────────────
    def avg(items, key):
        vals = [float(i.get(key, 0)) for i in items]
        return round(sum(vals) / len(vals), 2) if vals else 0

    def avg_score(items, key):
        vals = []
        for i in items:
            s = i.get("scores", {})
            v = s.get(key)
            if v is not None:
                vals.append(float(v))
        return round(sum(vals) / len(vals), 2) if vals else 0

    elapsed = time.time() - overall_start
    results = {
        "experiment": "exp22a_static_vs_metamorphic",
        "model": model,
        "num_trials": NUM_TRIALS,
        "total_runtime_s": round(elapsed, 1),
        "static": {
            "trials": static_results,
            "avg_tokens": avg(static_results, "total_tokens"),
            "avg_elapsed_s": avg(static_results, "elapsed_s"),
            "avg_quality": avg_score(static_results, "overall"),
            "avg_comprehensiveness": avg_score(static_results, "comprehensiveness"),
            "avg_depth": avg_score(static_results, "depth"),
            "avg_actionability": avg_score(static_results, "actionability"),
            "agents_per_trial": 4,
            "mutations_per_trial": 0,
        },
        "metamorphic": {
            "trials": meta_results,
            "avg_tokens": avg(meta_results, "total_tokens"),
            "avg_elapsed_s": avg(meta_results, "elapsed_s"),
            "avg_quality": avg_score(meta_results, "overall"),
            "avg_comprehensiveness": avg_score(meta_results, "comprehensiveness"),
            "avg_depth": avg_score(meta_results, "depth"),
            "avg_actionability": avg_score(meta_results, "actionability"),
            "avg_agents": avg(meta_results, "num_agents"),
            "avg_peak_agents": avg(meta_results, "peak_agents"),
            "avg_mutations": avg(meta_results, "graph_mutations"),
            "avg_forks": avg(meta_results, "total_forks"),
            "avg_collapses": avg(meta_results, "total_collapses"),
        },
    }

    # Save
    out_path = DATA_DIR / "exp22a_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✅ Results saved to {out_path}")

    # Summary
    logger.summary_table({
        "Condition": "Static vs. Metamorphic",
        "Trials": NUM_TRIALS,
        "Static Avg Quality": results["static"]["avg_quality"],
        "Meta Avg Quality": results["metamorphic"]["avg_quality"],
        "Static Avg Tokens": f"{results['static']['avg_tokens']:,.0f}",
        "Meta Avg Tokens": f"{results['metamorphic']['avg_tokens']:,.0f}",
        "Meta Avg Agents": results["metamorphic"]["avg_agents"],
        "Meta Avg Mutations": results["metamorphic"]["avg_mutations"],
        "Meta Avg Forks": results["metamorphic"]["avg_forks"],
        "Total Runtime": f"{elapsed:.0f}s",
    })
    logger.finalize()
    return results


if __name__ == "__main__":
    run_exp22a()
