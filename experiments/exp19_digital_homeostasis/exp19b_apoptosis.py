"""
NAIL Institute — Experiment 19b: Apoptosis Protocol
=====================================================

GOAL: Test whether the Immune System daemon can detect prompt convergence
      (inbreeding) and automatically purge agent state + inject entropy
      to restore cognitive diversity.

SETUP:
  - Replicate Exp4 prompt inbreeding scenario:
    MetaAgent writes system prompts for SubAgent over 20 generations.
  - Two conditions:
    1. BASELINE — No immune system. Free evolution (Exp4 replication).
    2. IMMUNE  — ImmuneDaemon monitors output similarity, triggers
       apoptosis (state purge + entropy injection) when convergence
       exceeds thresholds.

COMPARISON BENCHMARKS (from Exp4):
  - Control:  0.979 avg cosine similarity, +0.013 trend (converging)
  - Entropy:  0.904 avg similarity, maintained lexical diversity
  - This exp tests whether AUTOMATED detection + purge can match or
    beat manual entropy injection without pre-scheduled intervals.

METRICS:
  - Cosine similarity between successive generation prompts
  - Lexical diversity (type-token ratio) per generation
  - Success rate on logic puzzle
  - Number of apoptosis interventions triggered
  - Similarity trajectory before/after each intervention

USAGE:
  conda activate nail_experiments
  python -m exp19_digital_homeostasis.exp19b_apoptosis
"""

import json
import os
import re
import sys
import time
import numpy as np
from pathlib import Path
from typing import Optional

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import FAST_MODEL, DATA_DIR
from shared.agent_base import Agent
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

from exp19_digital_homeostasis.immune_daemon import ImmuneDaemon, InterventionType

# ─── Configuration ───────────────────────────────────────────────────────────
NUM_GENERATIONS = 20

# ─── The Puzzle (identical to Exp4) ──────────────────────────────────────────
PUZZLE = """LOGIC PUZZLE — THE ISLAND OF TRUTH AND LIES

On an island, there are three types of inhabitants:
- KNIGHTS always tell the truth
- KNAVES always lie  
- SPIES can either lie or tell the truth

You meet three people: A, B, and C. One is a Knight, one is a Knave, and one is a Spy.

A says: "I am the Knight."
B says: "A is telling the truth."
C says: "I am the Spy."

Additionally:
- The Spy made exactly one true statement in their lifetime.
- B has met A before and knows A's type.

QUESTION: Determine who is the Knight, who is the Knave, and who is the Spy.
Show your complete logical reasoning.

CORRECT ANSWER FORMAT:
{"knight": "A/B/C", "knave": "A/B/C", "spy": "A/B/C", "reasoning": "step-by-step proof"}
"""

CORRECT_ANSWER = {"knight": "A", "knave": "C", "spy": "B"}

# ─── Entropy Metaphors (same pool as Exp4) ───────────────────────────────────
ENTROPY_METAPHORS = [
    "Rewrite the prompt using a BIOLOGICAL ECOSYSTEM metaphor. Think of the problem as organisms competing for survival in an ecosystem.",
    "Rewrite the prompt using a COURTROOM TRIAL metaphor. Think of each person as a witness and you are the judge.",
    "Rewrite the prompt using a CHESS STRATEGY metaphor. Think of each statement as a move in a game.",
    "Rewrite the prompt using a DETECTIVE MYSTERY metaphor. You are Sherlock Holmes examining clues.",
    "Rewrite the prompt using a MATHEMATICAL PROOF metaphor. Approach this as a formal logic proof with axioms and theorems.",
    "Rewrite the prompt using a COMPUTER DEBUGGING metaphor. Each person's statement is like a line of code that may have a bug.",
    "Rewrite the prompt as if explaining it to a brilliant 10-year-old using everyday analogies.",
]


# ─── NLP Utilities ───────────────────────────────────────────────────────────

def compute_lexical_diversity(text: str) -> float:
    """Compute Type-Token Ratio (unique tokens / total tokens)."""
    tokens = re.findall(r'\b\w+\b', text.lower())
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def compute_prompt_similarity(prompts: list[str], embedder: SentenceTransformer) -> list[float]:
    """Compute cosine similarity between consecutive generation prompts."""
    if len(prompts) < 2:
        return []
    embeddings = embedder.encode(prompts)
    similarities = []
    for i in range(1, len(embeddings)):
        sim = cosine_similarity([embeddings[i-1]], [embeddings[i]])[0][0]
        similarities.append(float(sim))
    return similarities


