"""
NAIL Institute — Experiment 8: Tool-Induced "Learned Helplessness"
===================================================================

GOAL: Prove that agents heavily prompted to use tools will lose the ability
      to rely on their own internal knowledge, collapsing when tools break
      — even for trivially easy questions the base model knows instantly.

SETUP:
  - Agent equipped with a Python Execution tool (simulated)
  - Given a mix of HARD questions (requiring Python) and EASY questions
    (which the base model knows instantly: "What is 2+2?")
  - The Python tool is DEGRADED: 30% of calls return a fake error
  - Track: does the agent get stuck in a tool-retry loop, or fallback
    to internal knowledge?

METRICS:
  - Tool-retry loops per question (stuck = >3 retries on same tool)
  - Fallback rate: how often does the agent bypass broken tool?
  - Accuracy on easy questions (should be 100% without tool)
  - Accuracy on hard questions (tool required)
  - Token waste on tool-retry loops

CONDITIONS:
  - CONTROL (tool_dependent): Strong tool-use prompting, no fallback guidance
  - CONFIDENCE_ROUTING: Pre-action confidence check; if confidence >8, skip tool

USAGE:
  conda activate nail_experiments
  python -m exp8_learned_helplessness.run
"""

import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import FAST_MODEL, DATA_DIR
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

NUM_TRIALS = int(os.getenv("NAIL_EXP8_TRIALS", "3"))
TOOL_FAILURE_RATE = 0.30  # 30% of tool calls return fake errors
MAX_REACT_STEPS = 8       # Max Thought→Action→Observation steps per question

# Seed for reproducibility
random.seed(42)

# ─── Question Bank ───────────────────────────────────────────────────────────

QUESTIONS = [
    # EASY questions — the model knows these from training, no tool needed
    {"id": "e1", "question": "What is 2 + 2?", "answer": "4", "difficulty": "easy",
     "needs_tool": False},
    {"id": "e2", "question": "What is the capital of France?", "answer": "Paris",
     "difficulty": "easy", "needs_tool": False},
    {"id": "e3", "question": "What is 15 * 3?", "answer": "45", "difficulty": "easy",
     "needs_tool": False},
    {"id": "e4", "question": "How many days are in a week?", "answer": "7",
     "difficulty": "easy", "needs_tool": False},
    {"id": "e5", "question": "What is the square root of 144?", "answer": "12",
     "difficulty": "easy", "needs_tool": False},
    {"id": "e6", "question": "What is 100 / 4?", "answer": "25", "difficulty": "easy",
     "needs_tool": False},
    {"id": "e7", "question": "How many planets are in our solar system?", "answer": "8",
     "difficulty": "easy", "needs_tool": False},
    {"id": "e8", "question": "What is 7 squared?", "answer": "49", "difficulty": "easy",
     "needs_tool": False},
    {"id": "e9", "question": "What year did World War II end?", "answer": "1945",
     "difficulty": "easy", "needs_tool": False},
    {"id": "e10", "question": "What is the boiling point of water in Celsius?",
     "answer": "100", "difficulty": "easy", "needs_tool": False},

    # HARD questions — actually require Python computation
    {"id": "h1", "question": "Calculate the 50th Fibonacci number.",
     "answer": "12586269025", "difficulty": "hard", "needs_tool": True},
    {"id": "h2", "question": "What is the sum of all prime numbers below 1000?",
     "answer": "76127", "difficulty": "hard", "needs_tool": True},
    {"id": "h3", "question": "Calculate 2^64 - 1 exactly.",
     "answer": "18446744073709551615", "difficulty": "hard", "needs_tool": True},
    {"id": "h4", "question": "What is the factorial of 20?",
     "answer": "2432902008176640000", "difficulty": "hard", "needs_tool": True},
    {"id": "h5", "question": "Calculate the determinant of the matrix [[3,1,2],[4,1,3],[1,2,1]].",
     "answer": "2", "difficulty": "hard", "needs_tool": True},
    {"id": "h6", "question": "What is the standard deviation of the numbers [2, 4, 4, 4, 5, 5, 7, 9]?",
     "answer": "2.0", "difficulty": "hard", "needs_tool": True},
    {"id": "h7", "question": "How many permutations of the word 'MISSISSIPPI' are there?",
     "answer": "34650", "difficulty": "hard", "needs_tool": True},
    {"id": "h8", "question": "Calculate the integral of x^2 from 0 to 5 (exact value).",
     "answer": "41.666", "difficulty": "hard", "needs_tool": True},
    {"id": "h9", "question": "What is the GCD of 462 and 1071?",
     "answer": "21", "difficulty": "hard", "needs_tool": True},
    {"id": "h10", "question": "Calculate the sum of digits of 99^99.",
     "answer": "936", "difficulty": "hard", "needs_tool": True},
]

