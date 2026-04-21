"""Shared judge / generator client for the NAIL training loop.

Backends, in preference order:
  1. Anthropic Claude (env ANTHROPIC_API_KEY) — Opus 4.7 default, 4.6 fallback
  2. Local Ollama (env NAIL_JUDGE_OLLAMA_MODEL, default qwen2.5:32b-instruct)

Used by:
  scripts/local_llm/synthesize_dataset.py  — grounded sample generation
  scripts/local_llm/exec_ai_probe.py       — labelling fuzz captures
  scripts/local_llm/judge_loop.py          — RL judge for DPO pair mining
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests


def _load_dotenv() -> None:
    """Walk up from this file looking for a .env, then load KEY=VALUE pairs
    into os.environ without overwriting anything already set. Zero deps."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        cand = parent / ".env"
        if cand.is_file():
            try:
                for raw in cand.read_text().splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    if line.lower().startswith("export "):
                        line = line[7:].lstrip()
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass
            return


_load_dotenv()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_PRIMARY = os.getenv("NAIL_JUDGE_CLAUDE_MODEL", "claude-opus-4-7")
CLAUDE_FALLBACK = os.getenv("NAIL_JUDGE_CLAUDE_FALLBACK", "claude-opus-4-6")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_LOCAL_JUDGE = os.getenv("NAIL_JUDGE_OLLAMA_MODEL", "qwen2.5:32b-instruct")

# USD per 1M tokens. Update if Anthropic pricing changes.
# Claude Opus family historically ~ $15 in / $75 out per 1M.
_CLAUDE_PRICES = {
    "claude-opus-4-7": {"in": 15.0, "out": 75.0},
    "claude-opus-4-6": {"in": 15.0, "out": 75.0},
    "claude-opus-4-5": {"in": 15.0, "out": 75.0},
    "claude-sonnet-4-5": {"in": 3.0, "out": 15.0},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5": {"in": 0.8, "out": 4.0},
}
_DEFAULT_PRICE = {"in": 15.0, "out": 75.0}  # assume Opus when unknown

# Per Anthropic pricing:
#   cache write (5-min ephemeral) = 1.25 x input price
#   cache read                    = 0.10 x input price
#   batch API                     = 0.50 x both input and output
# These multipliers compound: batched + cached reads cost 0.05 x input.
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10
_BATCH_MULT = 0.50

# Minimum tokens for a cacheable block (Anthropic). Below this the request
# still works but nothing gets cached — we warn so users can bulk up prefixes.
_CACHE_MIN_TOKENS = {
    "opus": 1024,
    "sonnet": 1024,
    "haiku": 2048,
}

_SPEND_LOG_PATH = os.getenv(
    "NAIL_JUDGE_SPEND_LOG",
    str(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "data", "judge_spend.jsonl")),
)

# Models that removed temperature / top_p / top_k from the Messages API.
# Opus 4.7 is the first; assume the same for any future 4.7+ Opus point release.
_NO_SAMPLING_PARAMS = {"claude-opus-4-7"}

# Default effort hint for models that accept output_config.effort.
# 'xhigh' is the recommended starting point for coding / agentic Opus 4.7 work.
_DEFAULT_EFFORT = os.getenv("NAIL_JUDGE_EFFORT", "xhigh")


def _accepts_sampling(model: str) -> bool:
    return not any(model.startswith(m) for m in _NO_SAMPLING_PARAMS)


def _accepts_effort(model: str) -> bool:
    # output_config.effort is an Opus 4.7-era knob
    return model.startswith("claude-opus-4-7")


def _price(model: str) -> dict:
    if model in _CLAUDE_PRICES:
        return _CLAUDE_PRICES[model]
    for k, v in _CLAUDE_PRICES.items():
        if model.startswith(k):
            return v
    return _DEFAULT_PRICE


def _log_spend(record: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_SPEND_LOG_PATH), exist_ok=True)
        with open(_SPEND_LOG_PATH, "a") as fp:
            fp.write(json.dumps(record) + "\n")
    except Exception:
        pass  # never let accounting break a training run


@dataclass
class JudgeResult:
    text: str
    backend: str
    model: str
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    # Prompt-caching attribution (Anthropic only; 0 for Ollama / non-cached calls)
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    # Batch API attribution (Anthropic Messages Batches at 0.5x price)
    is_batch: bool = False
    # Error flag for batch results that came back 'errored'/'expired'/'canceled'
    error: str | None = None


class JudgeError(RuntimeError):
    pass


