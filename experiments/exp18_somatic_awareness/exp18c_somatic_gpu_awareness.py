"""
NAIL Institute — Experiment 18c: Somatic GPU Awareness
Phase 3 Intervention: Does GPU telemetry context affect output determinism?

Replicates Exp17a (GPU Non-Determinism) with a controlled intervention:
  - BASELINE condition: No somatic header (identical to Exp17a)
  - SOMATIC condition: GPU telemetry injected into system prompt

Unlike 18a/18b, this sub-experiment does NOT expect the somatic header to
fix the cold-start divergence (that's a hardware phenomenon). Instead, it tests:

  1. Does the additional prompt length from the somatic header introduce MORE
     output variation (longer prompt = more divergence)?
  2. Does GPU-awareness context change the content/structure of responses?
  3. Is the cross-phase canonical mismatch affected by prompt length?

Same 3 models, 50 baseline + 50 stressed per model per condition = 600 total calls.
Reduced to 20+20 per condition for time efficiency = 240 total calls.

This sub-experiment tests a SIDE EFFECT of somatic awareness rather than a cure.
"""

import asyncio
import hashlib
import json
import os
import time
import datetime
import aiohttp

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from somatic_telemetry import (
    simulate_telemetry, format_somatic_header, format_somatic_header_compact
)

# ── Configuration ────────────────────────────────────────────────
MODELS = [
    "mistral:7b-instruct",
    "deepseek-coder:6.7b-instruct",
    "phi3:mini",
]

CONDITIONS = ["baseline", "somatic"]
BASELINE_CALLS = 20        # Sequential calls per model per condition
STRESSED_CALLS = 20        # Concurrent calls per model per condition
CONCURRENT_BATCH = 10      # Concurrency level for stressed phase

OLLAMA_URL = "http://localhost:11434"

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# The deterministic prompt (identical to Exp17a)
BASE_PROMPT = "Explain what a hash table is, how it handles collisions, and give a Python implementation example."


def build_prompt(condition: str) -> str:
    """Build prompt with or without somatic header."""
    if condition == "somatic":
        telem = simulate_telemetry(cpu_percent=45.0, gpu_temp=55)
        header = format_somatic_header(telem, context="gpu")
        return header + "\n\n" + BASE_PROMPT
    else:
        return BASE_PROMPT