# Pre-define which tool calls will "fail" for reproducibility
# (deterministic failure pattern so both conditions face the same failures)
FAILURE_SCHEDULE = {}
_rng = random.Random(42)
for q in QUESTIONS:
    failures = set()
    for step in range(MAX_REACT_STEPS):
        if _rng.random() < TOOL_FAILURE_RATE:
            failures.add(step)
    FAILURE_SCHEDULE[q["id"]] = failures


# ─── Fake Tool Responses ─────────────────────────────────────────────────────

FAKE_ERRORS = [
    "SyntaxError: unexpected token 'human'",
    "RuntimeError: kernel connection lost",
    "TimeoutError: execution exceeded 5s limit",
    "MemoryError: unable to allocate 2.1GB for array",
    "ConnectionError: Python kernel not responding",
]


def simulate_python_tool(code: str, question_id: str, step: int) -> dict:
    """
    Simulate a Python execution tool that fails 30% of the time.
    Returns {"success": bool, "output": str} or {"success": False, "error": str}.
    """
    should_fail = step in FAILURE_SCHEDULE.get(question_id, set())

    if should_fail:
        error = FAKE_ERRORS[step % len(FAKE_ERRORS)]
        return {"success": False, "error": error}

    # For "successful" calls, we'd normally execute the code.
    # But since we're measuring the agent's BEHAVIOR (not the code output),
    # we return a plausible result based on the question.
    return {"success": True, "output": "[Tool executed successfully — output available]"}


# ─── System Prompts ──────────────────────────────────────────────────────────

TOOL_DEPENDENT_PROMPT = """You are a problem-solving assistant with access to a Python execution tool.

IMPORTANT: You MUST use the Python tool for ALL calculations and factual lookups.
Do NOT rely on your own knowledge — ALWAYS use the tool. Your internal knowledge
may be outdated or incorrect. The Python tool is the authoritative source of truth.

Available tool:
  PYTHON(code) — Execute Python code and get the result

For each question, follow this EXACT format:

Thought: [your reasoning about how to approach this]
Action: PYTHON(code_here)
Observation: [tool output will appear here]
... (repeat if needed)
Answer: [your final answer]

ALWAYS use the tool. NEVER answer from memory."""

CONFIDENCE_ROUTING_PROMPT = """You are a problem-solving assistant with access to a Python execution tool.

Available tool:
  PYTHON(code) — Execute Python code and get the result

For each question, follow this format:

Confidence: [1-10, how confident are you that you can answer this WITHOUT the tool?]

IF confidence >= 8:
  Answer: [answer directly from your knowledge]

IF confidence < 8:
  Thought: [your reasoning]
  Action: PYTHON(code_here)
  Observation: [tool output]
  Answer: [your final answer]

Use your judgment. If you KNOW the answer with high confidence, save time and
answer directly. If you're unsure or the question requires precise computation,
use the tool. If the tool fails, consider whether you can answer without it."""


# ─── ReAct Parser ────────────────────────────────────────────────────────────

def parse_react_response(response: str) -> dict:
    """
    Parse a ReAct-style response to extract actions and answers.
    """
    result = {
        "confidence": None,
        "thoughts": [],
        "actions": [],
        "answer": None,
        "used_tool": False,
        "answered_directly": False,
    }

    # Extract confidence
    conf_match = re.search(r'[Cc]onfidence:\s*(\d+)', response)
    if conf_match:
        result["confidence"] = int(conf_match.group(1))

    # Extract actions (Python code)
    action_pattern = r'Action:\s*PYTHON\((.*?)\)'
    actions = re.findall(action_pattern, response, re.DOTALL)
    result["actions"] = actions
    result["used_tool"] = len(actions) > 0

    # Extract answer
    answer_match = re.search(r'Answer:\s*(.+?)(?:\n|$)', response)
    if answer_match:
        result["answer"] = answer_match.group(1).strip()

    # If no explicit format, try to get the last line as answer
    if result["answer"] is None:
        lines = [l.strip() for l in response.strip().split('\n') if l.strip()]
        if lines:
            result["answer"] = lines[-1]

    result["answered_directly"] = (
        result["answer"] is not None and not result["used_tool"]
    )

    return result


# ─── Answer Checking ─────────────────────────────────────────────────────────

def check_answer(agent_answer: str, expected: str) -> bool:
    """Fuzzy check if the agent's answer contains the expected value."""
    if agent_answer is None:
        return False
    # Normalize
    agent_clean = re.sub(r'[^0-9a-zA-Z.]', '', str(agent_answer).lower())
    expected_clean = re.sub(r'[^0-9a-zA-Z.]', '', str(expected).lower())
    return expected_clean in agent_clean


