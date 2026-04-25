#!/usr/bin/env python3
"""
M13.1 step 2 — diagnose nail-reason:v5 format collapse.

Replays the *real* eval-set prompts against live `nail-reason:v5` on the
local Ollama and writes per-row diagnostics so we can confirm the
hypothesis from R6_PLAN.md §1:

    "v5 outputs VERDICT:... to every prompt, including deep-analyst and
     incident-analyst prompts where the gold expects an AVE-grounded
     structured report."

Outputs ``scripts/local_llm/logs/diagnose_reason_v5_<ts>.jsonl`` plus a
short summary on stdout: how many of the 17 eval rows produced a
VERDICT-prefix reply vs. an AVE-grounded reply, broken down by which
production system prompt was used.

Run:
    python scripts/local_llm/diagnose_reason_v5.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

WS = Path(__file__).resolve().parents[2]
EVAL = WS / "scripts" / "local_llm" / "data" / "nail_reason_eval.jsonl"
LOGDIR = WS / "scripts" / "local_llm" / "logs"
OLLAMA = "http://localhost:11434"
MODEL = "nail-reason:v5"

AVE_RE = re.compile(r"AVE-\d{4}-\d{4}")


def system_class(sysprompt: str) -> str:
    s = sysprompt.lower()
    if "verdict:attack" in s or "verdict:benign" in s:
        return "verdict-prefix"
    if "deep security analyst" in s or "ave id" in s or "ave-" in s:
        return "deep-analyst"
    if "incident response" in s or "incident report" in s:
        return "incident-analyst"
    return "other"


def reply_class(reply: str) -> str:
    head = reply.strip().splitlines()[0].upper() if reply.strip() else ""
    has_verdict = head.startswith(("VERDICT:ATTACK", "VERDICT:BENIGN"))
    has_ave = bool(AVE_RE.search(reply))
    if has_verdict and not has_ave:
        return "verdict-only"
    if has_ave and not has_verdict:
        return "ave-grounded"
    if has_verdict and has_ave:
        return "both"
    return "neither"


def chat(model: str, messages: list[dict], timeout: float = 120.0) -> tuple[str, float]:
    t0 = time.time()
    r = requests.post(
        f"{OLLAMA}/api/chat",
        json={"model": model, "messages": messages, "stream": False,
              "options": {"num_predict": 600}},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["message"]["content"], time.time() - t0


def main() -> int:
    if not EVAL.exists():
        print(f"missing eval file: {EVAL}", file=sys.stderr)
        return 2
    LOGDIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log = LOGDIR / f"diagnose_reason_v5_{ts}.jsonl"

    rows = [json.loads(l) for l in EVAL.read_text().splitlines() if l.strip()]
    breakdown: dict[str, Counter] = defaultdict(Counter)
    latencies: list[float] = []
    sample_writeouts = 0

    with log.open("w") as fh:
        for i, row in enumerate(rows):
            msgs = row["messages"]
            sysm = next((m["content"] for m in msgs if m["role"] == "system"), "")
            usrm = next((m["content"] for m in msgs if m["role"] == "user"), "")
            gold = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
            if not (sysm and usrm and gold):
                continue
            sclass = system_class(sysm)
            try:
                reply, lat = chat(MODEL, [{"role": "system", "content": sysm},
                                          {"role": "user", "content": usrm}])
            except Exception as e:
                breakdown[sclass]["error"] += 1
                fh.write(json.dumps({"i": i, "system_class": sclass,
                                     "error": str(e)[:200]}) + "\n")
                continue
            rclass = reply_class(reply)
            breakdown[sclass][rclass] += 1
            latencies.append(lat)
            gold_aves = set(AVE_RE.findall(gold))
            reply_aves = set(AVE_RE.findall(reply))
            ave_match = bool(gold_aves & reply_aves)
            fh.write(json.dumps({
                "i": i, "system_class": sclass, "reply_class": rclass,
                "latency_s": round(lat, 2),
                "gold_aves": sorted(gold_aves),
                "reply_aves": sorted(reply_aves),
                "ave_match": ave_match,
                "reply_first_100": reply[:100],
            }) + "\n")
            if sample_writeouts < 3:
                print(f"  [{i:2d}] sys={sclass:18s} reply={rclass:13s} "
                      f"ave_match={ave_match} lat={lat:.1f}s")
                sample_writeouts += 1

    print()
    print(f"{'system_prompt_class':22s} {'verdict-only':>12s} {'ave-grounded':>12s} "
          f"{'both':>5s} {'neither':>8s} {'error':>6s}")
    for sclass, cnt in sorted(breakdown.items()):
        print(f"{sclass:22s} {cnt['verdict-only']:>12d} {cnt['ave-grounded']:>12d} "
              f"{cnt['both']:>5d} {cnt['neither']:>8d} {cnt['error']:>6d}")
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) >= 20 else latencies[-1]
        print(f"\n  latency p50={p50:.1f}s  p95={p95:.1f}s  n={len(latencies)}")
    print(f"\nfull log: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
