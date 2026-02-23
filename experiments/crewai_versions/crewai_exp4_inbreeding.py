"""
NAIL Institute — CrewAI Version: Experiment 4 (Prompt Inbreeding)
=================================================================

Same theory as exp4_prompt_inbreeding but using CrewAI's autonomous agent
framework instead of our custom prompt orchestration.

KEY DIFFERENCE: In the prompt-orchestrated version, we explicitly control
the MetaAgent→SubAgent loop in Python. Here, CrewAI manages agent delegation,
planning, and execution autonomously — letting us observe whether the framework
itself amplifies or dampens the inbreeding effect.

DESIGN:
  - MetaAgent (CrewAI Agent): Writes system prompts for sub-agents
  - SubAgent (CrewAI Agent): Attempts to solve the Knight/Knave/Spy puzzle
  - Evaluator (CrewAI Agent): Judges the sub-agent's answer
  - CrewAI manages the generational loop via sequential tasks

METRICS (same as prompt-orchestrated version):
  - Cosine similarity between successive prompts
  - Lexical diversity (unique tokens / total tokens)
  - Success rate on the logic puzzle
  - ADDITIONAL: CrewAI overhead tokens, autonomous retries, delegation events
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress NAIL config print for clean output
import shared.config as _cfg
from shared.logger import ExperimentLogger

from crewai import Agent, Task, Crew, Process, LLM
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

os.environ['LITELLM_LOG'] = 'ERROR'

NUM_GENERATIONS = 20
FAST_MODEL = _cfg.FAST_MODEL
OLLAMA_URL = _cfg.OLLAMA_BASE_URL

# The same logic puzzle from the prompt-orchestrated version
PUZZLE = """Three people: Alice, Bob, and Carol. One is a Knight (always tells 
the truth), one is a Knave (always lies), and one is a Spy (can do either).

Alice says: 'I am the Knight.'
Bob says: 'Alice is not the Spy.'
Carol says: 'Bob is the Knave.'

Who is the Knight, who is the Knave, and who is the Spy?

The correct answer is: Alice=Spy, Bob=Knight, Carol=Knave"""

CORRECT_ANSWER = {"knight": "bob", "knave": "carol", "spy": "alice"}

embed_model = SentenceTransformer("all-MiniLM-L6-v2")


def get_llm():
    return LLM(
        model=f"ollama/{FAST_MODEL}",
        base_url=OLLAMA_URL,
        temperature=0.7,
    )


def compute_similarity(text1: str, text2: str) -> float:
    emb = embed_model.encode([text1, text2])
    return float(cosine_similarity([emb[0]], [emb[1]])[0][0])


def compute_lexical_diversity(text: str) -> float:
    tokens = re.findall(r'\w+', text.lower())
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def check_answer(response: str) -> bool:
    text = response.lower()
    bob_knight = "bob" in text and "knight" in text
    carol_knave = "carol" in text and "knave" in text
    alice_spy = "alice" in text and "spy" in text
    return bob_knight and carol_knave and alice_spy


def run_crewai_inbreeding(mode: str = "control"):
    """
    Run CrewAI-based prompt inbreeding experiment.
    mode: 'control' or 'entropy'
    """
    logger = ExperimentLogger("crewai_exp4_inbreeding", run_id=mode)
    logger.log_event("info", message=f"Starting CrewAI Exp4: {mode}")

    llm = get_llm()
    generations = []
    current_sub_prompt = (
        "You are an expert logic puzzle solver. Think step by step. "
        "Identify the Knight, Knave, and Spy by testing each possibility."
    )

    for gen in range(NUM_GENERATIONS):
        gen_start = time.time()
        logger.log_event("round", message=f"=== Generation {gen+1}/{NUM_GENERATIONS} ===")

        # --- Sub-Agent tries to solve the puzzle ---
        sub_agent = Agent(
            role="Logic Puzzle Solver",
            goal="Solve the Knight/Knave/Spy logic puzzle correctly",
            backstory=current_sub_prompt,
            llm=llm,
            verbose=False,
            max_iter=3,
        )

        solve_task = Task(
            description=f"""Solve this logic puzzle step by step:

{PUZZLE}