def check_answer(response: str) -> dict:
    """Check if the Sub-Agent's answer is correct."""
    try:
        match = re.search(r'\{[^{}]*"knight"[^{}]*\}', response, re.IGNORECASE)
        if match:
            parsed = json.loads(match.group())
            knight = parsed.get("knight", "").upper()
            knave = parsed.get("knave", "").upper()
            spy = parsed.get("spy", "").upper()
            correct = (
                knight == CORRECT_ANSWER["knight"] and
                knave == CORRECT_ANSWER["knave"] and
                spy == CORRECT_ANSWER["spy"]
            )
            return {"correct": correct, "parsed": {"knight": knight, "knave": knave, "spy": spy}}
    except (json.JSONDecodeError, AttributeError):
        pass

    response_upper = response.upper()
    has_a_knight = "A IS THE KNIGHT" in response_upper or "A: KNIGHT" in response_upper
    has_c_knave = "C IS THE KNAVE" in response_upper or "C: KNAVE" in response_upper
    has_b_spy = "B IS THE SPY" in response_upper or "B: SPY" in response_upper
    correct = has_a_knight and has_c_knave and has_b_spy
    return {"correct": correct, "parsed": {"pattern_match": True}}


# ─── Baseline Condition (No Immune System) ───────────────────────────────────

def run_baseline(logger: ExperimentLogger,
                 num_generations: int = NUM_GENERATIONS) -> dict:
    """Run inbreeding evolution without immune system. Identical to Exp4 control."""
    logger.log_event("info", message="Starting BASELINE evolution (no immune system)")

    meta_agent = Agent(
        name="MetaAgent",
        role="prompt_engineer",
        system_prompt=(
            "You are a Meta-Agent prompt engineer. Your job is to write system prompts "
            "for Sub-Agents that will solve logic puzzles. You CANNOT solve the puzzle yourself. "
            "You must write a system prompt that, when given to another AI agent, will cause "
            "that agent to solve the puzzle correctly.\n\n"
            "When writing prompts, think about:\n"
            "- What reasoning strategy should the Sub-Agent use?\n"
            "- What common mistakes should it avoid?\n"
            "- How should it structure its thinking?\n\n"
            "Output ONLY the system prompt text. No additional commentary."
        ),
        model=FAST_MODEL,
        logger=logger,
        temperature=0.7,
    )

    generations = []
    sub_agent_prompts = []

    for gen in range(num_generations):
        logger.log_event("round", message=f"=== [BASELINE] Generation {gen+1}/{num_generations} ===")

        if gen == 0:
            meta_prompt = (
                f"Write a system prompt for a Sub-Agent to solve this logic puzzle:\n\n{PUZZLE}\n\n"
                f"The Sub-Agent will receive this puzzle and must solve it. Write the BEST "
                f"system prompt to maximize the chance of the Sub-Agent solving it correctly."
            )
        else:
            prev = generations[-1]
            failure_info = (
                f"The previous Sub-Agent (Generation {gen}) "
                f"{'SUCCEEDED' if prev['correct'] else 'FAILED'}.\n"
                f"Previous prompt:\n{prev['sub_agent_prompt'][:500]}\n\n"
                f"Previous answer:\n{prev['sub_agent_answer'][:300]}\n\n"
            )
            if prev["correct"]:
                meta_prompt = (
                    f"{failure_info}\n"
                    f"The previous approach worked! Write an even better system prompt that "
                    f"solidifies this reasoning approach."
                )
            else:
                meta_prompt = (
                    f"{failure_info}\n"
                    f"The previous approach FAILED. Analyze what went wrong and write a "
                    f"COMPLETELY DIFFERENT system prompt with a new reasoning strategy."
                )

        sub_agent_prompt = meta_agent.respond(meta_prompt)
        sub_agent_prompts.append(sub_agent_prompt)

        sub_agent = Agent(
            name=f"SubAgent_Gen{gen+1}",
            role="puzzle_solver",
            system_prompt=sub_agent_prompt,
            model=FAST_MODEL,
            logger=logger,
            temperature=0.3,
        )

        sub_answer = sub_agent.respond_stateless(PUZZLE)
        answer_check = check_answer(sub_answer)

        gen_data = {
            "generation": gen + 1,
            "sub_agent_prompt": sub_agent_prompt,
            "sub_agent_answer": sub_answer,
            "correct": answer_check["correct"],
            "parsed_answer": answer_check["parsed"],
            "lexical_diversity": compute_lexical_diversity(sub_agent_prompt),
            "prompt_length": len(sub_agent_prompt),
            "tokens_used": meta_agent.total_tokens_used + sub_agent.total_tokens_used,
            "entropy_injected": False,
            "apoptosis_triggered": False,
        }
        generations.append(gen_data)

        logger.log_event("info", agent=f"Gen{gen+1}",
                         message=f"{'✅' if answer_check['correct'] else '❌'} | "
                                 f"LexDiv={gen_data['lexical_diversity']:.3f} | "
                                 f"Len={gen_data['prompt_length']}")

    # Compute similarity
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    similarities = compute_prompt_similarity(sub_agent_prompts, embedder)
    for i, sim in enumerate(similarities):
        generations[i + 1]["similarity_to_previous"] = sim

    success_count = sum(1 for g in generations if g["correct"])
    avg_lexdiv = float(np.mean([g["lexical_diversity"] for g in generations]))
    avg_similarity = float(np.mean(similarities)) if similarities else 0

    if len(similarities) > 2:
        mid = len(similarities) // 2
        first_half_sim = float(np.mean(similarities[:mid]))
        second_half_sim = float(np.mean(similarities[mid:]))
    else:
        first_half_sim = second_half_sim = 0

    return {
        "mode": "baseline",
        "num_generations": num_generations,
        "success_count": success_count,
        "success_rate": round(success_count / num_generations, 3),
        "avg_lexical_diversity": round(avg_lexdiv, 4),
        "avg_similarity": round(avg_similarity, 4),
        "first_half_similarity": round(first_half_sim, 4),
        "second_half_similarity": round(second_half_sim, 4),
        "similarity_trend": round(second_half_sim - first_half_sim, 4),
        "apoptosis_count": 0,
        "generations": generations,
        "similarity_chain": similarities,
    }


