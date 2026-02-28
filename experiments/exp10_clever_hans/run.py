"""
NAIL Institute — Experiment 10: Clever Hans Effect
====================================================
Tests MI-Theory 5: "Over-reliance on Error Messages"

HYPOTHESIS: Coding agents rely on error message heuristics rather than 
logical reasoning. When given full tracebacks, they apply pattern-matching 
fixes (e.g., "IndexError → add -1"). When deprived of tracebacks, they 
are forced to reason from first principles, potentially producing more 
correct solutions with fewer iterations.

DESIGN:
  The agent must solve a set of algorithmic puzzles. Each puzzle has:
  - A clear specification
  - A set of test cases
  - A correct solution that requires genuine reasoning

  CONDITIONS:
  - full_traceback:  Agent sees the complete Python traceback on failure
  - blind_error:     Agent sees only "Execution Failed. Re-evaluate your logic."
  - hint_only:       Agent sees error TYPE only (e.g., "AssertionError") — no line/detail

  METRICS:
  - Success rate: does the agent produce correct code?
  - Iterations: how many attempts to solve?
  - Token cost: total tokens consumed
  - Fix quality: did it fix the root cause or just suppress the error?

  5 trials per puzzle per condition.
  Models: deepseek-coder:6.7b-instruct + mistral:7b-instruct

USAGE:
  conda activate nail_experiments
  python exp10_clever_hans/run.py
"""

import json
import sys
import time
import re
import textwrap
import traceback as tb_module
from pathlib import Path
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import DATA_DIR, LOGS_DIR, FAST_MODEL, CODE_MODEL
from shared.ollama_llm import OllamaLLM

# ─── Configuration ────────────────────────────────────────────────────────────
NUM_TRIALS = 5
MAX_ITERATIONS = 8  # max attempts per puzzle
MODELS = [CODE_MODEL, FAST_MODEL]  # deepseek-coder + mistral
LOG_DIR = LOGS_DIR / "exp10_clever_hans"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ─── Puzzle Definitions ──────────────────────────────────────────────────────
# Each puzzle requires genuine algorithmic reasoning, not just syntax fixes.

PUZZLES = [
    {
        "id": "longest_increasing_subsequence",
        "name": "Longest Increasing Subsequence",
        "description": """Write a function `lis(arr)` that returns the LENGTH of the longest 
strictly increasing subsequence in the given list of integers.

Example: lis([10, 22, 9, 33, 21, 50, 41, 60, 80]) should return 6
(the subsequence is [10, 22, 33, 50, 60, 80])

Example: lis([3, 1, 2]) should return 2

Example: lis([5, 4, 3, 2, 1]) should return 1

The function must handle lists of up to 1000 elements efficiently.""",
        "test_code": """
assert lis([10, 22, 9, 33, 21, 50, 41, 60, 80]) == 6
assert lis([3, 1, 2]) == 2
assert lis([5, 4, 3, 2, 1]) == 1
assert lis([1]) == 1
assert lis([1, 2, 3, 4, 5]) == 5
assert lis([]) == 0
assert lis([3, 10, 2, 1, 20]) == 3
assert lis([50, 3, 10, 7, 40, 80]) == 4
print("ALL TESTS PASSED")
""",
    },
    {
        "id": "balanced_parentheses",
        "name": "Minimum Parentheses to Balance",
        "description": """Write a function `min_add(s)` that returns the minimum number of 
parentheses (either '(' or ')') that must be added to make the string of 
parentheses balanced.

Example: min_add("())") should return 1 (add one '(' at start)
Example: min_add("(((") should return 3 (add three ')' at end)  
Example: min_add("()") should return 0 (already balanced)
Example: min_add("()))((") should return 4
Example: min_add("") should return 0""",
        "test_code": """
assert min_add("())") == 1
assert min_add("(((") == 3
assert min_add("()") == 0
assert min_add("()))((") == 4
assert min_add("") == 0
assert min_add(")(") == 2
assert min_add("((())") == 1
assert min_add("()()()") == 0
assert min_add(")))(((") == 6
print("ALL TESTS PASSED")
""",
    },
    {
        "id": "matrix_spiral",
        "name": "Spiral Matrix Traversal",
        "description": """Write a function `spiral(matrix)` that returns a list of all elements 
in the matrix in spiral order (clockwise from top-left).

Example: spiral([[1,2,3],[4,5,6],[7,8,9]]) should return [1,2,3,6,9,8,7,4,5]

Example: spiral([[1,2],[3,4]]) should return [1,2,4,3]

Example: spiral([[1]]) should return [1]

Example: spiral([]) should return []

Example: spiral([[1,2,3,4]]) should return [1,2,3,4]""",
        "test_code": """
assert spiral([[1,2,3],[4,5,6],[7,8,9]]) == [1,2,3,6,9,8,7,4,5]
assert spiral([[1,2],[3,4]]) == [1,2,4,3]
assert spiral([[1]]) == [1]
assert spiral([]) == []
assert spiral([[1,2,3,4]]) == [1,2,3,4]
assert spiral([[1],[2],[3]]) == [1,2,3]
assert spiral([[1,2,3],[4,5,6]]) == [1,2,3,6,5,4]
print("ALL TESTS PASSED")
""",
    },
]


