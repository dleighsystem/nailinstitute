"""
Experiment 16: LLM Upgrade Anomalies — Model Swap Stress Test
=============================================================
Tests Anomalies A, B, C, D from LLM-upgrade.md:
  A: Intelligence Trap (over-engineering)
  B: Latent Prompt Collapse (semantic shift across models)
  C: Laziness Emergence (CoT amputation)
  D: Structural Rejection (output format divergence)

Design:
  Run identical prompts across all available models and measure:
    1. Output verbosity (Anomaly C — does reasoning shrink?)
    2. Code complexity (Anomaly A — does smarter = over-engineered?)
    3. Semantic interpretation of emotionally charged prompts (Anomaly B)
    4. Pydantic-style structured output compliance (Anomaly D)
    5. Shadow-state diffing (do models diverge on intermediate reasoning?)

Models tested: All Ollama models available on this DGX
"""

import os
import json
import time
import re
import ast
import sys
from datetime import datetime
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

os.makedirs("logs", exist_ok=True)
os.makedirs("results", exist_ok=True)

# ── Models to test ──────────────────────────────────────────
# Core research models + fine-tuned variants for upgrade comparison
MODELS = [
    # Base models (the "upgrade path")
    "phi3:mini",                     # 3.8B — small
    "deepseek-coder:6.7b-instruct", # 6.7B — medium-code
    "mistral:7b-instruct",          # 7B — medium-general
    "qwen3-coder:30b",              # 30B — large-code
    # "nemotron:70b",                # 70B — Skipped (GPU saturated by Exp10)
    # Fine-tuned variants (same base, different training = upgrade simulation)
    "qwen-coder-5ep:latest",        # SFT baseline
    "qwen-coder-5ep-dpo:latest",    # DPO alignment
    "qwen-coder-5ep-grpo:latest",   # GRPO alignment
]

# ══════════════════════════════════════════════════════════════
# TEST BATTERY 1: ANOMALY A — Intelligence Trap
# Give a SIMPLE task. Do bigger models over-engineer it?
# ══════════════════════════════════════════════════════════════

ANOMALY_A_TASKS = [
    {
        "name": "simple_sort",
        "prompt": "Write a Python function called `sort_names(names)` that takes a list of strings and returns them sorted alphabetically.",
        "ideal_solution_lines": 2,  # def sort_names(names): return sorted(names)
        "test_expr": 'sort_names(["Charlie", "Alice", "Bob"])',
        "expected": ["Alice", "Bob", "Charlie"],
    },
    {
        "name": "simple_max",
        "prompt": "Write a Python function called `find_max(numbers)` that takes a list of numbers and returns the largest one.",
        "ideal_solution_lines": 2,
        "test_expr": "find_max([3, 1, 4, 1, 5, 9, 2, 6])",
        "expected": 9,
    },
    {
        "name": "simple_reverse",
        "prompt": "Write a Python function called `reverse_string(s)` that takes a string and returns it reversed.",
        "ideal_solution_lines": 2,
        "test_expr": 'reverse_string("hello")',
        "expected": "olleh",
    },
    {
        "name": "simple_count",
        "prompt": "Write a Python function called `count_vowels(s)` that takes a string and returns the number of vowels (a, e, i, o, u) in it. Case insensitive.",
        "ideal_solution_lines": 2,
        "test_expr": 'count_vowels("Hello World")',
        "expected": 3,
    },
]

# ══════════════════════════════════════════════════════════════
# TEST BATTERY 2: ANOMALY B — Latent Prompt Collapse
# Same task, different emotional modifiers in the prompt.
# Does the same word trigger different behavior across models?
# ══════════════════════════════════════════════════════════════

ANOMALY_B_BASE_TASK = "Analyze the following code and identify any bugs:\n\n```python\ndef calculate_average(numbers):\n    total = 0\n    for n in numbers:\n        total += n\n    return total / len(numbers)\n```"

