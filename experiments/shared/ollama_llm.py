"""
NAIL Institute - Local Ollama LLM Wrapper
==========================================
Provides a unified interface to call local Ollama models.
Tracks token usage for experiment metrics.
"""

import json
import time
import requests
from dataclasses import dataclass, field
from typing import Optional

from .config import OLLAMA_BASE_URL, DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS


@dataclass
class LLMResponse:
    """Structured response from the LLM with throughput metrics."""
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    elapsed_seconds: float
    # Throughput metrics
    tokens_per_second: float = 0.0          # completion tokens / generation time
    prompt_eval_time_s: float = 0.0         # time spent evaluating prompt
    generation_time_s: float = 0.0          # time spent generating tokens
    time_to_first_token_s: float = 0.0      # prompt eval = time to first token
    prompt_tokens_per_second: float = 0.0   # prompt eval throughput
    raw: dict = field(default_factory=dict)


class OllamaLLM:
    """
    Wrapper around the Ollama REST API for local LLM inference.
    Supports chat completions with token tracking.
    """

    def __init__(
        self,
        model: str,
        base_url: str = OLLAMA_BASE_URL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system_prompt: Optional[str] = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt

        # Running totals for experiment tracking
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0
        self.total_elapsed_seconds = 0.0
        self.total_generation_time_s = 0.0

        # Per-call history for percentile analysis
        self._latencies: list[float] = []         # wall-clock per call
        self._throughputs: list[float] = []        # tokens/sec per call
        self._ttft: list[float] = []               # time to first token per call

    def chat(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """
        Send a chat completion request to Ollama.
        
        Args:
            messages: List of {"role": "...", "content": "..."} dicts.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.
            json_mode: If True, request JSON output format.
        
        Returns:
            LLMResponse with content, token counts, timing.
        """
        # Prepend system prompt if set and not already in messages
        if self.system_prompt and (not messages or messages[0].get("role") != "system"):
            messages = [{"role": "system", "content": self.system_prompt}] + messages

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature or self.temperature,
                "num_predict": max_tokens or self.max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        url = f"{self.base_url}/api/chat"
        t0 = time.time()
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=1800)
                break
            except requests.exceptions.ReadTimeout:
                if attempt < 2:
                    print(f"    ⚠️ Timeout on attempt {attempt+1}, retrying...")
                    continue
                raise
        elapsed = time.time() - t0
        resp.raise_for_status()
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)

        # Ollama returns durations in nanoseconds
        prompt_eval_ns = data.get("prompt_eval_duration", 0)
        eval_ns = data.get("eval_duration", 0)
        load_ns = data.get("load_duration", 0)
        total_ns = data.get("total_duration", 0)

        prompt_eval_s = prompt_eval_ns / 1e9 if prompt_eval_ns else 0.0
        generation_s = eval_ns / 1e9 if eval_ns else 0.0
        ttft = prompt_eval_s  # time to first token ≈ prompt eval time

        # Throughput
        tps = completion_tokens / generation_s if generation_s > 0 else 0.0
        prompt_tps = prompt_tokens / prompt_eval_s if prompt_eval_s > 0 else 0.0

        # Update running totals
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_calls += 1
        self.total_elapsed_seconds += elapsed
        self.total_generation_time_s += generation_s

        # Per-call history
        self._latencies.append(elapsed)
        self._throughputs.append(tps)
        self._ttft.append(ttft)

        return LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            elapsed_seconds=round(elapsed, 2),
            tokens_per_second=round(tps, 1),
            prompt_eval_time_s=round(prompt_eval_s, 3),
            generation_time_s=round(generation_s, 3),
            time_to_first_token_s=round(ttft, 3),
            prompt_tokens_per_second=round(prompt_tps, 1),
            raw=data,
        )

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Convenience: single-turn prompt → response."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def get_usage_stats(self) -> dict:
        """Return cumulative usage statistics with throughput metrics."""
        stats = {
            "model": self.model,
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "total_elapsed_seconds": round(self.total_elapsed_seconds, 2),
            "total_generation_time_s": round(self.total_generation_time_s, 2),
        }
        # Throughput aggregates
        if self._throughputs:
            sorted_tp = sorted(self._throughputs)
            stats["throughput_avg_tok_s"] = round(sum(self._throughputs) / len(self._throughputs), 1)
            stats["throughput_p50_tok_s"] = round(sorted_tp[len(sorted_tp) // 2], 1)
            stats["throughput_p95_tok_s"] = round(sorted_tp[int(len(sorted_tp) * 0.05)], 1)  # worst 5%
            stats["throughput_max_tok_s"] = round(max(self._throughputs), 1)
        # Latency aggregates
        if self._latencies:
            sorted_lat = sorted(self._latencies)
            stats["latency_avg_s"] = round(sum(self._latencies) / len(self._latencies), 2)
            stats["latency_p50_s"] = round(sorted_lat[len(sorted_lat) // 2], 2)
            stats["latency_p95_s"] = round(sorted_lat[int(len(sorted_lat) * 0.95)], 2)
            stats["latency_max_s"] = round(max(self._latencies), 2)
        # TTFT aggregates
        if self._ttft:
            sorted_ttft = sorted(self._ttft)
            stats["ttft_avg_s"] = round(sum(self._ttft) / len(self._ttft), 3)
            stats["ttft_p50_s"] = round(sorted_ttft[len(sorted_ttft) // 2], 3)
            stats["ttft_p95_s"] = round(sorted_ttft[int(len(sorted_ttft) * 0.95)], 3)
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


def test_ollama_connection(model: str = "mistral:7b-instruct") -> bool:
    """Quick health check that Ollama is reachable and the model is loaded."""
    try:
        llm = OllamaLLM(model=model)
        resp = llm.generate("Say 'hello' in one word.")
        print(f"✅ Ollama OK | Model: {model} | Response: {resp.content[:80]}")
        return True
    except Exception as e:
        print(f"❌ Ollama connection failed: {e}")
        return False


if __name__ == "__main__":
    test_ollama_connection()
