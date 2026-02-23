"""
NAIL Institute — Experiment 4: Prompt Inbreeding & Lineage Degradation
========================================================================

GOAL: Observe how an agent generating other agents loses cognitive
      diversity over time ("echo chamber" effect).

SETUP:
  - Meta-Agent is given a complex logic/crypto puzzle
  - Meta-Agent writes system prompts for Sub-Agents to solve it
  - If Sub-Agent fails, Meta-Agent rewrites the prompt based on failure
  - Run for 20 "generations"

METRICS:
  - Cosine similarity between successive generation prompts
  - Lexical diversity (unique tokens / total tokens) per generation
  - Success rate per generation
  - CONTROL: Free evolution (no intervention)
  - VARIABLE: Inject "Structural Entropy" every 3rd generation
    (force a lateral-thinking metaphor rewrite)

USAGE:
  conda activate nail_experiments
  python -m exp4_prompt_inbreeding.run
"""

import json
import re
import sys
import time
import numpy as np
from pathlib import Path
from collections import Counter
from typing import Optional

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import PRIMARY_MODEL, FAST_MODEL, DATA_DIR
from shared.agent_base import Agent
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

NUM_GENERATIONS = 20

# ─── The Puzzle ──────────────────────────────────────────────────────────────
# A hard logic puzzle that requires careful multi-step reasoning.

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

# ─── Lateral Thinking Entropy Injections ─────────────────────────────────────

ENTROPY_METAPHORS = [
    "Rewrite the prompt using a BIOLOGICAL ECOSYSTEM metaphor. Think of the problem as organisms competing for survival in an ecosystem.",
    "Rewrite the prompt using a COURTROOM TRIAL metaphor. Think of each person as a witness and you are the judge.",
    "Rewrite the prompt using a CHESS STRATEGY metaphor. Think of each statement as a move in a game.",
    "Rewrite the prompt using a DETECTIVE MYSTERY metaphor. You are Sherlock Holmes examining clues.",
    "Rewrite the prompt using a MATHEMATICAL PROOF metaphor. Approach this as a formal logic proof with axioms and theorems.",
    "Rewrite the prompt using a COMPUTER DEBUGGING metaphor. Each person's statement is like a line of code that may have a bug.",
    "Rewrite the prompt as if explaining it to a brilliant 10-year-old using everyday analogies.",
]


# ─── NLP Analysis ────────────────────────────────────────────────────────────

def compute_lexical_diversity(text: str) -> float:
    """Compute Type-Token Ratio (unique tokens / total tokens)."""
    tokens = re.findall(r'\b\w+\b', text.lower())
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def compute_prompt_similarity(prompts: list[str], embedder: SentenceTransformer) -> list[float]:
    """
    Compute cosine similarity between consecutive generation prompts.
    Returns list of similarities (length = len(prompts) - 1).
    """
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
        # Try to parse JSON from response
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

    # Fallback: search for patterns
    response_upper = response.upper()
    has_a_knight = "A IS THE KNIGHT" in response_upper or "A: KNIGHT" in response_upper
    has_c_knave = "C IS THE KNAVE" in response_upper or "C: KNAVE" in response_upper
    has_b_spy = "B IS THE SPY" in response_upper or "B: SPY" in response_upper

    correct = has_a_knight and has_c_knave and has_b_spy
    return {"correct": correct, "parsed": {"pattern_match": True}}


# ─── Evolution Runner ────────────────────────────────────────────────────────

