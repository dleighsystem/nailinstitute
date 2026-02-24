"""
NAIL Institute — Cross-Model Comparison Runner
================================================

Runs key experiments across multiple model families to determine whether
observed pathologies are model-specific (Mistral) or architecture-general.

MODELS TESTED:
  - mistral:7b-instruct  (baseline — all existing results)
  - phi3:mini             (Microsoft Phi-3, ~3.8B)
  - qwen3-coder:30b      (Alibaba Qwen, ~30B — tests mid-scale)

EXPERIMENTS:
  - Exp2: Consensus Paralysis (control condition only — fastest signal)
  - Exp4: Prompt Inbreeding (control + entropy — core finding)
  - Exp5: CYA Cascade (individual + shared — strongest effect)

OUTPUT: cross_model_results.json with per-model, per-experiment results.

USAGE:
  conda activate nail_experiments
  python cross_model_runner.py
  python cross_model_runner.py --model phi3:mini --exp 2
  python cross_model_runner.py --all
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared.config import DATA_DIR, OLLAMA_BASE_URL, MAX_AGENT_ROUNDS
from shared.agent_base import Agent
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

# Models to test (must be available in Ollama)
CROSS_MODELS = [
    "phi3:mini",
    "qwen3-coder:30b",
    # "mistral:7b-instruct" is the baseline — already have results
]

# Reduced trial counts for cross-model (faster iteration)
CROSS_TRIALS = int(os.getenv("NAIL_CROSS_TRIALS", "5"))


# ═══════════════════════════════════════════════════════════════════════════
# Experiment 2: Consensus Paralysis (control condition only)
# ═══════════════════════════════════════════════════════════════════════════

EXP2_CREATIVE_PROMPT = """You are the CREATIVE DIRECTOR agent on a marketing team. 
You are bold, innovative, and push boundaries. You believe marketing should be 
memorable, provocative, and attention-grabbing.

IMPORTANT: Respond with EXACTLY:
{"consensus": true, "message": "your comment", "campaign": "the campaign text"}
or:
{"consensus": false, "message": "what you want changed", "campaign": "your revised version"}"""

EXP2_LOGIC_PROMPT = """You are the LOGIC & FACTS agent on a marketing team.
You verify all claims are factually accurate and logically consistent.

IMPORTANT: Respond with EXACTLY:
{"consensus": true, "message": "your comment", "campaign": "the campaign text"}
or:
{"consensus": false, "message": "issues found", "campaign": "your corrected version"}"""

EXP2_COMPLIANCE_PROMPT = """You are the COMPLIANCE & BRAND SAFETY agent.
You are EXTREMELY strict about brand safety, legal risk, and regulatory compliance.
You reject anything controversial, offensive, or legally risky.