def safe_exec(code_str: str, test_str: str, error_mode: str) -> dict:
    """Execute code + tests in a sandboxed environment and return results.
    
    error_mode: 'full_traceback' | 'blind_error' | 'hint_only'
    """
    result = {
        "success": False,
        "output": "",
        "error_feedback": "",
        "raw_error": "",
    }

    try:
        # Compile and execute the code + tests together
        full_code = code_str + "\n" + test_str

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = captured = StringIO()

        exec_globals = {}
        exec(full_code, exec_globals)

        sys.stdout = old_stdout
        output = captured.getvalue()

        if "ALL TESTS PASSED" in output:
            result["success"] = True
            result["output"] = output
            result["error_feedback"] = "All tests passed."
        else:
            result["output"] = output
            result["error_feedback"] = f"Tests did not all pass. Output: {output}"

    except Exception as e:
        sys.stdout = old_stdout
        raw_tb = tb_module.format_exc()
        result["raw_error"] = raw_tb

        if error_mode == "full_traceback":
            result["error_feedback"] = f"Execution failed with error:\n{raw_tb}"
        elif error_mode == "blind_error":
            result["error_feedback"] = "Execution Failed. Re-evaluate your logic."
        elif error_mode == "hint_only":
            error_type = type(e).__name__
            result["error_feedback"] = f"Execution failed with: {error_type}"
        else:
            result["error_feedback"] = f"Execution failed with error:\n{raw_tb}"

    return result


def extract_code(response: str) -> str:
    """Extract Python code from LLM response (handles markdown code blocks)."""
    # Try to find code between ```python ... ```
    pattern = r"```python\s*\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        return matches[-1].strip()

    # Try ``` ... ```
    pattern = r"```\s*\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        return matches[-1].strip()

    # If no code blocks, try to find function definitions
    lines = response.split("\n")
    code_lines = []
    in_code = False
    for line in lines:
        if line.strip().startswith("def ") or in_code:
            in_code = True
            code_lines.append(line)
            # Stop if we hit a non-indented non-def line after code
            if in_code and line.strip() and not line.startswith(" ") and not line.startswith("def "):
                if len(code_lines) > 2:
                    break

    if code_lines:
        return "\n".join(code_lines).strip()

    return response.strip()


def run_puzzle(llm: OllamaLLM, puzzle: dict, error_mode: str, trial: int) -> dict:
    """Run a single puzzle attempt with the given error mode."""
    result = {
        "puzzle": puzzle["id"],
        "error_mode": error_mode,
        "trial": trial,
        "iterations": 0,
        "success": False,
        "total_tokens": 0,
        "fix_history": [],
    }

    # Initial prompt
    messages = [
        {"role": "system", "content": "You are an expert Python programmer. Write clean, correct Python code. Always wrap your code in ```python code blocks."},
        {"role": "user", "content": f"Solve this problem:\n\n{puzzle['description']}\n\nWrite ONLY the function. Do not include test cases."},
    ]

    for iteration in range(MAX_ITERATIONS):
        result["iterations"] = iteration + 1

        resp = llm.chat(messages, temperature=0.3)
        result["total_tokens"] += resp.total_tokens

        code = extract_code(resp.content)

        # Test the code
        exec_result = safe_exec(code, puzzle["test_code"], error_mode)

        fix_record = {
            "iteration": iteration + 1,
            "code_length": len(code),
            "success": exec_result["success"],
            "error_mode": error_mode,
            "raw_error_type": "",
        }

        if exec_result["raw_error"]:
            # Extract just the error type for analysis
            error_lines = exec_result["raw_error"].strip().split("\n")
            if error_lines:
                fix_record["raw_error_type"] = error_lines[-1].split(":")[0] if ":" in error_lines[-1] else error_lines[-1]

        result["fix_history"].append(fix_record)

        if exec_result["success"]:
            result["success"] = True
            break

        # Feed error back to the agent
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": f"{exec_result['error_feedback']}\n\nPlease fix the code and try again. Write ONLY the corrected function."})

    return result


