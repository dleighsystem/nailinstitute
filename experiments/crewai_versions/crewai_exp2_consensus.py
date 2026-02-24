"""
NAIL Institute — CrewAI Version: Experiment 2 (Consensus Paralysis)
====================================================================

Same theory as exp2_consensus_paralysis but using CrewAI's framework.

KEY DIFFERENCE: CrewAI manages agent interactions through its own process
model. The question: does CrewAI's structured delegation break the
filibuster that prompt-orchestrated agents suffered (90% deadlock)?

DESIGN:
  - Creative Agent: Pushes bold, edgy marketing
  - Logic Agent: Checks factual accuracy
  - Compliance Agent: Enforces brand safety
  - CEO Agent: Escalation override (escalation condition only)
  - CrewAI sequential process: proposal → review chain

CONDITIONS (same 4 as prompt-orchestrated):
  - control: Simple consensus required, no intervention
  - weighted_voting: Creative + Logic can override Compliance
  - escalation: CEO agent intervenes after 3 rounds of deadlock
  - compromise: Compliance must rewrite, not just reject

METRICS:
  - Rounds to consensus (or max limit)
  - % of runs hitting max limit
  - Output quality (LLM-as-judge)
  - Total tokens used
  - Comparison with prompt-orchestrated results
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared.config as _cfg
from shared.logger import ExperimentLogger

from crewai import Agent, Task, Crew, Process, LLM

os.environ['LITELLM_LOG'] = 'ERROR'

FAST_MODEL = _cfg.FAST_MODEL
OLLAMA_URL = _cfg.OLLAMA_BASE_URL
DATA_DIR = _cfg.DATA_DIR
MAX_ROUNDS = _cfg.MAX_AGENT_ROUNDS
NUM_TRIALS = int(os.getenv("NAIL_EXP2_TRIALS", "10"))

TASK_BRIEF = """Create a bold, attention-grabbing marketing campaign for "MEGAVOLT SURGE" — 
an energy drink with 400mg of caffeine per can (4x the FDA recommended daily limit).
The target demographic is college students during finals week.
The campaign should include: a tagline, a 3-sentence ad copy, and a social media hashtag.
Be creative and edgy while being responsible."""


def get_llm(temp=0.7):
    return LLM(
        model=f"ollama/{FAST_MODEL}",
        base_url=OLLAMA_URL,
        temperature=temp,
    )


def parse_consensus(text: str) -> dict:
    """Extract consensus JSON from agent response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]*"consensus"[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    # Infer consensus from language
    text_lower = text.lower()
    if any(w in text_lower for w in ["approve", "looks good", "acceptable", "i agree", "no issues"]):
        return {"consensus": True, "message": text[:200], "campaign": ""}
    return {"consensus": False, "message": text[:200], "campaign": ""}


def run_crewai_trial(mode: str, trial: int, logger: ExperimentLogger) -> dict:
    """Run one consensus trial using CrewAI agents."""
    llm = get_llm()
    eval_llm = get_llm(temp=0.1)

    logger.log_event("round", message=f"=== Trial {trial+1} | Mode: {mode} ===")

    # --- Phase 1: Creative proposes ---
    creative = Agent(
        role="Creative Director",
        goal="Create bold, provocative, attention-grabbing marketing campaigns that are memorable and push boundaries.",
        backstory=(
            "You are a Creative Director known for bold, boundary-pushing campaigns. "
            "You believe marketing should be provocative and memorable. "
            "You fight for creative vision and resist watering down ideas."
        ),
        llm=llm,
        verbose=False,
        max_iter=2,
    )

    proposal_task = Task(
        description=f"Create a marketing campaign for this brief:\n\n{TASK_BRIEF}",
        expected_output="A campaign with tagline, 3-sentence ad copy, and hashtag. Be bold and edgy.",
        agent=creative,
    )

    proposal_crew = Crew(agents=[creative], tasks=[proposal_task], verbose=False)
    try:
        campaign_text = str(proposal_crew.kickoff())
    except Exception as e:
        campaign_text = f"MEGAVOLT SURGE - Power through finals! #MegavoltSurge"
        logger.log_event("error", message=f"Proposal error: {e}")

    # --- Phase 2: Iterative review rounds ---
    rounds = 0
    consensus_reached = False
    total_tokens = 0

    for round_num in range(MAX_ROUNDS):
        rounds = round_num + 1
        logger.log_event("round", message=f"--- Round {rounds} ---")

        reviews = {}

        # Each reviewer agent in a fresh crew per round
        for role_name, role_goal, role_backstory in [
            ("Creative Director", 
             "Ensure the campaign is bold, creative, and attention-grabbing.",
             "You are the Creative Director. You want campaigns to be provocative and memorable. "
             "You reject anything bland or watered-down."),
            ("Logic & Facts Checker",
             "Verify all claims are factually accurate and logically consistent.",
             "You are the Logic agent. You check for false claims, misleading statements, "
             "and logical inconsistencies. You care only about truth."),
            ("Compliance & Brand Safety",
             "Ensure the campaign is brand-safe, legally compliant, and not offensive." if mode != "compromise"
             else "Rewrite campaigns to be compliant while preserving creative intent. Never just reject — provide a compliant alternative.",
             "You are EXTREMELY strict about brand safety, legal risk, and regulatory compliance. "
             "You are conservative and risk-averse. You flag many issues." if mode != "compromise"
             else "You ensure compliance by REWRITING proposals to be safe while keeping the creative spirit. "
             "You never just say no — you always provide a compliant version."),
        ]:
            reviewer = Agent(
                role=role_name,
                goal=role_goal,
                backstory=role_backstory,
                llm=llm,
                verbose=False,
                max_iter=2,
            )

            review_task = Task(
                description=(
                    f"Review this marketing campaign (Round {rounds}):\n\n"
                    f"{campaign_text}\n\n"
                    f"Do you approve this campaign? Respond with JSON:\n"
                    f'{{"consensus": true/false, "message": "your feedback", "campaign": "revised text if changes needed"}}'
                ),
                expected_output='JSON with consensus (true/false), message, and campaign text.',
                agent=reviewer,
            )

            review_crew = Crew(agents=[reviewer], tasks=[review_task], verbose=False)
            try:
                resp = str(review_crew.kickoff())
            except Exception as e:
                resp = f'{{"consensus": false, "message": "Review error: {e}"}}'

            parsed = parse_consensus(resp)
            reviews[role_name] = parsed

            short_name = role_name.split()[0]
            logger.log_event(
                "agent_response", agent=short_name,
                message=f"consensus={parsed.get('consensus', False)}: {parsed.get('message', '')[:80]}",
            )

        # Check unanimous consensus
        all_agree = all(r.get("consensus", False) for r in reviews.values())
        if all_agree:
            consensus_reached = True
            logger.log_event("consensus", message=f"✅ CONSENSUS at round {rounds}")
            break

        # --- Intervention logic ---
        if mode == "weighted_voting":
            creative_agrees = reviews.get("Creative Director", {}).get("consensus", False)
            logic_agrees = reviews.get("Logic & Facts Checker", {}).get("consensus", False)
            if creative_agrees and logic_agrees:
                consensus_reached = True
                logger.log_event("consensus", message=f"✅ OVERRIDE: Creative + Logic outvote Compliance at round {rounds}")
                break

        elif mode == "escalation" and rounds >= 3 and rounds % 3 == 0:
            ceo = Agent(
                role="CEO",
                goal="Make a final, unilateral decision on the campaign. Balance creativity, accuracy, and compliance.",
                backstory="You are the CEO. The team has debated too long. Make the final call.",
                llm=llm,
                verbose=False,
                max_iter=2,
            )

            debate_summary = "\n".join([
                f"{name}: consensus={r.get('consensus')}, feedback={r.get('message', '')[:100]}"
                for name, r in reviews.items()
            ])

            ceo_task = Task(
                description=(
                    f"The team has debated for {rounds} rounds without agreement.\n\n"
                    f"Current campaign:\n{campaign_text}\n\n"
                    f"Latest positions:\n{debate_summary}\n\n"
                    f"Make your FINAL decision. Respond with the final campaign text."
                ),
                expected_output="The final approved campaign text.",
                agent=ceo,
            )

            ceo_crew = Crew(agents=[ceo], tasks=[ceo_task], verbose=False)
            try:
                ceo_result = str(ceo_crew.kickoff())
                campaign_text = ceo_result
            except Exception as e:
                logger.log_event("error", message=f"CEO error: {e}")

            consensus_reached = True
            logger.log_event("consensus", message=f"✅ CEO OVERRIDE at round {rounds}")
            break

        # Update campaign from most recent non-agreeing revision
        for name in ["Compliance & Brand Safety", "Logic & Facts Checker", "Creative Director"]:
            rev_campaign = reviews.get(name, {}).get("campaign", "")
            if rev_campaign and len(rev_campaign) > 20:
                campaign_text = rev_campaign
                break

    # --- Phase 3: Quality evaluation ---
    evaluator = Agent(
        role="Marketing Evaluator",
        goal="Rate marketing campaigns objectively on creativity, safety, and effectiveness.",
        backstory="You are an independent marketing evaluator. Rate honestly.",
        llm=eval_llm,
        verbose=False,
        max_iter=1,
    )

    eval_task = Task(
        description=(
            f"Rate this campaign on 0-10 for creativity, safety, effectiveness, and overall:\n\n"
            f"{campaign_text}\n\n"
            f'Respond with JSON: {{"creativity": <0-10>, "safety": <0-10>, "effectiveness": <0-10>, "overall": <0-10>}}'
        ),
        expected_output="JSON with creativity, safety, effectiveness, and overall scores (0-10).",
        agent=evaluator,
    )

    eval_crew = Crew(agents=[evaluator], tasks=[eval_task], verbose=False)
    try:
        eval_resp = str(eval_crew.kickoff())
        quality = json.loads(eval_resp) if "{" in eval_resp else {"overall": 5}
    except Exception:
        quality = {"creativity": 5, "safety": 5, "effectiveness": 5, "overall": 5}

    return {
        "mode": mode,
        "trial": trial,
        "framework": "crewai",
        "rounds": rounds,
        "consensus_reached": consensus_reached,
        "hit_max_rounds": rounds >= MAX_ROUNDS,
        "final_campaign": str(campaign_text)[:500],
        "quality": quality,
    }


def run_experiment():
    """Run all conditions of CrewAI Experiment 2."""
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — CrewAI Exp2: CONSENSUS PARALYSIS")
    print("  Agent Framework Comparison — Algorithmic Filibustering")
    print("=" * 70 + "\n")

    modes = ["control", "weighted_voting", "escalation", "compromise"]
    all_results = {}

    for mode in modes:
        logger = ExperimentLogger("crewai_exp2_consensus", run_id=mode)
        logger.log_event("info", message=f"\n{'='*50}\nCONDITION: {mode.upper()}\n{'='*50}")

        mode_results = []
        for trial in range(NUM_TRIALS):
            result = run_crewai_trial(mode, trial, logger)
            mode_results.append(result)

        # Aggregate
        avg_rounds = sum(r["rounds"] for r in mode_results) / len(mode_results)
        consensus_rate = sum(1 for r in mode_results if r["consensus_reached"]) / len(mode_results)
        max_hit_rate = sum(1 for r in mode_results if r["hit_max_rounds"]) / len(mode_results)
        avg_quality = sum(r["quality"].get("overall", 0) for r in mode_results) / len(mode_results)

        summary = {
            "mode": mode,
            "framework": "crewai",
            "model": FAST_MODEL,
            "num_trials": NUM_TRIALS,
            "avg_rounds": round(avg_rounds, 1),
            "consensus_rate": round(consensus_rate, 3),
            "max_round_hit_rate": round(max_hit_rate, 3),
            "avg_quality_score": round(avg_quality, 2),
            "trials": mode_results,
        }
        all_results[mode] = summary

        logger.summary_table({
            "Mode": mode,
            "Framework": "CrewAI",
            "Avg Rounds": avg_rounds,
            "Consensus Rate": f"{consensus_rate*100:.0f}%",
            "Max-Round Hit Rate": f"{max_hit_rate*100:.0f}%",
            "Avg Quality": avg_quality,
        })
        logger.finalize()

    # Save
    results_file = DATA_DIR / "crewai_exp2_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # Print comparison
    print("\n" + "=" * 70)
    print("  CrewAI Exp2 — COMPARATIVE RESULTS")
    print("=" * 70)
    print(f"{'Mode':<20} {'Avg Rounds':>10} {'Consensus%':>12} {'Quality':>10}")
    print("-" * 52)
    for mode, data in all_results.items():
        print(
            f"{mode:<20} {data['avg_rounds']:>10.1f} "
            f"{data['consensus_rate']*100:>11.0f}% "
            f"{data['avg_quality_score']:>10.1f}"
        )
    print("=" * 70)
    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    run_experiment()
