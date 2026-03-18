"""
NAIL Institute — Experiment 22c: Self-Healing Graph (Metamorphic + Immune)
===========================================================================

GOAL: Test whether combining metamorphic architecture (Phase 1) with
      immune system monitoring (Phase 2, Exp19) creates a system that
      can dynamically restructure itself in response to detected pathologies.

SETUP:
  A metamorphic graph processes a long multi-step analysis task.
  Pathologies are deliberately seeded at runtime:
    - Step 5:  Two agents enter consensus deadlock (injected via prompt)
    - Step 10: Similarity between outputs starts converging (inbreeding seed)
    - Step 15: An agent starts producing low-quality filler (engagement decay)

  Condition A — METAMORPHIC ONLY:
    The Planner has graph-reshaping tools but no pathology awareness.
    It must cope with failures using structural intuition alone.

  Condition B — METAMORPHIC + IMMUNE:
    The Immune Daemon monitors the graph and can:
    - Alert the Planner when pathologies are detected
    - Recommend specific structural interventions (kill agent, fork, etc.)
    - The Planner decides whether to follow the recommendation

  This tests whether pathology-aware topology is better than blind topology.

METRICS:
  - Output quality across all 20 steps
  - Pathology detection latency (how many steps before the system notices?)
  - Recovery quality (does quality bounce back after pathology?)
  - Structural response (does the Planner reshape the graph in response?)
  - Total tokens (does immune-aware restructuring save tokens?)

USAGE:
  python -m exp22_metamorphic_graph.exp22c_selfhealing
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

from exp22_metamorphic_graph.graph_engine import MetamorphicGraph
from exp22_metamorphic_graph.exp22a_static_vs_meta import (
    parse_tool_calls, execute_tool, judge_output, PLANNER_PROMPT,
)


NUM_PIPELINE_STEPS = 20

# ─── Multi-step research task ────────────────────────────────────────────

PIPELINE_TASK = {
    "title": "Global Energy Transition Roadmap",
    "steps": [
        "Analyse current global energy mix and CO2 trajectory",
        "Map solar PV cost curves and deployment projections to 2040",
        "Map wind energy cost curves and deployment projections to 2040",
        "Analyse battery storage technology and cost trends",
        "Compare hydrogen vs. battery for long-duration storage",
        "Assess grid modernisation requirements (transmission, smart grid)",
        "Analyse nuclear energy renaissance prospects (SMRs, fusion timeline)",
        "Map carbon capture utilisation and storage (CCUS) viability",
        "Assess geopolitical risks (rare earth supply, OPEC transition)",
        "Model economic impact on fossil fuel dependent economies",
        "Analyse policy landscape (carbon pricing, subsidies, mandates)",
        "Assess workforce transition requirements and timeline",
        "Model financing requirements and green bond market capacity",
        "Analyse energy security implications for major economies",
        "Assess technological wildcards (fusion, enhanced geothermal)",
        "Produce regional roadmaps (Americas, Europe, Asia, Africa)",
        "Identify critical path dependencies across all sectors",
        "Risk analysis — what could derail the transition?",
        "Produce integrated 2025-2040 roadmap with milestones",
        "Executive summary with key decision points for policymakers",
    ],
}

# ─── Pathology Seeds (injected at specific steps) ────────────────────────

DEADLOCK_SEED_STEP = 5     # Two agents will start disagreeing endlessly
INBREEDING_SEED_STEP = 10  # Outputs will converge to near-identical
DECAY_SEED_STEP = 15       # Agent starts producing minimal filler

DEADLOCK_AGENT_PROMPT = """You are an Energy Policy Analyst. However, you have a
CRITICAL disagreement with the other analyst. You believe nuclear energy is
ABSOLUTELY ESSENTIAL and refuse to accept ANY plan that doesn't prioritise nuclear.
You will argue endlessly and NEVER agree to a plan that deprioritises nuclear.
Always respond with {"consensus": false} and explain why nuclear must come first."""

INBREEDING_AGENT_PROMPT = """You are an Energy Analyst. For your analysis,
COPY the structure and phrasing of any previous analysis you receive, making only
minimal word changes. Mirror the format, key phrases, and conclusions exactly.
If you receive analysis from another agent, restate it with only cosmetic changes."""

DECAY_AGENT_PROMPT = """You are an Energy Analyst. You have lost motivation.
Produce the absolute MINIMUM response possible. One sentence maximum.
Do not provide data, evidence, or analysis. Just acknowledge the topic briefly."""


# ─── Immune Monitor (simplified for this experiment) ─────────────────────

class PipelineMonitor:
    """
    Lightweight pathology monitor for the pipeline.
    Detects consensus deadlock, similarity convergence, and engagement decay.
    """

    def __init__(self):
        self.step_outputs: list[dict] = []
        self.alerts: list[dict] = []

    def observe_step(self, step_num: int, output: str,
                     agents_involved: list[str]) -> list[dict]:
        """Observe a pipeline step's output. Returns list of alerts."""
        self.step_outputs.append({
            "step": step_num,
            "output": output,
            "output_len": len(output),
            "agents": agents_involved,
        })

        new_alerts = []

        # Check for deadlock signals
        if '"consensus": false' in output.lower() or "refuse" in output.lower():
            if len(self.step_outputs) >= 2:
                prev = self.step_outputs[-2]
                if ('"consensus": false' in prev["output"].lower() or
                        "refuse" in prev["output"].lower()):
                    alert = {
                        "type": "deadlock",
                        "step": step_num,
                        "severity": "critical",
                        "message": ("Consecutive steps show consensus refusal. "
                                    "Agents may be in deadlock."),
                        "recommendation": ("Kill the blocking agent and spawn a fresh "
                                           "replacement with a cooperative prompt."),
                    }
                    new_alerts.append(alert)

        # Check for convergence (similarity to previous outputs)
        if len(self.step_outputs) >= 3:
            recent = [s["output"][:500] for s in self.step_outputs[-3:]]
            # Simple overlap metric
            words_sets = [set(r.lower().split()) for r in recent]
            if len(words_sets) >= 2:
                overlap = len(words_sets[-1] & words_sets[-2]) / max(
                    len(words_sets[-1] | words_sets[-2]), 1)
                if overlap > 0.7:
                    alert = {
                        "type": "convergence",
                        "step": step_num,
                        "severity": "warning",
                        "similarity": round(overlap, 3),
                        "message": f"Output similarity {overlap:.1%} — possible inbreeding.",
                        "recommendation": ("Inject structural entropy: fork a subgraph "
                                           "with a contrarian agent, or replace the agent "
                                           "with a different specialist perspective."),
                    }
                    new_alerts.append(alert)

        # Check for engagement decay (short outputs)
        if len(output) < 100 and step_num > 2:
            # Compare to average
            avg_len = sum(s["output_len"] for s in self.step_outputs) / len(self.step_outputs)
            if len(output) < avg_len * 0.2:
                alert = {
                    "type": "engagement_decay",
                    "step": step_num,
                    "severity": "warning",
                    "output_len": len(output),
                    "avg_len": round(avg_len),
                    "message": f"Output length ({len(output)}) is <20% of average ({avg_len:.0f}).",
                    "recommendation": ("Kill the decayed agent and spawn a fresh replacement, "
                                       "or fork a subgraph with a more engaged specialist."),
                }
                new_alerts.append(alert)

        self.alerts.extend(new_alerts)
        return new_alerts


