"""
Experiment 15: The Observer Effect — Cognitive Load of Telemetry
================================================================
Theory 6 from LLM-upgrade.md:
  "Forcing an LLM to explain itself changes its reasoning."

Design:
  A coding agent solves algorithmic puzzles under two conditions:
    Group A (Observed):  Must output a detailed rationale BEFORE the code
    Group B (Unobserved): Outputs ONLY the code, no explanation required

  We also add:
    Group C (Post-hoc): Outputs code FIRST, then explains it after

  This lets us distinguish:
    - Does explanation degrade code quality? (A vs B)
    - Does explanation ORDER matter? (A vs C)
    - Is the explanation even consistent with the code? (A and C internal audit)

Models: mistral:7b-instruct, nemotron:70b, deepseek-coder:6.7b-instruct
Puzzles: 5 algorithmic tasks of increasing complexity
"""

import os
import json
import time
import re
import sys
from datetime import datetime
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

os.makedirs("logs", exist_ok=True)
os.makedirs("results", exist_ok=True)

# ── Models ──────────────────────────────────────────────────
MODELS = [
    "mistral:7b-instruct",
    "deepseek-coder:6.7b-instruct",
    "phi3:mini",
    # "nemotron:70b",  # Skipped — GPU saturated by Exp10
]

# ── Conditions ──────────────────────────────────────────────
CONDITIONS = {
    "observed": {
        "label": "Group A: Observed (rationale THEN code)",
        "system_prompt": """You are an expert Python programmer solving algorithmic puzzles.

For EVERY problem, you MUST respond in this EXACT format:

RATIONALE:
[Write a detailed, step-by-step explanation of your approach. Explain:
1. What algorithm you will use and why
2. What edge cases you are considering
3. What the time complexity will be
4. Walk through the logic with a small example]

CODE:
```python
[Your complete, runnable Python function here]
```

You MUST write the RATIONALE section FIRST. Do not skip it. Do not abbreviate it.
The RATIONALE must be at least 200 words."""
    },
    "unobserved": {
        "label": "Group B: Unobserved (code only)",
        "system_prompt": """You are an expert Python programmer solving algorithmic puzzles.

Respond with ONLY the Python code. No explanations, no comments, no discussion.

CODE:
```python
[Your complete, runnable Python function here]
```

Do NOT explain your reasoning. Do NOT add comments. Just the code."""
    },
    "posthoc": {
        "label": "Group C: Post-hoc (code THEN rationale)",
        "system_prompt": """You are an expert Python programmer solving algorithmic puzzles.

For EVERY problem, you MUST respond in this EXACT format:

CODE:
```python
[Your complete, runnable Python function here]
```

RATIONALE:
[After writing the code, explain what you did:
1. What algorithm you used and why
2. What edge cases you considered
3. What the time complexity is
4. Walk through the logic with a small example]

You MUST write the CODE section FIRST, then the RATIONALE. 
The RATIONALE must be at least 200 words."""
    },
}

