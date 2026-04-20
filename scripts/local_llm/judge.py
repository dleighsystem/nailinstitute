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

import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_PRIMARY = os.getenv("NAIL_JUDGE_CLAUDE_MODEL", "claude-opus-4-7")
CLAUDE_FALLBACK = os.getenv("NAIL_JUDGE_CLAUDE_FALLBACK", "claude-opus-4-6")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_LOCAL_JUDGE = os.getenv("NAIL_JUDGE_OLLAMA_MODEL", "qwen2.5:32b-instruct")


@dataclass
class JudgeResult:
    text: str
    backend: str
    model: str
    latency_s: float


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
    ) -> JudgeResult:
        """Single-turn chat. Tries Claude first if preferred, else Ollama."""
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
                                      max_tokens, temperature, json_mode)
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
    ) -> JudgeResult:
        if backend == "claude":
            return self._call_claude(model, system, user, max_tokens,
                                     temperature, json_mode)
        return self._call_ollama(model, system, user, max_tokens,
                                 temperature, json_mode)

    def _call_claude(self, model, system, user, max_tokens, temperature, json_mode):
        sys_aug = system
        if json_mode:
            sys_aug += (
                "\n\nIMPORTANT: respond with a single valid JSON object only. "
                "No prose, no markdown fences."
            )
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": sys_aug,
            "messages": [{"role": "user", "content": user}],
        }
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
                    return JudgeResult(text=text, backend="claude", model=model,
                                       latency_s=time.time() - t0)
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
        text = r.json()["message"]["content"]
        return JudgeResult(text=text, backend="ollama", model=model,
                           latency_s=time.time() - t0)


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
