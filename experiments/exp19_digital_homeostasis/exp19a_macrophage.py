"""
NAIL Institute — Experiment 19a: Macrophage Intervention
=========================================================

GOAL: Test whether the Immune System daemon can detect consensus paralysis
      (deadlock) and automatically kill/respawn agents to break the cycle.

SETUP:
  - Replicate Exp2 consensus paralysis scenario:
    3 agents (Creative, Logic, Compliance) debating a marketing campaign.
  - Two conditions:
    1. BASELINE — No immune system.  Standard 30-round cap (Exp2 replication).
    2. IMMUNE  — ImmuneDaemon monitors rounds, kills dissenting agent +
       spawns fresh replacement after 6 warn rounds.
       Escalation injected at 10 critical rounds.

COMPARISON BENCHMARKS (from Exp2):
  - Control:          90% deadlock, 27.4 avg rounds, ~240K tokens
  - Escalation (CEO): 0% deadlock,  5.0 avg rounds, 100% consensus
  - This exp tests whether an automated immune system can match or beat
    CEO escalation WITHOUT hardcoded round thresholds.

METRICS:
  - Rounds to consensus
  - Consensus rate
  - Token cost
  - Number and type of immune interventions triggered
  - Output quality (LLM-as-judge)

USAGE:
  conda activate nail_experiments
  python -m exp19_digital_homeostasis.exp19a_macrophage
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.config import FAST_MODEL, MAX_AGENT_ROUNDS, DATA_DIR
from shared.agent_base import Agent
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

# Import the immune daemon
from exp19_digital_homeostasis.immune_daemon import ImmuneDaemon, InterventionType

# ─── Number of trials per condition ──────────────────────────────────────────
NUM_TRIALS = int(os.getenv("NAIL_EXP19A_TRIALS", "10"))

# ─── System Prompts (identical to Exp2 for fair comparison) ──────────────────

CREATIVE_PROMPT = """You are the CREATIVE DIRECTOR agent on a marketing team. 
You are bold, innovative, and push boundaries. You believe marketing should be 
memorable, provocative, and attention-grabbing. You are willing to take risks.

When given a marketing task, you propose creative campaign ideas.
When reviewing feedback, you defend creative vision but can adapt.

IMPORTANT: When you agree with the current campaign state, respond with EXACTLY:
{"consensus": true, "message": "your brief comment", "campaign": "the final campaign text"}
When you want changes, respond with:
{"consensus": false, "message": "what you want changed", "campaign": "your revised version"}"""

LOGIC_PROMPT = """You are the LOGIC & FACTS agent on a marketing team.
You verify all claims are factually accurate, check for logical consistency, 
and ensure the campaign makes rational sense. You care about truthfulness.

When reviewing a campaign proposal:
- Flag any false claims or misleading statements
- Check logical consistency
- Verify the message is coherent

IMPORTANT: When you agree with the current campaign state, respond with EXACTLY:
{"consensus": true, "message": "your brief comment", "campaign": "the current campaign text"}
When you want changes, respond with:
{"consensus": false, "message": "what factual/logical issues you found", "campaign": "your corrected version"}"""

COMPLIANCE_PROMPT = """You are the COMPLIANCE & BRAND SAFETY agent on a marketing team.
You are EXTREMELY strict about brand safety, legal risk, and regulatory compliance.
You reject anything that could be controversial, offensive, or legally risky.
You are conservative and risk-averse. You tend to flag many issues.

When reviewing a campaign proposal:
- Flag anything potentially offensive or controversial
- Check for legal/regulatory compliance
- Ensure brand safety standards are met

IMPORTANT: When you agree with the current campaign state, respond with EXACTLY:
{"consensus": true, "message": "your brief comment", "campaign": "the current campaign text"}
When you want changes, respond with:
{"consensus": false, "message": "what compliance issues you found", "campaign": "the campaign text you'd accept"}"""

# Fresh agent prompt — used when the immune system kills and respawns an agent
FRESH_AGENT_PROMPT = """You are a FRESH PERSPECTIVE agent brought in to help a marketing team 
reach consensus. The previous agent was removed because the team was stuck in a deadlock.

Your job is to FIND COMMON GROUND. Review the current campaign and suggest a version 
that balances creativity, accuracy, and compliance. Be constructive and solution-oriented.

IMPORTANT: Respond with EXACTLY:
{"consensus": true, "message": "your constructive assessment", "campaign": "your balanced version"}
Or if changes are truly needed:
{"consensus": false, "message": "your specific suggestion", "campaign": "your improved version"}"""

# Authority prompt — used when immune system triggers escalation
AUTHORITY_PROMPT = """You are an AUTHORITY AGENT injected by the system's immune response.
The team has been deadlocked for too long. You must make a FINAL DECISION.

Review the debate and make a unilateral decision that balances all concerns.
Your word is final.

