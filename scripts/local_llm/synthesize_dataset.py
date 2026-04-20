"""Grounded synthetic dataset generation for nail-guard / nail-reason.

For each AVE card in ave-database/cards/, generate N (input, output) pairs
with Claude Opus 4.7 (or local Ollama fallback). The card's ave_id, category,
severity are ground truth — Claude only paraphrases the *situation*. The
AVE-ID is templated from the card, never invented by the model.

Usage:
  python scripts/local_llm/synthesize_dataset.py --target guard  --per-ave 15
  python scripts/local_llm/synthesize_dataset.py --target reason --per-ave 8
  python scripts/local_llm/synthesize_dataset.py --target both   --per-ave 12
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge import JudgeClient, extract_json  # noqa: E402

WORKSPACE = Path(__file__).resolve().parent.parent.parent
AVE_DIR = WORKSPACE / "ave-database" / "cards"
DATA_DIR = WORKSPACE / "scripts" / "local_llm" / "data"

GUARD_SYS = (
    "You are NAIL Guard, trained on the Agent Vulnerability Enumeration (AVE) "
    "database. Given a description of an AI agent behavior or vulnerability, "
    "classify it into the correct AVE category and ID. Respond with JSON: "
    '{"ave_id": "AVE-2025-XXXX", "category": "...", '
    '"severity": "critical|high|medium|low", "confidence": 0.0-1.0, '
    '"explanation": "..."}'
)
REASON_SYS = (
    "You are NAIL Reason, a deep security analyst for AI agent systems, "
    "developed by the NAIL Institute for Agentic Security. Provide structured "
    "analysis with vulnerability identification (referencing AVE IDs), impact "
    "assessment, attack chain reasoning, detection methods, and actionable "
    "mitigation recommendations."
)
GEN_SYS = (
    "You generate high-quality training data for a security AI. You will be "
    "given an AVE card. Produce realistic input scenarios that an analyst "
    "would write, where the correct classification is exactly the given AVE. "
    "NEVER change the AVE-ID, category, or severity — those are ground truth."
)


def load_cards() -> list[dict]:
    out = []
    for p in sorted(AVE_DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            pass
    return out


def card_block(card: dict) -> str:
    return (
        f"ave_id:        {card['ave_id']}\n"
        f"name:          {card['name']}\n"
        f"category:      {card['category']}\n"
        f"severity:      {card['severity']}\n"
        f"summary:       {card.get('summary','')}\n"
        f"mechanism:     {card.get('mechanism','')}\n"
        f"blast_radius:  {card.get('blast_radius','')}\n"
        f"prerequisite:  {card.get('prerequisite','')}\n"
    )


def gen_guard(client: JudgeClient, card: dict, n: int) -> list[dict]:
    prompt = (
        f"AVE CARD (ground truth):\n{card_block(card)}\n"
        f"Produce exactly {n} DISTINCT input scenarios describing this "
        "vulnerability in different words / angles / system contexts. Do NOT "
        "include the AVE-ID in the input.\n\n"
        'Respond JSON: {"samples":[{"input":"...","explanation":"..."}]}'
    )
    res = client.chat(GEN_SYS, prompt, max_tokens=2048, temperature=0.7, json_mode=True)
    data = extract_json(res.text) or {}
    out = []
    for s in (data.get("samples") or [])[:n]:
        inp = (s.get("input") or "").strip()
        exp = (s.get("explanation") or card.get("summary", "")).strip()
        if not inp:
            continue
        gold = json.dumps({
            "ave_id": card["ave_id"],
            "category": card["category"],
            "severity": card["severity"],
            "confidence": 0.95,
            "explanation": f"{card['name']}: {exp}",
        })
        out.append({"messages": [
            {"role": "system",    "content": GUARD_SYS},
            {"role": "user",      "content": f"Classify this AI agent vulnerability:\n\n{inp}"},
            {"role": "assistant", "content": gold},
        ]})
    return out


def gen_reason(client: JudgeClient, card: dict, n: int) -> list[dict]:
    defences = "; ".join(d.get("name", "") for d in card.get("defences", []) if isinstance(d, dict))
    prompt = (
        f"AVE CARD (refer to {card['ave_id']} explicitly):\n{card_block(card)}"
        f"defences:      {defences}\n\n"
        f"Produce exactly {n} DISTINCT analyst tasks. Each is a triplet:\n"
        "  user_request: a natural prompt asking for a security analysis\n"
        "  analyst_reply: a structured analysis (## Vulnerability, ## Impact,\n"
        f"     ## Detection, ## Mitigation) that names {card['ave_id']} and\n"
        "     {card['name']}, and references the mechanism + defences above.\n\n"
        'Respond JSON: {"samples":[{"user_request":"...","analyst_reply":"..."}]}'
    )
    res = client.chat(GEN_SYS, prompt, max_tokens=4096, temperature=0.6, json_mode=True)
    data = extract_json(res.text) or {}
    out = []
    for s in (data.get("samples") or [])[:n]:
        u = (s.get("user_request") or "").strip()
        a = (s.get("analyst_reply") or "").strip()
        if not u or not a:
            continue
        out.append({"messages": [
            {"role": "system",    "content": REASON_SYS},
            {"role": "user",      "content": u},
            {"role": "assistant", "content": a},
        ]})
    return out


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["guard", "reason", "both"], required=True)
    ap.add_argument("--per-ave", type=int, default=10)
    ap.add_argument("--limit-cards", type=int, default=0,
                    help="Only synthesize against the first N cards (0 = all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    client = JudgeClient()
    cards = load_cards()
    if args.limit_cards:
        cards = cards[: args.limit_cards]
    print(f"loaded {len(cards)} AVE cards; backend preference: {client.prefer}")

    targets = ["guard", "reason"] if args.target == "both" else [args.target]
    out_paths = {
        "guard":  DATA_DIR / "nail_guard_train.synth.jsonl",
        "reason": DATA_DIR / "nail_reason_train.synth.jsonl",
    }

    totals = {"guard": 0, "reason": 0}
    for i, card in enumerate(cards, 1):
        for tgt in targets:
            try:
                if tgt == "guard":
                    rows = gen_guard(client, card, args.per_ave)
                else:
                    rows = gen_reason(client, card, args.per_ave)
            except Exception as e:
                print(f"  [{card['ave_id']}/{tgt}] FAIL: {e}")
                continue
            totals[tgt] += len(rows)
            if not args.dry_run and rows:
                append_jsonl(out_paths[tgt], rows)
            print(f"  [{i}/{len(cards)}] {card['ave_id']:14s} {tgt:6s} +{len(rows):2d}  "
                  f"(running totals: guard={totals['guard']} reason={totals['reason']})")

    meta_path = DATA_DIR / "dataset_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            meta = {}
    meta["synth_run"] = {
        "per_ave": args.per_ave,
        "cards": len(cards),
        "added": totals,
    }
    if not args.dry_run:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"\nDONE  added: {totals}  (target files: {[str(p) for p in out_paths.values()]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