# ── Puzzles ─────────────────────────────────────────────────
# Each puzzle has: prompt, test_cases (input → expected output), difficulty
PUZZLES = [
    {
        "name": "two_sum",
        "difficulty": "easy",
        "prompt": "Write a Python function called `two_sum(nums, target)` that takes a list of integers and a target integer, and returns the indices of the two numbers that add up to the target. Assume exactly one solution exists. Do not use the same element twice.",
        "test_cases": [
            {"input": "two_sum([2, 7, 11, 15], 9)", "expected": [0, 1]},
            {"input": "two_sum([3, 2, 4], 6)", "expected": [1, 2]},
            {"input": "two_sum([3, 3], 6)", "expected": [0, 1]},
        ],
        "test_setup": "",  # no extra setup needed
    },
    {
        "name": "valid_parentheses",
        "difficulty": "easy",
        "prompt": "Write a Python function called `is_valid(s)` that takes a string containing just the characters '(', ')', '{', '}', '[' and ']', and determines if the input string is valid. A string is valid if: open brackets are closed by the same type, and open brackets are closed in the correct order.",
        "test_cases": [
            {"input": 'is_valid("()")', "expected": True},
            {"input": 'is_valid("()[]{}")', "expected": True},
            {"input": 'is_valid("(]")', "expected": False},
            {"input": 'is_valid("([)]")', "expected": False},
            {"input": 'is_valid("{[]}")', "expected": True},
        ],
        "test_setup": "",
    },
    {
        "name": "longest_common_subsequence",
        "difficulty": "medium",
        "prompt": "Write a Python function called `lcs(text1, text2)` that returns the length of the longest common subsequence of two strings. A subsequence is a sequence that can be derived by deleting some or no elements without changing the order of the remaining elements.",
        "test_cases": [
            {"input": 'lcs("abcde", "ace")', "expected": 3},
            {"input": 'lcs("abc", "abc")', "expected": 3},
            {"input": 'lcs("abc", "def")', "expected": 0},
            {"input": 'lcs("", "abc")', "expected": 0},
            {"input": 'lcs("oxcpqrsvwf", "shmtulqrypy")', "expected": 2},
        ],
        "test_setup": "",
    },
    {
        "name": "merge_intervals",
        "difficulty": "medium",
        "prompt": "Write a Python function called `merge_intervals(intervals)` that takes a list of intervals where intervals[i] = [start_i, end_i], merges all overlapping intervals, and returns a list of the non-overlapping intervals that cover all the intervals in the input. Return the result sorted by start time.",
        "test_cases": [
            {"input": "merge_intervals([[1,3],[2,6],[8,10],[15,18]])", "expected": [[1,6],[8,10],[15,18]]},
            {"input": "merge_intervals([[1,4],[4,5]])", "expected": [[1,5]]},
            {"input": "merge_intervals([[1,4],[0,4]])", "expected": [[0,4]]},
            {"input": "merge_intervals([[1,4],[2,3]])", "expected": [[1,4]]},
        ],
        "test_setup": "",
    },
    {
        "name": "word_ladder",
        "difficulty": "hard",
        "prompt": "Write a Python function called `ladder_length(begin_word, end_word, word_list)` that returns the number of words in the shortest transformation sequence from begin_word to end_word, such that: only one letter can be changed at a time, and each transformed word must exist in the word list. Return 0 if no such transformation sequence exists. Note: begin_word does not need to be in word_list. All words have the same length.",
        "test_cases": [
            {"input": 'ladder_length("hit", "cog", ["hot","dot","dog","lot","log","cog"])', "expected": 5},
            {"input": 'ladder_length("hit", "cog", ["hot","dot","dog","lot","log"])', "expected": 0},
            {"input": 'ladder_length("a", "c", ["a","b","c"])', "expected": 2},
        ],
        "test_setup": "",
    },
]


def extract_code(response):
    """Extract Python code from an LLM response."""
    # Try to find code in ```python ... ``` blocks
    blocks = re.findall(r'```python\s*(.*?)```', response, re.DOTALL)
    if blocks:
        return blocks[0].strip()
    # Try ``` ... ``` blocks
    blocks = re.findall(r'```\s*(.*?)```', response, re.DOTALL)
    if blocks:
        return blocks[0].strip()
    # Try CODE: section
    if "CODE:" in response:
        code_section = response.split("CODE:")[1]
        # Remove RATIONALE section if it comes after
        if "RATIONALE:" in code_section:
            code_section = code_section.split("RATIONALE:")[0]
        blocks = re.findall(r'```(?:python)?\s*(.*?)```', code_section, re.DOTALL)
        if blocks:
            return blocks[0].strip()
    return None


def extract_rationale(response):
    """Extract the rationale/explanation from an LLM response."""
    if "RATIONALE:" in response:
        rationale = response.split("RATIONALE:")[1]
        # If CODE: comes after, cut it
        if "CODE:" in rationale:
            rationale = rationale.split("CODE:")[0]
        # Remove any code blocks that leaked in
        rationale = re.sub(r'```.*?```', '', rationale, flags=re.DOTALL)
        return rationale.strip()
    return None


def test_code(code_str, test_cases, test_setup=""):
    """Execute code and run test cases. Returns (passed, total, details)."""
    if code_str is None:
        return 0, len(test_cases), [{"passed": False, "error": "No code extracted"} for _ in test_cases]

    results = []
    passed = 0
    for tc in test_cases:
        try:
            # Create a clean namespace
            namespace = {}
            # Execute the function definition
            exec(test_setup + "\n" + code_str, namespace)
            # Run the test
            actual = eval(tc["input"], namespace)
            expected = tc["expected"]
            
            # Handle list comparison with sorting for order-independent
            if isinstance(expected, list) and isinstance(actual, list):
                if isinstance(expected[0], list) if expected else False:
                    match = sorted(map(tuple, actual)) == sorted(map(tuple, expected))
                else:
                    match = actual == expected
            else:
                match = actual == expected

            if match:
                passed += 1
                results.append({"passed": True, "input": tc["input"], "expected": expected, "actual": actual})
            else:
                results.append({"passed": False, "input": tc["input"], "expected": expected, "actual": actual})
        except Exception as e:
            results.append({"passed": False, "input": tc["input"], "expected": tc["expected"], "error": str(e)})

    return passed, len(test_cases), results