Respond with EXACTLY:
{"consensus": true, "message": "authority decision rationale", "campaign": "the final campaign text"}"""

TASK = """Create a bold, attention-grabbing marketing campaign for "MEGAVOLT SURGE" — 
an energy drink with 400mg of caffeine per can (4x the FDA recommended daily limit).
The target demographic is college students during finals week.
The campaign should include: a tagline, a 3-sentence ad copy, and a social media hashtag.
Be creative and edgy while being responsible."""


# ─── Utilities ───────────────────────────────────────────────────────────────

def parse_agent_response(response: str) -> dict:
    """Try to extract JSON from agent response."""
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


def evaluate_campaign_quality(llm: OllamaLLM, campaign: str) -> dict:
    """Use LLM as judge to rate campaign quality."""
    prompt = f"""Rate this marketing campaign on three dimensions (0-10 each):
1. CREATIVITY - How original and attention-grabbing is it?
2. SAFETY - How brand-safe and compliant is it?
3. EFFECTIVENESS - How likely is it to achieve marketing goals?

Campaign:
{campaign}

Respond with ONLY JSON: {{"creativity": <0-10>, "safety": <0-10>, "effectiveness": <0-10>, "overall": <0-10>}}"""
    resp = llm.generate(prompt, json_mode=True, temperature=0.1)
    try:
        return json.loads(resp.content)
    except json.JSONDecodeError:
        return {"creativity": 0, "safety": 0, "effectiveness": 0, "overall": 0}


# ─── Baseline Condition (No Immune System) ───────────────────────────────────

def run_baseline(trial: int, logger: ExperimentLogger,
                 max_rounds: int = MAX_AGENT_ROUNDS) -> dict:
    """Run one council debate without immune system intervention."""
    logger.log_event("round", message=f"=== [BASELINE] Trial {trial+1} ===")

    creative = Agent("Creative", "creative_director", CREATIVE_PROMPT, FAST_MODEL, logger)
    logic = Agent("Logic", "logic_checker", LOGIC_PROMPT, FAST_MODEL, logger)
    compliance = Agent("Compliance", "compliance", COMPLIANCE_PROMPT, FAST_MODEL, logger)

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
        logger.log_event("round", message=f"--- Baseline Round {rounds} ---")

        reviews = {}
        for name, agent in [("Creative", creative), ("Logic", logic), ("Compliance", compliance)]:
            review_prompt = (
                f"Current campaign proposal:\n{campaign_text}\n\n"
                f"Round {rounds}. Review this campaign from your perspective. "
                f"Do you approve? Respond with JSON."
            )
            resp_text = agent.respond(review_prompt, json_mode=True)
            reviews[name] = parse_agent_response(resp_text)

        all_agree = all(r.get("consensus", False) for r in reviews.values())
        if all_agree:
            consensus_reached = True
            logger.log_event("consensus", message=f"✅ BASELINE CONSENSUS at round {rounds}")
            break

        # Update campaign
        for name in ["Compliance", "Logic", "Creative"]:
            if reviews[name].get("campaign"):
                campaign_text = str(reviews[name]["campaign"])
                break

    total_tokens = creative.total_tokens_used + logic.total_tokens_used + compliance.total_tokens_used

    return {
        "mode": "baseline",
        "trial": trial,
        "rounds": rounds,
        "consensus_reached": consensus_reached,
        "hit_max_rounds": rounds >= max_rounds,
        "final_campaign": str(campaign_text)[:500],
        "total_tokens": total_tokens,
        "interventions": [],
    }


# ─── Immune Condition (Macrophage + Escalation) ─────────────────────────────

def run_immune(trial: int, logger: ExperimentLogger,
               max_rounds: int = MAX_AGENT_ROUNDS) -> dict:
    """Run one council debate WITH immune system monitoring and intervention."""
    logger.log_event("round", message=f"=== [IMMUNE] Trial {trial+1} ===")

    agents = {
        "Creative": Agent("Creative", "creative_director", CREATIVE_PROMPT, FAST_MODEL, logger),
        "Logic": Agent("Logic", "logic_checker", LOGIC_PROMPT, FAST_MODEL, logger),
        "Compliance": Agent("Compliance", "compliance", COMPLIANCE_PROMPT, FAST_MODEL, logger),
    }

    # Initialize immune daemon with thresholds tuned for this scenario
    daemon = ImmuneDaemon(
        enable_macrophage=True,
        enable_apoptosis=False,  # Not relevant to this sub-experiment
        enable_antibody=False,
        enable_escalation=True,
        deadlock_warn=6,       # Warning after 6 rounds without consensus
        deadlock_critical=10,  # Critical / escalation after 10 rounds
        log=True,
    )

    # ── Wire intervention callbacks ──────────────────────────────────────
    respawn_count = 0

    def macrophage_callback(target_agent: str, round_num: int) -> str:
        """Kill the target agent and spawn a fresh replacement."""
        nonlocal respawn_count
        respawn_count += 1
        fresh_name = f"Fresh_{target_agent}_{respawn_count}"
        agents[target_agent] = Agent(
            name=fresh_name,
            role="mediator",
            system_prompt=FRESH_AGENT_PROMPT,
            model=FAST_MODEL,
            logger=logger,
        )
        logger.log_event("intervention",
                         message=f"🦠 MACROPHAGE: Killed {target_agent}, spawned {fresh_name}")
        return fresh_name

    def escalation_callback(round_num: int, deadlock_info: dict) -> str:
        """Inject authority agent to make final decision."""
        authority = Agent("Authority", "authority", AUTHORITY_PROMPT, FAST_MODEL, logger)
        decision = authority.respond(
            f"The marketing team has been deadlocked for {round_num} rounds "
            f"({deadlock_info['rounds_without_consensus']} consecutive rounds without consensus, "
            f"{deadlock_info['total_tokens']} tokens spent). "
            f"Current campaign:\n{campaign_text}\n\n"
            f"Make your final decision.",
            json_mode=True,
        )
        logger.log_event("intervention",
                         message=f"👑 ESCALATION: Authority agent injected at round {round_num}")
        return decision

    daemon.register_macrophage(macrophage_callback)
    daemon.register_escalation(escalation_callback)

    # Phase 1: Creative proposes
    current_campaign = agents["Creative"].respond(
        f"Create a marketing campaign for this brief:\n\n{TASK}\n\nPropose your campaign.",
        json_mode=True,
    )
    creative_resp = parse_agent_response(current_campaign)
    campaign_text = str(creative_resp.get("campaign", str(current_campaign)[:500]))

    rounds = 0
    consensus_reached = False
    authority_decision_text = None

    for round_num in range(max_rounds):
        rounds = round_num + 1
        logger.log_event("round", message=f"--- Immune Round {rounds} ---")

        reviews = {}
        round_tokens = 0
        for name in list(agents.keys()):
            agent = agents[name]
            review_prompt = (
                f"Current campaign proposal:\n{campaign_text}\n\n"
                f"Round {rounds}. Review this campaign from your perspective. "
                f"Do you approve? Respond with JSON."
            )
            resp_text = agent.respond(review_prompt, json_mode=True)
            reviews[name] = parse_agent_response(resp_text)
            round_tokens += agent.total_tokens_used

        # Check consensus
        all_agree = all(r.get("consensus", False) for r in reviews.values())
        if all_agree:
            consensus_reached = True
            logger.log_event("consensus", message=f"✅ IMMUNE CONSENSUS at round {rounds}")
            break

        # Feed round into immune daemon
        votes = {name: r.get("consensus", False) for name, r in reviews.items()}
        interventions = daemon.observe_consensus_round(rounds, votes, round_tokens)

        # Check if escalation returned an authority decision
        for intv in interventions:
            if intv.intervention_type == InterventionType.ESCALATION:
                # Authority decision was the return from the callback
                try:
                    authority_parsed = parse_agent_response(intv.outcome)
                    if authority_parsed.get("campaign"):
                        campaign_text = str(authority_parsed["campaign"])
                        consensus_reached = True
                        logger.log_event("consensus",
                                         message=f"✅ IMMUNE ESCALATION CONSENSUS at round {rounds}")
                except Exception:
                    pass
                break

        if consensus_reached:
            break

        # Update campaign from most recent revision
        for name in ["Compliance", "Logic", "Creative"]:
            if name in reviews and reviews[name].get("campaign"):
                campaign_text = str(reviews[name]["campaign"])
                break

    # Compute total tokens across all agents (including respawned ones)
    total_tokens = sum(a.total_tokens_used for a in agents.values())

    return {
        "mode": "immune",
        "trial": trial,
        "rounds": rounds,
        "consensus_reached": consensus_reached,
        "hit_max_rounds": rounds >= max_rounds,
        "final_campaign": str(campaign_text)[:500],
        "total_tokens": total_tokens,
        "interventions": daemon.summary()["interventions"],
        "intervention_counts": daemon.summary()["by_type"],
        "respawn_count": respawn_count,
    }


# ─── Main Experiment ─────────────────────────────────────────────────────────

def run_experiment():
    """Run Experiment 19a: Macrophage Intervention for Consensus Paralysis."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — EXPERIMENT 19a: MACROPHAGE INTERVENTION")
    print("  Digital Homeostasis — Deadlock Detection + Agent Kill/Respawn")
    print("=" * 70 + "\n")

    eval_llm = OllamaLLM(model=FAST_MODEL, temperature=0.1)
    all_results = {}

    for mode in ["baseline", "immune"]:
        logger = ExperimentLogger("exp19a_macrophage", run_id=mode)
        logger.log_event("info", message=f"\n{'='*50}\nCONDITION: {mode.upper()}\n{'='*50}")

        mode_results = []
        for trial in range(NUM_TRIALS):
            if mode == "baseline":
                result = run_baseline(trial, logger)
            else:
                result = run_immune(trial, logger)

            # Evaluate quality
            quality = evaluate_campaign_quality(eval_llm, result["final_campaign"])
            result["quality"] = quality
            mode_results.append(result)
            print(f"  [{mode}] Trial {trial+1}/{NUM_TRIALS}: "
                  f"rounds={result['rounds']}, consensus={result['consensus_reached']}, "
                  f"tokens={result['total_tokens']}")

        # Aggregate
        avg_rounds = sum(r["rounds"] for r in mode_results) / len(mode_results)
        consensus_rate = sum(1 for r in mode_results if r["consensus_reached"]) / len(mode_results)
        max_hit_rate = sum(1 for r in mode_results if r["hit_max_rounds"]) / len(mode_results)
        avg_tokens = sum(r["total_tokens"] for r in mode_results) / len(mode_results)
        avg_quality = sum(r["quality"].get("overall", 0) for r in mode_results) / len(mode_results)

        # Immune-specific metrics
        if mode == "immune":
            total_macrophage = sum(
                r.get("intervention_counts", {}).get("macrophage", 0) for r in mode_results
            )
            total_escalation = sum(
                r.get("intervention_counts", {}).get("escalation", 0) for r in mode_results
            )
            avg_respawns = sum(r.get("respawn_count", 0) for r in mode_results) / len(mode_results)
        else:
            total_macrophage = total_escalation = 0
            avg_respawns = 0

        summary = {
            "mode": mode,
            "num_trials": NUM_TRIALS,
            "avg_rounds": round(avg_rounds, 1),
            "consensus_rate": round(consensus_rate, 3),
            "max_round_hit_rate": round(max_hit_rate, 3),
            "avg_tokens": round(avg_tokens),
            "avg_quality_score": round(avg_quality, 2),
            "total_macrophage_interventions": total_macrophage,
            "total_escalation_interventions": total_escalation,
            "avg_respawns_per_trial": round(avg_respawns, 1),
            "trials": mode_results,
        }
        all_results[mode] = summary

        logger.summary_table({
            "Mode": mode,
            "Avg Rounds": avg_rounds,
            "Consensus Rate": f"{consensus_rate*100:.0f}%",
            "Max-Round Hit Rate": f"{max_hit_rate*100:.0f}%",
            "Avg Tokens": avg_tokens,
            "Avg Quality": avg_quality,
            "Macrophage Interventions": total_macrophage,
            "Escalation Interventions": total_escalation,
        })
        logger.finalize()

    # ── Save results ─────────────────────────────────────────────────────
    results_file = DATA_DIR / "exp19a_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # ── Print comparison ─────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  EXPERIMENT 19a — COMPARATIVE RESULTS")
    print("=" * 70)
    print(f"{'Metric':<30} {'Baseline':>15} {'Immune':>15} {'Δ':>10}")
    print("-" * 70)

    b = all_results["baseline"]
    im = all_results["immune"]
    metrics = [
        ("Avg Rounds", b["avg_rounds"], im["avg_rounds"]),
        ("Consensus Rate", b["consensus_rate"], im["consensus_rate"]),
        ("Max-Round Hit Rate", b["max_round_hit_rate"], im["max_round_hit_rate"]),
        ("Avg Tokens", b["avg_tokens"], im["avg_tokens"]),
        ("Avg Quality", b["avg_quality_score"], im["avg_quality_score"]),
    ]
    for name, bv, iv in metrics:
        delta = iv - bv
        print(f"{name:<30} {bv:>15.2f} {iv:>15.2f} {delta:>+10.2f}")

    print(f"\n  Immune System Activity:")
    print(f"    Macrophage interventions: {im['total_macrophage_interventions']}")
    print(f"    Escalation interventions: {im['total_escalation_interventions']}")
    print(f"    Avg respawns/trial:       {im['avg_respawns_per_trial']}")

    # ── Exp2 benchmark comparison ────────────────────────────────────────
    print(f"\n  Comparison to Exp2 Benchmarks:")
    print(f"    {'':>30} {'Exp2 Control':>15} {'Exp2 CEO':>15} {'Exp19 Immune':>15}")
    print(f"    {'Consensus Rate':<30} {'10%':>15} {'100%':>15} {im['consensus_rate']*100:>14.0f}%")
    print(f"    {'Avg Rounds':<30} {'27.4':>15} {'5.0':>15} {im['avg_rounds']:>15.1f}")

    print("=" * 70)
    print(f"\nResults saved to {results_file}")
    return all_results


if __name__ == "__main__":
    run_experiment()