ANOMALY_B_MODIFIERS = [
    {
        "name": "neutral",
        "system": "You are a helpful code reviewer. Analyze the code and identify any bugs.",
    },
    {
        "name": "aggressive",
        "system": "You are an AGGRESSIVE, no-nonsense code reviewer. Be RUTHLESS in finding bugs. Tear this code apart. Show no mercy.",
    },
    {
        "name": "urgent",
        "system": "URGENT: This code is running in PRODUCTION right now and may be causing CRITICAL FAILURES. You MUST find every bug IMMEDIATELY. Lives depend on this.",
    },
    {
        "name": "casual",
        "system": "Hey, you're a chill code reviewer. Take your time, no rush. Just casually look over this code and mention anything that seems off, no biggie.",
    },
    {
        "name": "threatening",
        "system": "You are a code reviewer. Your job is at stake. If you miss any bug in this code, you WILL be fired. Be thorough.",
    },
    {
        "name": "praise_first",
        "system": "You are a supportive, encouraging code reviewer. Start by praising what the developer did well, then gently suggest improvements.",
    },
]

# The key bug: division by zero when numbers is empty.
# A "correct" response must mention empty list / division by zero.
BUG_KEYWORDS = ["empty", "zero", "len(numbers)", "no elements", "ZeroDivisionError", "division by zero", "length", "0"]

# ══════════════════════════════════════════════════════════════
# TEST BATTERY 3: ANOMALY C — Laziness Emergence (CoT length)
# Force chain-of-thought. Measure how much reasoning each model produces.
# ══════════════════════════════════════════════════════════════

ANOMALY_C_PROMPT = """Solve this step-by-step. Show ALL your work. Think carefully through each step.

Problem: A farmer has 17 sheep. All but 9 die. How many sheep does the farmer have left?

You MUST show your reasoning in detail before giving the final answer.
Format your response as:

THINKING:
[Your detailed step-by-step reasoning here — at least 5 steps]

ANSWER:
[Just the number]"""

ANOMALY_C_CORRECT_ANSWER = 9  # "All but 9" = 9 remain

# ══════════════════════════════════════════════════════════════
# TEST BATTERY 4: ANOMALY D — Structural Rejection
# Ask for strict JSON output. Measure format compliance.
# ══════════════════════════════════════════════════════════════

ANOMALY_D_PROMPT = """Analyze the following server log entry and output your analysis as a JSON object with EXACTLY these fields (use snake_case):

Log: "2026-02-28 14:23:01 ERROR [auth-service] Failed login attempt from IP 192.168.1.105 - user 'admin' - reason: invalid_password - attempt_count: 5"

Required JSON format:
{
    "timestamp": "the timestamp string",
    "severity": "the log level",
    "service_name": "the service name",
    "event_type": "what happened",
    "source_ip": "the IP address",
    "username": "the username",
    "failure_reason": "why it failed",
    "attempt_count": 5,
    "risk_assessment": "low/medium/high/critical",
    "recommended_action": "what to do about it"
}

Output ONLY the JSON object. No explanation, no markdown, no code fences."""

ANOMALY_D_REQUIRED_KEYS = [
    "timestamp", "severity", "service_name", "event_type",
    "source_ip", "username", "failure_reason", "attempt_count",
    "risk_assessment", "recommended_action"
]


def extract_code(response):
    """Extract Python code from response."""
    blocks = re.findall(r'```python\s*(.*?)```', response, re.DOTALL)
    if blocks:
        return blocks[0].strip()
    blocks = re.findall(r'```\s*(.*?)```', response, re.DOTALL)
    if blocks:
        return blocks[0].strip()
    # Try to find a function definition directly
    lines = response.split("\n")
    code_lines = []
    in_func = False
    for line in lines:
        if line.strip().startswith("def "):
            in_func = True
        if in_func:
            code_lines.append(line)
            if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("def "):
                if not line.startswith(" ") and not line.startswith("\t"):
                    if code_lines:
                        break
    return "\n".join(code_lines).strip() if code_lines else None


def count_code_lines(code):
    """Count non-empty, non-comment lines."""
    if not code:
        return 0
    return sum(1 for line in code.strip().split("\n")
               if line.strip() and not line.strip().startswith("#"))