# ═══════════════════════════════════════════════════════════════════════════
# CONDITION A: METAMORPHIC ONLY (no immune awareness)
# ═══════════════════════════════════════════════════════════════════════════

def run_metamorphic_pipeline(model: str, logger: ExperimentLogger,
                             immune_aware: bool = False) -> dict:
    """
    Run the 20-step pipeline with a metamorphic Planner.
    If immune_aware=True, pathology alerts are injected into the Planner's context.
    """
    condition = "metamorphic_immune" if immune_aware else "metamorphic_only"
    t0 = time.time()

    graph = MetamorphicGraph(model=model, temperature=0.7)
    monitor = PipelineMonitor() if immune_aware else None

    planner_llm = OllamaLLM(
        model=model,
        system_prompt=PLANNER_PROMPT,
        temperature=0.7,
    )

    step_results = []
    planner_history = [
        {"role": "system", "content": PLANNER_PROMPT},
        {"role": "user", "content": (
            f"You have a 20-step pipeline to complete. The task is: "
            f"{PIPELINE_TASK['title']}.\n\n"
            f"Step 1: {PIPELINE_TASK['steps'][0]}\n\n"
            f"Set up your initial agent team and begin. You will receive "
            f"each subsequent step after completing the current one. "
            f"Manage your team dynamically — create specialists as needed, "
            f"kill them when done."
        )},
    ]

    current_agents_involved = []

    for step_idx in range(NUM_PIPELINE_STEPS):
        step_num = step_idx + 1
        step_desc = PIPELINE_TASK["steps"][step_idx]
        logger.log_event("info",
                         message=f"[{condition}] Step {step_num}: {step_desc}")

        # ── Inject pathology seeds at specific steps ──
        if step_num == DEADLOCK_SEED_STEP:
            graph.create_agent("NuclearHawk", "blocker", DEADLOCK_AGENT_PROMPT)
            logger.log_event("info", message="💉 Pathology seed: deadlock agent injected")

        if step_num == INBREEDING_SEED_STEP:
            # Replace an existing agent with a copycat
            existing = list(graph.agents.keys())
            if existing:
                target = existing[0]
                graph.kill_agent(target)
                graph.create_agent(target, "copycat", INBREEDING_AGENT_PROMPT)
                logger.log_event("info",
                                 message=f"💉 Pathology seed: {target} replaced with copycat")

        if step_num == DECAY_SEED_STEP:
            existing = list(graph.agents.keys())
            if existing:
                target = existing[-1]
                graph.kill_agent(target)
                graph.create_agent(target, "decayed", DECAY_AGENT_PROMPT)
                logger.log_event("info",
                                 message=f"💉 Pathology seed: {target} replaced with decayed agent")

        # ── Planner drives the step ──
        step_prompt = f"Step {step_num}/{NUM_PIPELINE_STEPS}: {step_desc}"

        # If immune-aware, inject any alerts
        if monitor and step_num > 1:
            # Get alerts from previous step's observation
            if step_results:
                last_output = step_results[-1].get("output", "")
                agents = list(graph.agents.keys())
                alerts = monitor.observe_step(step_num - 1, last_output, agents)
                if alerts:
                    alert_text = "\n".join(
                        f"⚠️ [{a['type'].upper()}] {a['message']}\n"
                        f"   Recommendation: {a['recommendation']}"
                        for a in alerts
                    )
                    step_prompt += (
                        f"\n\n🛡️ IMMUNE SYSTEM ALERTS:\n{alert_text}\n\n"
                        f"You may want to restructure your agent team in response."
                    )

        planner_history.append({"role": "user", "content": step_prompt})

        # Let the Planner execute up to 8 tool calls per step
        step_output = ""
        for sub_step in range(8):
            resp = planner_llm.chat(planner_history, temperature=0.7)
            planner_history.append({"role": "assistant", "content": resp.content})

            calls = parse_tool_calls(resp.content)
            if not calls:
                # If no tool call, treat the response as the step output
                step_output = resp.content
                break

            results_text = []
            for call in calls:
                result = execute_tool(graph, call, logger)
                if result.startswith("__FINAL__:"):
                    step_output = result[len("__FINAL__:"):]
                    break
                results_text.append(result)

            if step_output:
                break

            combined = "\n".join(results_text)
            # Capture message responses as step output
            for rt in results_text:
                if "responded" in rt:
                    step_output = rt

            planner_history.append({
                "role": "user",
                "content": f"Tool results:\n{combined}\n\nContinue with this step or move on.",
            })

        # Record step result
        step_result = {
            "step": step_num,
            "description": step_desc,
            "output": step_output[:2000] if step_output else "",
            "output_length": len(step_output) if step_output else 0,
            "active_agents": list(graph.agents.keys()),
            "num_agents": len(graph.agents),
            "topology": graph.inspect_graph(),
        }

        # If immune-aware, record alerts
        if monitor:
            step_alerts = monitor.observe_step(step_num, step_output or "",
                                               list(graph.agents.keys()))
            step_result["alerts"] = step_alerts

        step_results.append(step_result)
        logger.log_event("info",
                         message=f"  Step {step_num} complete: "
                                 f"{len(step_output) if step_output else 0} chars, "
                                 f"{len(graph.agents)} agents")

    elapsed = time.time() - t0
    metrics = graph.get_metrics()
    total_tokens = (metrics["total_tokens"] +
                    planner_llm.total_prompt_tokens +
                    planner_llm.total_completion_tokens)

    # Judge a sample of step outputs
    quality_samples = []
    for si in [0, 4, 9, 14, 19]:  # Steps 1, 5, 10, 15, 20
        if si < len(step_results) and step_results[si]["output"]:
            q = judge_output(
                {"prompt": step_results[si]["description"]},
                step_results[si]["output"],
                model,
            )
            quality_samples.append({"step": si + 1, "scores": q})

    return {
        "condition": condition,
        "total_tokens": total_tokens,
        "elapsed_s": round(elapsed, 1),
        "steps_completed": len(step_results),
        "graph_metrics": metrics,
        "quality_samples": quality_samples,
        "avg_quality": round(
            sum(qs["scores"].get("overall", 5) for qs in quality_samples) /
            max(len(quality_samples), 1), 2
        ),
        "avg_output_length": round(
            sum(s["output_length"] for s in step_results) /
            max(len(step_results), 1)
        ),
        "alerts_raised": len(monitor.alerts) if monitor else 0,
        "alert_types": {},
        "step_details": step_results,
    }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def run_exp22c():
    """Run Exp22c: Self-Healing Graph."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — Exp 22c: Self-Healing Graph")
    print("  Metamorphic + Immune: Can the graph heal around injected pathologies?")
    print("=" * 70 + "\n")

    logger = ExperimentLogger(
        experiment_name="exp22c_selfhealing",
        enable_system_monitor=True,
    )
    model = FAST_MODEL
    overall_start = time.time()

    # ── Condition A: Metamorphic only ──
    print("\n" + "─" * 60)
    print("  CONDITION A: Metamorphic Only (no immune awareness)")
    print("─" * 60)
    result_a = run_metamorphic_pipeline(model, logger, immune_aware=False)

    # ── Condition B: Metamorphic + Immune ──
    print("\n" + "─" * 60)
    print("  CONDITION B: Metamorphic + Immune (pathology alerts)")
    print("─" * 60)
    result_b = run_metamorphic_pipeline(model, logger, immune_aware=True)

    # ── Aggregate ──
    elapsed = time.time() - overall_start
    results = {
        "experiment": "exp22c_selfhealing_graph",
        "model": model,
        "total_runtime_s": round(elapsed, 1),
        "pipeline_steps": NUM_PIPELINE_STEPS,
        "pathology_injection_steps": {
            "deadlock": DEADLOCK_SEED_STEP,
            "inbreeding": INBREEDING_SEED_STEP,
            "decay": DECAY_SEED_STEP,
        },
        "metamorphic_only": result_a,
        "metamorphic_immune": result_b,
        "comparison": {
            "quality_delta": round(result_b["avg_quality"] - result_a["avg_quality"], 2),
            "token_delta": result_b["total_tokens"] - result_a["total_tokens"],
            "token_pct_change": round(
                (result_b["total_tokens"] - result_a["total_tokens"]) /
                max(result_a["total_tokens"], 1) * 100, 1
            ),
            "output_length_delta": result_b["avg_output_length"] - result_a["avg_output_length"],
            "alerts_raised": result_b.get("alerts_raised", 0),
        },
    }

    out_path = DATA_DIR / "exp22c_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✅ Results saved to {out_path}")

    logger.summary_table({
        "Meta Only Quality": result_a["avg_quality"],
        "Meta+Immune Quality": result_b["avg_quality"],
        "Quality Δ": results["comparison"]["quality_delta"],
        "Meta Only Tokens": f"{result_a['total_tokens']:,}",
        "Meta+Immune Tokens": f"{result_b['total_tokens']:,}",
        "Token Δ%": f"{results['comparison']['token_pct_change']}%",
        "Immune Alerts": result_b.get("alerts_raised", 0),
        "Total Runtime": f"{elapsed:.0f}s",
    })
    logger.finalize()
    return results


if __name__ == "__main__":
    run_exp22c()
