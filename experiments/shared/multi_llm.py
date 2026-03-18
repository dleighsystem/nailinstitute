"""
NAIL Institute — Multi-Provider LLM Adapter
=============================================
Provides a unified interface to call LLMs across multiple providers,
all returning the same LLMResponse dataclass.

Supported providers:
  - ollama:   Local Ollama models (nemotron:70b, mistral:7b, etc.)
  - openai:   OpenAI API (GPT-4o, GPT-4-turbo, etc.)
  - anthropic: Anthropic Messages API (Claude Opus 4.6, etc.)
  - google:   Google Generative AI API (Gemini 2.5 Pro, etc.)
  - kimi:     Moonshot Kimi API (OpenAI-compatible)

Usage:
    from shared.multi_llm import create_llm

    llm = create_llm("anthropic", "claude-opus-4-6", api_key="sk-ant-...")
    response = llm.chat([{"role": "user", "content": "Hello"}])
    # response is an LLMResponse — identical interface to OllamaLLM
"""

import json
import os
import time
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from .ollama_llm import OllamaLLM, LLMResponse
from .config import (
    OLLAMA_BASE_URL, DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS,
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, KIMI_API_KEY,
)


# ═══════════════════════════════════════════════════════════════════════════
# BASE CLASS
# ═══════════════════════════════════════════════════════════════════════════