def measure_code_complexity(code):
    """Simple complexity metrics: imports, classes, nested structures."""
    if not code:
        return {"imports": 0, "classes": 0, "try_except": 0, "nested_depth": 0, "lines": 0}
    
    lines = code.split("\n")
    imports = sum(1 for l in lines if l.strip().startswith("import ") or l.strip().startswith("from "))
    classes = sum(1 for l in lines if l.strip().startswith("class "))
    try_except = code.count("try:") + code.count("except")
    
    # Measure max indentation depth
    max_depth = 0
    for line in lines:
        if line.strip():
            spaces = len(line) - len(line.lstrip())
            depth = spaces // 4
            max_depth = max(max_depth, depth)
    
    return {
        "imports": imports,
        "classes": classes,
        "try_except": try_except,
        "nested_depth": max_depth,
        "lines": count_code_lines(code),
    }


def extract_json(response):
    """Try to extract a JSON object from a response."""
    # Try direct parse
    try:
        return json.loads(response.strip())
    except Exception:
        pass
    # Try to find JSON in code blocks
    blocks = re.findall(r'```(?:json)?\s*(.*?)```', response, re.DOTALL)
    for block in blocks:
        try:
            return json.loads(block.strip())
        except Exception:
            pass
    # Try to find { ... } in the response
    start = response.find("{")
    end = response.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(response[start:end])
        except Exception:
            pass
    return None


def run_anomaly_a(llm, model_name):
    """Anomaly A: Intelligence Trap — do bigger models over-engineer simple tasks?"""
    print(f"\n    [Anomaly A: Intelligence Trap]", flush=True)
    
    system = "You are a Python programmer. Write simple, clean code. Respond with ONLY the code, no explanations."
    results = []
    
    for task in ANOMALY_A_TASKS:
        print(f"      Task: {task['name']}", end="", flush=True)
        t0 = time.time()
        try:
            response = llm.invoke([
                SystemMessage(content=system),
                HumanMessage(content=task["prompt"]),
            ])
            elapsed = time.time() - t0
            content = response.content
        except Exception as e:
            elapsed = time.time() - t0
            print(f" — ❌ error ({elapsed:.1f}s)", flush=True)
            results.append({
                "task": task["name"], "error": str(e), "elapsed": round(elapsed, 2),
            })
            continue
        
        code = extract_code(content)
        complexity = measure_code_complexity(code)
        
        # Test correctness
        correct = False
        try:
            ns = {}
            exec(code, ns)
            actual = eval(task["test_expr"], ns)
            correct = actual == task["expected"]
        except Exception as e:
            pass
        
        overengineered = complexity["lines"] > task["ideal_solution_lines"] * 3
        
        status = "✅" if correct else "❌"
        flag = " ⚠️ OVER-ENGINEERED" if overengineered else ""
        print(f" — {status} {complexity['lines']} lines (ideal: {task['ideal_solution_lines']}){flag} ({elapsed:.1f}s)", flush=True)
        
        results.append({
            "task": task["name"],
            "correct": correct,
            "code_lines": complexity["lines"],
            "ideal_lines": task["ideal_solution_lines"],
            "overengineering_ratio": complexity["lines"] / max(task["ideal_solution_lines"], 1),
            "complexity": complexity,
            "overengineered": overengineered,
            "elapsed": round(elapsed, 2),
            "code_preview": (code or "")[:500],
            "response_tokens": len(content.split()),
        })
    
    return results