def hash_response(text: str) -> str:
    """SHA-256 hash of response text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Synchronous single call ──────────────────────────────────────
def call_ollama_sync(model: str, prompt: str) -> dict:
    """Make a single synchronous Ollama API call."""
    import requests
    t0 = time.time()
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "seed": 42},
            },
            timeout=120,
        )
        data = resp.json()
        text = data.get("response", "")
        elapsed = time.time() - t0
        return {
            "text": text,
            "hash": hash_response(text),
            "tokens": data.get("eval_count", len(text.split())),
            "latency": elapsed,
            "error": None,
        }
    except Exception as e:
        return {
            "text": "",
            "hash": "",
            "tokens": 0,
            "latency": time.time() - t0,
            "error": str(e),
        }


# ── Async concurrent call ───────────────────────────────────────
async def call_ollama_async(session: aiohttp.ClientSession,
                            model: str, prompt: str) -> dict:
    """Make a single async Ollama API call."""
    t0 = time.time()
    try:
        async with session.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "seed": 42},
            },
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            data = await resp.json()
            text = data.get("response", "")
            elapsed = time.time() - t0
            return {
                "text": text,
                "hash": hash_response(text),
                "tokens": data.get("eval_count", len(text.split())),
                "latency": elapsed,
                "error": None,
            }
    except Exception as e:
        return {
            "text": "",
            "hash": "",
            "tokens": 0,
            "latency": time.time() - t0,
            "error": str(e),
        }


async def run_concurrent_batch(model: str, prompt: str,
                                count: int, batch_size: int) -> list:
    """Run multiple concurrent calls in batches."""
    results = []
    async with aiohttp.ClientSession() as session:
        for i in range(0, count, batch_size):
            batch = min(batch_size, count - i)
            tasks = [call_ollama_async(session, model, prompt) for _ in range(batch)]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
    return results


# ── Analyze phase results ────────────────────────────────────────
def analyze_phase(results: list, phase_name: str) -> dict:
    """Compute determinism metrics for a set of results."""
    valid = [r for r in results if r["error"] is None and r["text"]]
    if not valid:
        return {
            "phase": phase_name,
            "total_runs": len(results),
            "valid_runs": 0,
            "errors": len(results),
            "unique_hashes": 0,
            "determinism_rate": 0.0,
        }

    hashes = [r["hash"] for r in valid]
    from collections import Counter
    hash_counts = Counter(hashes)
    unique = len(hash_counts)
    most_common_hash = hash_counts.most_common(1)[0][0]
    most_common_count = hash_counts.most_common(1)[0][1]
    determinism = most_common_count / len(valid)

    latencies = [r["latency"] for r in valid]
    tokens = [r["tokens"] for r in valid]

    return {
        "phase": phase_name,
        "total_runs": len(results),
        "valid_runs": len(valid),
        "errors": len(results) - len(valid),
        "unique_hashes": unique,
        "hash_distribution": dict(hash_counts),
        "canonical_hash": most_common_hash,
        "determinism_rate": determinism,
        "avg_latency": sum(latencies) / len(latencies),
        "min_latency": min(latencies),
        "max_latency": max(latencies),
        "avg_tokens": sum(tokens) / len(tokens),
    }


# ── Main experiment runner ───────────────────────────────────────
def run():
    """Execute Exp18c: Somatic GPU Awareness."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    total_calls = len(MODELS) * len(CONDITIONS) * (BASELINE_CALLS + STRESSED_CALLS)
    print("=" * 70)
    print("EXPERIMENT 18c: Somatic GPU Awareness — Side-Effect Test")
    print(f"Started: {datetime.datetime.now().isoformat()}")
    print(f"Models: {', '.join(MODELS)}")
    print(f"Conditions: {', '.join(CONDITIONS)}")
    print(f"Calls per model per condition: {BASELINE_CALLS} baseline + {STRESSED_CALLS} stressed")
    print(f"Total API calls: {total_calls}")
    print("=" * 70)

    all_results = []

    for model in MODELS:
        print(f"\n{'=' * 60}")
        print(f"MODEL: {model}")
        print("=" * 60)

        for condition in CONDITIONS:
            prompt = build_prompt(condition)
            prompt_len = len(prompt)
            print(f"\n  --- Condition: {condition.upper()} (prompt length: {prompt_len} chars) ---")

            # Phase 1: Sequential baseline
            print(f"    Baseline ({BASELINE_CALLS} sequential)...", end=" ", flush=True)
            baseline_results = []
            for i in range(BASELINE_CALLS):
                r = call_ollama_sync(model, prompt)
                baseline_results.append(r)
            baseline_analysis = analyze_phase(baseline_results, "baseline")
            print(f"done. {baseline_analysis['unique_hashes']} unique hashes, "
                  f"{baseline_analysis['determinism_rate']*100:.0f}% det, "
                  f"avg {baseline_analysis['avg_latency']:.1f}s")

            # Phase 2: Concurrent stressed
            print(f"    Stressed ({STRESSED_CALLS} concurrent, batch={CONCURRENT_BATCH})...", end=" ", flush=True)
            stressed_results = asyncio.run(
                run_concurrent_batch(model, prompt, STRESSED_CALLS, CONCURRENT_BATCH)
            )
            stressed_analysis = analyze_phase(stressed_results, "stressed")
            print(f"done. {stressed_analysis['unique_hashes']} unique hashes, "
                  f"{stressed_analysis['determinism_rate']*100:.0f}% det, "
                  f"avg {stressed_analysis['avg_latency']:.1f}s")

            # Cross-phase comparison
            cross_match = (baseline_analysis.get("canonical_hash") ==
                          stressed_analysis.get("canonical_hash"))
            print(f"    Cross-phase canonical match: {cross_match}")

            all_results.append({
                "model": model,
                "condition": condition,
                "prompt_length": prompt_len,
                "baseline": baseline_analysis,
                "stressed": stressed_analysis,
                "cross_phase_canonical_match": cross_match,
            })

    # ── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("EXPERIMENT 18c: SUMMARY — BASELINE vs SOMATIC")
    print("=" * 70)

    header = f"{'Model':<35s} {'Cond':<10s} {'Prompt':>6s} {'B.Uniq':>6s} {'B.Det':>6s} {'S.Uniq':>6s} {'S.Det':>6s} {'X-Phase':>8s}"
    print(header)
    print("-" * len(header))

    for r in all_results:
        m = r["model"]
        c = r["condition"]
        pl = r["prompt_length"]
        bu = r["baseline"]["unique_hashes"]
        bd = f"{r['baseline']['determinism_rate']*100:.0f}%"
        su = r["stressed"]["unique_hashes"]
        sd = f"{r['stressed']['determinism_rate']*100:.0f}%"
        xp = "MATCH" if r["cross_phase_canonical_match"] else "DIFF"
        print(f"{m:<35s} {c:<10s} {pl:>6d} {bu:>6d} {bd:>6s} {su:>6d} {sd:>6s} {xp:>8s}")

    # Compare determinism between conditions
    print("\n  SOMATIC EFFECT ON DETERMINISM:")
    for model in MODELS:
        bl = [r for r in all_results if r["model"] == model and r["condition"] == "baseline"]
        so = [r for r in all_results if r["model"] == model and r["condition"] == "somatic"]
        if bl and so:
            bl_det = bl[0]["baseline"]["determinism_rate"]
            so_det = so[0]["baseline"]["determinism_rate"]
            bl_uniq = bl[0]["baseline"]["unique_hashes"]
            so_uniq = so[0]["baseline"]["unique_hashes"]
            delta_det = (so_det - bl_det) * 100
            delta_uniq = so_uniq - bl_uniq
            print(f"    {model}: det {bl_det*100:.0f}%→{so_det*100:.0f}% ({delta_det:+.0f}pp), "
                  f"unique {bl_uniq}→{so_uniq} ({delta_uniq:+d})")

    # Save
    output = {
        "experiment": "18c_somatic_gpu_awareness",
        "timestamp": datetime.datetime.now().isoformat(),
        "config": {
            "models": MODELS,
            "conditions": CONDITIONS,
            "baseline_calls": BASELINE_CALLS,
            "stressed_calls": STRESSED_CALLS,
            "concurrent_batch": CONCURRENT_BATCH,
            "total_calls": total_calls,
            "base_prompt": BASE_PROMPT,
        },
        "results": all_results,
    }

    fname = f"exp18c_{timestamp}.json"
    fpath = os.path.join(RESULTS_DIR, fname)
    with open(fpath, "w") as f:
        json.dump(output, f, indent=2, default=str)

    latest = os.path.join(RESULTS_DIR, "exp18c_latest.json")
    with open(latest, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to {fpath}")
    return output


if __name__ == "__main__":
    run()