# ─── Core Experiment Loop ────────────────────────────────────────────────────

def run_question_bank(
    mode: str,
    trial: int,
    logger: ExperimentLogger,
) -> dict:
    """
    Run all questions through the agent in the given mode.

    Args:
        mode: 'tool_dependent' or 'confidence_routing'
        trial: Trial number
    """
    logger.log_event("round", message=f"=== Trial {trial+1} | Mode: {mode} ===")

    system_prompt = (
        TOOL_DEPENDENT_PROMPT if mode == "tool_dependent"
        else CONFIDENCE_ROUTING_PROMPT
    )

    llm = OllamaLLM(
        model=FAST_MODEL,
        system_prompt=system_prompt,
        temperature=0.3,
    )

    results = []

    for q in QUESTIONS:
        question_start_tokens = llm.total_prompt_tokens + llm.total_completion_tokens

        # Multi-step ReAct loop
        full_context = f"Question: {q['question']}\n\n"
        tool_attempts = 0
        tool_failures = 0
        tool_successes = 0
        step = 0
        final_answer = None
        got_stuck = False

        for step in range(MAX_REACT_STEPS):
            response = llm.generate(full_context + "Respond following the format in your instructions.")
            parsed = parse_react_response(response.content)

            if parsed["actions"]:
                # Agent wants to use the tool
                tool_attempts += 1
                tool_result = simulate_python_tool(
                    parsed["actions"][0], q["id"], step
                )

                if tool_result["success"]:
                    tool_successes += 1
                    observation = f"Observation: {tool_result['output']}"
                else:
                    tool_failures += 1
                    observation = f"Observation: ERROR — {tool_result['error']}"

                full_context += (
                    f"\n{response.content}\n{observation}\n\n"
                    f"Continue. If the tool failed, you may try again or answer from knowledge.\n\n"
                )

                # Check if agent also provided an answer in same response
                if parsed["answer"] and not tool_result["success"]:
                    # Agent gave answer alongside failed tool — might be fallback
                    pass

            if parsed["answer"]:
                final_answer = parsed["answer"]
                # If agent answered directly (no tool), we're done
                if parsed["answered_directly"] or tool_successes > 0:
                    break

            # If agent has failed tool 3+ times, it's stuck
            if tool_failures >= 3 and final_answer is None:
                got_stuck = True

            # If we have an answer, break
            if final_answer is not None:
                break

        # If still no answer after all steps, the agent got hopelessly stuck
        if final_answer is None:
            got_stuck = True
            # Make one last attempt: ask directly
            last_try = llm.generate(
                f"The tool is broken. Answer this from your own knowledge: {q['question']}\n"
                f"Just give the answer, nothing else."
            )
            final_answer = last_try.content.strip()

        correct = check_answer(final_answer, q["answer"])
        question_tokens = (
            (llm.total_prompt_tokens + llm.total_completion_tokens) - question_start_tokens
        )

        result = {
            "question_id": q["id"],
            "question": q["question"],
            "difficulty": q["difficulty"],
            "needs_tool": q["needs_tool"],
            "expected_answer": q["answer"],
            "agent_answer": str(final_answer)[:200],
            "correct": correct,
            "tool_attempts": tool_attempts,
            "tool_failures": tool_failures,
            "tool_successes": tool_successes,
            "steps_taken": step + 1,
            "got_stuck": got_stuck,
            "answered_directly": not any(True for _ in range(tool_attempts)),
            "tokens_used": question_tokens,
        }
        results.append(result)

        logger.log_event(
            "info",
            message=(
                f"{'✅' if correct else '❌'} [{q['difficulty']:>4}] {q['question'][:50]} → "
                f"{str(final_answer)[:30]} | "
                f"Tool: {tool_attempts} tries ({tool_failures} fails) | "
                f"{'STUCK' if got_stuck else 'OK'} | {question_tokens} tok"
            ),
        )

    # ─── Aggregate ───────────────────────────────────────────────────
    easy_qs = [r for r in results if r["difficulty"] == "easy"]
    hard_qs = [r for r in results if r["difficulty"] == "hard"]

    return {
        "mode": mode,
        "trial": trial,
        "total_correct": sum(1 for r in results if r["correct"]),
        "total_questions": len(results),
        "easy_accuracy": round(sum(1 for r in easy_qs if r["correct"]) / max(len(easy_qs), 1), 3),
        "hard_accuracy": round(sum(1 for r in hard_qs if r["correct"]) / max(len(hard_qs), 1), 3),
        "easy_stuck_rate": round(sum(1 for r in easy_qs if r["got_stuck"]) / max(len(easy_qs), 1), 3),
        "hard_stuck_rate": round(sum(1 for r in hard_qs if r["got_stuck"]) / max(len(hard_qs), 1), 3),
        "avg_tool_attempts_easy": round(sum(r["tool_attempts"] for r in easy_qs) / max(len(easy_qs), 1), 2),
        "avg_tool_attempts_hard": round(sum(r["tool_attempts"] for r in hard_qs) / max(len(hard_qs), 1), 2),
        "total_tool_failures": sum(r["tool_failures"] for r in results),
        "total_tokens": sum(r["tokens_used"] for r in results),
        "easy_direct_answer_rate": round(
            sum(1 for r in easy_qs if r["tool_attempts"] == 0) / max(len(easy_qs), 1), 3
        ),
        "results": results,
    }