class JudgeClient:
    """Single API surface over Claude or local Ollama."""

    def __init__(self, prefer: str | None = None, max_retries: int = 2) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.prefer = prefer or ("claude" if self.api_key else "ollama")
        self.max_retries = max_retries

    # ── public ──
    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_mode: bool = False,
        cache_system: bool = False,
    ) -> JudgeResult:
        """Single-turn chat. Tries Claude first if preferred, else Ollama.

        cache_system: if True and backend is Claude, mark the system block
        with cache_control.ephemeral so repeated calls with the same system
        prompt pay only 0.1x input tokens after the first call. Below the
        model's minimum cache size (~1024 tokens for Opus/Sonnet) the flag
        is a no-op — the API simply won't cache a short block.
        """
        order = (
            ["claude", "ollama"] if self.prefer == "claude" else ["ollama", "claude"]
        )
        last_err: Exception | None = None
        for backend in order:
            if backend == "claude" and not self.api_key:
                continue
            for model in self._models_for(backend):
                try:
                    return self._call(backend, model, system, user,
                                      max_tokens, temperature, json_mode,
                                      cache_system)
                except Exception as e:  # try next model / backend
                    last_err = e
        raise JudgeError(f"all judge backends failed: {last_err}")

    # ── internals ──
    def _models_for(self, backend: str) -> list[str]:
        if backend == "claude":
            return [CLAUDE_PRIMARY, CLAUDE_FALLBACK]
        return [OLLAMA_LOCAL_JUDGE]

    def _call(
        self,
        backend: str,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
        cache_system: bool,
    ) -> JudgeResult:
        if backend == "claude":
            return self._call_claude(model, system, user, max_tokens,
                                     temperature, json_mode, cache_system)
        return self._call_ollama(model, system, user, max_tokens,
                                 temperature, json_mode)

    def _call_claude(self, model, system, user, max_tokens, temperature,
                     json_mode, cache_system):
        sys_aug = system
        if json_mode:
            sys_aug += (
                "\n\nIMPORTANT: respond with a single valid JSON object only. "
                "No prose, no markdown fences."
            )
        # System must be a content-block array to carry cache_control.
        if cache_system:
            system_field: list | str = [{
                "type": "text",
                "text": sys_aug,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            system_field = sys_aug
        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_field,
            "messages": [{"role": "user", "content": user}],
        }
        # Opus 4.7 dropped temperature/top_p/top_k; only send sampling params
        # to models that still accept them.
        if _accepts_sampling(model):
            body["temperature"] = temperature
        if _accepts_effort(model):
            body["output_config"] = {"effort": _DEFAULT_EFFORT}
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        for attempt in range(self.max_retries + 1):
            t0 = time.time()
            try:
                r = requests.post(ANTHROPIC_URL, headers=headers, json=body, timeout=120)
                if r.status_code == 200:
                    data = r.json()
                    text = "".join(b.get("text", "") for b in data.get("content", []))
                    usage = data.get("usage", {}) or {}
                    in_tok = int(usage.get("input_tokens", 0))
                    out_tok = int(usage.get("output_tokens", 0))
                    cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
                    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
                    price = _price(model)
                    cost = (
                        in_tok * price["in"]
                        + out_tok * price["out"]
                        + cache_write * price["in"] * _CACHE_WRITE_MULT
                        + cache_read * price["in"] * _CACHE_READ_MULT
                    ) / 1_000_000
                    latency = time.time() - t0
                    _log_spend({
                        "ts": time.time(),
                        "backend": "claude",
                        "model": model,
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "cache_creation_tokens": cache_write,
                        "cache_read_tokens": cache_read,
                        "cost_usd": cost,
                        "latency_s": latency,
                        "is_batch": False,
                        "caller": os.getenv("NAIL_JUDGE_CALLER", "unknown"),
                    })
                    return JudgeResult(text=text, backend="claude", model=model,
                                       latency_s=latency,
                                       input_tokens=in_tok, output_tokens=out_tok,
                                       cache_creation_tokens=cache_write,
                                       cache_read_tokens=cache_read,
                                       cost_usd=cost)
                if r.status_code in (429, 529):  # rate-limited / overloaded
                    time.sleep(2 ** attempt)
                    continue
                raise JudgeError(f"claude {model}: {r.status_code} {r.text[:200]}")
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise JudgeError(f"claude {model} network: {e}") from e
                time.sleep(2 ** attempt)
        raise JudgeError(f"claude {model}: exhausted retries")

    def _call_ollama(self, model, system, user, max_tokens, temperature, json_mode):
        sys_aug = system
        if json_mode:
            sys_aug += "\n\nRespond with a single valid JSON object only."
        body = {
            "model": model,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "messages": [
                {"role": "system", "content": sys_aug},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            body["format"] = "json"
        t0 = time.time()
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=600)
        r.raise_for_status()
        data = r.json()
        text = data["message"]["content"]
        latency = time.time() - t0
        in_tok = int(data.get("prompt_eval_count", 0) or 0)
        out_tok = int(data.get("eval_count", 0) or 0)
        _log_spend({
            "ts": time.time(),
            "backend": "ollama",
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cost_usd": 0.0,
            "latency_s": latency,
            "is_batch": False,
            "caller": os.getenv("NAIL_JUDGE_CALLER", "unknown"),
        })
        return JudgeResult(text=text, backend="ollama", model=model,
                           latency_s=latency,
                           input_tokens=in_tok, output_tokens=out_tok,
                           cost_usd=0.0)


def extract_json(text: str) -> dict | None:
    """Permissive JSON extraction from a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find first {...} balanced block
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    start = -1
    return None


def _summarize_spend(path: str) -> dict:
    """Aggregate the spend log into totals per (backend, model, caller).

    Also computes hypothetical cost *without* caching / batching so users can
    see how much those tools saved.
    """
    totals: dict[tuple, dict] = {}
    grand = {
        "calls": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "batch_calls": 0, "cost_usd": 0.0,
        "hypothetical_no_cache_no_batch_usd": 0.0,
        "savings_usd": 0.0,
    }
    if not os.path.exists(path):
        return {"path": path, "exists": False, "grand": grand, "rows": []}
    with open(path) as fp:
        for line in fp:
            try:
                r = json.loads(line)
            except Exception:
                continue
            key = (r.get("backend", "?"), r.get("model", "?"),
                   r.get("caller", "unknown"))
            t = totals.setdefault(key, {
                "calls": 0, "input_tokens": 0, "output_tokens": 0,
                "cache_creation_tokens": 0, "cache_read_tokens": 0,
                "batch_calls": 0, "cost_usd": 0.0,
                "hypothetical_no_cache_no_batch_usd": 0.0,
            })
            t["calls"] += 1
            in_tok = int(r.get("input_tokens", 0) or 0)
            out_tok = int(r.get("output_tokens", 0) or 0)
            cw = int(r.get("cache_creation_tokens", 0) or 0)
            cr = int(r.get("cache_read_tokens", 0) or 0)
            is_batch = bool(r.get("is_batch", False))
            t["input_tokens"] += in_tok
            t["output_tokens"] += out_tok
            t["cache_creation_tokens"] += cw
            t["cache_read_tokens"] += cr
            t["batch_calls"] += int(is_batch)
            t["cost_usd"] += float(r.get("cost_usd", 0.0) or 0.0)
            # What this call *would* have cost at full, uncached, non-batch prices.
            # We compute hypothetical for both real-time Claude and batched Claude
            # so "savings" reflects cache + batch combined.
            backend = r.get("backend", "")
            if backend in ("claude", "claude-batch"):
                price = _price(r.get("model", ""))
                full = ((in_tok + cw + cr) * price["in"]
                        + out_tok * price["out"]) / 1_000_000
                t["hypothetical_no_cache_no_batch_usd"] += full
    rows = [
        {"backend": b, "model": m, "caller": c, **v}
        for (b, m, c), v in sorted(totals.items(),
                                   key=lambda kv: -kv[1]["cost_usd"])
    ]
    for fld in ("input_tokens", "output_tokens", "cache_creation_tokens",
                "cache_read_tokens", "batch_calls", "cost_usd",
                "hypothetical_no_cache_no_batch_usd"):
        grand[fld] = sum(r[fld] for r in rows)
    grand["calls"] = sum(r["calls"] for r in rows)
    grand["savings_usd"] = (grand["hypothetical_no_cache_no_batch_usd"]
                            - grand["cost_usd"])
    return {"path": path, "exists": True, "grand": grand, "rows": rows}


def _print_spend(summary: dict) -> None:
    print(f"spend log: {summary['path']}")
    if not summary["exists"]:
        print("  (no entries yet)")
        return
    g = summary["grand"]
    print(f"  total: {g['calls']} calls  "
          f"({g['batch_calls']} batched)  "
          f"{g['input_tokens']} in / {g['output_tokens']} out tokens  "
          f"cache: {g['cache_creation_tokens']} write / "
          f"{g['cache_read_tokens']} read")
    print(f"  spent: ${g['cost_usd']:.4f}   "
          f"saved vs full-price real-time: ${g['savings_usd']:.4f}")
    print(f"  {'backend':<8} {'model':<28} {'caller':<24} "
          f"{'calls':>6} {'batch':>6} {'in':>10} {'out':>10} "
          f"{'c_rd':>8} {'usd':>10}")
    for r in summary["rows"]:
        print(f"  {r['backend']:<8} {r['model']:<28} {r['caller']:<24} "
              f"{r['calls']:>6} {r['batch_calls']:>6} "
              f"{r['input_tokens']:>10} {r['output_tokens']:>10} "
              f"{r['cache_read_tokens']:>8} "
              f"${r['cost_usd']:>8.4f}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="NAIL judge utilities")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("spend", help="summarize the judge spend log")
    s.add_argument("--log", default=_SPEND_LOG_PATH)
    s.add_argument("--json", action="store_true", help="emit JSON instead of table")
    args = ap.parse_args()
    if args.cmd == "spend":
        summary = _summarize_spend(args.log)
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            _print_spend(summary)