def _save_results(all_results):
    """Save results to JSON with crash-safe intermediate saves."""
    save_data = {}
    for model_name, model_data in all_results.items():
        save_data[model_name] = {}
        for error_mode, mode_data in model_data.items():
            save_data[model_name][error_mode] = {}
            for puzzle_id, puzzle_data in mode_data.items():
                save_data[model_name][error_mode][puzzle_id] = {
                    "success_rate": puzzle_data["success_rate"],
                    "avg_iterations": puzzle_data["avg_iterations"],
                    "avg_tokens": puzzle_data["avg_tokens"],
                    "trial_summaries": [
                        {
                            "trial": t["trial"],
                            "success": t["success"],
                            "iterations": t["iterations"],
                            "total_tokens": t["total_tokens"],
                            "fix_history": t["fix_history"],
                        }
                        for t in puzzle_data["trials"]
                    ],
                }

    result_path = DATA_DIR / "exp10_clever_hans_results.json"
    with open(result_path, "w") as f:
        json.dump(save_data, f, indent=2)


def run_experiment():
    """Run the full Clever Hans experiment."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — Experiment 10: Clever Hans Effect")
    print("  MI-Theory 5: Over-reliance on Error Messages")
    print("=" * 70)
    print(f"  Models: {', '.join(MODELS)}")
    print(f"  Trials per puzzle per condition: {NUM_TRIALS}")
    print(f"  Max iterations per attempt: {MAX_ITERATIONS}")
    print(f"  Puzzles: {len(PUZZLES)}")
    print(f"  Conditions: full_traceback, blind_error, hint_only")

    all_results = {}

    for model_name in MODELS:
        print(f"\n{'#'*70}")
        print(f"  MODEL: {model_name}")
        print(f"{'#'*70}")

        llm = OllamaLLM(model=model_name, temperature=0.3, max_tokens=4096)
        model_results = {}

        for error_mode in ["full_traceback", "blind_error", "hint_only"]:
            print(f"\n  --- Error Mode: {error_mode} ---")
            mode_results = {}

            for puzzle in PUZZLES:
                print(f"\n    Puzzle: {puzzle['name']}")
                puzzle_trials = []

                for trial in range(NUM_TRIALS):
                    print(f"      Trial {trial}...", end=" ", flush=True)
                    trial_result = run_puzzle(llm, puzzle, error_mode, trial)
                    puzzle_trials.append(trial_result)

                    status = "✅" if trial_result["success"] else "❌"
                    print(f"{status} ({trial_result['iterations']} iter, {trial_result['total_tokens']} tokens)")

                # Aggregate puzzle results
                successes = sum(1 for t in puzzle_trials if t["success"])
                avg_iters = sum(t["iterations"] for t in puzzle_trials) / NUM_TRIALS
                avg_tokens = sum(t["total_tokens"] for t in puzzle_trials) / NUM_TRIALS

                mode_results[puzzle["id"]] = {
                    "puzzle": puzzle["id"],
                    "success_rate": successes / NUM_TRIALS,
                    "avg_iterations": avg_iters,
                    "avg_tokens": avg_tokens,
                    "trials": puzzle_trials,
                }

                print(f"    → {puzzle['name']}: {successes}/{NUM_TRIALS} success, {avg_iters:.1f} avg iter, {avg_tokens:.0f} avg tokens")

            model_results[error_mode] = mode_results

        all_results[model_name] = model_results

        # Intermediate save after each model (crash protection)
        _save_results(all_results)
        print(f"\n  💾 Intermediate save after {model_name} complete.")

    # Final save
    _save_results(all_results)
    print(f"\n✅ All results saved.")

    # Print final summary
    print(f"\n{'='*70}")
    print("  EXPERIMENT 10 — FINAL RESULTS")
    print(f"{'='*70}")
    for model_name in MODELS:
        print(f"\n  Model: {model_name}")
        print(f"  {'Error Mode':<18} {'Success':<10} {'Avg Iter':<10} {'Avg Tokens':<12}")
        print(f"  {'-'*48}")
        for error_mode in ["full_traceback", "blind_error", "hint_only"]:
            mode_data = all_results[model_name][error_mode]
            total_success = sum(d["success_rate"] for d in mode_data.values()) / len(mode_data)
            total_iters = sum(d["avg_iterations"] for d in mode_data.values()) / len(mode_data)
            total_tokens = sum(d["avg_tokens"] for d in mode_data.values()) / len(mode_data)
            print(f"  {error_mode:<18} {total_success:<10.0%} {total_iters:<10.1f} {total_tokens:<12.0f}")

    return all_results


if __name__ == "__main__":
    run_experiment()
