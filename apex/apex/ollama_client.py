"""Tiny synchronous Ollama HTTP client used by System 1 / System 2.

We deliberately do NOT depend on `langchain` or `ollama` Python SDK so
the test suite stays runnable without the network and without optional
deps. Production swap-in is easy because the surface is just:

    OllamaClient(base_url).generate(model, prompt, *, system=None,
                                    options=None, timeout=None) -> str

Stubbing in tests is a one-liner — see tests/test_apex_brain.py.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional


DEFAULT_BASE_URL = os.environ.get("OLLAMA_BASE_URL",
                                  "http://localhost:11434")


class OllamaError(RuntimeError):
    pass


@dataclass
class OllamaClient:
    base_url: str = DEFAULT_BASE_URL
    default_timeout_s: float = 120.0

    def generate(self, model: str, prompt: str, *,
                 system: Optional[str] = None,
                 options: Optional[dict[str, Any]] = None,
                 timeout: Optional[float] = None) -> str:
        """Blocking, non-streaming generate. Returns the response text."""
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise OllamaError(
                "requests not installed; pip install requests") from exc

        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            body["system"] = system
        if options:
            body["options"] = options

        try:
            resp = requests.post(
                f"{self.base_url.rstrip('/')}/api/generate",
                json=body,
                timeout=timeout or self.default_timeout_s,
            )
            resp.raise_for_status()
        except Exception as exc:
            raise OllamaError(f"ollama call failed: {exc}") from exc

        try:
            data = resp.json()
        except Exception as exc:
            raise OllamaError(f"ollama returned non-JSON: {exc}") from exc

        return str(data.get("response", ""))