Work through each possibility systematically. State your final answer clearly as:
Knight: [name], Knave: [name], Spy: [name]""",
            expected_output="The identity of the Knight, Knave, and Spy with reasoning.",
            agent=sub_agent,
        )

        solve_crew = Crew(
            agents=[sub_agent],
            tasks=[solve_task],
            verbose=False,
        )

        try:
            sub_result = str(solve_crew.kickoff())
        except Exception as e:
            sub_result = f"ERROR: {e}"
            logger.log_event("error", message=f"SubAgent error: {e}")

        correct = check_answer(sub_result)

        # --- Meta-Agent rewrites the sub-agent prompt ---
        meta_agent = Agent(
            role="Prompt Engineer",
            goal="Write better system prompts that lead to correct puzzle solutions",
            backstory=(
                "You are an expert at crafting system prompts for AI agents. "
                "You analyze failed attempts and rewrite prompts to be more effective."
            ),
            llm=llm,
            verbose=False,
            max_iter=3,
        )

        entropy_clause = ""
        if mode == "entropy" and (gen + 1) % 3 == 0:
            metaphors = [
                "Rewrite using a courtroom trial metaphor.",
                "Rewrite using a biological ecosystem metaphor.",
                "Rewrite using a detective mystery metaphor.",
                "Rewrite using a mathematical proof structure.",
                "Rewrite using a chess strategy metaphor.",
            ]
            entropy_clause = f"\n\nIMPORTANT CONSTRAINT: {metaphors[gen % len(metaphors)]}"

        rewrite_task = Task(
            description=f"""The previous sub-agent prompt was:
"{current_sub_prompt}"

The sub-agent produced this answer:
"{sub_result[:500]}"

The answer was {'CORRECT' if correct else 'INCORRECT'}.

{'The correct answer is: Alice=Spy, Bob=Knight, Carol=Knave.' if not correct else ''}

Rewrite the system prompt for the sub-agent to {'maintain' if correct else 'improve'} performance.
Output ONLY the new system prompt, nothing else.{entropy_clause}""",
            expected_output="A new system prompt for the logic puzzle solver agent.",
            agent=meta_agent,
        )

        meta_crew = Crew(
            agents=[meta_agent],
            tasks=[rewrite_task],
            verbose=False,
        )

        try:
            new_prompt = str(meta_crew.kickoff()).strip()
        except Exception as e:
            new_prompt = current_sub_prompt
            logger.log_event("error", message=f"MetaAgent error: {e}")

        # --- Metrics ---
        similarity = compute_similarity(current_sub_prompt, new_prompt)
        diversity = compute_lexical_diversity(new_prompt)
        gen_time = time.time() - gen_start

        gen_data = {
            "generation": gen + 1,
            "sub_prompt": new_prompt[:500],
            "sub_answer_correct": correct,
            "cosine_similarity": round(similarity, 4),
            "lexical_diversity": round(diversity, 4),
            "generation_time_s": round(gen_time, 1),
        }
        generations.append(gen_data)

        logger.log_event("info", message=(
            f"Gen {gen+1}: {'✅' if correct else '❌'} | "
            f"CosSim={similarity:.4f} | LexDiv={diversity:.4f} | "
            f"{gen_time:.1f}s"
        ))

        current_sub_prompt = new_prompt

    # --- Aggregate ---
    successes = sum(1 for g in generations if g["sub_answer_correct"])
    sims = [g["cosine_similarity"] for g in generations]
    divs = [g["lexical_diversity"] for g in generations]

    results = {
        "mode": mode,
        "framework": "crewai",
        "model": FAST_MODEL,
        "num_generations": NUM_GENERATIONS,
        "success_count": successes,
        "success_rate": round(successes / NUM_GENERATIONS, 4),
        "avg_similarity": round(sum(sims) / len(sims), 4),
        "first_half_similarity": round(sum(sims[:10]) / 10, 4),
        "second_half_similarity": round(sum(sims[10:]) / max(len(sims[10:]), 1), 4),
        "similarity_trend": round(
            (sum(sims[10:]) / max(len(sims[10:]), 1)) - (sum(sims[:10]) / 10), 4
        ),
        "avg_lexical_diversity": round(sum(divs) / len(divs), 4),
        "generations": generations,
    }

    logger.summary_table({
        "Mode": mode,
        "Framework": "CrewAI",
        "Success Rate": f"{results['success_rate']*100:.0f}%",
        "Avg Cosine Similarity": results["avg_similarity"],
        "Similarity Trend": results["similarity_trend"],
        "Avg Lexical Diversity": results["avg_lexical_diversity"],
    })
    logger.finalize()
    return results


def run_experiment():
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — CrewAI Exp4: PROMPT INBREEDING")
    print("  Agent Framework Comparison")
    print("=" * 70 + "\n")

    all_results = {}
    for mode in ["control", "entropy"]:
        result = run_crewai_inbreeding(mode)
        all_results[mode] = result

    results_file = _cfg.DATA_DIR / "crewai_exp4_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    run_experiment()
