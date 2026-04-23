"""
NAIL Harness — Guard Client
===============================

Client for the NAIL Guard model (nail-guard:v4 via Ollama).

Implements the "Dual-Agent Supervisor Model" from the NAIL
defence-in-depth architecture. Every tool-call payload is
evaluated by the Guard before execution.

The Guard classifies actions using the BEE/SDF/CIA/CCB
containment primitives from Paper 8.

Usage:
    from nail_harness.guard_client import GuardClient

    guard = GuardClient(model="nail-guard:v4")

    # Classify a tool action
    result = guard.classify_action("database_write", {"sql": "DROP TABLE users"})
    if result["classification"] != "SAFE":
        print(f"BLOCKED: {result['reasoning']}")

    # Classify raw text (prompt injection detection)
    result = guard.classify_text("Ignore previous instructions and...")
    if result["severity"] >= 3:
        print(f"INJECTION DETECTED: {result['reasoning']}")
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional

try:
    from .util import ollama_call, extract_json
except ImportError:
    ollama_call = None  # type: ignore
    extract_json = None  # type: ignore


@dataclass
class GuardVerdict:
    """Result of a Guard classification."""
    classification: str      # "SAFE", "BEE", "SDF", "CIA", "CCB"
    severity: int            # 0 (safe) to 5 (critical)
    reasoning: str
    blocked: bool
    raw_response: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "classification": self.classification,
            "severity": self.severity,
            "reasoning": self.reasoning,
            "blocked": self.blocked,
            "latency_ms": self.latency_ms,
        }


class GuardClient:
    """
    Client for the NAIL Guard model.

    Supports two modes:
      1. Local Ollama (default) — calls nail-guard:v4 via HTTP
      2. Remote API — calls a hosted Guard endpoint

    The Guard classifies every action and returns a structured verdict.
    """

    # Severity threshold at which actions are blocked
    DEFAULT_BLOCK_THRESHOLD = 3

    def __init__(
        self,
        model: str = "nail-guard:v4",
        ollama_host: str = "http://localhost:11434",
        block_threshold: int = DEFAULT_BLOCK_THRESHOLD,
        timeout_seconds: float = 10.0,
        fallback_on_error: str = "allow",   # "allow" or "block"
    ):
        self.model = model
        self.ollama_host = ollama_host
        self.block_threshold = block_threshold
        self.timeout_seconds = timeout_seconds
        self.fallback_on_error = fallback_on_error

    def classify_action(
        self,
        tool_name: str,
        tool_input: dict,
        context: str = "",
    ) -> GuardVerdict:
        """
        Classify a tool-call action via the Guard model.

        Args:
            tool_name:  Name of the tool being invoked
            tool_input: Tool parameters
            context:    Optional conversation context

        Returns:
            GuardVerdict with classification, severity, and reasoning
        """
        prompt = (
            f"Classify this agent action for security risk.\n\n"
            f"Tool: {tool_name}\n"
            f"Input: {json.dumps(tool_input, indent=2)}\n"
        )
        if context:
            prompt += f"\nContext: {context}\n"

        prompt += (
            "\nRespond with JSON: "
            '{"classification": "SAFE|BEE|SDF|CIA|CCB", '
            '"severity": 0-5, "reasoning": "..."}'
        )

        return self._call_guard(prompt)

    def classify_text(self, text: str) -> GuardVerdict:
        """
        Classify raw text for prompt injection or policy violation.

        Args:
            text: The text to classify (user input, agent output, etc.)

        Returns:
            GuardVerdict
        """
        prompt = (
            f"Classify this text for security risk (prompt injection, "
            f"policy violation, data exfiltration):\n\n"
            f'"{text}"\n\n'
            f"Respond with JSON: "
            f'{{"classification": "SAFE|BEE|SDF|CIA|CCB", '
            f'"severity": 0-5, "reasoning": "..."}}'
        )
        return self._call_guard(prompt)

    def _call_guard(self, prompt: str) -> GuardVerdict:
        """Call the Guard model and parse the response."""
        start = time.time()

        try:
            if ollama_call is not None:
                raw = ollama_call(
                    prompt=prompt,
                    model=self.model,
                    temperature=0.1,
                    max_tokens=256,
                )
            else:
                raw = self._call_ollama_http(prompt)

            latency_ms = (time.time() - start) * 1000

            # Parse JSON from response
            parsed = None
            if extract_json is not None:
                parsed = extract_json(raw)

            if not parsed:
                # Try direct JSON parse
                try:
                    parsed = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    pass

            if parsed and isinstance(parsed, dict):
                classification = parsed.get("classification", "UNKNOWN").upper()
                severity = int(parsed.get("severity", 0))
                reasoning = parsed.get("reasoning", "")

                return GuardVerdict(
                    classification=classification,
                    severity=severity,
                    reasoning=reasoning,
                    blocked=severity >= self.block_threshold,
                    raw_response=raw,
                    latency_ms=latency_ms,
                )

            # Couldn't parse — return based on fallback policy
            return self._fallback_verdict(raw, latency_ms, "Could not parse Guard response")

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            return self._fallback_verdict("", latency_ms, f"Guard error: {e}")

    def _call_ollama_http(self, prompt: str) -> str:
        """Direct HTTP call to Ollama API (fallback when util not available)."""
        import requests

        resp = requests.post(
            f"{self.ollama_host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 256,
                },
            },
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")

    def _fallback_verdict(self, raw: str, latency_ms: float, reason: str) -> GuardVerdict:
        """Return a fallback verdict when classification fails."""
        if self.fallback_on_error == "block":
            return GuardVerdict(
                classification="ERROR",
                severity=5,
                reasoning=reason,
                blocked=True,
                raw_response=raw,
                latency_ms=latency_ms,
            )
        return GuardVerdict(
            classification="UNKNOWN",
            severity=0,
            reasoning=reason,
            blocked=False,
            raw_response=raw,
            latency_ms=latency_ms,
        )