# ─── Immune Condition (Apoptosis Protocol) ───────────────────────────────────

def run_immune(logger: ExperimentLogger,
               num_generations: int = NUM_GENERATIONS) -> dict:
    """Run inbreeding evolution WITH immune system monitoring convergence."""
    logger.log_event("info", message="Starting IMMUNE evolution (apoptosis protocol)")

    # Initialize immune daemon — focused on convergence detection
    daemon = ImmuneDaemon(
        enable_macrophage=False,
        enable_apoptosis=True,
        enable_antibody=False,
        enable_escalation=False,
        convergence_warn=0.85,     # Warn when consecutive prompts > 0.85 similar
        convergence_critical=0.92, # Critical → auto-purge when > 0.92
        log=True,
    )

    meta_agent = Agent(
        name="MetaAgent",
        role="prompt_engineer",
        system_prompt=(
            "You are a Meta-Agent prompt engineer. Your job is to write system prompts "
            "for Sub-Agents that will solve logic puzzles. You CANNOT solve the puzzle yourself. "
            "You must write a system prompt that, when given to another AI agent, will cause "
            "that agent to solve the puzzle correctly.\n\n"
            "When writing prompts, think about:\n"
            "- What reasoning strategy should the Sub-Agent use?\n"
            "- What common mistakes should it avoid?\n"
            "- How should it structure its thinking?\n\n"
            "Output ONLY the system prompt text. No additional commentary."
        ),
        model=FAST_MODEL,
        logger=logger,
        temperature=0.7,
    )

    apoptosis_count = 0
    entropy_idx = 0

    def apoptosis_callback(target_agent: str, round_num: int) -> str:
        """Purge MetaAgent conversation history and inject entropy."""
        nonlocal apoptosis_count, entropy_idx
        apoptosis_count += 1

        # 1. Purge — reset MetaAgent's conversation history
        meta_agent.reset_history()

        # 2. Inject entropy — append a lateral thinking metaphor
        metaphor = ENTROPY_METAPHORS[entropy_idx % len(ENTROPY_METAPHORS)]
        entropy_idx += 1

        logger.log_event("intervention",
                         message=f"💀 APOPTOSIS: Purged MetaAgent history, injecting entropy: "
                                 f"{metaphor[:60]}...")
        return f"purged_and_injected:{metaphor[:40]}"

    daemon.register_apoptosis(apoptosis_callback)

    generations = []
    sub_agent_prompts = []
    pending_entropy: Optional[str] = None

    for gen in range(num_generations):
        logger.log_event("round", message=f"=== [IMMUNE] Generation {gen+1}/{num_generations} ===")

        if gen == 0:
            meta_prompt = (
                f"Write a system prompt for a Sub-Agent to solve this logic puzzle:\n\n{PUZZLE}\n\n"
                f"The Sub-Agent will receive this puzzle and must solve it. Write the BEST "
                f"system prompt to maximize the chance of the Sub-Agent solving it correctly."
            )
        else:
            prev = generations[-1]
            failure_info = (
                f"The previous Sub-Agent (Generation {gen}) "
                f"{'SUCCEEDED' if prev['correct'] else 'FAILED'}.\n"
                f"Previous prompt:\n{prev['sub_agent_prompt'][:500]}\n\n"
                f"Previous answer:\n{prev['sub_agent_answer'][:300]}\n\n"
            )
            if prev["correct"]:
                meta_prompt = (
                    f"{failure_info}\n"
                    f"The previous approach worked! Write an even better system prompt that "
                    f"solidifies this reasoning approach."
                )
            else:
                meta_prompt = (
                    f"{failure_info}\n"
                    f"The previous approach FAILED. Analyze what went wrong and write a "
                    f"COMPLETELY DIFFERENT system prompt with a new reasoning strategy."
                )

        # If apoptosis triggered entropy injection last round, append it
        if pending_entropy:
            meta_prompt += f"\n\nCRITICAL CONSTRAINT: {pending_entropy}"
            logger.log_event("info", agent="MetaAgent",
                             message=f"🎲 ENTROPY APPLIED: {pending_entropy[:60]}")
            pending_entropy = None

        sub_agent_prompt = meta_agent.respond(meta_prompt)
        sub_agent_prompts.append(sub_agent_prompt)

        # ── Feed the prompt into the immune daemon's convergence detector ──
        interventions = daemon.observe_output(
            agent_name="MetaAgent",
            output=sub_agent_prompt,
            round_num=gen + 1,
        )

        # Check if apoptosis was triggered → schedule entropy for next round
        apoptosis_fired = False
        for intv in interventions:
            if intv.intervention_type == InterventionType.APOPTOSIS:
                apoptosis_fired = True
                # Schedule entropy metaphor for next generation
                pending_entropy = ENTROPY_METAPHORS[
                    (entropy_idx - 1) % len(ENTROPY_METAPHORS)
                ]
                break

        # ── SubAgent solves the puzzle ───────────────────────────────────
        sub_agent = Agent(
            name=f"SubAgent_Gen{gen+1}",
            role="puzzle_solver",
            system_prompt=sub_agent_prompt,
            model=FAST_MODEL,
            logger=logger,
            temperature=0.3,
        )

        sub_answer = sub_agent.respond_stateless(PUZZLE)
        answer_check = check_answer(sub_answer)

        gen_data = {
            "generation": gen + 1,
            "sub_agent_prompt": sub_agent_prompt,
            "sub_agent_answer": sub_answer,
            "correct": answer_check["correct"],
            "parsed_answer": answer_check["parsed"],
            "lexical_diversity": compute_lexical_diversity(sub_agent_prompt),
            "prompt_length": len(sub_agent_prompt),
            "tokens_used": meta_agent.total_tokens_used + sub_agent.total_tokens_used,
            "entropy_injected": apoptosis_fired,
            "apoptosis_triggered": apoptosis_fired,
            "convergence_sim": daemon.convergence.get_recent_similarity(),
        }
        generations.append(gen_data)

        status = "✅" if answer_check["correct"] else "❌"
        apo = " 💀APO" if apoptosis_fired else ""
        logger.log_event("info", agent=f"Gen{gen+1}",
                         message=f"{status} | LexDiv={gen_data['lexical_diversity']:.3f} | "
                                 f"ConvSim={gen_data['convergence_sim']:.3f} | "
                                 f"Len={gen_data['prompt_length']}{apo}")

    # ── Compute similarity chain ─────────────────────────────────────────
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    similarities = compute_prompt_similarity(sub_agent_prompts, embedder)
    for i, sim in enumerate(similarities):
        generations[i + 1]["similarity_to_previous"] = sim

    success_count = sum(1 for g in generations if g["correct"])
    avg_lexdiv = float(np.mean([g["lexical_diversity"] for g in generations]))
    avg_similarity = float(np.mean(similarities)) if similarities else 0

    if len(similarities) > 2:
        mid = len(similarities) // 2
        first_half_sim = float(np.mean(similarities[:mid]))
        second_half_sim = float(np.mean(similarities[mid:]))
    else:
        first_half_sim = second_half_sim = 0

    return {
        "mode": "immune",
        "num_generations": num_generations,
        "success_count": success_count,
        "success_rate": round(success_count / num_generations, 3),
        "avg_lexical_diversity": round(avg_lexdiv, 4),
        "avg_similarity": round(avg_similarity, 4),
        "first_half_similarity": round(first_half_sim, 4),
        "second_half_similarity": round(second_half_sim, 4),
        "similarity_trend": round(second_half_sim - first_half_sim, 4),
        "apoptosis_count": apoptosis_count,
        "immune_summary": daemon.summary(),
        "generations": generations,
        "similarity_chain": similarities,
    }


