"""
NAIL Harness — Core Utility Functions
=======================================

Equivalent to Anthropic's patterns/agents/util.py, but wraps
local Ollama models instead of the Anthropic API.

Provides:
    - ollama_call():  Single LLM call with system prompt
    - extract_json(): Parse JSON from LLM output
    - extract_xml():  Parse XML-tagged sections from LLM output
    - ollama_chat():  Multi-turn chat with history
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

OLLAMA_BASE_URL = "http://localhost:11434"

# Model aliases — matches experiments/shared/config.py
MODELS = {
    "primary": "nemotron:70b",
    "fast":    "mistral:7b-instruct",
    "code":    "deepseek-coder:6.7b-instruct",
}


# ═══════════════════════════════════════════════════════════════════════════
# Response container
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class LLMResponse:
    """Structured response from an Ollama call."""
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    elapsed_seconds: float = 0.0
    tokens_per_second: float = 0.0
    raw: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Core LLM Call (equivalent to Anthropic's llm_call)
# ═══════════════════════════════════════════════════════════════════════════

def ollama_call(
    prompt: str,
    system_prompt: str = "",
    model: str = "nemotron:70b",
    temperature: float = 0.1,
    max_tokens: int = 4096,
    json_mode: bool = False,
    timeout: int = 1800,
) -> str:
    """
    Call a local Ollama model and return the text response.

    This is the NAIL equivalent of Anthropic's util.llm_call().
    All agent patterns are built by composing this primitive.

    Args:
        prompt:        User message
        system_prompt: System instructions (optional)
        model:         Ollama model name
        temperature:   Sampling temperature (0.1 = deterministic)
        max_tokens:    Max generation tokens
        json_mode:     If True, request JSON output format
        timeout:       Request timeout in seconds

    Returns:
        str: The model's response text
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if json_mode:
        payload["format"] = "json"

    url = f"{OLLAMA_BASE_URL}/api/chat"

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except requests.exceptions.ReadTimeout:
            if attempt < 2:
                print(f"  ⚠️  Ollama timeout (attempt {attempt+1}/3), retrying...")
                time.sleep(2)
                continue
            raise
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
                "Is the Ollama server running?"
            )

    return ""


def ollama_call_full(
    prompt: str,
    system_prompt: str = "",
    model: str = "nemotron:70b",
    temperature: float = 0.1,
    max_tokens: int = 4096,
    json_mode: bool = False,
    timeout: int = 1800,
) -> LLMResponse:
    """
    Full LLM call that returns an LLMResponse with token counts and timing.

    Use this when you need metrics; use ollama_call() for simple text output.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if json_mode:
        payload["format"] = "json"

    url = f"{OLLAMA_BASE_URL}/api/chat"
    t0 = time.time()

    resp = requests.post(url, json=payload, timeout=timeout)
    elapsed = time.time() - t0
    resp.raise_for_status()
    data = resp.json()

    content = data.get("message", {}).get("content", "")
    prompt_tokens = data.get("prompt_eval_count", 0)
    completion_tokens = data.get("eval_count", 0)
    total = prompt_tokens + completion_tokens

    # Compute throughput
    gen_ns = data.get("eval_duration", 0)
    gen_s = gen_ns / 1e9 if gen_ns else elapsed
    tps = completion_tokens / gen_s if gen_s > 0 else 0.0

    return LLMResponse(
        content=content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        elapsed_seconds=elapsed,
        tokens_per_second=tps,
        raw=data,
    )


def ollama_chat(
    messages: list[dict],
    system_prompt: str = "",
    model: str = "nemotron:70b",
    temperature: float = 0.3,
    max_tokens: int = 4096,
    json_mode: bool = False,
    timeout: int = 1800,
) -> LLMResponse:
    """
    Multi-turn chat call.  Messages should be a list of
    {"role": "user"|"assistant", "content": "..."} dicts.
    """
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    payload = {
        "model": model,
        "messages": full_messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if json_mode:
        payload["format"] = "json"

    url = f"{OLLAMA_BASE_URL}/api/chat"
    t0 = time.time()

    resp = requests.post(url, json=payload, timeout=timeout)
    elapsed = time.time() - t0
    resp.raise_for_status()
    data = resp.json()

    content = data.get("message", {}).get("content", "")
    prompt_tokens = data.get("prompt_eval_count", 0)
    completion_tokens = data.get("eval_count", 0)
    total = prompt_tokens + completion_tokens

    gen_ns = data.get("eval_duration", 0)
    gen_s = gen_ns / 1e9 if gen_ns else elapsed
    tps = completion_tokens / gen_s if gen_s > 0 else 0.0

    return LLMResponse(
        content=content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        elapsed_seconds=elapsed,
        tokens_per_second=tps,
        raw=data,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Extraction helpers (equivalent to Anthropic's extract_xml)
# ═══════════════════════════════════════════════════════════════════════════

def extract_xml(text: str, tag: str) -> str:
    """
    Extract content between XML tags from LLM output.

    Equivalent to Anthropic's patterns/agents/util.extract_xml().

    Args:
        text: The text containing XML tags
        tag:  The tag name to extract (e.g., "result")

    Returns:
        The content between <tag> and </tag>, or empty string
    """
    match = re.search(f"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_json(text: str) -> dict | list | None:
    """
    Extract and parse JSON from LLM output.

    Handles:
      - Raw JSON output
      - JSON inside ```json ... ``` code blocks
      - JSON inside <json>...</json> tags
      - First { ... } or [ ... ] block in text

    Returns:
        Parsed JSON object, or None if extraction fails
    """
    # Try direct parse first
    text_stripped = text.strip()
    if text_stripped.startswith(("{", "[")):
        try:
            return json.loads(text_stripped)
        except json.JSONDecodeError:
            pass

    # Try code block extraction
    code_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try XML tag extraction
    xml_match = re.search(r"<json>(.*?)</json>", text, re.DOTALL)
    if xml_match:
        try:
            return json.loads(xml_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first JSON object/array
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        # Find matching end bracket
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    return None


def extract_all_xml(text: str, tag: str) -> list[str]:
    """Extract all occurrences of a tagged section."""
    return [m.strip() for m in re.findall(
        f"<{tag}>(.*?)</{tag}>", text, re.DOTALL
    )]
