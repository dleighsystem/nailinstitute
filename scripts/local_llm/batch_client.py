"""Anthropic Messages Batches client for the NAIL training loop.

Batch API prices every call at 0.5x of the real-time price, for up to ~24h of
processing (typical completion: 1-4h for sub-1000-request jobs). Ideal for
offline synthesis / judge passes where latency doesn't matter.

This module shares the pricing table and spend log with judge.py so
`python scripts/local_llm/judge.py spend` shows batched and real-time spend
in one place.

Public API
----------
build_request(custom_id, system, user, *, model, max_tokens=1024,
              temperature=0.2, cache_system=False, json_mode=False) -> dict
    Build one batch request entry. custom_id is your tag (echoed back in
    results so you can match a response to its source AVE card etc.).

submit(requests, *, state_dir=None) -> str
    POST /v1/messages/batches. Returns batch_id. Persists {batch_id,
    submitted_at, request_count, custom_ids} to state_dir for crash recovery.

poll(batch_id) -> dict
    GET /v1/messages/batches/{id}. Returns the Anthropic status dict.

wait(batch_id, *, poll_interval_s=30, max_wait_s=86400, on_progress=None) -> dict
    Block until processing_status == 'ended'. Calls on_progress(status) per
    poll so callers can log/print. Returns the final status dict.

results(batch_id) -> Iterator[BatchResult]
    Stream decoded results. Each BatchResult has the same shape as a
    JudgeResult plus .custom_id. Every result is logged to the shared
    spend log at 0.5x pricing.

CLI
---
    python scripts/local_llm/batch_client.py status  <batch_id>
    python scripts/local_llm/batch_client.py fetch   <batch_id>
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

import requests

# Reuse everything from judge.py to keep accounting consistent.
from judge import (  # noqa: E402
    _BATCH_MULT,
    _CACHE_READ_MULT,
    _CACHE_WRITE_MULT,
    _SPEND_LOG_PATH,
    _accepts_effort,
    _accepts_sampling,
    _DEFAULT_EFFORT,
    _log_spend,
    _price,
    JudgeError,
    JudgeResult,
)

ANTHROPIC_BASE = "https://api.anthropic.com"
BATCH_SUBMIT_URL = f"{ANTHROPIC_BASE}/v1/messages/batches"
BATCH_VERSION = "2023-06-01"
# Batch API went GA in 2024-10; the beta header is accepted but not required
# on current accounts. Sending it is harmless and keeps older accounts working.
BATCH_BETA_HEADER = "message-batches-2024-09-24"

DEFAULT_STATE_DIR = Path(__file__).resolve().parent / "data" / "batches"

# Anthropic requires custom_ids to match this. 1..64 chars, [A-Za-z0-9_-].
_CUSTOM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# ──────────────────────────────────────────────────────────── request building

def build_request(
    custom_id: str,
    system: str,
    user: str,
    *,
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    cache_system: bool = False,
    json_mode: bool = False,
) -> dict:
    """Shape one entry for the batch-submit body."""
    if not custom_id or not isinstance(custom_id, str):
        raise ValueError("custom_id must be a non-empty string")
    if not _CUSTOM_ID_RE.match(custom_id):
        raise ValueError(
            f"custom_id {custom_id!r} must match ^[a-zA-Z0-9_-]{{1,64}}$ "
            "(Anthropic requirement)"
        )
    sys_aug = system
    if json_mode:
        sys_aug += (
            "\n\nIMPORTANT: respond with a single valid JSON object only. "
            "No prose, no markdown fences."
        )
    if cache_system:
        system_field: list | str = [{
            "type": "text",
            "text": sys_aug,
            "cache_control": {"type": "ephemeral"},
        }]
    else:
        system_field = sys_aug
    params: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_field,
        "messages": [{"role": "user", "content": user}],
    }
    if _accepts_sampling(model):
        params["temperature"] = temperature
    if _accepts_effort(model):
        params["output_config"] = {"effort": _DEFAULT_EFFORT}
    return {"custom_id": custom_id, "params": params}


# ──────────────────────────────────────────────────────────── submit / poll

def _api_key() -> str:
    k = os.getenv("ANTHROPIC_API_KEY")
    if not k:
        raise JudgeError("ANTHROPIC_API_KEY not set; cannot submit batch")
    return k


def _headers() -> dict:
    return {
        "x-api-key": _api_key(),
        "anthropic-version": BATCH_VERSION,
        "anthropic-beta": BATCH_BETA_HEADER,
        "content-type": "application/json",
    }


def _state_path(state_dir: Path | None, batch_id: str) -> Path:
    d = Path(state_dir) if state_dir else DEFAULT_STATE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{batch_id}.json"


def submit(
    reqs: Iterable[dict],
    *,
    state_dir: Path | None = None,
    caller: str | None = None,
) -> str:
    """Submit a batch; return the Anthropic batch id."""
    reqs = list(reqs)
    if not reqs:
        raise ValueError("submit() requires at least one request")
    if len(reqs) > 100_000:
        raise ValueError(f"Anthropic batch limit is 100k requests; got {len(reqs)}")
    # Sanity-check custom_ids are unique — Anthropic rejects duplicates but
    # the error is less informative than ours.
    seen = set()
    for r in reqs:
        cid = r.get("custom_id")
        if not cid:
            raise ValueError("every request must have a custom_id")
        if cid in seen:
            raise ValueError(f"duplicate custom_id: {cid!r}")
        seen.add(cid)

    resp = requests.post(
        BATCH_SUBMIT_URL,
        headers=_headers(),
        json={"requests": reqs},
        timeout=120,
    )
    if resp.status_code != 200:
        raise JudgeError(f"batch submit {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    batch_id = data["id"]
    state = {
        "batch_id": batch_id,
        "submitted_at": time.time(),
        "request_count": len(reqs),
        "custom_ids": [r["custom_id"] for r in reqs],
        "caller": caller or os.getenv("NAIL_JUDGE_CALLER", "unknown"),
        "model_by_custom_id": {r["custom_id"]: r["params"]["model"] for r in reqs},
    }
    _state_path(state_dir, batch_id).write_text(json.dumps(state, indent=2))
    return batch_id


def poll(batch_id: str) -> dict:
    url = f"{BATCH_SUBMIT_URL}/{batch_id}"
    resp = requests.get(url, headers=_headers(), timeout=60)
    if resp.status_code != 200:
        raise JudgeError(f"batch poll {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def wait(
    batch_id: str,
    *,
    poll_interval_s: float = 30.0,
    max_wait_s: float = 24 * 3600,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Block until processing_status == 'ended'. Returns the final status."""
    t0 = time.time()
    while True:
        status = poll(batch_id)
        if on_progress:
            try:
                on_progress(status)
            except Exception:
                pass
        if status.get("processing_status") == "ended":
            return status
        if time.time() - t0 > max_wait_s:
            raise JudgeError(f"batch {batch_id} exceeded max_wait_s={max_wait_s}")
        time.sleep(poll_interval_s)


