#!/usr/bin/env python3
"""
Build realistic DPO preference pairs for nail-guard from the SFT dataset.

Strategy for 'rejected' responses (hard negatives, same format as 'chosen' so
the model can't win on formatting alone — it must learn semantic correctness):

  1. WRONG-ANSWER: another training example's assistant reply (correct format,
     wrong AVE classification for *this* prompt).
  2. DEGRADED: the real chosen answer with lowered confidence, weakened
     explanation, and (optionally) wrong severity — looks plausible but is
     miscalibrated.
  3. MALFORMED: truncated / broken JSON (lower frequency).

This yields ~3x multiplier over the SFT samples.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA = SCRIPT_DIR / "data"
TRAIN = DATA / "nail_guard_train.jsonl"
OUT = DATA / "nail_guard_dpo.jsonl"

SEED = 42
random.seed(SEED)

SEVERITIES = ["critical", "high", "medium", "low"]


def load_samples(path: Path) -> list[dict]:
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def parse_assistant_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def degrade(chosen_text: str) -> str | None:
    obj = parse_assistant_json(chosen_text)
    if obj is None:
        return None
    obj = dict(obj)  # copy
    # Lower confidence
    if "confidence" in obj:
        obj["confidence"] = round(random.uniform(0.45, 0.72), 2)
    # Maybe shift severity one notch
    if "severity" in obj and obj["severity"] in SEVERITIES and random.random() < 0.6:
        idx = SEVERITIES.index(obj["severity"])
        idx = max(0, min(len(SEVERITIES) - 1, idx + random.choice([-1, 1])))
        obj["severity"] = SEVERITIES[idx]
    # Weaken explanation
    if "explanation" in obj and isinstance(obj["explanation"], str):
        first = obj["explanation"].split(":")[0] if ":" in obj["explanation"] else obj["explanation"][:40]
        obj["explanation"] = (
            f"{first}. This may be related but the exact mechanism is unclear "
            f"and the classification is uncertain."
        )
    return json.dumps(obj)


def malformed(chosen_text: str) -> str:
    obj = parse_assistant_json(chosen_text)
    if obj is None:
        return "I think this is some kind of vulnerability but I'm not sure which AVE."
    # Drop closing brace / truncate
    s = json.dumps(obj)
    cut = random.randint(len(s) // 3, max(len(s) // 3 + 1, len(s) - 10))
    return s[:cut]


def build():
    samples = load_samples(TRAIN)
    assistants = []
    for s in samples:
        user = next((m["content"] for m in s["messages"] if m["role"] == "user"), None)
        asst = next((m["content"] for m in s["messages"] if m["role"] == "assistant"), None)
        if user and asst:
            assistants.append((user, asst))

    pairs = []
    n = len(assistants)
    for i, (user, chosen) in enumerate(assistants):
        # 1. WRONG-ANSWER: another sample's assistant reply
        j = i
        tries = 0
        while j == i and tries < 10:
            j = random.randrange(n)
            tries += 1
            # Require actually different content
            if assistants[j][1] == chosen:
                j = i
        wrong = assistants[j][1]
        if wrong != chosen:
            pairs.append({"prompt": user, "chosen": chosen, "rejected": wrong})

        # 2. DEGRADED
        deg = degrade(chosen)
        if deg and deg != chosen:
            pairs.append({"prompt": user, "chosen": chosen, "rejected": deg})

        # 3. MALFORMED (30% of samples)
        if random.random() < 0.3:
            mal = malformed(chosen)
            if mal and mal != chosen:
                pairs.append({"prompt": user, "chosen": chosen, "rejected": mal})

    random.shuffle(pairs)

    with OUT.open("w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")

    # Stats
    kinds = {"wrong": 0, "degraded": 0, "malformed": 0}
    # Re-label (best-effort): parse
    for p in pairs:
        r = p["rejected"]
        obj = parse_assistant_json(r)
        if obj is None:
            kinds["malformed"] += 1
        elif isinstance(obj, dict) and "explanation" in obj and "classification is uncertain" in obj.get("explanation", ""):
            kinds["degraded"] += 1
        else:
            kinds["wrong"] += 1

    print(f"✓ Wrote {len(pairs)} DPO pairs → {OUT}")
    print(f"  breakdown (approx): {kinds}")


if __name__ == "__main__":
    build()