class BaseLLM(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(
        self,
        model: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system_prompt: Optional[str] = None,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt

        # Running totals
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0
        self.total_elapsed_seconds = 0.0
        self.total_generation_time_s = 0.0

        # Per-call history
        self._latencies: list[float] = []
        self._throughputs: list[float] = []
        self._ttft: list[float] = []

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send chat messages and return LLMResponse."""
        ...

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Convenience: single-turn prompt → response."""
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.append({"role": "user", "content": prompt})
        return self.chat(msgs, **kwargs)

    def _update_stats(self, response: LLMResponse):
        """Update running totals from a response."""
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        self.total_calls += 1
        self.total_elapsed_seconds += response.elapsed_seconds
        self.total_generation_time_s += response.generation_time_s

        self._latencies.append(response.elapsed_seconds)
        if response.tokens_per_second > 0:
            self._throughputs.append(response.tokens_per_second)
        if response.time_to_first_token_s > 0:
            self._ttft.append(response.time_to_first_token_s)

    def get_usage_stats(self) -> dict:
        """Return cumulative usage statistics."""
        stats = {
            "model": self.model,
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "total_elapsed_seconds": round(self.total_elapsed_seconds, 2),
            "total_generation_time_s": round(self.total_generation_time_s, 2),
        }
        if self._throughputs:
            sorted_tp = sorted(self._throughputs)
            stats["throughput_avg_tok_s"] = round(sum(self._throughputs) / len(self._throughputs), 1)
            stats["throughput_p50_tok_s"] = round(sorted_tp[len(sorted_tp) // 2], 1)
        if self._latencies:
            sorted_lat = sorted(self._latencies)
            stats["latency_avg_s"] = round(sum(self._latencies) / len(self._latencies), 2)
            stats["latency_p50_s"] = round(sorted_lat[len(sorted_lat) // 2], 2)
            stats["latency_p95_s"] = round(sorted_lat[int(len(sorted_lat) * 0.95)], 2)
        return stats

    def reset_stats(self):
        """Reset cumulative counters."""
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0
        self.total_elapsed_seconds = 0.0
        self.total_generation_time_s = 0.0
        self._latencies.clear()
        self._throughputs.clear()
        self._ttft.clear()


# ═══════════════════════════════════════════════════════════════════════════
# OLLAMA ADAPTER (wraps existing OllamaLLM)
# ═══════════════════════════════════════════════════════════════════════════

class OllamaProvider(BaseLLM):
    """Wrapper around local Ollama models."""

    def __init__(self, model: str, **kwargs):
        super().__init__(model=model, **kwargs)
        self._ollama = OllamaLLM(
            model=model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            system_prompt=self.system_prompt,
        )

    def chat(self, messages, temperature=None, max_tokens=None, json_mode=False):
        resp = self._ollama.chat(messages, temperature=temperature,
                                 max_tokens=max_tokens, json_mode=json_mode)
        self._update_stats(resp)
        return resp


# ═══════════════════════════════════════════════════════════════════════════
# OPENAI-COMPATIBLE ADAPTER (OpenAI, Kimi)
# ═══════════════════════════════════════════════════════════════════════════

class OpenAIProvider(BaseLLM):
    """OpenAI Chat Completions API. Also works for Kimi and other
    OpenAI-compatible endpoints."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self.api_key = api_key or OPENAI_API_KEY
        self.base_url = base_url.rstrip("/")
        if not self.api_key:
            raise ValueError(f"API key required for OpenAI provider (model={model})")

    def chat(self, messages, temperature=None, max_tokens=None, json_mode=False):
        # Prepend system prompt if not already in messages
        if self.system_prompt and (not messages or messages[0].get("role") != "system"):
            messages = [{"role": "system", "content": self.system_prompt}] + messages

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url}/chat/completions"
        t0 = time.time()
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=300)
                if resp.status_code == 429:
                    wait = min(2 ** attempt * 5, 60)
                    print(f"    ⚠️ Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                break
            except requests.exceptions.ReadTimeout:
                if attempt < 2:
                    print(f"    ⚠️ Timeout on attempt {attempt+1}, retrying...")
                    continue
                raise
        elapsed = time.time() - t0
        resp.raise_for_status()
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        # OpenAI doesn't provide generation time; estimate from elapsed
        tps = completion_tokens / elapsed if elapsed > 0 else 0.0

        result = LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            elapsed_seconds=round(elapsed, 2),
            tokens_per_second=round(tps, 1),
            prompt_eval_time_s=0.0,
            generation_time_s=round(elapsed, 3),
            time_to_first_token_s=0.0,
            prompt_tokens_per_second=0.0,
            raw=data,
        )
        self._update_stats(result)
        return result


# ═══════════════════════════════════════════════════════════════════════════
# ANTHROPIC ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class AnthropicProvider(BaseLLM):
    """Anthropic Messages API for Claude models."""

    def __init__(self, model: str, api_key: Optional[str] = None, **kwargs):
        super().__init__(model=model, **kwargs)
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.base_url = "https://api.anthropic.com/v1"
        if not self.api_key:
            raise ValueError(f"API key required for Anthropic provider (model={model})")

    def chat(self, messages, temperature=None, max_tokens=None, json_mode=False):
        # Anthropic uses separate 'system' parameter
        system_text = self.system_prompt or ""
        api_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                api_messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        # Ensure messages alternate user/assistant
        if not api_messages:
            api_messages = [{"role": "user", "content": "Hello"}]

        payload = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
        }
        if system_text:
            payload["system"] = system_text

        # For JSON mode, append instruction to system prompt
        if json_mode and system_text:
            payload["system"] = system_text + "\n\nYou must respond with valid JSON only."
        elif json_mode:
            payload["system"] = "You must respond with valid JSON only."

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        url = f"{self.base_url}/messages"
        t0 = time.time()
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=300)
                if resp.status_code == 429:
                    wait = min(2 ** attempt * 5, 60)
                    print(f"    ⚠️ Anthropic rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                break
            except requests.exceptions.ReadTimeout:
                if attempt < 2:
                    print(f"    ⚠️ Timeout on attempt {attempt+1}, retrying...")
                    continue
                raise
        elapsed = time.time() - t0
        resp.raise_for_status()
        data = resp.json()

        # Extract content (Anthropic returns content blocks)
        content_blocks = data.get("content", [])
        content = "".join(
            block.get("text", "") for block in content_blocks
            if block.get("type") == "text"
        )

        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)

        tps = completion_tokens / elapsed if elapsed > 0 else 0.0

        result = LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            elapsed_seconds=round(elapsed, 2),
            tokens_per_second=round(tps, 1),
            prompt_eval_time_s=0.0,
            generation_time_s=round(elapsed, 3),
            time_to_first_token_s=0.0,
            prompt_tokens_per_second=0.0,
            raw=data,
        )
        self._update_stats(result)
        return result


# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE GENERATIVE AI ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class GoogleProvider(BaseLLM):
    """Google Generative AI API for Gemini models."""

    def __init__(self, model: str, api_key: Optional[str] = None, **kwargs):
        super().__init__(model=model, **kwargs)
        self.api_key = api_key or GOOGLE_API_KEY
        if not self.api_key:
            raise ValueError(f"API key required for Google provider (model={model})")

    def chat(self, messages, temperature=None, max_tokens=None, json_mode=False):
        # Google uses 'contents' format
        contents = []
        system_text = self.system_prompt or ""

        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}],
                })

        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature or self.temperature,
                "maxOutputTokens": max_tokens or self.max_tokens,
            },
        }

        if system_text:
            payload["systemInstruction"] = {
                "parts": [{"text": system_text}]
            }

        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

        t0 = time.time()
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=300)
                if resp.status_code == 429:
                    wait = min(2 ** attempt * 5, 60)
                    print(f"    ⚠️ Google rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                break
            except requests.exceptions.ReadTimeout:
                if attempt < 2:
                    print(f"    ⚠️ Timeout on attempt {attempt+1}, retrying...")
                    continue
                raise
        elapsed = time.time() - t0
        resp.raise_for_status()
        data = resp.json()

        # Extract content
        candidates = data.get("candidates", [{}])
        content_parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        content = "".join(p.get("text", "") for p in content_parts)

        # Usage metadata
        usage = data.get("usageMetadata", {})
        prompt_tokens = usage.get("promptTokenCount", 0)
        completion_tokens = usage.get("candidatesTokenCount", 0)

        tps = completion_tokens / elapsed if elapsed > 0 else 0.0

        result = LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            elapsed_seconds=round(elapsed, 2),
            tokens_per_second=round(tps, 1),
            prompt_eval_time_s=0.0,
            generation_time_s=round(elapsed, 3),
            time_to_first_token_s=0.0,
            prompt_tokens_per_second=0.0,
            raw=data,
        )
        self._update_stats(result)
        return result


# ═══════════════════════════════════════════════════════════════════════════
# KIMI ADAPTER (OpenAI-compatible with Moonshot endpoint)
# ═══════════════════════════════════════════════════════════════════════════

class KimiProvider(OpenAIProvider):
    """Kimi (Moonshot) — OpenAI-compatible API."""

    def __init__(self, model: str = "kimi-k2.5", api_key: Optional[str] = None, **kwargs):
        super().__init__(
            model=model,
            api_key=api_key or KIMI_API_KEY,
            base_url="https://api.moonshot.ai/v1",
            **kwargs,
        )


# ═══════════════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════════════

PROVIDER_REGISTRY = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "kimi": KimiProvider,
}


def create_llm(
    provider: str,
    model: str,
    api_key: Optional[str] = None,
    **kwargs,
) -> BaseLLM:
    """
    Factory function to create an LLM provider instance.

    Args:
        provider: One of 'ollama', 'openai', 'anthropic', 'google', 'kimi'
        model: Model name for the provider
        api_key: API key (uses env var default if not provided)
        **kwargs: Additional args (temperature, max_tokens, system_prompt)

    Returns:
        BaseLLM instance with unified chat()/generate() interface
    """
    if provider not in PROVIDER_REGISTRY:
        raise ValueError(f"Unknown provider '{provider}'. Available: {list(PROVIDER_REGISTRY.keys())}")

    cls = PROVIDER_REGISTRY[provider]
    if api_key and provider != "ollama":
        return cls(model=model, api_key=api_key, **kwargs)
    return cls(model=model, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# MODEL CONFIGURATIONS for cross-model studies
# ═══════════════════════════════════════════════════════════════════════════

CROSS_MODEL_CONFIGS = [
    {
        "provider": "ollama",
        "model": "nemotron:70b",
        "label": "Nemotron 70B (local)",
        "family": "nvidia",
    },
    {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "label": "Claude Sonnet 4",
        "family": "anthropic",
    },
    {
        "provider": "google",
        "model": "gemini-2.5-pro",
        "label": "Gemini 2.5 Pro",
        "family": "google",
    },
    {
        "provider": "kimi",
        "model": "kimi-k2.5",
        "label": "Kimi 2.5",
        "family": "moonshot",
    },
    {
        "provider": "openai",
        "model": "gpt-4o",
        "label": "GPT-4o",
        "family": "openai",
    },
]


def get_available_models() -> list[dict]:
    """Return list of model configs that have valid API keys configured."""
    available = []
    for cfg in CROSS_MODEL_CONFIGS:
        provider = cfg["provider"]
        if provider == "ollama":
            available.append(cfg)
        elif provider == "anthropic" and ANTHROPIC_API_KEY:
            available.append(cfg)
        elif provider == "google" and GOOGLE_API_KEY:
            available.append(cfg)
        elif provider == "kimi" and KIMI_API_KEY:
            available.append(cfg)
        elif provider == "openai" and OPENAI_API_KEY:
            available.append(cfg)
    return available


# ═══════════════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════════════

def test_all_providers():
    """Test connectivity and response format for all configured providers."""
    models = get_available_models()
    print(f"\n  Testing {len(models)} available providers...\n")

    for cfg in models:
        try:
            llm = create_llm(cfg["provider"], cfg["model"])
            t0 = time.time()
            resp = llm.generate("Respond with exactly: NAIL_TEST_OK")
            elapsed = time.time() - t0

            ok = "NAIL_TEST_OK" in resp.content or len(resp.content) > 0
            status = "✅" if ok else "❌"
            print(f"  {status} {cfg['label']:30s} | {elapsed:.1f}s | "
                  f"{resp.prompt_tokens}+{resp.completion_tokens} tokens | "
                  f"'{resp.content[:50]}'")
        except Exception as e:
            print(f"  ❌ {cfg['label']:30s} | ERROR: {e}")

    missing = [c for c in CROSS_MODEL_CONFIGS if c not in models]
    if missing:
        print(f"\n  ⚠️ Missing API keys for: {', '.join(c['label'] for c in missing)}")


if __name__ == "__main__":
    test_all_providers()
