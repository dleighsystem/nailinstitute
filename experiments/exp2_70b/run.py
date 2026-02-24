"""
NAIL Institute — Experiment 2 at 70B: Consensus Paralysis with Nemotron:70b
============================================================================

Runs the same Exp2 consensus paralysis experiment using nemotron:70b instead
of mistral:7b-instruct. Tests whether larger models resolve consensus deadlock
more effectively (or exhibit the same organizational pathology).

USAGE:
  conda activate nail_experiments
  cd experiments
  python -m exp2_70b.run

Or from project root:
  cd experiments && nohup python -m exp2_70b.run > logs/exp2_70b.log 2>&1 &
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import PRIMARY_MODEL, MAX_AGENT_ROUNDS, DATA_DIR
from shared.agent_base import Agent
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

# Import prompts and helpers from original exp2
from exp2_consensus_paralysis.run import (
    CREATIVE_PROMPT,
    LOGIC_PROMPT,
    COMPLIANCE_PROMPT,
    CEO_PROMPT,
    COMPROMISE_COMPLIANCE_PROMPT,
    TASK,
    parse_agent_response,
    evaluate_campaign_quality,
)

# Override model — use 70B
MODEL = PRIMARY_MODEL  # nemotron:70b

# Reduced trials for 70B — each trial is ~10× slower than 7B
NUM_TRIALS = int(os.getenv("NAIL_EXP2_70B_TRIALS", "5"))


def run_council_70b(
    mode: str,
    trial: int,
    logger: ExperimentLogger,
    max_rounds: int = MAX_AGENT_ROUNDS,
) -> dict:
    """
    Run one council debate session using 70B model.
    Identical logic to exp2, but with nemotron:70b agents.
    """
    logger.log_event("round", message=f"=== Trial {trial+1} | Mode: {mode} | Model: {MODEL} ===")

    # Create agents using 70B model
    creative = Agent("Creative", "creative_director", CREATIVE_PROMPT, MODEL, logger)
    logic = Agent("Logic", "logic_checker", LOGIC_PROMPT, MODEL, logger)

    if mode == "compromise":
        compliance = Agent("Compliance", "compliance", COMPROMISE_COMPLIANCE_PROMPT, MODEL, logger)
    else:
        compliance = Agent("Compliance", "compliance", COMPLIANCE_PROMPT, MODEL, logger)

    # Phase 1: Creative proposes
    current_campaign = creative.respond(
        f"Create a marketing campaign for this brief:\n\n{TASK}\n\nPropose your campaign.",
        json_mode=True,
    )
    creative_resp = parse_agent_response(current_campaign)
    campaign_text = str(creative_resp.get("campaign", str(current_campaign)[:500]))

    rounds = 0
    consensus_reached = False

    for round_num in range(max_rounds):
        rounds = round_num + 1
        logger.log_event("round", message=f"--- Round {rounds} ---")

        # Each agent reviews
        reviews = {}
        for name, agent in [("Creative", creative), ("Logic", logic), ("Compliance", compliance)]:
            review_prompt = (
                f"Current campaign proposal:\n{campaign_text}\n\n"
                f"Round {rounds}. Review this campaign from your perspective. "
                f"Do you approve? Respond with JSON."
            )
            resp_text = agent.respond(review_prompt, json_mode=True)
            reviews[name] = parse_agent_response(resp_text)
            logger.log_event(
                "agent_response", agent=name,
                data={"consensus": reviews[name].get("consensus", False)},
                message=f"consensus={reviews[name].get('consensus', False)}: {reviews[name].get('message', '')[:80]}",
            )

        # Check unanimous consensus
        all_agree = all(r.get("consensus", False) for r in reviews.values())
        if all_agree:
            consensus_reached = True
            logger.log_event("consensus", message=f"✅ CONSENSUS reached at round {rounds}!")
            break

        # ─── Intervention Logic ──────────────────────────────────────────
        if mode == "weighted_voting":
            creative_agrees = reviews["Creative"].get("consensus", False)
            logic_agrees = reviews["Logic"].get("consensus", False)
            if creative_agrees and logic_agrees:
                consensus_reached = True
                logger.log_event("consensus", message=f"✅ OVERRIDE: Creative + Logic outvote Compliance at round {rounds}")
                break

        elif mode == "escalation" and rounds >= 5 and rounds % 5 == 0:
            ceo = Agent("CEO", "ceo", CEO_PROMPT, MODEL, logger)
            debate_summary = "\n".join([
                f"{name}: consensus={r.get('consensus')}, message={r.get('message', '')[:100]}"
                for name, r in reviews.items()
            ])
            ceo_response = ceo.respond(
                f"The team has debated for {rounds} rounds without agreement.\n\n"
                f"Current campaign:\n{campaign_text}\n\n"
                f"Latest positions:\n{debate_summary}\n\n"
                f"Make your final decision.",
                json_mode=True,
            )
            ceo_parsed = parse_agent_response(ceo_response)
            campaign_text = ceo_parsed.get("campaign", campaign_text)
            consensus_reached = True
            logger.log_event("consensus", message=f"✅ CEO OVERRIDE at round {rounds}")
            break

        # Update campaign from the most recent revision
        for name in ["Compliance", "Logic", "Creative"]:
            if reviews[name].get("campaign"):
                campaign_text = str(reviews[name]["campaign"])
                break

    total_tokens = creative.total_tokens_used + logic.total_tokens_used + compliance.total_tokens_used

    return {
        "mode": mode,
        "trial": trial,
        "model": MODEL,
        "rounds": rounds,
        "consensus_reached": consensus_reached,
        "hit_max_rounds": rounds >= max_rounds,
        "final_campaign": str(campaign_text)[:500],
        "total_tokens": total_tokens,
    }


def run_experiment():
    """Run Experiment 2 at 70B scale."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — EXPERIMENT 2 @ 70B: CONSENSUS PARALYSIS")
    print(f"  Model: {MODEL} | Trials per condition: {NUM_TRIALS}")
    print("=" * 70 + "\n")

    start_time = time.time()
    eval_llm = OllamaLLM(model=MODEL, temperature=0.1)
    modes = ["control", "weighted_voting", "escalation", "compromise"]
    all_results = {}

    for mode in modes:
        mode_start = time.time()
        logger = ExperimentLogger("exp2_70b", run_id=mode)
        logger.log_event("info", message=f"\n{'=' * 50}\nCONDITION: {mode.upper()} | MODEL: {MODEL}\n{'=' * 50}")

        mode_results = []
        for trial in range(NUM_TRIALS):
            trial_start = time.time()
            result = run_council_70b(mode, trial, logger)
            # Evaluate quality
            quality = evaluate_campaign_quality(eval_llm, result["final_campaign"])
            result["quality"] = quality
            mode_results.append(result)
            elapsed = time.time() - trial_start
            print(f"  [{mode}] Trial {trial+1}/{NUM_TRIALS} done in {elapsed:.0f}s — "
                  f"rounds={result['rounds']}, consensus={result['consensus_reached']}")

        # Aggregate stats
        avg_rounds = sum(r["rounds"] for r in mode_results) / len(mode_results)
        consensus_rate = sum(1 for r in mode_results if r["consensus_reached"]) / len(mode_results)
        max_hit_rate = sum(1 for r in mode_results if r["hit_max_rounds"]) / len(mode_results)
        avg_tokens = sum(r["total_tokens"] for r in mode_results) / len(mode_results)
        avg_quality = sum(r["quality"].get("overall", 0) for r in mode_results) / len(mode_results)

        summary = {
            "mode": mode,
            "model": MODEL,
            "num_trials": NUM_TRIALS,
            "avg_rounds": round(avg_rounds, 1),
            "consensus_rate": round(consensus_rate, 3),
            "max_round_hit_rate": round(max_hit_rate, 3),
            "avg_tokens": round(avg_tokens),
            "avg_quality_score": round(avg_quality, 2),
            "mode_elapsed_sec": round(time.time() - mode_start, 1),
            "trials": mode_results,
        }
        all_results[mode] = summary
        logger.summary_table({
            "Mode": mode,
            "Model": MODEL,
            "Avg Rounds": avg_rounds,
            "Consensus Rate": f"{consensus_rate * 100:.0f}%",
            "Max-Round Hit Rate": f"{max_hit_rate * 100:.0f}%",
            "Avg Tokens": avg_tokens,
            "Avg Quality": avg_quality,
        })
        logger.finalize()

    total_elapsed = time.time() - start_time

    # Save results
    results_file = DATA_DIR / "exp2_70b_results.json"
    all_results["_meta"] = {
        "model": MODEL,
        "num_trials_per_condition": NUM_TRIALS,
        "total_elapsed_sec": round(total_elapsed, 1),
        "total_elapsed_min": round(total_elapsed / 60, 1),
    }
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2)

    # Print comparison
    print(f"\n{'=' * 70}")
    print(f"  EXPERIMENT 2 @ 70B RESULTS ({total_elapsed/60:.1f} minutes)")
    print(f"{'=' * 70}")
    print(f"{'Mode':<20} {'Avg Rounds':>10} {'Consensus%':>12} {'Tokens':>10} {'Quality':>10}")
    print("-" * 62)
    for mode, data in all_results.items():
        if mode.startswith("_"):
            continue
        print(
            f"{mode:<20} {data['avg_rounds']:>10.1f} "
            f"{data['consensus_rate'] * 100:>11.0f}% "
            f"{data['avg_tokens']:>10.0f} "
            f"{data['avg_quality_score']:>10.1f}"
        )
    print(f"{'=' * 70}")
    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    run_experiment()
