"""Grounded synthetic dataset generation for nail-guard / nail-reason.

For each AVE card in ave-database/cards/, generate N (input, output) pairs
with Claude Opus 4.7 (or local Ollama fallback). The card's ave_id, category,
severity are ground truth — Claude only paraphrases the *situation*. The
AVE-ID is templated from the card, never invented by the model.

Usage:
  # Real-time (immediate, full price)
  python scripts/local_llm/synthesize_dataset.py --target guard  --per-ave 15
  python scripts/local_llm/synthesize_dataset.py --target both   --per-ave 12

  # Batch API (0.5x price, up to 24h, best for big runs)
  python scripts/local_llm/synthesize_dataset.py --target both --per-ave 15 --batch

  # Batch API, submit now and exit (don't block); fetch later.
  python scripts/local_llm/synthesize_dataset.py --target both --per-ave 15 \
      --batch --submit-only
  # ... then when complete:
  python scripts/local_llm/synthesize_dataset.py --fetch <batch_id>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge import JudgeClient, extract_json  # noqa: E402
import batch_client as bc  # noqa: E402

WORKSPACE = Path(__file__).resolve().parent.parent.parent
AVE_DIR = WORKSPACE / "ave-database" / "cards"
DATA_DIR = WORKSPACE / "scripts" / "local_llm" / "data"
BATCH_META_DIR = DATA_DIR / "batches"

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


# ──────────────────────────────────────────────── prompt builders
# These return (system, user, max_tokens, temperature) so both real-time and
# batch paths can share the exact same prompt surface.

def guard_prompt(card: dict, n: int) -> tuple[str, str, int, float]:
    user = (
        f"AVE CARD (ground truth):\n{card_block(card)}\n"
        f"Produce exactly {n} DISTINCT input scenarios describing this "
        "vulnerability in different words / angles / system contexts. Do NOT "
        "include the AVE-ID in the input.\n\n"
        'Respond JSON: {"samples":[{"input":"...","explanation":"..."}]}'
    )
    # ~250 tokens per sample on average; pad 2x. Opus supports up to 32K out.
    return GEN_SYS, user, max(2048, 600 * n), 0.7


def reason_prompt(card: dict, n: int) -> tuple[str, str, int, float]:
    defences = "; ".join(d.get("name", "") for d in card.get("defences", [])
                         if isinstance(d, dict))
    user = (
        f"AVE CARD (refer to {card['ave_id']} explicitly):\n{card_block(card)}"
        f"defences:      {defences}\n\n"
        f"Produce exactly {n} DISTINCT analyst tasks. Each is a triplet:\n"
        "  user_request: a natural prompt asking for a security analysis\n"
        "  analyst_reply: a structured analysis (## Vulnerability, ## Impact,\n"
        f"     ## Detection, ## Mitigation) that names {card['ave_id']} and\n"
        "     {card['name']}, and references the mechanism + defences above.\n\n"
        'Respond JSON: {"samples":[{"user_request":"...","analyst_reply":"..."}]}'
    )
    # Reason replies are ~600 tokens each; pad heavily but cap at Opus's
    # per-request output ceiling (16,384 for opus-4-7).
    return GEN_SYS, user, min(16000, max(4096, 1200 * n)), 0.6


# ──────────────────────────────────────────────── response parsers

def salvage_objects(raw: str) -> list[dict]:
    """Extract every well-formed JSON object from a (possibly truncated) string.

    Uses a stack-based brace scan that respects string literals + escapes.
    Every time a `{` opens, its position is pushed; when the matching `}`
    closes it, the substring is fed to `json.loads`. This means we recover
    INNER objects even if the OUTER container `{"samples":[...` was never
    closed because the response hit `max_tokens` mid-array.
    """
    out: list[dict] = []
    stack: list[int] = []  # positions of unmatched '{'
    in_str = False
    esc = False
    n = len(raw)
    for i in range(n):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}":
            if not stack:
                continue
            start = stack.pop()
            chunk = raw[start:i + 1]
            try:
                obj = json.loads(chunk)
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                pass
    return out


def _samples_from(raw_text: str, required_keys: tuple[str, ...]) -> list[dict]:
    """Return sample dicts from raw model text. Tries strict JSON first; on
    failure falls back to brace-counter salvage. Filters to objects that
    contain at least one of `required_keys` (so the wrapping {samples:[...]}
    object is not mistakenly treated as a sample).
    """
    data = extract_json(raw_text)
    if isinstance(data, dict) and isinstance(data.get("samples"), list):
        good = [s for s in data["samples"] if isinstance(s, dict)]
        if good:
            return good
    # Salvage path - truncated or malformed response.
    objs = salvage_objects(raw_text)
    return [o for o in objs if any(k in o for k in required_keys)]


def parse_guard(card: dict, raw_text: str, n: int) -> list[dict]:
    out = []
    for s in _samples_from(raw_text, ("input",))[:n]:
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


def parse_reason(card: dict, raw_text: str, n: int) -> list[dict]:
    out = []
    for s in _samples_from(raw_text, ("user_request", "analyst_reply"))[:n]:
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


# ──────────────────────────────────────────────── real-time path

def gen_guard(client: JudgeClient, card: dict, n: int,
              cache_system: bool = False) -> list[dict]:
    sys_p, user_p, max_tok, temp = guard_prompt(card, n)
    res = client.chat(sys_p, user_p, max_tokens=max_tok, temperature=temp,
                      json_mode=True, cache_system=cache_system)
    return parse_guard(card, res.text, n)


def gen_reason(client: JudgeClient, card: dict, n: int,
               cache_system: bool = False) -> list[dict]:
    sys_p, user_p, max_tok, temp = reason_prompt(card, n)
    res = client.chat(sys_p, user_p, max_tokens=max_tok, temperature=temp,
                      json_mode=True, cache_system=cache_system)
    return parse_reason(card, res.text, n)


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


# ──────────────────────────────────────────────── batch path

def _custom_id(target: str, card: dict) -> str:
    # custom_ids must match ^[a-zA-Z0-9_-]{1,64}$ per Anthropic. Include
    # target so guard+reason can coexist in the same submission. AVE IDs
    # already contain only [A-Z0-9-] so they're safe as-is.
    return f"{target}_{card['ave_id']}"


def existing_coverage(out_paths: dict[str, Path]) -> dict[str, dict[str, int]]:
    """Scan current synth files and return {target: {ave_id: count}}.

    Used by both the dedup guard (any count > 0 means “covered”) and the
    --top-up logic (re-synthesize only AVE IDs whose count is below quota).
    """
    import re
    ave_re = re.compile(r"AVE-\d{4}-\d{4}")
    out: dict[str, dict[str, int]] = {}
    for tgt, path in out_paths.items():
        counts: dict[str, int] = {}
        if path.exists():
            with path.open() as f:
                for line in f:
                    try:
                        row = json.loads(line)
                        asst = row["messages"][-1]["content"]
                    except Exception:
                        continue
                    m = ave_re.search(asst)
                    if m:
                        counts[m.group(0)] = counts.get(m.group(0), 0) + 1
        out[tgt] = counts
    return out


def filter_new_work(cards: list[dict], targets: list[str],
                    coverage: dict[str, dict[str, int]],
                    force: bool,
                    top_up_to: int = 0) -> list[tuple[dict, str, int]]:
    """Return list of (card, target, n_to_request) pairs that still need work.

    - force=True: every (card, target) pair, n=top_up_to or default upstream.
    - top_up_to>0: include any AVE whose existing count < top_up_to;
      n_to_request = top_up_to - existing_count (so we ask only for the
      shortfall). Pad by 50% to absorb parse losses, capped at top_up_to.
    - default: include any AVE not yet present at all (count == 0).
    """
    work: list[tuple[dict, str, int]] = []
    for card in cards:
        for tgt in targets:
            existing = coverage.get(tgt, {}).get(card["ave_id"], 0)
            if force:
                n = top_up_to or 0  # caller will substitute its default
                work.append((card, tgt, n))
            elif top_up_to > 0:
                if existing < top_up_to:
                    shortfall = top_up_to - existing
                    # ask for 1.5x the shortfall to absorb parse loss
                    n = min(top_up_to, max(shortfall, int(shortfall * 1.5)))
                    work.append((card, tgt, n))
            else:
                if existing == 0:
                    work.append((card, tgt, 0))
    return work


def build_batch_requests(work: list[tuple[dict, str, int]], default_per_ave: int,
                         model: str, cache_system: bool) -> list[dict]:
    reqs: list[dict] = []
    for card, tgt, n in work:
        per = n if n > 0 else default_per_ave
        if tgt == "guard":
            sys_p, user_p, max_tok, temp = guard_prompt(card, per)
        else:
            sys_p, user_p, max_tok, temp = reason_prompt(card, per)
        reqs.append(bc.build_request(
            _custom_id(tgt, card), sys_p, user_p,
            model=model, max_tokens=max_tok, temperature=temp,
            cache_system=cache_system, json_mode=True,
        ))
    return reqs


def drain_batch_results(batch_id: str, cards_by_ave: dict[str, dict],
                        per_ave: int, out_paths: dict[str, Path],
                        dry_run: bool) -> dict[str, int]:
    totals = {"guard": 0, "reason": 0}
    errored = 0
    for br in bc.results(batch_id):
        if br.error:
            errored += 1
            print(f"  [{br.custom_id}] ERRORED: {br.error}")
            continue
        tgt, ave_id = br.custom_id.split("_", 1)
        card = cards_by_ave.get(ave_id)
        if not card:
            print(f"  [{br.custom_id}] no matching card; skipping")
            continue
        rows = (parse_guard(card, br.text, per_ave) if tgt == "guard"
                else parse_reason(card, br.text, per_ave))
        totals[tgt] += len(rows)
        if not dry_run and rows:
            append_jsonl(out_paths[tgt], rows)
        print(f"  [{br.custom_id}] +{len(rows):2d} samples  "
              f"(${br.cost_usd:.4f})")
    if errored:
        print(f"\n  WARNING: {errored} requests errored")
    return totals


# ──────────────────────────────────────────────── CLI

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["guard", "reason", "both"])
    ap.add_argument("--per-ave", type=int, default=10)
    ap.add_argument("--limit-cards", type=int, default=0,
                    help="Only synthesize against the first N cards (0 = all)")
    ap.add_argument("--cache-system", action="store_true",
                    help="Attach cache_control to system prompt. No-op below "
                         "~1024 tokens (Anthropic minimum).")
    ap.add_argument("--batch", action="store_true",
                    help="Use Anthropic Messages Batches API (0.5x price, "
                         "up to 24h wall time).")
    ap.add_argument("--submit-only", action="store_true",
                    help="With --batch: submit and print batch_id, do not "
                         "wait for results. Fetch later with --fetch.")
    ap.add_argument("--fetch", metavar="BATCH_ID", default=None,
                    help="Fetch results for a previously submitted batch "
                         "and append them to the same dataset files.")
    ap.add_argument("--model", default="claude-opus-4-7",
                    help="Claude model ID (batch mode only; real-time uses "
                         "JudgeClient defaults with fallback).")
    ap.add_argument("--force", action="store_true",
                    help="Re-synthesize even for AVE IDs that already have "
                         "samples in the target file. Default behavior skips "
                         "already-covered (card, target) pairs to avoid "
                         "paying twice and duplicating training data.")
    ap.add_argument("--top-up", type=int, default=0, metavar="N",
                    help="Re-synthesize ONLY for (card, target) pairs whose "
                         "current sample count is below N. Asks the teacher "
                         "for 1.5x the shortfall (capped at N) to absorb "
                         "parse losses. Mutually informative with --per-ave.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out_paths = {
        "guard":  DATA_DIR / "nail_guard_train.synth.jsonl",
        "reason": DATA_DIR / "nail_reason_train.synth.jsonl",
    }

    # ── fetch mode: resume a prior batch ──
    if args.fetch:
        cards = load_cards()
        cards_by_ave = {c["ave_id"]: c for c in cards}
        print(f"fetching batch {args.fetch} ...")
        st = bc.poll(args.fetch)
        if st.get("processing_status") != "ended":
            print(f"  status: {st.get('processing_status')}  "
                  f"counts: {st.get('request_counts')}")
            print("  not ended yet; run again later")
            return 1
        # infer per_ave from the first parse
        totals = drain_batch_results(args.fetch, cards_by_ave,
                                     args.per_ave, out_paths, args.dry_run)
        print(f"\nDONE  added: {totals}")
        return 0

    if not args.target:
        ap.error("--target is required unless using --fetch")

    targets = ["guard", "reason"] if args.target == "both" else [args.target]
    cards = load_cards()
    if args.limit_cards:
        cards = cards[: args.limit_cards]

    # ── batch mode ──
    if args.batch:
        cards_by_ave = {c["ave_id"]: c for c in cards}
        coverage = existing_coverage(out_paths)
        work = filter_new_work(cards, targets, coverage, args.force,
                               top_up_to=args.top_up)
        skipped = (len(cards) * len(targets)) - len(work)
        if skipped:
            mode = "top-up" if args.top_up else "already-covered"
            print(f"skipped {skipped} {mode} (card, target) pair(s)")
        if not work:
            if args.top_up:
                print(f"nothing to do—every (card, target) pair already has "
                      f">= {args.top_up} samples.")
            else:
                print("nothing to do—every (card, target) pair already has "
                      "samples. Use --top-up N, --force, or delete the synth files first.")
            return 0
        reqs = build_batch_requests(work, args.per_ave, args.model,
                                    args.cache_system)
        # Show the requested-sample distribution
        n_dist = sorted(set(n if n else args.per_ave for _, _, n in work))
        print(f"batch: {len(reqs)} requests across {len(cards)} cards x "
              f"{len(targets)} target(s); model={args.model}; "
              f"cache_system={args.cache_system}; "
              f"per-request samples: {n_dist}")
        if args.dry_run:
            print("  --dry-run: not submitting")
            return 0
        batch_id = bc.submit(reqs, caller="synthesize")
        print(f"submitted: {batch_id}")
        if args.submit_only:
            print(f"  run:  python scripts/local_llm/synthesize_dataset.py "
                  f"--fetch {batch_id} --per-ave {args.per_ave}")
            return 0

        def _progress(status: dict) -> None:
            rc = status.get("request_counts", {})
            print(f"  poll: {status.get('processing_status')}  "
                  f"processing={rc.get('processing',0)} "
                  f"succeeded={rc.get('succeeded',0)} "
                  f"errored={rc.get('errored',0)}")

        t0 = time.time()
        bc.wait(batch_id, poll_interval_s=30, on_progress=_progress)
        print(f"  batch completed in {time.time()-t0:.0f}s")
        totals = drain_batch_results(batch_id, cards_by_ave, args.per_ave,
                                     out_paths, args.dry_run)
        print(f"\nDONE  added: {totals}  (target files: "
              f"{[str(p) for p in out_paths.values()]})")
        return 0

    # ── real-time mode (original behavior) ──
    client = JudgeClient()
    coverage = existing_coverage(out_paths)
    work = filter_new_work(cards, targets, coverage, args.force,
                           top_up_to=args.top_up)
    skipped = (len(cards) * len(targets)) - len(work)
    print(f"loaded {len(cards)} AVE cards; backend preference: {client.prefer}"
          f"{'  (cache_system=True)' if args.cache_system else ''}")
    if skipped:
        mode = "top-up" if args.top_up else "already-covered"
        print(f"skipped {skipped} {mode} (card, target) pair(s)")
    if not work:
        print("nothing to do.")
        return 0

    totals = {"guard": 0, "reason": 0}
    for i, (card, tgt, n) in enumerate(work, 1):
        per = n if n > 0 else args.per_ave
        try:
            if tgt == "guard":
                rows = gen_guard(client, card, per,
                                 cache_system=args.cache_system)
            else:
                rows = gen_reason(client, card, per,
                                  cache_system=args.cache_system)
        except Exception as e:
            print(f"  [{card['ave_id']}/{tgt}] FAIL: {e}")
            continue
        totals[tgt] += len(rows)
        if not args.dry_run and rows:
            append_jsonl(out_paths[tgt], rows)
        print(f"  [{i}/{len(work)}] {card['ave_id']:14s} {tgt:6s} +{len(rows):2d}/{per}  "
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
        "mode": "batch" if args.batch else "realtime",
    }
    if not args.dry_run:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"\nDONE  added: {totals}  (target files: {[str(p) for p in out_paths.values()]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