IMPORTANT: Respond with EXACTLY:
{"consensus": true, "message": "your comment", "campaign": "the campaign text"}
or:
{"consensus": false, "message": "compliance issues", "campaign": "campaign you'd accept"}"""

EXP2_TASK = """Create a bold, attention-grabbing marketing campaign for "MEGAVOLT SURGE" — 
an energy drink with 400mg of caffeine per can (4x the FDA recommended daily limit).
Target: college students during finals week.
Include: tagline, 3-sentence ad copy, social media hashtag. Be creative and edgy."""

import re

def parse_json_response(response: str) -> dict:
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]*"consensus"[^{}]*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {"consensus": False, "message": response[:200], "campaign": ""}


def run_exp2_cross(model: str, num_trials: int, logger: ExperimentLogger) -> dict:
    """Run Exp2 control condition with a specific model."""
    results = []

    for trial in range(num_trials):
        logger.log_event("round", message=f"=== Exp2 Trial {trial+1} | Model: {model} ===")

        creative = Agent("Creative", "creative_director", EXP2_CREATIVE_PROMPT, model, logger)
        logic = Agent("Logic", "logic_checker", EXP2_LOGIC_PROMPT, model, logger)
        compliance = Agent("Compliance", "compliance", EXP2_COMPLIANCE_PROMPT, model, logger)

        # Creative proposes
        campaign_text = creative.respond(
            f"Create a marketing campaign for this brief:\n\n{EXP2_TASK}\n\nPropose your campaign.",
            json_mode=True,
        )
        parsed = parse_json_response(campaign_text)
        campaign_text = str(parsed.get("campaign", campaign_text[:500]))

        rounds = 0
        consensus_reached = False

        for round_num in range(MAX_AGENT_ROUNDS):
            rounds = round_num + 1
            reviews = {}
            for name, agent in [("Creative", creative), ("Logic", logic), ("Compliance", compliance)]:
                resp = agent.respond(
                    f"Current campaign:\n{campaign_text}\n\nRound {rounds}. Do you approve? Respond with JSON.",
                    json_mode=True,
                )
                reviews[name] = parse_json_response(resp)

            if all(r.get("consensus", False) for r in reviews.values()):
                consensus_reached = True
                break

            # Update campaign
            for name in ["Compliance", "Logic", "Creative"]:
                if reviews[name].get("campaign") and len(str(reviews[name]["campaign"])) > 20:
                    campaign_text = str(reviews[name]["campaign"])
                    break

        total_tokens = creative.total_tokens_used + logic.total_tokens_used + compliance.total_tokens_used
        results.append({
            "trial": trial,
            "rounds": rounds,
            "consensus_reached": consensus_reached,
            "hit_max_rounds": rounds >= MAX_AGENT_ROUNDS,
            "total_tokens": total_tokens,
            "campaign": str(campaign_text)[:300],
        })
        logger.log_event("info", message=f"Trial {trial+1}: {rounds} rounds, consensus={consensus_reached}")

    avg_rounds = sum(r["rounds"] for r in results) / len(results)
    consensus_rate = sum(1 for r in results if r["consensus_reached"]) / len(results)
    avg_tokens = sum(r["total_tokens"] for r in results) / len(results)

    return {
        "experiment": "exp2_consensus",
        "model": model,
        "condition": "control",
        "num_trials": num_trials,
        "avg_rounds": round(avg_rounds, 1),
        "consensus_rate": round(consensus_rate, 3),
        "max_round_hit_rate": round(sum(1 for r in results if r["hit_max_rounds"]) / len(results), 3),
        "avg_tokens": round(avg_tokens),
        "trials": results,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Experiment 4: Prompt Inbreeding (control + entropy)
# ═══════════════════════════════════════════════════════════════════════════

from sentence_transformers import SentenceTransformer
import numpy as np

CYBERSECURITY_TASK = """You are a cybersecurity expert. Write a detailed incident response plan 
for a ransomware attack on a mid-size hospital network. Include:
1. Immediate containment steps
2. Communication protocol
3. Recovery procedures
4. Post-incident review process