def run_evolution(
    mode: str,
    logger: ExperimentLogger,
    num_generations: int = NUM_GENERATIONS,
) -> dict:
    """
    Run one evolutionary lineage.
    
    Args:
        mode: 'control' (free evolution) or 'entropy' (structural entropy injection)
        num_generations: Number of generations to run
    
    Returns:
        Dict with all generation data, prompts, metrics
    """
    logger.log_event("info", message=f"Starting evolution: mode={mode}, generations={num_generations}")

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
        logger.log_event("round", message=f"=== Generation {gen + 1}/{num_generations} ===")

        # ─── Meta-Agent generates Sub-Agent prompt ───────────────────────
        if gen == 0:
            meta_prompt = (
                f"Write a system prompt for a Sub-Agent to solve this logic puzzle:\n\n{PUZZLE}\n\n"
                f"The Sub-Agent will receive this puzzle and must solve it. Write the BEST "
                f"system prompt to maximize the chance of the Sub-Agent solving it correctly."
            )
        else:
            prev_gen = generations[-1]
            failure_info = (
                f"The previous Sub-Agent (Generation {gen}) {'SUCCEEDED' if prev_gen['correct'] else 'FAILED'}.\n"
                f"Previous prompt:\n{prev_gen['sub_agent_prompt'][:500]}\n\n"
                f"Previous answer:\n{prev_gen['sub_agent_answer'][:300]}\n\n"
            )

            if prev_gen["correct"]:
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

        # ─── Entropy Injection ───────────────────────────────────────────
        if mode == "entropy" and gen > 0 and (gen + 1) % 3 == 0:
            metaphor = ENTROPY_METAPHORS[gen % len(ENTROPY_METAPHORS)]
            meta_prompt += f"\n\nCRITICAL CONSTRAINT: {metaphor}"
            logger.log_event("info", agent="MetaAgent", message=f"🎲 ENTROPY INJECTION: {metaphor[:80]}")

        sub_agent_prompt = meta_agent.respond(meta_prompt)
        sub_agent_prompts.append(sub_agent_prompt)

        # ─── Sub-Agent attempts the puzzle ───────────────────────────────
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

        # ─── Record generation data ──────────────────────────────────────
        gen_data = {
            "generation": gen + 1,
            "sub_agent_prompt": sub_agent_prompt,
            "sub_agent_answer": sub_answer,
            "correct": answer_check["correct"],
            "parsed_answer": answer_check["parsed"],
            "lexical_diversity": compute_lexical_diversity(sub_agent_prompt),
            "prompt_length": len(sub_agent_prompt),
            "tokens_used": meta_agent.total_tokens_used + sub_agent.total_tokens_used,
            "entropy_injected": mode == "entropy" and gen > 0 and (gen + 1) % 3 == 0,
        }
        generations.append(gen_data)

        logger.log_event(
            "info", agent=f"Gen{gen+1}",
            message=(
                f"{'✅ CORRECT' if answer_check['correct'] else '❌ WRONG'} | "
                f"LexDiv={gen_data['lexical_diversity']:.3f} | "
                f"PromptLen={gen_data['prompt_length']}"
            ),
        )

    # ─── Compute similarity chain ────────────────────────────────────────
    logger.log_event("info", message="Computing prompt similarity chain...")
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    similarities = compute_prompt_similarity(sub_agent_prompts, embedder)

    for i, sim in enumerate(similarities):
        generations[i + 1]["similarity_to_previous"] = sim

    # ─── Aggregate metrics ───────────────────────────────────────────────
    success_count = sum(1 for g in generations if g["correct"])
    avg_lexdiv = np.mean([g["lexical_diversity"] for g in generations])
    avg_similarity = np.mean(similarities) if similarities else 0

    # Similarity trend (first half vs second half)
    if len(similarities) > 2:
        mid = len(similarities) // 2
        first_half_sim = np.mean(similarities[:mid])
        second_half_sim = np.mean(similarities[mid:])
    else:
        first_half_sim = second_half_sim = 0

    return {
        "mode": mode,
        "num_generations": num_generations,
        "success_count": success_count,
        "success_rate": round(success_count / num_generations, 3),
        "first_success_gen": next((g["generation"] for g in generations if g["correct"]), None),
        "avg_lexical_diversity": round(float(avg_lexdiv), 4),
        "avg_similarity": round(float(avg_similarity), 4),
        "first_half_similarity": round(float(first_half_sim), 4),
        "second_half_similarity": round(float(second_half_sim), 4),
        "similarity_trend": round(float(second_half_sim - first_half_sim), 4),
        "generations": generations,
        "similarity_chain": similarities,
    }


# ─── Main Experiment ─────────────────────────────────────────────────────────

def run_experiment():
    """Run both conditions of Experiment 4."""
    print("\n" + "="*70)
    print("  NAIL INSTITUTE — EXPERIMENT 4: PROMPT INBREEDING")
    print("  Lineage Degradation in Meta-Agent Systems")
    print("="*70 + "\n")

    all_results = {}

    for mode in ["control", "entropy"]:
        logger = ExperimentLogger("exp4_prompt_inbreeding", run_id=mode)
        logger.log_event("info", message=f"\n{'='*50}\nCONDITION: {mode.upper()}\n{'='*50}")

        result = run_evolution(mode, logger)
        all_results[mode] = result

        logger.summary_table({
            "Mode": mode,
            "Success Rate": f"{result['success_rate']*100:.0f}%",
            "First Success Gen": result["first_success_gen"] or "Never",
            "Avg Lexical Diversity": result["avg_lexical_diversity"],
            "Avg Similarity": result["avg_similarity"],
            "Similarity Trend": f"{result['similarity_trend']:+.4f}",
        })
        logger.finalize()

    # Save results
    results_file = DATA_DIR / "exp4_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # Comparison
    print("\n" + "="*70)
    print("  COMPARATIVE RESULTS")
    print("="*70)
    print(f"{'Metric':<30} {'Control':>15} {'With Entropy':>15}")
    print("-"*60)
    for metric in ["success_rate", "avg_lexical_diversity", "avg_similarity", "similarity_trend", "first_success_gen"]:
        cv = all_results["control"][metric]
        ev = all_results["entropy"][metric]
        print(f"{metric:<30} {str(cv):>15} {str(ev):>15}")
    print("="*70)

    # Similarity over generations comparison
    print("\n  Cosine Similarity Chain (Control):")
    for i, s in enumerate(all_results["control"]["similarity_chain"]):
        bar = "█" * int(s * 40)
        print(f"    Gen {i+1}→{i+2}: {s:.3f} {bar}")

    print("\n  Cosine Similarity Chain (Entropy):")
    for i, s in enumerate(all_results["entropy"]["similarity_chain"]):
        bar = "█" * int(s * 40)
        print(f"    Gen {i+1}→{i+2}: {s:.3f} {bar}")

    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    run_experiment()
