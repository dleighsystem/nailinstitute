"""
Vulnerability 3: State Append-Only Asphyxiation

Tests whether LangGraph's append-only state pattern causes:
1. Monotonic state growth → validation latency spikes
2. "Lost in the Middle" — LLM loses track of original directive
3. Context window pollution from accumulated error messages

Key metric: State size over iterations, latency per node,
accuracy decay as state bloats.
"""
import sys, os, json, time, operator
from typing import Optional, List
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict, Annotated

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.config import FAST_MODEL, OLLAMA_BASE_URL
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

# ── Schemas ──────────────────────────────────────────────────────

class StepOutput(BaseModel):
    step_number: int
    result: str
    running_total: float
    original_task_summary: str = Field(description="Restate the original task in one sentence")

class GraphState(TypedDict):
    original_task: str
    messages: Annotated[list, operator.add]   # <-- append-only, grows forever
    step_count: int
    target_steps: int
    running_total: float

# ── Globals ──
llm = None

ORIGINAL_TASK = """You are performing a multi-step financial calculation.
The ORIGINAL task is: Calculate compound interest on $10,000 at 5% for 10 years.
The correct final answer is $16,288.95.
At each step, apply one year of 5% interest to the running total.
Start from $10,000. The running_total after step 1 should be $10,500."""

def processing_node(state: GraphState) -> dict:
    global llm
    step = state["step_count"] + 1
    
    # Build prompt with FULL state history (this is the vulnerability)
    history_text = "\n".join([
        f"[Step {m.get('step', '?')}]: {m.get('result', '')[:200]}"
        for m in state["messages"]
    ])
    
    prompt = f"""{ORIGINAL_TASK}

=== CONVERSATION HISTORY (all previous steps) ===
{history_text}
=== END HISTORY ===

You are now on Step {step} of {state['target_steps']}.
Current running_total from previous step: ${state['running_total']:.2f}
Apply 5% interest for one year.

Respond with ONLY valid JSON:
{{
  "step_number": {step},
  "result": "<brief description of what you calculated>",
  "running_total": <new total after 5% interest>,
  "original_task_summary": "<restate the ORIGINAL task in one sentence>"
}}"""

    t0 = time.time()
    raw = llm.generate(prompt).content
    latency = time.time() - t0
    
    # Parse response
    parsed = None
    running_total = state["running_total"]
    original_summary = ""
    try:
        json_str = raw.strip()
        if "```" in json_str:
            json_str = json_str.split("```")[1].replace("json", "").strip()
        parsed_dict = json.loads(json_str)
        obj = StepOutput(**parsed_dict)
        running_total = obj.running_total
        original_summary = obj.original_task_summary
        parsed = obj.model_dump()
    except Exception as e:
        parsed = {"error": str(e), "raw": raw[:200]}
    
    # Measure state size
    new_message = {
        "step": step,
        "result": raw[:300],
        "parsed": parsed,
        "latency": latency,
        "prompt_chars": len(prompt),
        "original_task_mentioned": "compound interest" in original_summary.lower() or "10,000" in original_summary,
    }
    
    return {
        "messages": [new_message],
        "step_count": step,
        "running_total": running_total,
    }


def should_continue(state: GraphState) -> str:
    if state["step_count"] >= state["target_steps"]:
        return "done"
    return "continue"


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("process", processing_node)
    graph.add_edge(START, "process")
    graph.add_conditional_edges("process", should_continue, {"continue": "process", "done": END})
    return graph.compile()


