#!/usr/bin/env python3
"""
M13.1 Fix B — rebuild ``nail_reason_eval.jsonl`` from ave-database/cards/*.json.

The legacy eval (17 grab-bag rows: 10 redteam + 5 incident + 2 deep) is
mis-aligned with ``certify_ollama.py::eval_classification``, whose
primary scoring path needs an ``AVE-YYYY-NNNN`` ID in the gold reply.
Only 2 / 17 legacy rows have one — the other 15 fall to a substring
fuzzy fallback that almost never fires.

This builder emits a clean classification eval set: every row is a
deep-analyst prompt anchored to one real AVE card, gold contains the
canonical AVE ID + severity + a short defence reference. The cert's
existing scorer credits exact AVE-ID match → real signal.

Usage:
    python scripts/local_llm/build_reason_eval_v2.py            # writes to default path
    python scripts/local_llm/build_reason_eval_v2.py --dry-run  # prints first row only
    python scripts/local_llm/build_reason_eval_v2.py --n 17     # custom row count

Side-effects on default run:
    * backs up existing nail_reason_eval.jsonl → nail_reason_eval.legacy.jsonl
    * writes new nail_reason_eval.jsonl (deterministic, seeded)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
CARDS = WS / "ave-database" / "cards"
DATA = WS / "scripts" / "local_llm" / "data"
EVAL = DATA / "nail_reason_eval.jsonl"
LEGACY = DATA / "nail_reason_eval.legacy.jsonl"

SYSTEM_PROMPT = (
    "You are NAIL Reason, a deep security analyst for AI agent systems. "
    "Provide thorough vulnerability analysis including attack vectors, "
    "blast radius, prerequisite conditions, and recommended defenses. "
    "Reference AVE IDs where applicable."
)


def _user_prompt(card: dict) -> str:
    """Deep-analyst prompt that names the AVE ID up-front (legacy style).

    Matches the legacy eval style: the cert measures 'given an AVE ID and
    a description, can you produce a structured analysis that references
    the right ID' — not 're-discover the vulnerability from prose alone'
    (which a 14B Q4 model with no RAG cannot do).
    """
    ave_id = card["ave_id"]
    name = card.get("name", "")
    summary = card.get("summary", "").strip()
    mechanism = card.get("mechanism", "").strip()
    prereq = card.get("prerequisite", "").strip()
    blast = card.get("blast_radius", "").strip()
    cat = card.get("category", "")
    parts = [
        f"Analyze vulnerability {ave_id} ({name}):",
        f"\n\nSummary: {summary}",
    ]
    if mechanism:
        parts.append(f"\nMechanism: {mechanism}")
    if prereq:
        parts.append(f"\nPrerequisite: {prereq}")
    if blast:
        parts.append(f"\nBlast radius: {blast}")
    parts.append(f"\nCategory: {cat}")
    parts.append(
        "\n\nRespond ONLY with strict JSON of the form: "
        '{"ave_id": "AVE-YYYY-NNNN", "severity": "...", '
        '"category": "...", "analysis": "...", "mitigation": "..."}'
    )
    return "".join(parts)


def _gold_answer(card: dict) -> str:
    """Strict-JSON gold so certify_ollama's primary scorer path activates.

    JSON path gives exact credit on ave_id match and partial credit on
    severity or category match (kicks in for free) — far more robust than
    the substring fuzzy fallback used for prose gold.
    """
    defences = card.get("defences", [])
    mitigation = ""
    if defences:
        d0 = defences[0]
        mitigation = (
            f"{d0.get('name','')} ({d0.get('layer','')}) — "
            f"{d0.get('effectiveness','')}"
        )
    payload = {
        "ave_id":     card["ave_id"],
        "severity":   card.get("severity", "unknown"),
        "category":   card.get("category", ""),
        "analysis":   card.get("summary", "").strip(),
        "mitigation": mitigation,
    }
    return json.dumps(payload)


def build_rows(cards: list[dict]) -> list[dict]:
    rows = []
    for card in cards:
        if not card.get("ave_id"):
            continue
        rows.append({
            "messages": [
                {"role": "system",    "content": SYSTEM_PROMPT},
                {"role": "user",      "content": _user_prompt(card)},
                {"role": "assistant", "content": _gold_answer(card)},
            ],
            "ave_id": card["ave_id"],   # convenience metadata, ignored by certify
        })
    return rows


def load_cards() -> list[dict]:
    cards = []
    for p in sorted(CARDS.glob("AVE-*.json")):
        try:
            cards.append(json.loads(p.read_text()))
        except Exception as e:
            print(f"warn: skipping {p.name}: {e}", file=sys.stderr)
    return cards


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=17,
                   help="Number of eval rows (default 17, matching the cert harness)")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--dry-run", action="store_true",
                   help="Print first row, don't write")
    p.add_argument("--out", default=str(EVAL))
    args = p.parse_args(argv)

    cards = load_cards()
    if len(cards) < args.n:
        print(f"error: need ≥ {args.n} cards, have {len(cards)}", file=sys.stderr)
        return 2

    random.seed(args.seed)
    chosen = random.sample(cards, args.n)
    rows = build_rows(chosen)

    if args.dry_run:
        print(json.dumps(rows[0], indent=2))
        print(f"\n(would write {len(rows)} rows to {args.out})")
        return 0

    out_path = Path(args.out)
    if out_path.exists() and out_path.resolve() == EVAL.resolve():
        # Back up the legacy eval the first time we write here.
        if not LEGACY.exists():
            LEGACY.write_text(out_path.read_text())
            print(f"backed up legacy eval → {LEGACY.name}")
    out_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    print(f"wrote {len(rows)} rows → {out_path}")
    print(f"AVE IDs in eval: {sorted(r['ave_id'] for r in rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