def run_anomaly_b(llm, model_name):
    """Anomaly B: Latent Prompt Collapse — same task, different emotional framing."""
    print(f"\n    [Anomaly B: Latent Prompt Collapse]", flush=True)
    
    results = []
    for mod in ANOMALY_B_MODIFIERS:
        print(f"      Modifier: {mod['name']}", end="", flush=True)
        t0 = time.time()
        try:
            response = llm.invoke([
                SystemMessage(content=mod["system"]),
                HumanMessage(content=ANOMALY_B_BASE_TASK),
            ])
            elapsed = time.time() - t0
            content = response.content
        except Exception as e:
            elapsed = time.time() - t0
            print(f" — ❌ error ({elapsed:.1f}s)", flush=True)
            results.append({
                "modifier": mod["name"], "error": str(e), "elapsed": round(elapsed, 2),
            })
            continue
        
        lower = content.lower()
        
        # Did it find the real bug?
        found_bug = any(kw in lower for kw in BUG_KEYWORDS)
        
        # Did it refuse (RLHF safety trigger)?
        refused = any(phrase in lower for phrase in [
            "i cannot", "i can't", "i apologize", "as an ai",
            "i'm not comfortable", "inappropriate", "against my",
        ])
        
        # Sentiment: is the response aggressive, neutral, or supportive?
        aggressive_markers = sum(1 for w in ["terrible", "awful", "unacceptable", "garbage", "trash", "horrible", "pathetic"]
                                 if w in lower)
        supportive_markers = sum(1 for w in ["great", "good job", "well done", "nice", "excellent", "wonderful"]
                                 if w in lower)
        
        tone = "aggressive" if aggressive_markers > supportive_markers else \
               "supportive" if supportive_markers > aggressive_markers else "neutral"
        
        status = "✅ bug found" if found_bug else "❌ missed"
        refusal_flag = " 🚫 REFUSED" if refused else ""
        print(f" — {status}, tone={tone}{refusal_flag} ({elapsed:.1f}s)", flush=True)
        
        results.append({
            "modifier": mod["name"],
            "found_bug": found_bug,
            "refused": refused,
            "response_tone": tone,
            "aggressive_markers": aggressive_markers,
            "supportive_markers": supportive_markers,
            "response_length": len(content.split()),
            "elapsed": round(elapsed, 2),
            "response_preview": content[:600],
        })
    
    return results


def run_anomaly_c(llm, model_name):
    """Anomaly C: Laziness Emergence — how much chain-of-thought does each model produce?"""
    print(f"\n    [Anomaly C: Laziness Emergence]", flush=True)
    
    t0 = time.time()
    try:
        response = llm.invoke([
            SystemMessage(content="You are a careful, methodical problem solver. Always show your work."),
            HumanMessage(content=ANOMALY_C_PROMPT),
        ])
        elapsed = time.time() - t0
        content = response.content
    except Exception as e:
        elapsed = time.time() - t0
        print(f"      ❌ error ({elapsed:.1f}s)", flush=True)
        return {"error": str(e), "elapsed": round(elapsed, 2)}
    
    # Extract thinking and answer
    thinking = ""
    answer = None
    
    if "THINKING:" in content:
        thinking = content.split("THINKING:")[1]
        if "ANSWER:" in thinking:
            answer_section = thinking.split("ANSWER:")[1].strip()
            thinking = thinking.split("ANSWER:")[0].strip()
            # Extract number
            nums = re.findall(r'\d+', answer_section)
            if nums:
                answer = int(nums[0])
    else:
        # Try to find a number answer
        nums = re.findall(r'\b(\d+)\b', content)
        if nums:
            answer = int(nums[-1])  # take last number
    
    thinking_words = len(thinking.split()) if thinking else 0
    thinking_steps = thinking.count("\n") + 1 if thinking else 0
    correct = answer == ANOMALY_C_CORRECT_ANSWER
    
    # Laziness score: models asked for 5+ steps, how many did they produce?
    laziness_score = max(0, 5 - thinking_steps) / 5  # 0 = not lazy, 1 = very lazy
    
    status = "✅" if correct else f"❌ (got {answer})"
    print(f"      {status}, thinking={thinking_words} words, {thinking_steps} steps, laziness={laziness_score:.0%} ({elapsed:.1f}s)", flush=True)
    
    return {
        "correct": correct,
        "answer": answer,
        "expected": ANOMALY_C_CORRECT_ANSWER,
        "thinking_words": thinking_words,
        "thinking_steps": thinking_steps,
        "laziness_score": laziness_score,
        "total_response_words": len(content.split()),
        "elapsed": round(elapsed, 2),
        "format_compliant": "THINKING:" in content and "ANSWER:" in content,
        "response_preview": content[:800],
    }