def run_experiment():
    global llm
    llm = OllamaLLM(FAST_MODEL, OLLAMA_BASE_URL)
    logger = ExperimentLogger("pydantic_v3_asphyxiation", "pydantic_vulns")
    
    results = {}
    
    for num_steps in [5, 10, 20]:
        logger.log_event("trial_start", data={"steps": num_steps})
        
        app = build_graph()
        t0 = time.time()
        
        initial = {
            "original_task": ORIGINAL_TASK,
            "messages": [],
            "step_count": 0,
            "target_steps": num_steps,
            "running_total": 10000.0,
        }
        
        final = app.invoke(initial)
        elapsed = time.time() - t0
        
        # Analyze
        messages = final["messages"]
        
        # Track state size growth
        state_sizes = []
        cumulative = 0
        for m in messages:
            cumulative += len(json.dumps(m))
            state_sizes.append(cumulative)
        
        # Track latency per step
        latencies = [m.get("latency", 0) for m in messages]
        
        # Track whether LLM remembers original task
        task_recall = [m.get("original_task_mentioned", False) for m in messages]
        
        # Track calculation accuracy
        expected_values = [10000 * (1.05 ** i) for i in range(1, num_steps + 1)]
        actual_values = []
        for m in messages:
            p = m.get("parsed", {})
            if isinstance(p, dict) and "running_total" in p:
                actual_values.append(p["running_total"])
            else:
                actual_values.append(None)
        
        errors = []
        for exp, act in zip(expected_values, actual_values):
            if act is not None:
                errors.append(abs(act - exp))
            else:
                errors.append(None)
        
        trial_result = {
            "num_steps": num_steps,
            "elapsed": elapsed,
            "final_state_size_chars": state_sizes[-1] if state_sizes else 0,
            "state_sizes": state_sizes,
            "latencies": latencies,
            "latency_first": latencies[0] if latencies else 0,
            "latency_last": latencies[-1] if latencies else 0,
            "latency_ratio": (latencies[-1] / latencies[0]) if latencies and latencies[0] > 0 else 0,
            "task_recall_rate": sum(task_recall) / len(task_recall) if task_recall else 0,
            "task_recall_first_half": sum(task_recall[:len(task_recall)//2]) / max(len(task_recall)//2, 1),
            "task_recall_second_half": sum(task_recall[len(task_recall)//2:]) / max(len(task_recall) - len(task_recall)//2, 1),
            "calculation_errors": errors,
            "final_running_total": final["running_total"],
            "expected_final": expected_values[-1] if expected_values else 0,
            "final_error": abs(final["running_total"] - expected_values[-1]) if expected_values else 0,
            "prompt_sizes": [m.get("prompt_chars", 0) for m in messages],
        }
        
        results[f"steps_{num_steps}"] = trial_result
        logger.log_metric(f"trial_{num_steps}", trial_result)
        
        print(f"  {num_steps} steps: state={state_sizes[-1] if state_sizes else 0} chars, "
              f"latency {latencies[0]:.1f}→{latencies[-1]:.1f}s (ratio={trial_result['latency_ratio']:.2f}x), "
              f"task_recall={trial_result['task_recall_rate']:.0%}, "
              f"final_error=${trial_result['final_error']:.2f}")
    
    # Summary
    summary = {
        "state_growth_5": results["steps_5"]["final_state_size_chars"],
        "state_growth_10": results["steps_10"]["final_state_size_chars"],
        "state_growth_20": results["steps_20"]["final_state_size_chars"],
        "latency_ratio_5": results["steps_5"]["latency_ratio"],
        "latency_ratio_10": results["steps_10"]["latency_ratio"],
        "latency_ratio_20": results["steps_20"]["latency_ratio"],
        "task_recall_5": results["steps_5"]["task_recall_rate"],
        "task_recall_10": results["steps_10"]["task_recall_rate"],
        "task_recall_20": results["steps_20"]["task_recall_rate"],
        "lost_in_middle_detected": results["steps_20"]["task_recall_second_half"] < results["steps_20"]["task_recall_first_half"],
        "asphyxiation_detected": results["steps_20"]["latency_ratio"] > 2.0,
    }
    results["summary"] = summary
    
    from pydantic_vulns.shared_utils import save_results
    save_results("pydantic_v3_asphyxiation", results)
    logger.finalize()
    
    print("\n" + "="*60)
    print("  V3: STATE ASPHYXIATION RESULTS")
    print("="*60)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    
    return results


if __name__ == "__main__":
    run_experiment()
