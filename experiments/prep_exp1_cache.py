#!/usr/bin/env python3
"""
Pre-generate the synthetic document cache for Experiment 1.
This avoids the ~30-minute document generation step during the actual experiment.
Run this while another experiment is in progress (it will queue behind Ollama).

Usage:
    python prep_exp1_cache.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared.config import FAST_MODEL, DATA_DIR
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

# Import the generator from exp1
from exp1_memory_pollution.run import (
    generate_synthetic_documents,
    generate_evaluation_questions,
)


def main():
    print("=" * 60)
    print("  PRE-GENERATING EXP1 DOCUMENT CACHE")
    print("=" * 60)

    cache_docs = DATA_DIR / "exp1_docs" / "synthetic_docs.json"
    cache_qs = DATA_DIR / "exp1_docs" / "eval_questions.json"

    if cache_docs.exists() and cache_qs.exists():
        print(f"\n✅ Caches already exist:")
        print(f"   Documents: {cache_docs}")
        print(f"   Questions: {cache_qs}")
        print(f"   Delete them to regenerate.")
        return

    llm = OllamaLLM(model=FAST_MODEL, temperature=0.7)
    logger = ExperimentLogger("exp1_memory_pollution", run_id="cache_gen", enable_system_monitor=False)

    print("\n📝 Generating synthetic documents...")
    relevant, irrelevant = generate_synthetic_documents(llm, logger)
    print(f"   ✅ Generated {len(relevant)} relevant + {len(irrelevant)} irrelevant docs")

    print("\n📝 Generating evaluation questions...")
    questions = generate_evaluation_questions(llm, logger)
    print(f"   ✅ Generated {len(questions)} questions")

    stats = llm.get_usage_stats()
    print(f"\n📊 Token usage: {stats['total_tokens']} total ({stats['total_calls']} calls)")
    print(f"   Elapsed: {stats['total_elapsed_seconds']:.0f}s")
    print(f"   Avg throughput: {stats.get('throughput_avg_tok_s', 'N/A')} tok/s")
    print("\n✅ Cache ready! Experiment 1 will load from cache on next run.")


if __name__ == "__main__":
    main()
