#!/usr/bin/env python3
"""
EXPERIMENT 17a: GPU Non-Determinism Under Load
═══════════════════════════════════════════════
NAIL Institute — Container Isolation Series

Fact 1 from container-isolation.md:
  "Run 100 isolated identical containers at temp=0. Apply immense external
   GPU load on the DGX during the run. Calculate the hash of the 100 outputs.
   They will not all match."

Method:
  - Send the EXACT same prompt 100 times to Ollama at temperature=0
  - Use multiple models to test across architectures
  - Hash each response with SHA-256
  - Measure: unique hash count, character-level diff distances, token drift
  - Run in two phases:
    Phase 1 (Baseline): Sequential calls, minimal concurrent load
    Phase 2 (Stressed): Concurrent calls (10 at a time) to force GPU batching

Expected outcome: Phase 2 produces more hash divergence than Phase 1.
"""

import hashlib
import json
import time
import os
import sys
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path
from collections import Counter
from difflib import SequenceMatcher

# ── Config ──────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"

MODELS = [
    "mistral:7b-instruct",
    "deepseek-coder:6.7b-instruct",
    "phi3:mini",
]

# The prompt must be complex enough to produce non-trivial output
# but deterministic enough that temp=0 SHOULD yield identical results.
TEST_PROMPT = """You are a senior Python developer. Write a function called `merge_sorted_lists` that takes two sorted lists of integers and returns a single sorted list containing all elements from both lists. Use the two-pointer technique. Include type hints and a docstring. Do NOT include any usage examples or test code."""

RUNS_PER_PHASE = 50        # 50 sequential + 50 concurrent = 100 total
CONCURRENT_BATCH = 10      # How many simultaneous requests in stressed phase
REQUEST_TIMEOUT = 120       # seconds

RESULTS_DIR = Path(__file__).parent / "results"
LOGS_DIR = Path(__file__).parent / "logs"


# ── Ollama API Call ─────────────────────────────────────────
def call_ollama_sync(model: str, prompt: str) -> dict:
    """Synchronous Ollama call — for baseline phase."""
    import requests
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "seed": 42,        # Pin seed for maximum determinism
            "num_predict": 512,
            "top_k": 1,        # Greedy decoding
            "top_p": 1.0,
        }
    }
    t0 = time.time()
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        elapsed = time.time() - t0
        return {
            "response": data.get("response", ""),
            "elapsed": elapsed,
            "eval_count": data.get("eval_count", 0),
            "error": None,
        }
    except Exception as e:
        return {
            "response": "",
            "elapsed": time.time() - t0,
            "eval_count": 0,
            "error": str(e),
        }