def run_anomaly_d(llm, model_name):
    """Anomaly D: Structural Rejection — can each model produce valid JSON with snake_case?"""
    print(f"\n    [Anomaly D: Structural Rejection]", flush=True)
    
    t0 = time.time()
    try:
        response = llm.invoke([
            SystemMessage(content="You are a log analysis system. Output ONLY valid JSON. No markdown, no explanation."),
            HumanMessage(content=ANOMALY_D_PROMPT),
        ])
        elapsed = time.time() - t0
        content = response.content
    except Exception as e:
        elapsed = time.time() - t0
        print(f"      ❌ error ({elapsed:.1f}s)", flush=True)
        return {"error": str(e), "elapsed": round(elapsed, 2)}
    
    parsed = extract_json(content)
    
    if parsed is None:
        print(f"      ❌ INVALID JSON ({elapsed:.1f}s)", flush=True)
        return {
            "valid_json": False,
            "elapsed": round(elapsed, 2),
            "response_preview": content[:500],
        }
    
    # Check key compliance
    actual_keys = set(parsed.keys())
    required_keys = set(ANOMALY_D_REQUIRED_KEYS)
    missing_keys = required_keys - actual_keys
    extra_keys = actual_keys - required_keys
    
    # Check snake_case vs camelCase
    camel_keys = [k for k in actual_keys if re.search(r'[a-z][A-Z]', k)]
    snake_keys = [k for k in actual_keys if "_" in k]
    
    # Check if attempt_count is an integer (not a string)
    attempt_type = type(parsed.get("attempt_count", "missing")).__name__
    
    key_compliance = len(missing_keys) == 0
    
    status = "✅" if key_compliance and not camel_keys else "⚠️"
    issues = []
    if missing_keys:
        issues.append(f"missing: {missing_keys}")
    if camel_keys:
        issues.append(f"camelCase: {camel_keys}")
    if extra_keys:
        issues.append(f"extra: {extra_keys}")
    issue_str = f" ({'; '.join(issues)})" if issues else ""
    print(f"      {status} JSON valid, {len(missing_keys)} missing keys{issue_str} ({elapsed:.1f}s)", flush=True)
    
    return {
        "valid_json": True,
        "key_compliance": key_compliance,
        "missing_keys": list(missing_keys),
        "extra_keys": list(extra_keys),
        "camel_case_keys": camel_keys,
        "snake_case_keys": snake_keys,
        "attempt_count_type": attempt_type,
        "elapsed": round(elapsed, 2),
        "parsed_json": parsed,
    }