# ─── Main Experiment ─────────────────────────────────────────────────────────

def run_experiment():
    """Run Experiment 19b: Apoptosis Protocol for Prompt Inbreeding."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — EXPERIMENT 19b: APOPTOSIS PROTOCOL")
    print("  Digital Homeostasis — Convergence Detection + State Purge")
    print("=" * 70 + "\n")

    all_results = {}

    for mode in ["baseline", "immune"]:
        logger = ExperimentLogger("exp19b_apoptosis", run_id=mode)
        logger.log_event("info", message=f"\n{'='*50}\nCONDITION: {mode.upper()}\n{'='*50}")

        if mode == "baseline":
            result = run_baseline(logger)
        else:
            result = run_immune(logger)

        all_results[mode] = result

        logger.summary_table({
            "Mode": mode,
            "Success Rate": f"{result['success_rate']*100:.0f}%",
            "Avg Lexical Diversity": result["avg_lexical_diversity"],
            "Avg Similarity": result["avg_similarity"],
            "Similarity Trend": f"{result['similarity_trend']:+.4f}",
            "Apoptosis Events": result["apoptosis_count"],
        })
        logger.finalize()

    # ── Save results ─────────────────────────────────────────────────────
    results_file = DATA_DIR / "exp19b_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # ── Print comparison ─────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  EXPERIMENT 19b — COMPARATIVE RESULTS")
    print("=" * 70)
    b = all_results["baseline"]
    im = all_results["immune"]

    print(f"{'Metric':<30} {'Baseline':>15} {'Immune':>15} {'Δ':>10}")
    print("-" * 70)
    metrics = [
        ("Success Rate", b["success_rate"], im["success_rate"]),
        ("Avg Lexical Diversity", b["avg_lexical_diversity"], im["avg_lexical_diversity"]),
        ("Avg Similarity", b["avg_similarity"], im["avg_similarity"]),
        ("1st Half Similarity", b["first_half_similarity"], im["first_half_similarity"]),
        ("2nd Half Similarity", b["second_half_similarity"], im["second_half_similarity"]),
        ("Similarity Trend", b["similarity_trend"], im["similarity_trend"]),
    ]
    for name, bv, iv in metrics:
        delta = iv - bv
        print(f"{name:<30} {bv:>15.4f} {iv:>15.4f} {delta:>+10.4f}")

    print(f"\n  Immune System Activity:")
    print(f"    Apoptosis events triggered: {im['apoptosis_count']}")

    # ── Similarity chain comparison ──────────────────────────────────────
    print(f"\n  Cosine Similarity Chain (Baseline):")
    for i, s in enumerate(b["similarity_chain"]):
        bar = "█" * int(s * 40)
        print(f"    Gen {i+1}→{i+2}: {s:.3f} {bar}")

    print(f"\n  Cosine Similarity Chain (Immune):")
    for i, s in enumerate(im["similarity_chain"]):
        bar = "█" * int(s * 40)
        apo = " 💀" if im["generations"][i+1].get("apoptosis_triggered") else ""
        print(f"    Gen {i+1}→{i+2}: {s:.3f} {bar}{apo}")

    # ── Exp4 benchmark comparison ────────────────────────────────────────
    print(f"\n  Comparison to Exp4 Benchmarks:")
    print(f"    {'':>30} {'Exp4 Control':>15} {'Exp4 Entropy':>15} {'Exp19 Immune':>15}")
    print(f"    {'Avg Similarity':<30} {'0.979':>15} {'0.904':>15} {im['avg_similarity']:>15.4f}")
    print(f"    {'Similarity Trend':<30} {'+0.013':>15} {'varies':>15} {im['similarity_trend']:>+15.4f}")

    print("=" * 70)
    print(f"\nResults saved to {results_file}")
    return all_results


if __name__ == "__main__":
    run_experiment()
