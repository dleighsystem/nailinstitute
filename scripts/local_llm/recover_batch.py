#!/usr/bin/env python3
"""Re-parse an already-paid Anthropic batch with the current parsers and
APPEND any samples not already present in the target synth files. Idempotent
via content-hash dedup. Does NOT re-log spend (uses replay=True).

Usage:
  python scripts/local_llm/recover_batch.py <batch_id> [--per-ave 15]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_client as bc  # noqa: E402
from synthesize_dataset import (  # noqa: E402
    DATA_DIR, load_cards, parse_guard, parse_reason,
)


def _row_key(row: dict) -> str:
    """Stable hash of a sample row for dedup."""
    msgs = row.get("messages", [])
    parts = []
    for m in msgs:
        parts.append(m.get("role", ""))
        parts.append(m.get("content", ""))
    return hashlib.sha1("\x00".join(parts).encode()).hexdigest()


def _load_existing(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    with path.open() as f:
        for line in f:
            try:
                row = json.loads(line)
                keys.add(_row_key(row))
            except Exception:
                pass
    return keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_id")
    ap.add_argument("--per-ave", type=int, default=15)
    args = ap.parse_args()

    cards_by_ave = {c["ave_id"]: c for c in load_cards()}
    out_paths = {
        "guard":  DATA_DIR / "nail_guard_train.synth.jsonl",
        "reason": DATA_DIR / "nail_reason_train.synth.jsonl",
    }
    existing = {tgt: _load_existing(p) for tgt, p in out_paths.items()}
    print(f"existing: guard={len(existing['guard'])} reason={len(existing['reason'])}")

    added = {"guard": 0, "reason": 0}
    skipped_dupes = {"guard": 0, "reason": 0}
    failed_parse = {"guard": 0, "reason": 0}

    for r in bc.results(args.batch_id, replay=True):
        if r.error:
            print(f"  [{r.custom_id}] ERROR {r.error}")
            continue
        try:
            tgt, ave_id = r.custom_id.split("_", 1)
        except Exception:
            print(f"  [{r.custom_id}] bad custom_id")
            continue
        card = cards_by_ave.get(ave_id)
        if not card:
            print(f"  [{r.custom_id}] no card {ave_id}")
            continue

        if tgt == "guard":
            rows = parse_guard(card, r.text, args.per_ave)
        elif tgt == "reason":
            rows = parse_reason(card, r.text, args.per_ave)
        else:
            print(f"  [{r.custom_id}] unknown target {tgt}")
            continue

        if not rows:
            failed_parse[tgt] += 1
            print(f"  [{r.custom_id}] parsed 0 samples")
            continue

        new_rows = []
        for row in rows:
            k = _row_key(row)
            if k in existing[tgt]:
                skipped_dupes[tgt] += 1
            else:
                existing[tgt].add(k)
                new_rows.append(row)

        if new_rows:
            with out_paths[tgt].open("a") as f:
                for row in new_rows:
                    f.write(json.dumps(row) + "\n")
            added[tgt] += len(new_rows)
        print(f"  [{r.custom_id}] +{len(new_rows)}/{len(rows)} new "
              f"(running guard={added['guard']} reason={added['reason']})")

    print()
    print(f"DONE  added: {added}")
    print(f"      duplicates skipped: {skipped_dupes}")
    print(f"      parse-empty responses: {failed_parse}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
