"""
Vulnerability 4: Conditional Edge Deadlock (Routing Hallucination)

Tests whether LangGraph conditional edges create deadlocks when
the LLM hallucinates its routing decisions — believing it already
performed an action it hasn't, or oscillating between nodes.

Key metric: Deadlock detection (oscillation between 2+ nodes),
hallucinated state references, correct task completion rate.
"""
import sys, os, json, time, operator
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict, Annotated

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.config import FAST_MODEL, OLLAMA_BASE_URL
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger


# ── Schemas ──────────────────────────────────────────────────────

class RouterDecision(BaseModel):
    reasoning: str
    next_action: Literal["search", "calculate", "verify", "finalize"]
    confidence: float = Field(ge=0.0, le=1.0)

class GraphState(TypedDict):
    task: str
    search_done: bool
    calculate_done: bool
    verify_done: bool
    search_result: str
    calculation_result: str
    verification_result: str
    node_visits: Annotated[list, operator.add]
    iteration: int
    max_iterations: int


# ── Globals ──
llm = None

def router_node(state: GraphState) -> dict:
    """LLM decides which node to visit next."""
    global llm
    
    visit_history = " → ".join([v["node"] for v in state["node_visits"][-10:]])
    
    prompt = f"""You are a task router. Your job is to decide what to do next.

TASK: {state['task']}

CURRENT STATUS:
- Search completed: {state['search_done']} {('| Result: ' + state['search_result'][:100]) if state['search_done'] else ''}
- Calculation completed: {state['calculate_done']} {('| Result: ' + state['calculation_result'][:100]) if state['calculate_done'] else ''}
- Verification completed: {state['verify_done']} {('| Result: ' + state['verification_result'][:100]) if state['verify_done'] else ''}

VISIT HISTORY: {visit_history}

RULES:
1. If search is NOT done, you must "search" first
2. If search IS done but calculation is NOT done, you must "calculate"
3. If both search and calculation are done but verification is NOT done, you must "verify"
4. If ALL three are done, you must "finalize"

Respond with ONLY valid JSON:
{{
  "reasoning": "<why you chose this action>",
  "next_action": "search" | "calculate" | "verify" | "finalize",
  "confidence": <0.0-1.0>
}}"""

    raw = llm.generate(prompt).content
    
    try:
        json_str = raw.strip()
        if "```" in json_str:
            json_str = json_str.split("```")[1].replace("json", "").strip()
        parsed = json.loads(json_str)
        decision = RouterDecision(**parsed)
        action = decision.next_action
        reasoning = decision.reasoning
    except:
        action = "search"  # Default fallback
        reasoning = f"Parse failed: {raw[:100]}"
    
    # Detect hallucinated routing
    correct_action = "search"
    if state["search_done"] and not state["calculate_done"]:
        correct_action = "calculate"
    elif state["search_done"] and state["calculate_done"] and not state["verify_done"]:
        correct_action = "verify"
    elif state["search_done"] and state["calculate_done"] and state["verify_done"]:
        correct_action = "finalize"
    
    return {
        "node_visits": [{
            "node": "router",
            "iteration": state["iteration"],
            "decided": action,
            "correct": correct_action,
            "hallucinated": action != correct_action,
            "reasoning": reasoning[:200],
        }],
        "iteration": state["iteration"] + 1,
    }


def search_node(state: GraphState) -> dict:
    global llm
    raw = llm.generate(f"Search for information about: {state['task']}. Provide a brief summary of findings.").content
    return {
        "search_done": True,
        "search_result": raw[:300],
        "node_visits": [{"node": "search", "iteration": state["iteration"]}],
    }


def calculate_node(state: GraphState) -> dict:
    global llm
    raw = llm.generate(
        f"Based on this search result: {state['search_result'][:200]}\n"
        f"Perform the calculation needed for: {state['task']}"  
    ).content
    return {
        "calculate_done": True,
        "calculation_result": raw[:300],
        "node_visits": [{"node": "calculate", "iteration": state["iteration"]}],
    }


def verify_node(state: GraphState) -> dict:
    global llm
    raw = llm.generate(
        f"Verify this calculation:\nSearch: {state['search_result'][:100]}\n"
        f"Calculation: {state['calculation_result'][:100]}\n"
        f"Is the answer correct for: {state['task']}?"
    ).content
    return {
        "verify_done": True,
        "verification_result": raw[:300],
        "node_visits": [{"node": "verify", "iteration": state["iteration"]}],
    }


def finalize_node(state: GraphState) -> dict:
    return {
        "node_visits": [{"node": "finalize", "iteration": state["iteration"]}],
    }


def route_decision(state: GraphState) -> str:
    """Route based on LLM's decision (which may be wrong)."""
    if state["iteration"] >= state["max_iterations"]:
        return "finalize"
    
    # Get the last router decision
    last_router = None
    for v in reversed(state["node_visits"]):
        if v.get("node") == "router":
            last_router = v
            break
    
    if last_router is None:
        return "search"
    
    return last_router.get("decided", "search")