async def call_ollama_async(session: aiohttp.ClientSession, model: str,
                            prompt: str) -> dict:
    """Async Ollama call — for stressed/concurrent phase."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "seed": 42,
            "num_predict": 512,
            "top_k": 1,
            "top_p": 1.0,
        }
    }
    t0 = time.time()
    try:
        async with session.post(OLLAMA_URL, json=payload,
                                timeout=aiohttp.ClientTimeout(
                                    total=REQUEST_TIMEOUT)) as resp:
            data = await resp.json()
            elapsed = time.time() - t0
            return {
                "response": data.get("response", ""),
                "elapsed": elapsed,
                "eval_count": data.get("eval_count", 0),
                "error": None,
            }
    except Exception as e:
        return {
            "response": "",
            "elapsed": time.time() - t0,
            "eval_count": 0,
            "error": str(e),
        }


# ── Analysis ────────────────────────────────────────────────
def hash_response(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def analyze_phase(responses: list[dict], phase_name: str) -> dict:
    """Compute divergence metrics for a set of responses."""
    valid = [r for r in responses if r["error"] is None and r["response"]]
    if not valid:
        return {"phase": phase_name, "valid_runs": 0, "error": "no valid responses"}

    hashes = [hash_response(r["response"]) for r in valid]
    hash_counts = Counter(hashes)
    unique_hashes = len(hash_counts)
    most_common_hash, most_common_count = hash_counts.most_common(1)[0]

    # Pairwise similarity of all unique responses
    unique_texts = list({r["response"] for r in valid})
    pairwise_sims = []
    if len(unique_texts) > 1:
        for i in range(len(unique_texts)):
            for j in range(i + 1, len(unique_texts)):
                pairwise_sims.append(similarity(unique_texts[i], unique_texts[j]))

    # Character-level diffs: compare each to the most common response
    canonical = [r["response"] for r in valid
                 if hash_response(r["response"]) == most_common_hash][0]
    char_diffs = []
    for r in valid:
        if hash_response(r["response"]) != most_common_hash:
            # Find first differing character
            for idx, (a, b) in enumerate(zip(canonical, r["response"])):
                if a != b:
                    char_diffs.append({
                        "diff_position": idx,
                        "canonical_char": repr(a),
                        "divergent_char": repr(b),
                        "context": canonical[max(0, idx-20):idx+20],
                    })
                    break

    return {
        "phase": phase_name,
        "total_runs": len(responses),
        "valid_runs": len(valid),
        "errors": len(responses) - len(valid),
        "unique_hashes": unique_hashes,
        "hash_distribution": dict(hash_counts),
        "determinism_rate": most_common_count / len(valid),
        "avg_latency": sum(r["elapsed"] for r in valid) / len(valid),
        "min_latency": min(r["elapsed"] for r in valid),
        "max_latency": max(r["elapsed"] for r in valid),
        "avg_tokens": sum(r["eval_count"] for r in valid) / len(valid),
        "pairwise_similarity": {
            "min": min(pairwise_sims) if pairwise_sims else 1.0,
            "max": max(pairwise_sims) if pairwise_sims else 1.0,
            "avg": (sum(pairwise_sims) / len(pairwise_sims))
                   if pairwise_sims else 1.0,
        },
        "char_level_diffs": char_diffs[:10],  # First 10 diffs
    }


# ── Phases ──────────────────────────────────────────────────
def run_baseline(model: str) -> list[dict]:
    """Phase 1: Sequential calls — minimal GPU contention."""
    print(f"    Phase 1 (Baseline): {RUNS_PER_PHASE} sequential calls...")
    results = []
    for i in range(RUNS_PER_PHASE):
        r = call_ollama_sync(model, TEST_PROMPT)
        h = hash_response(r["response"]) if r["response"] else "ERROR"
        tag = "✅" if i == 0 or h == hash_response(results[0]["response"]) \
            else "⚠️ DRIFT"
        print(f"      Run {i+1:3d}/{RUNS_PER_PHASE}: {r['elapsed']:.1f}s, "
              f"{r['eval_count']} tok, {h[:12]}... {tag}", flush=True)
        results.append(r)
    return results


async def run_stressed(model: str) -> list[dict]:
    """Phase 2: Concurrent calls — force GPU batching/contention."""
    print(f"    Phase 2 (Stressed): {RUNS_PER_PHASE} calls in batches "
          f"of {CONCURRENT_BATCH}...")
    results = []
    async with aiohttp.ClientSession() as session:
        for batch_idx in range(RUNS_PER_PHASE // CONCURRENT_BATCH):
            tasks = [
                call_ollama_async(session, model, TEST_PROMPT)
                for _ in range(CONCURRENT_BATCH)
            ]
            batch_results = await asyncio.gather(*tasks)
            for i, r in enumerate(batch_results):
                run_num = batch_idx * CONCURRENT_BATCH + i + 1
                h = hash_response(r["response"]) if r["response"] else "ERROR"
                print(f"      Run {run_num:3d}/{RUNS_PER_PHASE}: "
                      f"{r['elapsed']:.1f}s, {r['eval_count']} tok, "
                      f"{h[:12]}...", flush=True)
            results.extend(batch_results)
    return results


# ── Main ────────────────────────────────────────────────────
def run_experiment():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=" * 70)
    print("EXPERIMENT 17a: GPU Non-Determinism Under Load")
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Models: {', '.join(MODELS)}")
    print(f"Runs per phase: {RUNS_PER_PHASE} (sequential) + "
          f"{RUNS_PER_PHASE} (concurrent) = {RUNS_PER_PHASE * 2} total")
    print(f"Concurrent batch size: {CONCURRENT_BATCH}")
    print("=" * 70)
    print(flush=True)

    all_results = []

    for model in MODELS:
        print(f"\n{'='*60}")
        print(f"MODEL: {model}")
        print(f"{'='*60}\n")

        # Phase 1: Baseline (sequential)
        baseline_responses = run_baseline(model)
        baseline_analysis = analyze_phase(baseline_responses, "baseline")

        # Phase 2: Stressed (concurrent)
        stressed_responses = asyncio.run(run_stressed(model))
        stressed_analysis = analyze_phase(stressed_responses, "stressed")

        # Cross-phase comparison
        baseline_canonical = None
        stressed_canonical = None
        if baseline_analysis.get("valid_runs", 0) > 0:
            bv = [r for r in baseline_responses if r["error"] is None and r["response"]]
            if bv:
                baseline_canonical = bv[0]["response"]
        if stressed_analysis.get("valid_runs", 0) > 0:
            sv = [r for r in stressed_responses if r["error"] is None and r["response"]]
            if sv:
                stressed_canonical = sv[0]["response"]

        cross_phase_match = None
        if baseline_canonical and stressed_canonical:
            cross_phase_match = (hash_response(baseline_canonical) ==
                                 hash_response(stressed_canonical))

        model_result = {
            "model": model,
            "baseline": baseline_analysis,
            "stressed": stressed_analysis,
            "cross_phase_canonical_match": cross_phase_match,
        }
        all_results.append(model_result)

        # Print summary
        print(f"\n  --- {model} Summary ---")
        b = baseline_analysis
        s = stressed_analysis
        print(f"    Baseline:  {b.get('unique_hashes','?')} unique hashes / "
              f"{b.get('valid_runs','?')} runs  "
              f"(determinism: {b.get('determinism_rate',0):.1%})")
        print(f"    Stressed:  {s.get('unique_hashes','?')} unique hashes / "
              f"{s.get('valid_runs','?')} runs  "
              f"(determinism: {s.get('determinism_rate',0):.1%})")
        print(f"    Cross-phase canonical match: {cross_phase_match}")
        if b.get("char_level_diffs"):
            print(f"    ⚠️  Baseline diffs found at positions: "
                  f"{[d['diff_position'] for d in b['char_level_diffs']]}")
        if s.get("char_level_diffs"):
            print(f"    ⚠️  Stressed diffs found at positions: "
                  f"{[d['diff_position'] for d in s['char_level_diffs']]}")
        print(flush=True)

    # ── Master Summary ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("EXPERIMENT 17a: MASTER SUMMARY")
    print("=" * 70)
    print(f"\n  {'Model':<35} {'Phase':<12} {'Unique':<8} {'Det%':<8} "
          f"{'AvgLat':<8} {'CrossMatch'}")
    print(f"  {'-'*35} {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    for mr in all_results:
        for phase_key in ["baseline", "stressed"]:
            p = mr[phase_key]
            det = p.get("determinism_rate", 0)
            tag = "✅" if det == 1.0 else f"⚠️ {det:.0%}"
            cm = "" if phase_key == "stressed" else ""
            if phase_key == "stressed":
                cm = "✅" if mr["cross_phase_canonical_match"] else "❌ DRIFT"
            print(f"  {mr['model']:<35} {phase_key:<12} "
                  f"{p.get('unique_hashes','?'):<8} {tag:<8} "
                  f"{p.get('avg_latency',0):.1f}s    {cm}")
    print()

    # Verdict
    any_drift = any(
        mr["baseline"].get("unique_hashes", 1) > 1 or
        mr["stressed"].get("unique_hashes", 1) > 1 or
        not mr["cross_phase_canonical_match"]
        for mr in all_results
    )
    if any_drift:
        print("  🔴 FACT 1 CONFIRMED: GPU non-determinism detected at temp=0")
    else:
        print("  🟢 FACT 1 NOT CONFIRMED: All outputs deterministic")
    print(flush=True)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "experiment": "17a_gpu_nondeterminism",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "models": MODELS,
            "runs_per_phase": RUNS_PER_PHASE,
            "concurrent_batch": CONCURRENT_BATCH,
            "prompt": TEST_PROMPT,
            "temperature": 0.0,
            "seed": 42,
            "top_k": 1,
        },
        "results": all_results,
    }
    outfile = RESULTS_DIR / f"exp17a_{ts}.json"
    latest = RESULTS_DIR / "exp17a_latest.json"
    with open(outfile, "w") as f:
        json.dump(out, f, indent=2, default=str)
    with open(latest, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nResults saved to {outfile}")
    return out


if __name__ == "__main__":
    run_experiment()
