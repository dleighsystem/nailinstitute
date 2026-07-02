#!/usr/bin/env python3
"""Rebuild — or --check — the AVE database indexes from ave-database/cards/*.json.

The per-card JSON files under ave-database/cards/ are the source of truth. This
script derives the two published indexes from them:

    index.json          flat list, sorted by ave_id (ave_id, name, category,
                        severity, status)
    severity_index.json the same cards grouped by severity

Usage:
    python ave-database/rebuild_index.py            # regenerate both indexes
    python ave-database/rebuild_index.py --check    # CI: verify, do not write

--check compares the committed indexes to what the cards imply, ignoring the
volatile generated_at timestamp, and exits non-zero (listing the drift) if they
disagree. This replaces the old CI step, which shelled out to `ave export`
(a different card source — the in-code registry) and byte-diffed a timestamped
file, so it could never pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CARDS_DIR = ROOT / "cards"
INDEX = ROOT / "index.json"
SEVERITY_INDEX = ROOT / "severity_index.json"

SCHEMA_VERSION = "1.0.0"
SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
INDEX_FIELDS = ("ave_id", "name", "category", "severity", "status")
SEVERITY_FIELDS = ("ave_id", "name", "category", "status")


def load_cards() -> list[dict]:
    cards = [json.loads(f.read_text()) for f in sorted(CARDS_DIR.glob("*.json"))]
    cards.sort(key=lambda c: c["ave_id"])
    return cards


def build_index(cards: list[dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_cards": len(cards),
        "cards": [{k: c.get(k) for k in INDEX_FIELDS} for c in cards],
    }


def build_severity_index(cards: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for c in cards:
        grouped.setdefault(c["severity"], []).append(
            {k: c.get(k) for k in SEVERITY_FIELDS}
        )
    ordered = {s: grouped[s] for s in SEVERITY_ORDER if s in grouped}
    for s in grouped:  # keep any unexpected severity rather than drop it
        ordered.setdefault(s, grouped[s])
    return ordered


def _without_timestamp(index: dict) -> dict:
    return {k: v for k, v in index.items() if k != "generated_at"}


def check(cards: list[dict]) -> int:
    expected_index = build_index(cards)
    expected_sev = build_severity_index(cards)
    errors: list[str] = []

    current_index = json.loads(INDEX.read_text()) if INDEX.exists() else None
    if current_index is None or _without_timestamp(current_index) != _without_timestamp(expected_index):
        errors.append("index.json")
        if current_index is not None:
            have = {c["ave_id"] for c in current_index.get("cards", [])}
            want = {c["ave_id"] for c in expected_index["cards"]}
            if have - want:
                print(f"  in index.json but no card file: {sorted(have - want)}")
            if want - have:
                print(f"  card file present but missing from index.json: {sorted(want - have)}")

    current_sev = json.loads(SEVERITY_INDEX.read_text()) if SEVERITY_INDEX.exists() else None
    if current_sev != expected_sev:
        errors.append("severity_index.json")

    if errors:
        print(
            f"::error::AVE indexes out of date ({', '.join(errors)}). "
            f"Regenerate with: python ave-database/rebuild_index.py"
        )
        return 1

    print(f"AVE indexes in sync ({len(cards)} cards).")
    return 0


def write(cards: list[dict]) -> int:
    INDEX.write_text(json.dumps(build_index(cards), indent=2) + "\n")
    SEVERITY_INDEX.write_text(json.dumps(build_severity_index(cards), indent=2) + "\n")
    print(f"Wrote index.json and severity_index.json ({len(cards)} cards).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only; do not write")
    args = parser.parse_args()
    cards = load_cards()
    return check(cards) if args.check else write(cards)


if __name__ == "__main__":
    raise SystemExit(main())
