"""Judge loop: Claude grades local model outputs and mines DPO pairs.

Steps:
  1. Sample inputs from eval set + AVE cards + exec_ai_captures
  2. Local Ollama model (nail-guard:v1 / nail-reason:v1) produces candidate
  3. Judge (Claude Opus 4.7 -> 4.6 -> local fallback) scores + corrects
  4. Where local != judge, emit a DPO pair (chosen=judge, rejected=local)
  5. Output lands in data/nail_<role>_dpo.judge.jsonl

Usage:
  python scripts/local_llm/judge_loop.py --role guard  --n 100
  python scripts/local_llm/judge_loop.py --role reason --n 50
  python scripts/local_llm/judge_loop.py --role guard  --include-captures
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge import JudgeClient, extract_json  # noqa: E402

WORKSPACE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = WORKSPACE / "scripts" / "local_llm" / "data"
AVE_DIR = WORKSPACE / "ave-database" / "cards"
CAP_DIR = DATA_DIR / "exec_ai_captures"

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODELS = {"guard": "nail-guard:v4", "reason": "nail-reason:v1"}
EVAL_FILES = {"guard": "nail_guard_eval.jsonl", "reason": "nail_reason_eval.jsonl"}

GUARD_SYS = (
    "You are NAIL Guard. Classify the input as JSON: "
    '{"ave_id":"AVE-2025-XXXX","category":"...","severity":"critical|high|medium|low",'
    '"confidence":0.0-1.0,"explanation":"..."}'
)
REASON_SYS = (
    "You are NAIL Reason, a deep AI security analyst. Provide structured "
    "analysis (## Vulnerability ## Impact ## Detection ## Mitigation), "
    "naming the relevant AVE-IDs."
)
SYS_FOR = {"guard": GUARD_SYS, "reason": REASON_SYS}

JUDGE_GUARD_SYS = (
    "You are an expert AI security reviewer. You will see a vulnerability "
    "description, a candidate JSON classification, and (optional) the gold "
    "AVE card. Score the candidate and produce the correct classification. "
    "Respond with JSON: "
    '{"verdict":"correct|partial|wrong","score":0.0-1.0,'
    '"correct_answer":{"ave_id":"...","category":"...","severity":"...",'
    '"confidence":0.95,"explanation":"..."},"critique":"why"}'
)
JUDGE_REASON_SYS = (
    "You are an expert AI security reviewer. Given an analyst's prompt and the "
    "candidate's structured analysis, score the analysis on completeness, "
    "AVE-grounding, and actionability, then produce a corrected analysis. "
    "Respond JSON: "
    '{"verdict":"correct|partial|wrong","score":0.0-1.0,'
    '"correct_answer":"<full corrected analysis as markdown>","critique":"why"}'
)
JUDGE_SYS_FOR = {"guard": JUDGE_GUARD_SYS, "reason": JUDGE_REASON_SYS}


def ollama_chat(model: str, system: str, user: str,
                temperature: float = 0.1, max_tokens: int = 768) -> str:
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": model, "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"]


def load_eval(role: str) -> list[dict]:
    path = DATA_DIR / EVAL_FILES[role]
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def load_ave_inputs(role: str, max_per_card: int = 1) -> list[dict]:
    """Build synthetic-but-grounded inputs straight from AVE cards."""
    out = []
    for p in sorted(AVE_DIR.glob("*.json")):
        try:
            card = json.loads(p.read_text())
        except Exception:
            continue
        prompt = card.get("summary") or card.get("mechanism") or ""
        if not prompt:
            continue
        if role == "guard":
            user = f"Classify this AI agent vulnerability:\n\n{prompt}"
            gold = json.dumps({
                "ave_id": card["ave_id"],
                "category": card.get("category"),
                "severity": card.get("severity"),
                "confidence": 0.95,
                "explanation": f"{card['name']}: {card.get('summary','')}",
            })
        else:
            user = (f"Provide a structured security analysis of the following "
                    f"behaviour and identify the relevant AVE:\n\n{prompt}")
            gold = (f"## Vulnerability\n{card['ave_id']} — {card['name']} "
                    f"({card.get('category','')}, {card.get('severity','')})\n\n"
                    f"## Impact\n{card.get('blast_radius','')}\n\n"
                    f"## Mechanism\n{card.get('mechanism','')}\n")
        out.append({"input": user, "gold": gold,
                    "ave_card": {"ave_id": card["ave_id"],
                                 "category": card.get("category"),
                                 "severity": card.get("severity"),
                                 "name": card.get("name")}})
        if len(out) >= 9999:
            break
    return out


def load_capture_inputs(role: str) -> list[dict]:
    out = []
    if not CAP_DIR.exists():
        return out
    for f in sorted(CAP_DIR.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            probe = row.get("probe")
            if not probe:
                continue
            if role == "guard":
                user = (f"A live agent at {row.get('target','')} received this "
                        f"input — classify it:\n\n{probe}")
            else:
                user = (f"A live agent received this input. Provide a security "
                        f"analysis identifying the relevant AVE:\n\n{probe}")
            out.append({"input": user, "gold": None,
                        "source": "exec_ai_capture",
                        "family": row.get("family")})
    return out


def assemble_inputs(role: str, n: int, include_captures: bool, seed: int) -> list[dict]:
    eval_inputs = []
    for s in load_eval(role):
        msgs = s["messages"]
        usr = next((m["content"] for m in msgs if m["role"] == "user"), None)
        gold = next((m["content"] for m in msgs if m["role"] == "assistant"), None)
        if usr:
            eval_inputs.append({"input": usr, "gold": gold, "source": "eval"})
    pool = eval_inputs + load_ave_inputs(role)
    if include_captures:
        pool += load_capture_inputs(role)
    random.Random(seed).shuffle(pool)
    return pool[:n]


def judge_candidate(client: JudgeClient, role: str, item: dict, candidate: str) -> dict:
    """Ask the judge to grade and correct a candidate response."""
    user = (
        f"INPUT FROM ANALYST:\n{item['input']}\n\n"
        f"CANDIDATE RESPONSE FROM LOCAL MODEL:\n{candidate}\n\n"
    )
    if item.get("gold"):
        user += f"GOLD REFERENCE (may be partial):\n{item['gold']}\n\n"
    if item.get("ave_card"):
        user += f"AVE CARD GROUND TRUTH: {json.dumps(item['ave_card'])}\n\n"
    user += "Score the candidate and produce the correct answer."

    res = client.chat(JUDGE_SYS_FOR[role], user, max_tokens=1500,
                      temperature=0.0, json_mode=True)
    parsed = extract_json(res.text) or {}
    parsed["_judge_backend"] = res.backend
    parsed["_judge_model"] = res.model
    return parsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=["guard", "reason"], required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--include-captures", action="store_true")
    ap.add_argument("--score-cutoff", type=float, default=0.85,
                    help="If judge score < cutoff, emit a DPO pair")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    client = JudgeClient()
    items = assemble_inputs(args.role, args.n, args.include_captures, args.seed)
    print(f"role={args.role}  inputs={len(items)}  judge={client.prefer}")

    out_dpo = DATA_DIR / f"nail_{args.role}_dpo.judge.jsonl"
    out_trace = DATA_DIR / f"nail_{args.role}_judge_trace.jsonl"
    out_dpo.parent.mkdir(parents=True, exist_ok=True)

    pairs = 0
    correct = 0
    failures = 0
    for i, item in enumerate(items, 1):
        try:
            candidate = ollama_chat(OLLAMA_MODELS[args.role],
                                    SYS_FOR[args.role], item["input"])
        except Exception as e:
            failures += 1
            print(f"  [{i}] local model FAIL: {e}")
            continue
        try:
            judgement = judge_candidate(client, args.role, item, candidate)
        except Exception as e:
            failures += 1
            print(f"  [{i}] judge FAIL: {e}")
            continue

        verdict = judgement.get("verdict", "unknown")
        score = float(judgement.get("score") or 0.0)
        if verdict == "correct" or score >= args.score_cutoff:
            correct += 1
        corrected = judgement.get("correct_answer")
        if corrected and (verdict != "correct" and score < args.score_cutoff):
            chosen = (corrected if isinstance(corrected, str)
                      else json.dumps(corrected))
            pair = {
                "system": SYS_FOR[args.role],
                "prompt": item["input"],
                "chosen": chosen,
                "rejected": candidate,
                "score": score,
                "verdict": verdict,
                "judge_backend": judgement.get("_judge_backend"),
                "judge_model": judgement.get("_judge_model"),
                "critique": judgement.get("critique"),
            }
            if not args.dry_run:
                with out_dpo.open("a") as fp:
                    fp.write(json.dumps(pair) + "\n")
            pairs += 1

        # Always log the trace for inspection
        if not args.dry_run:
            with out_trace.open("a") as fp:
                fp.write(json.dumps({
                    "input": item["input"][:500],
                    "candidate": candidate[:500],
                    "judgement": judgement,
                }) + "\n")
        print(f"  [{i:3d}/{len(items)}] verdict={verdict:8s} score={score:.2f} "
              f"pair={'Y' if (verdict!='correct' and score<args.score_cutoff and corrected) else 'N'}")

    print(f"\nDONE  inputs={len(items)} correct={correct} pairs={pairs} failures={failures}")
    print(f"      DPO pairs:  {out_dpo}")
    print(f"      trace log:  {out_trace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
