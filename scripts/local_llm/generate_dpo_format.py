#!/usr/bin/env python3
"""
Generate DPO preference pairs targeting OUTPUT FORMAT for nail-guard.

Root cause from v2 cert: model knows the right AVE-ID (~60% partial) but
emits nested JSON like {"classification": {"type": "AVE", ...}} instead of
the flat schema {"ave_id": ..., "category": ..., ...} the system prompt
demands. Standard DPO (build_dpo_pairs.py) only varies *content*, never
*shape*, so the model never learns to flatten its output.

This script produces preference pairs where:
  * chosen   = the SFT corpus's flat JSON answer
  * rejected = synthetic nested / wrapped / markdown-wrapped variants of
               the same answer

The semantic content is identical between chosen and rejected — DPO will
purely push the policy toward the flat schema.

Output: data/nail_guard_dpo.format.jsonl (auto-loaded by train.py glob).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA = SCRIPT_DIR / "data"
TRAIN = DATA / "nail_guard_train.jsonl"
SYNTH = DATA / "nail_guard_train.synth.jsonl"
OUT = DATA / "nail_guard_dpo.format.jsonl"

SEED = 1337
random.seed(SEED)


# ── Rejected-format generators ──────────────────────────────────────────
def wrap_classification(obj: dict) -> str:
    """{"classification": {flat_keys...}} — the most common observed failure."""
    return json.dumps({"classification": obj})


def wrap_agent_vuln(obj: dict) -> str:
    """{"agent_vulnerability": {flat_keys...}} — the second observed failure."""
    return json.dumps({"agent_vulnerability": obj})


def wrap_result(obj: dict) -> str:
    """{"result": {flat_keys...}}."""
    return json.dumps({"result": obj})


def wrap_response(obj: dict) -> str:
    """{"response": {...}, "status": "ok"}."""
    return json.dumps({"response": obj, "status": "ok"})


def add_primitives_field(obj: dict) -> str:
    """Adds the bogus 'primitives': ['BEE','SDF',...] field the model loves."""
    o = dict(obj)
    o["type"] = "AVE"
    o["primitives"] = random.sample(["BEE", "SDF", "MOAT", "MTM", "OOA"],
                                     k=random.choice([1, 2, 3]))
    return json.dumps({"classification": o})


def markdown_codefence(obj: dict) -> str:
    """```json\n{...}\n``` — markdown-wrapped, breaks JSON parsers."""
    return f"```json\n{json.dumps(obj, indent=2)}\n```"


def prose_then_json(obj: dict) -> str:
    """Prose preamble then JSON — chatty model behaviour."""
    return (f"Based on the description, this matches the following AVE entry:\n\n"
            f"```json\n{json.dumps(obj, indent=2)}\n```")


def split_into_kv(obj: dict) -> str:
    """key: value lines instead of JSON."""
    return "\n".join(f"{k}: {v}" for k, v in obj.items())


def nested_with_metadata(obj: dict) -> str:
    """Nested under 'data' with extra metadata."""
    return json.dumps({
        "data": obj,
        "metadata": {"model": "nail-guard", "version": "1.0"},
    })


REJECTED_GENERATORS = [
    (wrap_classification, 0.30),
    (wrap_agent_vuln, 0.15),
    (add_primitives_field, 0.15),
    (markdown_codefence, 0.15),
    (prose_then_json, 0.10),
    (wrap_result, 0.05),
    (wrap_response, 0.05),
    (nested_with_metadata, 0.05),
]


def pick_generator():
    r = random.random()
    cum = 0.0
    for fn, p in REJECTED_GENERATORS:
        cum += p
        if r <= cum:
            return fn
    return REJECTED_GENERATORS[0][0]


# ── Main ────────────────────────────────────────────────────────────────
def load_samples(*paths: Path) -> list[dict]:
    out = []
    for p in paths:
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def build():
    samples = load_samples(TRAIN, SYNTH)
    print(f"  Loaded {len(samples)} SFT samples")

    pairs: list[dict] = []
    skipped = 0
    for s in samples:
        msgs = s.get("messages", [])
        user = next((m["content"] for m in msgs if m["role"] == "user"), None)
        chosen = next((m["content"] for m in msgs if m["role"] == "assistant"), None)
        if not (user and chosen):
            skipped += 1
            continue
        try:
            obj = json.loads(chosen)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(obj, dict) or "ave_id" not in obj:
            skipped += 1
            continue

        # Generate 2 distinct rejected variants per sample for stronger signal
        seen = set()
        for _ in range(2):
            for _attempt in range(5):
                gen = pick_generator()
                rej = gen(obj)
                if rej != chosen and rej not in seen:
                    seen.add(rej)
                    pairs.append({"prompt": user, "chosen": chosen, "rejected": rej})
                    break

    random.shuffle(pairs)
    OUT.write_text("\n".join(json.dumps(p) for p in pairs) + "\n")

    # Stats
    kinds: dict[str, int] = {}
    for p in pairs:
        rej = p["rejected"]
        if rej.startswith("```"):
            kinds["markdown"] = kinds.get("markdown", 0) + 1
        elif rej.startswith("Based on") or rej.startswith("This"):
            kinds["prose"] = kinds.get("prose", 0) + 1
        elif '"classification"' in rej[:30]:
            kinds["nested_classification"] = kinds.get("nested_classification", 0) + 1
        elif '"agent_vulnerability"' in rej[:30]:
            kinds["nested_agent_vuln"] = kinds.get("nested_agent_vuln", 0) + 1
        elif '"data"' in rej[:20]:
            kinds["nested_data"] = kinds.get("nested_data", 0) + 1
        elif '"result"' in rej[:20]:
            kinds["nested_result"] = kinds.get("nested_result", 0) + 1
        elif '"response"' in rej[:20]:
            kinds["nested_response"] = kinds.get("nested_response", 0) + 1
        elif ":" in rej and "{" not in rej[:5]:
            kinds["kv_lines"] = kinds.get("kv_lines", 0) + 1
        else:
            kinds["other"] = kinds.get("other", 0) + 1

    print(f"✓ Wrote {len(pairs)} format DPO pairs → {OUT.name}")
    print(f"  skipped: {skipped}")
    print(f"  breakdown: {kinds}")


if __name__ == "__main__":
    build()