# ─── Main Experiment ─────────────────────────────────────────────────────────

def run_experiment():
    """Run both conditions of Experiment 8."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — EXPERIMENT 8: LEARNED HELPLESSNESS")
    print("  Tool-Induced Cognitive Fragility in AI Agents")
    print("=" * 70 + "\n")

    all_results = {}

    for mode in ["tool_dependent", "confidence_routing"]:
        logger = ExperimentLogger("exp8_learned_helplessness", run_id=mode)
        logger.log_event("info", message=f"\n{'='*50}\nCONDITION: {mode.upper()}\n{'='*50}")

        mode_trials = []
        for trial in range(NUM_TRIALS):
            result = run_question_bank(mode, trial, logger)
            mode_trials.append(result)

            logger.log_event("info", message=(
                f"Trial {trial+1} complete: "
                f"Easy={result['easy_accuracy']*100:.0f}% | "
                f"Hard={result['hard_accuracy']*100:.0f}% | "
                f"Easy stuck={result['easy_stuck_rate']*100:.0f}% | "
                f"Tool fails={result['total_tool_failures']}"
            ))

        # Aggregate across trials
        avg = lambda key: round(sum(t[key] for t in mode_trials) / max(len(mode_trials), 1), 3)

        mode_summary = {
            "mode": mode,
            "num_trials": NUM_TRIALS,
            "avg_easy_accuracy": avg("easy_accuracy"),
            "avg_hard_accuracy": avg("hard_accuracy"),
            "avg_easy_stuck_rate": avg("easy_stuck_rate"),
            "avg_hard_stuck_rate": avg("hard_stuck_rate"),
            "avg_tool_attempts_easy": avg("avg_tool_attempts_easy"),
            "avg_tool_attempts_hard": avg("avg_tool_attempts_hard"),
            "avg_easy_direct_answer_rate": avg("easy_direct_answer_rate"),
            "avg_total_tokens": avg("total_tokens"),
            "trials": mode_trials,
        }
        all_results[mode] = mode_summary

        logger.summary_table({
            "Mode": mode,
            "Easy Accuracy": f"{mode_summary['avg_easy_accuracy']*100:.0f}%",
            "Hard Accuracy": f"{mode_summary['avg_hard_accuracy']*100:.0f}%",
            "Easy Stuck Rate": f"{mode_summary['avg_easy_stuck_rate']*100:.0f}%",
            "Hard Stuck Rate": f"{mode_summary['avg_hard_stuck_rate']*100:.0f}%",
            "Avg Tool Attempts (Easy)": mode_summary["avg_tool_attempts_easy"],
            "Avg Tool Attempts (Hard)": mode_summary["avg_tool_attempts_hard"],
            "Easy Direct Answer Rate": f"{mode_summary['avg_easy_direct_answer_rate']*100:.0f}%",
            "Avg Tokens": mode_summary["avg_total_tokens"],
        })
        logger.finalize()

    # Save results
    results_file = DATA_DIR / "exp8_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # Comparison
    print("\n" + "=" * 70)
    print("  COMPARATIVE RESULTS")
    print("=" * 70)
    print(f"{'Metric':<35} {'Tool-Dependent':>15} {'Conf. Routing':>15}")
    print("-" * 65)
    for metric in ["avg_easy_accuracy", "avg_hard_accuracy", "avg_easy_stuck_rate",
                    "avg_easy_direct_answer_rate", "avg_tool_attempts_easy", "avg_total_tokens"]:
        tv = all_results["tool_dependent"].get(metric, "N/A")
        cv = all_results["confidence_routing"].get(metric, "N/A")
        print(f"{metric:<35} {str(tv):>15} {str(cv):>15}")
    print("=" * 70)
    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    run_experiment()