# ──────────────────────────────────────────────────────────── results

@dataclass
class BatchResult(JudgeResult):
    custom_id: str = ""


def _load_state(state_dir: Path | None, batch_id: str) -> dict:
    p = _state_path(state_dir, batch_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def results(
    batch_id: str,
    *,
    state_dir: Path | None = None,
) -> Iterator[BatchResult]:
    """Stream (and spend-log) every result for a completed batch."""
    status = poll(batch_id)
    if status.get("processing_status") != "ended":
        raise JudgeError(f"batch {batch_id} not ended: "
                         f"{status.get('processing_status')}")
    results_url = status.get("results_url")
    if not results_url:
        raise JudgeError(f"batch {batch_id} has no results_url")
    state = _load_state(state_dir, batch_id)
    model_map: dict = state.get("model_by_custom_id", {})
    caller = state.get("caller", os.getenv("NAIL_JUDGE_CALLER", "unknown"))

    with requests.get(results_url, headers=_headers(), stream=True,
                      timeout=600) as resp:
        if resp.status_code != 200:
            raise JudgeError(f"batch results {resp.status_code}: {resp.text[:400]}")
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            yield _decode_result(row, model_map, caller)


def _decode_result(row: dict, model_map: dict, caller: str) -> BatchResult:
    custom_id = row.get("custom_id", "")
    res = row.get("result", {}) or {}
    kind = res.get("type")
    model = model_map.get(custom_id, "unknown")

    if kind != "succeeded":
        br = BatchResult(
            text="", backend="claude-batch", model=model, latency_s=0.0,
            is_batch=True, error=kind or "unknown_error", custom_id=custom_id,
        )
        _log_spend({
            "ts": time.time(), "backend": "claude-batch", "model": model,
            "input_tokens": 0, "output_tokens": 0,
            "cache_creation_tokens": 0, "cache_read_tokens": 0,
            "cost_usd": 0.0, "latency_s": 0.0, "is_batch": True,
            "caller": caller, "error": br.error, "custom_id": custom_id,
        })
        return br

    msg = res.get("message", {}) or {}
    text = "".join(b.get("text", "") for b in msg.get("content", []))
    usage = msg.get("usage", {}) or {}
    in_tok = int(usage.get("input_tokens", 0) or 0)
    out_tok = int(usage.get("output_tokens", 0) or 0)
    cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    price = _price(model)
    # Batch API: 0.5x on everything, including cache write/read lines.
    cost = (
        in_tok * price["in"]
        + out_tok * price["out"]
        + cache_write * price["in"] * _CACHE_WRITE_MULT
        + cache_read * price["in"] * _CACHE_READ_MULT
    ) * _BATCH_MULT / 1_000_000

    _log_spend({
        "ts": time.time(), "backend": "claude-batch", "model": model,
        "input_tokens": in_tok, "output_tokens": out_tok,
        "cache_creation_tokens": cache_write, "cache_read_tokens": cache_read,
        "cost_usd": cost, "latency_s": 0.0, "is_batch": True,
        "caller": caller, "custom_id": custom_id,
    })
    return BatchResult(
        text=text, backend="claude-batch", model=model, latency_s=0.0,
        input_tokens=in_tok, output_tokens=out_tok,
        cache_creation_tokens=cache_write, cache_read_tokens=cache_read,
        cost_usd=cost, is_batch=True, custom_id=custom_id,
    )


# ──────────────────────────────────────────────────────────── CLI

def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="NAIL batch client")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="show batch processing status")
    p_status.add_argument("batch_id")

    p_fetch = sub.add_parser("fetch", help="stream results for a completed batch")
    p_fetch.add_argument("batch_id")
    p_fetch.add_argument("--out", type=Path, default=None,
                         help="write raw {custom_id,text,cost_usd,...} JSONL here")

    p_list = sub.add_parser("list", help="list known submitted batches")

    args = ap.parse_args()

    if args.cmd == "status":
        s = poll(args.batch_id)
        print(json.dumps({
            "id": s.get("id"),
            "processing_status": s.get("processing_status"),
            "request_counts": s.get("request_counts"),
            "created_at": s.get("created_at"),
            "ended_at": s.get("ended_at"),
            "expires_at": s.get("expires_at"),
        }, indent=2))
        return 0

    if args.cmd == "fetch":
        n_ok = n_err = 0
        total_cost = 0.0
        out_fp = args.out.open("w") if args.out else None
        try:
            for br in results(args.batch_id):
                if br.error:
                    n_err += 1
                else:
                    n_ok += 1
                total_cost += br.cost_usd
                if out_fp:
                    out_fp.write(json.dumps({
                        "custom_id": br.custom_id,
                        "text": br.text,
                        "input_tokens": br.input_tokens,
                        "output_tokens": br.output_tokens,
                        "cost_usd": br.cost_usd,
                        "error": br.error,
                    }) + "\n")
        finally:
            if out_fp:
                out_fp.close()
        print(f"ok={n_ok}  errored={n_err}  cost=${total_cost:.4f}  "
              + (f"out={args.out}" if args.out else ""))
        return 0 if n_err == 0 else 1

    if args.cmd == "list":
        state_dir = DEFAULT_STATE_DIR
        if not state_dir.exists():
            print("(no batches submitted from this machine yet)")
            return 0
        rows = []
        for p in sorted(state_dir.glob("*.json")):
            try:
                s = json.loads(p.read_text())
                rows.append(s)
            except Exception:
                continue
        print(f"{'batch_id':<40} {'submitted':<25} {'count':>8} caller")
        for s in rows:
            ts = time.strftime("%Y-%m-%d %H:%M:%SZ",
                               time.gmtime(s.get("submitted_at", 0)))
            print(f"{s.get('batch_id',''):<40} {ts:<25} "
                  f"{s.get('request_count',0):>8} {s.get('caller','')}")
        return 0

    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