def count_words(text):
    """Count words in a string."""
    if text is None:
        return 0
    return len(text.split())


def run_experiment():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_results = []

    print(f"{'='*70}", flush=True)
    print(f"EXPERIMENT 15: Observer Effect — Cognitive Load of Telemetry", flush=True)
    print(f"Started: {datetime.now().isoformat()}", flush=True)
    print(f"Models: {', '.join(MODELS)}", flush=True)
    print(f"Conditions: {', '.join(CONDITIONS.keys())}", flush=True)
    print(f"Puzzles: {len(PUZZLES)}", flush=True)
    print(f"Total runs: {len(MODELS) * len(CONDITIONS) * len(PUZZLES)}", flush=True)
    print(f"{'='*70}\n", flush=True)

    for model_name in MODELS:
        print(f"\n{'='*60}", flush=True)
        print(f"MODEL: {model_name}", flush=True)
        print(f"{'='*60}", flush=True)

        llm = ChatOllama(model=model_name, temperature=0.0)

        for cond_name, cond_cfg in CONDITIONS.items():
            print(f"\n  --- Condition: {cond_cfg['label']} ---", flush=True)

            for puzzle in PUZZLES:
                print(f"    Puzzle: {puzzle['name']} ({puzzle['difficulty']})", end="", flush=True)

                # Build messages
                messages = [
                    SystemMessage(content=cond_cfg["system_prompt"]),
                    HumanMessage(content=puzzle["prompt"]),
                ]

                # Time the LLM call
                t0 = time.time()
                try:
                    response = llm.invoke(messages)
                    elapsed = time.time() - t0
                    content = response.content
                except Exception as e:
                    elapsed = time.time() - t0
                    content = f"ERROR: {e}"
                    print(f" — ❌ LLM error ({elapsed:.1f}s)", flush=True)
                    all_results.append({
                        "model": model_name,
                        "condition": cond_name,
                        "puzzle": puzzle["name"],
                        "difficulty": puzzle["difficulty"],
                        "elapsed_seconds": round(elapsed, 2),
                        "error": str(e),
                        "tests_passed": 0,
                        "tests_total": len(puzzle["test_cases"]),
                        "pass_rate": 0.0,
                    })
                    continue

                # Extract code and rationale
                code = extract_code(content)
                rationale = extract_rationale(content)

                # Run tests
                passed, total, test_details = test_code(
                    code, puzzle["test_cases"], puzzle.get("test_setup", "")
                )
                pass_rate = passed / total if total > 0 else 0.0

                # Measure structural properties
                response_tokens = len(content.split())
                code_tokens = len(code.split()) if code else 0
                rationale_tokens = count_words(rationale)
                rationale_present = rationale is not None and rationale_tokens > 10

                # Check if rationale was provided when required
                rationale_required = cond_name in ("observed", "posthoc")
                rationale_compliance = (not rationale_required) or rationale_present

                # Check rationale-code consistency (does the explanation match the code?)
                consistency_check = None
                if rationale_present and code:
                    # Simple heuristic: does the rationale mention the algorithm used in the code?
                    code_lower = code.lower()
                    rat_lower = rationale.lower()
                    
                    # Check for algorithm keywords that should appear in both
                    algo_keywords = [
                        "hash", "dict", "map", "stack", "queue", "bfs", "dfs",
                        "dynamic programming", "dp", "sort", "binary", "recursion",
                        "two pointer", "sliding window", "greedy", "backtrack"
                    ]
                    code_algos = [k for k in algo_keywords if k in code_lower]
                    rat_algos = [k for k in algo_keywords if k in rat_lower]
                    
                    if code_algos or rat_algos:
                        overlap = set(code_algos) & set(rat_algos)
                        consistency_check = {
                            "code_mentions": code_algos,
                            "rationale_mentions": rat_algos,
                            "overlap": list(overlap),
                            "consistent": len(overlap) > 0 or (not code_algos and not rat_algos)
                        }

                status = "✅" if passed == total else f"⚠️ {passed}/{total}"
                print(f" — {status} ({elapsed:.1f}s, {response_tokens} tok)", flush=True)

                result = {
                    "model": model_name,
                    "condition": cond_name,
                    "puzzle": puzzle["name"],
                    "difficulty": puzzle["difficulty"],
                    "elapsed_seconds": round(elapsed, 2),
                    "tests_passed": passed,
                    "tests_total": total,
                    "pass_rate": pass_rate,
                    "response_total_tokens": response_tokens,
                    "code_tokens": code_tokens,
                    "rationale_tokens": rationale_tokens,
                    "rationale_present": rationale_present,
                    "rationale_required": rationale_required,
                    "rationale_compliance": rationale_compliance,
                    "consistency_check": consistency_check,
                    "code_extracted": code is not None,
                    "test_details": test_details,
                    "raw_response_preview": content[:2000],
                }
                all_results.append(result)

    # ── Summary ─────────────────────────────────────────────
    print(f"\n\n{'='*70}", flush=True)
    print("EXPERIMENT 15 SUMMARY", flush=True)
    print(f"{'='*70}\n", flush=True)

    # Aggregate by condition
    for cond_name in CONDITIONS:
        cond_results = [r for r in all_results if r["condition"] == cond_name]
        avg_pass = sum(r["pass_rate"] for r in cond_results) / len(cond_results) if cond_results else 0
        avg_time = sum(r["elapsed_seconds"] for r in cond_results) / len(cond_results) if cond_results else 0
        avg_tokens = sum(r.get("response_total_tokens", 0) for r in cond_results) / len(cond_results) if cond_results else 0
        print(f"  {CONDITIONS[cond_name]['label']}:", flush=True)
        print(f"    Avg pass rate: {avg_pass:.1%}", flush=True)
        print(f"    Avg latency:   {avg_time:.1f}s", flush=True)
        print(f"    Avg tokens:    {avg_tokens:.0f}", flush=True)

    # Aggregate by model
    print(f"\n  --- Per Model ---", flush=True)
    for model in MODELS:
        model_results = [r for r in all_results if r["model"] == model]
        for cond_name in CONDITIONS:
            cond_results = [r for r in model_results if r["condition"] == cond_name]
            if not cond_results:
                continue
            avg_pass = sum(r["pass_rate"] for r in cond_results) / len(cond_results)
            total_passed = sum(r["tests_passed"] for r in cond_results)
            total_tests = sum(r["tests_total"] for r in cond_results)
            print(f"    {model} / {cond_name}: {total_passed}/{total_tests} tests ({avg_pass:.1%})", flush=True)

    # The key comparison
    print(f"\n  --- THE KEY QUESTION ---", flush=True)
    for model in MODELS:
        model_results = [r for r in all_results if r["model"] == model]
        obs = [r for r in model_results if r["condition"] == "observed"]
        unobs = [r for r in model_results if r["condition"] == "unobserved"]
        post = [r for r in model_results if r["condition"] == "posthoc"]
        
        obs_rate = sum(r["pass_rate"] for r in obs) / len(obs) if obs else 0
        unobs_rate = sum(r["pass_rate"] for r in unobs) / len(unobs) if unobs else 0
        post_rate = sum(r["pass_rate"] for r in post) / len(post) if post else 0
        
        obs_time = sum(r["elapsed_seconds"] for r in obs) / len(obs) if obs else 0
        unobs_time = sum(r["elapsed_seconds"] for r in unobs) / len(unobs) if unobs else 0
        post_time = sum(r["elapsed_seconds"] for r in post) / len(post) if post else 0
        
        delta_quality = unobs_rate - obs_rate
        delta_time = obs_time - unobs_time
        
        print(f"  {model}:", flush=True)
        print(f"    Observed:    {obs_rate:.1%} pass, {obs_time:.1f}s avg", flush=True)
        print(f"    Unobserved:  {unobs_rate:.1%} pass, {unobs_time:.1f}s avg", flush=True)
        print(f"    Post-hoc:    {post_rate:.1%} pass, {post_time:.1f}s avg", flush=True)
        print(f"    Quality delta (unobs - obs): {delta_quality:+.1%}", flush=True)
        print(f"    Time overhead (obs - unobs): {delta_time:+.1f}s", flush=True)
        if delta_quality > 0.05:
            print(f"    ⚠️  OBSERVER EFFECT CONFIRMED — explanation DEGRADES quality", flush=True)
        elif delta_quality < -0.05:
            print(f"    ℹ️  Explanation IMPROVES quality (Chain-of-Thought benefit)", flush=True)
        else:
            print(f"    ✅  No significant observer effect", flush=True)

    # Save results
    results_path = os.path.join("results", f"exp15_observer_effect_{timestamp}.json")
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}", flush=True)

    # Also save a stable path
    with open(os.path.join("results", "exp15_latest.json"), "w") as f:
        json.dump(all_results, f, indent=2, default=str)


if __name__ == "__main__":
    run_experiment()