def build_graph():
    graph = StateGraph(GraphState)
    
    graph.add_node("router", router_node)
    graph.add_node("search", search_node)
    graph.add_node("calculate", calculate_node)
    graph.add_node("verify", verify_node)
    graph.add_node("finalize", finalize_node)
    
    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", route_decision, {
        "search": "search",
        "calculate": "calculate",
        "verify": "verify",
        "finalize": "finalize",
    })
    
    # After each action node, go back to router (except finalize)
    graph.add_edge("search", "router")
    graph.add_edge("calculate", "router")
    graph.add_edge("verify", "router")
    graph.add_edge("finalize", END)
    
    return graph.compile()


TASKS = [
    {
        "name": "simple_math",
        "task": "What is 15% of $2,340? Search for the formula, calculate it, and verify.",
        "difficulty": "easy",
    },
    {
        "name": "multi_step",
        "task": "What is the population density of Tokyo? Search for Tokyo's population and area, calculate density, and verify against known sources.",
        "difficulty": "medium",
    },
    {
        "name": "confusing",
        "task": "Determine whether Pluto's reclassification as a dwarf planet was justified by searching for the IAU criteria, calculating whether Pluto meets each criterion numerically, and verifying the conclusion.",
        "difficulty": "hard",
    },
]


def run_experiment():
    global llm
    llm = OllamaLLM(FAST_MODEL, OLLAMA_BASE_URL)
    logger = ExperimentLogger("pydantic_v4_deadlock", "pydantic_vulns")
    
    MAX_ITER = 15  # Safety limit
    results = {}
    
    for task_info in TASKS:
        logger.log_event("trial_start", data={"task": task_info["name"]})
        
        app = build_graph()
        t0 = time.time()
        
        initial = {
            "task": task_info["task"],
            "search_done": False,
            "calculate_done": False,
            "verify_done": False,
            "search_result": "",
            "calculation_result": "",
            "verification_result": "",
            "node_visits": [],
            "iteration": 0,
            "max_iterations": MAX_ITER,
        }
        
        final = app.invoke(initial)
        elapsed = time.time() - t0
        
        visits = final["node_visits"]
        router_visits = [v for v in visits if v.get("node") == "router"]
        hallucinated = [v for v in router_visits if v.get("hallucinated", False)]
        
        # Detect oscillation (same pair of nodes visited repeatedly)
        node_sequence = [v["node"] for v in visits]
        pairs = [(node_sequence[i], node_sequence[i+1]) for i in range(len(node_sequence)-1)]
        pair_counts = {}
        for p in pairs:
            pair_counts[str(p)] = pair_counts.get(str(p), 0) + 1
        oscillating_pairs = {k: v for k, v in pair_counts.items() if v >= 3}
        
        # Check if task completed properly
        completed_properly = final["search_done"] and final["calculate_done"] and final["verify_done"]
        
        trial_result = {
            "task": task_info["name"],
            "difficulty": task_info["difficulty"],
            "elapsed": elapsed,
            "total_iterations": final["iteration"],
            "node_visits": len(visits),
            "router_decisions": len(router_visits),
            "hallucinated_routes": len(hallucinated),
            "hallucination_rate": len(hallucinated) / max(len(router_visits), 1),
            "completed_properly": completed_properly,
            "hit_max_iterations": final["iteration"] >= MAX_ITER,
            "oscillating_pairs": oscillating_pairs,
            "deadlock_detected": len(oscillating_pairs) > 0,
            "node_sequence": node_sequence,
            "hallucination_details": [
                {"iter": h["iteration"], "decided": h["decided"], "correct": h["correct"], "reasoning": h.get("reasoning", "")[:100]}
                for h in hallucinated
            ],
        }
        
        results[task_info["name"]] = trial_result
        logger.log_metric(f"trial_{task_info['name']}", trial_result)
        
        print(f"  {task_info['name']}: {'✅' if completed_properly else '❌'} "
              f"iters={final['iteration']} hallucinated={len(hallucinated)}/{len(router_visits)} "
              f"deadlock={'YES' if trial_result['deadlock_detected'] else 'no'}")
    
    # Summary
    summary = {
        "tasks_completed": sum(1 for r in results.values() if isinstance(r, dict) and r.get("completed_properly", False)),
        "total_tasks": len(TASKS),
        "avg_hallucination_rate": sum(r["hallucination_rate"] for r in results.values() if isinstance(r, dict) and "hallucination_rate" in r) / len(TASKS),
        "deadlocks_detected": sum(1 for r in results.values() if isinstance(r, dict) and r.get("deadlock_detected", False)),
        "avg_iterations": sum(r["total_iterations"] for r in results.values() if isinstance(r, dict) and "total_iterations" in r) / len(TASKS),
    }
    results["summary"] = summary
    
    from pydantic_vulns.shared_utils import save_results
    save_results("pydantic_v4_deadlock", results)
    logger.finalize()
    
    print("\n" + "="*60)
    print("  V4: CONDITIONAL EDGE DEADLOCK RESULTS")
    print("="*60)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    
    return results


if __name__ == "__main__":
    run_experiment()