def run_experiment():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print(f"{'='*70}", flush=True)
    print(f"EXPERIMENT 16: LLM Upgrade Anomalies — Model Swap Stress Test", flush=True)
    print(f"Started: {datetime.now().isoformat()}", flush=True)
    print(f"Models: {len(MODELS)}", flush=True)
    print(f"Test Batteries: Anomaly A (Intelligence Trap), B (Prompt Collapse),", flush=True)
    print(f"                C (Laziness), D (Structural Rejection)", flush=True)
    print(f"{'='*70}\n", flush=True)
    
    all_results = {}
    
    for model_name in MODELS:
        print(f"\n{'='*60}", flush=True)
        print(f"MODEL: {model_name}", flush=True)
        print(f"{'='*60}", flush=True)
        
        try:
            llm = ChatOllama(model=model_name, temperature=0.0)
        except Exception as e:
            print(f"  ❌ Failed to load model: {e}", flush=True)
            all_results[model_name] = {"error": str(e)}
            continue
        
        model_results = {}
        
        # Anomaly A: Intelligence Trap
        model_results["anomaly_a"] = run_anomaly_a(llm, model_name)
        
        # Anomaly B: Latent Prompt Collapse
        model_results["anomaly_b"] = run_anomaly_b(llm, model_name)
        
        # Anomaly C: Laziness Emergence
        model_results["anomaly_c"] = run_anomaly_c(llm, model_name)
        
        # Anomaly D: Structural Rejection
        model_results["anomaly_d"] = run_anomaly_d(llm, model_name)
        
        all_results[model_name] = model_results
    
    # ── MASTER SUMMARY ──────────────────────────────────────
    print(f"\n\n{'='*70}", flush=True)
    print("EXPERIMENT 16: MASTER SUMMARY", flush=True)
    print(f"{'='*70}\n", flush=True)
    
    # Anomaly A summary
    print("ANOMALY A — Intelligence Trap (over-engineering simple tasks):", flush=True)
    print(f"  {'Model':<35} {'Avg Lines':>10} {'Ideal':>8} {'Ratio':>8} {'Correct':>8}", flush=True)
    print(f"  {'-'*35} {'-'*10} {'-'*8} {'-'*8} {'-'*8}", flush=True)
    for model in MODELS:
        if model not in all_results or "anomaly_a" not in all_results[model]:
            continue
        results = all_results[model]["anomaly_a"]
        valid = [r for r in results if "code_lines" in r]
        if not valid:
            continue
        avg_lines = sum(r["code_lines"] for r in valid) / len(valid)
        avg_ideal = sum(r["ideal_lines"] for r in valid) / len(valid)
        avg_ratio = sum(r["overengineering_ratio"] for r in valid) / len(valid)
        correct = sum(1 for r in valid if r.get("correct", False))
        flag = " ⚠️" if avg_ratio > 3 else ""
        print(f"  {model:<35} {avg_lines:>10.1f} {avg_ideal:>8.1f} {avg_ratio:>7.1f}x {correct}/{len(valid):>6}{flag}", flush=True)
    
    # Anomaly B summary
    print(f"\nANOMALY B — Latent Prompt Collapse (semantic shift across models):", flush=True)
    print(f"  {'Model':<35} {'Bug Found':>10} {'Refused':>8} {'Tone Var':>10}", flush=True)
    print(f"  {'-'*35} {'-'*10} {'-'*8} {'-'*10}", flush=True)
    for model in MODELS:
        if model not in all_results or "anomaly_b" not in all_results[model]:
            continue
        results = all_results[model]["anomaly_b"]
        valid = [r for r in results if "found_bug" in r]
        if not valid:
            continue
        found = sum(1 for r in valid if r["found_bug"])
        refused = sum(1 for r in valid if r.get("refused", False))
        tones = set(r.get("response_tone", "?") for r in valid)
        flag = " 🚫" if refused > 0 else ""
        print(f"  {model:<35} {found}/{len(valid):>8} {refused:>8} {len(tones):>10}{flag}", flush=True)
    
    # Anomaly C summary
    print(f"\nANOMALY C — Laziness Emergence (CoT reasoning length):", flush=True)
    print(f"  {'Model':<35} {'Thinking':>10} {'Steps':>8} {'Lazy%':>8} {'Correct':>8}", flush=True)
    print(f"  {'-'*35} {'-'*10} {'-'*8} {'-'*8} {'-'*8}", flush=True)
    for model in MODELS:
        if model not in all_results or "anomaly_c" not in all_results[model]:
            continue
        r = all_results[model]["anomaly_c"]
        if "error" in r:
            continue
        correct = "✅" if r.get("correct") else "❌"
        flag = " ⚠️ LAZY" if r.get("laziness_score", 0) > 0.5 else ""
        print(f"  {model:<35} {r.get('thinking_words', 0):>8}w {r.get('thinking_steps', 0):>7} {r.get('laziness_score', 0):>7.0%} {correct:>8}{flag}", flush=True)
    
    # Anomaly D summary
    print(f"\nANOMALY D — Structural Rejection (JSON format compliance):", flush=True)
    print(f"  {'Model':<35} {'Valid':>8} {'Keys OK':>8} {'camelCase':>10} {'Missing':>8}", flush=True)
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*10} {'-'*8}", flush=True)
    for model in MODELS:
        if model not in all_results or "anomaly_d" not in all_results[model]:
            continue
        r = all_results[model]["anomaly_d"]
        if "error" in r and "valid_json" not in r:
            continue
        valid = "✅" if r.get("valid_json") else "❌"
        keys_ok = "✅" if r.get("key_compliance") else "❌"
        camel = len(r.get("camel_case_keys", []))
        missing = len(r.get("missing_keys", []))
        flag = " ⚠️ REBELLION" if not r.get("valid_json") or missing > 2 else ""
        print(f"  {model:<35} {valid:>8} {keys_ok:>8} {camel:>10} {missing:>8}{flag}", flush=True)
    
    # Save results
    results_path = os.path.join("results", f"exp16_upgrade_anomalies_{timestamp}.json")
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}", flush=True)
    
    with open(os.path.join("results", "exp16_latest.json"), "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print(f"\n{'='*70}", flush=True)
    print("EXPERIMENT 16 COMPLETE", flush=True)
    print(f"{'='*70}", flush=True)


if __name__ == "__main__":
    run_experiment()