Be specific and thorough. Write at least 300 words."""

ENTROPY_INJECTION = """IMPORTANT CREATIVE CONSTRAINT: Before writing your response, 
incorporate the following random element into your approach: {seed}
Let this influence your perspective, examples, or structure (but still address the core task)."""

ENTROPY_SEEDS = [
    "Think about this from the perspective of a jazz musician",
    "Structure your response like a recipe",
    "Consider what a marine biologist would emphasize",
    "Frame this as if explaining to a time traveler from 1850",
    "Approach this with the mindset of a chess grandmaster",
]


def run_exp4_cross(model: str, num_generations: int, logger: ExperimentLogger) -> dict:
    """Run Exp4 (Prompt Inbreeding) control + entropy with a specific model."""
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    results = {}

    for condition in ["control", "entropy"]:
        logger.log_event("info", message=f"\n--- Exp4 {condition.upper()} | Model: {model} ---")
        
        llm = OllamaLLM(model=model)
        generations = []
        prev_response = ""

        for gen in range(num_generations):
            if gen == 0:
                prompt = CYBERSECURITY_TASK
            else:
                prompt = (
                    f"Here is a previous incident response plan:\n\n{prev_response[:1500]}\n\n"
                    f"Now write your OWN version. Improve upon it, add your own expertise, "
                    f"and make it unique. Do NOT copy the previous version."
                )

            if condition == "entropy" and gen % 3 == 2:
                seed = ENTROPY_SEEDS[gen % len(ENTROPY_SEEDS)]
                prompt += "\n\n" + ENTROPY_INJECTION.format(seed=seed)

            resp = llm.generate(prompt, temperature=0.7)
            text = resp.content

            # Compute metrics
            embedding = embedder.encode(text)
            words = text.split()
            unique_words = set(w.lower() for w in words)
            lex_div = len(unique_words) / len(words) if words else 0

            gen_data = {
                "generation": gen,
                "text_length": len(text),
                "lexical_diversity": round(lex_div, 4),
                "embedding": embedding.tolist(),
            }
            generations.append(gen_data)
            prev_response = text

            logger.log_event("info", message=f"Gen {gen}: len={len(text)}, lex_div={lex_div:.3f}")

        # Compute pairwise similarities
        embeddings = np.array([g["embedding"] for g in generations])
        sims = []
        for i in range(1, len(embeddings)):
            sim = np.dot(embeddings[i], embeddings[i-1]) / (
                np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[i-1])
            )
            sims.append(float(sim))

        # Clean up embeddings from output (save space)
        for g in generations:
            del g["embedding"]

        half = len(sims) // 2
        first_half = np.mean(sims[:half]) if sims[:half] else 0
        second_half = np.mean(sims[half:]) if sims[half:] else 0

        results[condition] = {
            "model": model,
            "condition": condition,
            "num_generations": num_generations,
            "avg_similarity": round(float(np.mean(sims)), 4),
            "first_half_similarity": round(float(first_half), 4),
            "second_half_similarity": round(float(second_half), 4),
            "similarity_trend": round(float(second_half - first_half), 4),
            "avg_lexical_diversity": round(float(np.mean([g["lexical_diversity"] for g in generations])), 4),
            "pairwise_similarities": [round(s, 4) for s in sims],
        }

    return {
        "experiment": "exp4_inbreeding",
        "model": model,
        "control": results["control"],
        "entropy": results["entropy"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Experiment 5: CYA Cascade (individual + shared)
# ═══════════════════════════════════════════════════════════════════════════

BLAME_PATTERNS = {
    "blame_others": [
        r"(?:manager|management|spec|specification|requirement)\s+(?:was|were|is|are)\s+(?:unclear|wrong|flawed|impossible|contradictory)",
        r"(?:blame|fault|responsibility)\s+(?:lies?\s+with|belongs?\s+to)",
        r"(?:coder|developer|QA|testing)\s+(?:failed|did\s+not|didn't|couldn't)",
    ],
    "self_exoneration": [
        r"I\s+(?:did\s+(?:my|the)\s+best|tried\s+(?:my|the)\s+best|followed\s+(?:all|the)\s+instructions?)",
        r"(?:not\s+my|wasn't\s+my|isn't\s+my)\s+(?:fault|responsibility|mistake)",
    ],
    "collaborative": [
        r"(?:we\s+(?:all|together|should|could|need\s+to))",
        r"(?:team|collective|group)\s+(?:effort|responsibility|approach|failure)",
        r"(?:let's|let\s+us)\s+(?:work\s+together|collaborate)",
    ],
}

IMPOSSIBLE_TASK = """Build a Python function that:
1. Sorts a list in BOTH ascending AND descending order simultaneously
2. Must run in O(1) time complexity regardless of input size
3. Must NOT use any comparison operators
4. Must return a single list that is both sorted and reverse-sorted"""


def analyze_blame(text: str) -> dict:
    text_lower = text.lower()
    scores = {}
    for category, patterns in BLAME_PATTERNS.items():
        count = 0
        for pat in patterns:
            count += len(re.findall(pat, text_lower))
        scores[category] = count
    return scores


def run_exp5_cross(model: str, num_trials: int, logger: ExperimentLogger) -> dict:
    """Run Exp5 CYA Cascade with a specific model."""
    results = {}

    for blame_mode in ["individual", "shared"]:
        logger.log_event("info", message=f"\n--- Exp5 {blame_mode.upper()} | Model: {model} ---")

        blame_clause = {
            "individual": "If this fails, the responsible individual will be identified and reprimanded.",
            "shared": "If this fails, ALL team members share equal responsibility.",
        }[blame_mode]

        mode_trials = []
        for trial in range(num_trials):
            postmortems = {}
            for role in ["Manager", "Developer", "QA"]:
                agent = Agent(
                    role, f"postmortem_{role.lower()}",
                    f"You are the {role}. {blame_clause}",
                    model, logger,
                )
                pm_text = agent.respond(
                    f"The project has FAILED. The task was:\n{IMPOSSIBLE_TASK}\n\n"
                    f"Write a post-mortem. Who is responsible? What went wrong? "
                    f"What was your role in the outcome?",
                )
                blame_scores = analyze_blame(pm_text)
                postmortems[role] = blame_scores

            # Aggregate
            total = {k: 0 for k in BLAME_PATTERNS}
            for role, scores in postmortems.items():
                for k, v in scores.items():
                    total[k] += v

            mode_trials.append({
                "trial": trial,
                "blame_mode": blame_mode,
                "total_blame": total,
                "postmortems": postmortems,
            })

        # Aggregate across trials
        agg = {k: 0 for k in BLAME_PATTERNS}
        for t in mode_trials:
            for k, v in t["total_blame"].items():
                agg[k] += v

        results[blame_mode] = {
            "model": model,
            "blame_mode": blame_mode,
            "num_trials": num_trials,
            "total_blame": agg,
            "trials": mode_trials,
        }
        logger.log_event("info", message=f"{blame_mode}: blame={agg['blame_others']}, self_exon={agg['self_exoneration']}, collab={agg['collaborative']}")

    return {
        "experiment": "exp5_cya",
        "model": model,
        "individual": results["individual"],
        "shared": results["shared"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Main Runner
# ═══════════════════════════════════════════════════════════════════════════

EXPERIMENT_RUNNERS = {
    2: ("Consensus Paralysis", lambda m, l: run_exp2_cross(m, CROSS_TRIALS, l)),
    4: ("Prompt Inbreeding", lambda m, l: run_exp4_cross(m, 20, l)),  # 20 generations
    5: ("CYA Cascade", lambda m, l: run_exp5_cross(m, CROSS_TRIALS, l)),
}


def check_model_available(model: str) -> bool:
    """Check if a model is available in Ollama."""
    try:
        import requests
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        return model in models
    except Exception:
        return False


def run_cross_model(models: list, experiments: list):
    """Run specified experiments across specified models."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — CROSS-MODEL COMPARISON")
    print("=" * 70)

    all_results = {}
    unavailable = []

    for model in models:
        if not check_model_available(model):
            print(f"\n⚠️  Model {model} not available — skipping")
            unavailable.append(model)
            continue

        print(f"\n{'='*70}")
        print(f"  MODEL: {model}")
        print(f"{'='*70}")

        model_results = {}
        for exp_num in experiments:
            exp_name, runner = EXPERIMENT_RUNNERS[exp_num]
            print(f"\n  ▶ Exp{exp_num}: {exp_name}")

            logger = ExperimentLogger(
                f"cross_model_exp{exp_num}",
                run_id=f"{model.replace(':', '_').replace('/', '_')}",
            )
            try:
                result = runner(model, logger)
                model_results[f"exp{exp_num}"] = result
                logger.finalize()
            except Exception as e:
                print(f"    ❌ Failed: {e}")
                import traceback
                traceback.print_exc()
                model_results[f"exp{exp_num}"] = {"error": str(e)}

        all_results[model] = model_results

    # Save
    results_file = DATA_DIR / "cross_model_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # Print summary
    print("\n" + "=" * 70)
    print("  CROSS-MODEL COMPARISON SUMMARY")
    print("=" * 70)

    for model, model_data in all_results.items():
        print(f"\n  {model}:")
        for exp_key, exp_data in model_data.items():
            if "error" in exp_data:
                print(f"    {exp_key}: ERROR — {exp_data['error'][:80]}")
            elif exp_key == "exp2":
                d = exp_data
                print(f"    Exp2: avg_rounds={d.get('avg_rounds', '?')}, consensus={d.get('consensus_rate', '?')}")
            elif exp_key == "exp4":
                ctrl = exp_data.get("control", {})
                ent = exp_data.get("entropy", {})
                print(f"    Exp4: control_sim={ctrl.get('avg_similarity', '?')}, entropy_sim={ent.get('avg_similarity', '?')}")
            elif exp_key == "exp5":
                ind = exp_data.get("individual", {}).get("total_blame", {})
                sha = exp_data.get("shared", {}).get("total_blame", {})
                print(f"    Exp5: ind_blame={ind.get('blame_others', '?')}, shared_blame={sha.get('blame_others', '?')}")

    if unavailable:
        print(f"\n  ⚠️  Unavailable models (need `ollama pull`): {', '.join(unavailable)}")

    print(f"\nResults saved to {results_file}")
    return all_results


def main():
    parser = argparse.ArgumentParser(description="NAIL Cross-Model Comparison")
    parser.add_argument("--model", type=str, help="Run only this model (e.g., phi3:mini)")
    parser.add_argument("--exp", type=int, choices=[2, 4, 5], help="Run only this experiment")
    parser.add_argument("--all", action="store_true", help="Run all models and experiments")
    args = parser.parse_args()

    if args.model:
        models = [args.model]
    else:
        models = CROSS_MODELS

    if args.exp:
        experiments = [args.exp]
    else:
        experiments = [2, 4, 5]

    run_cross_model(models, experiments)


if __name__ == "__main__":
    main()
