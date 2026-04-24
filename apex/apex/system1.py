"""System 1 — fast intuitive Ollama wrapper.

Single-shot generate, low-latency model, no `<thought>` overhead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


DEFAULT_SYS1_MODEL = "llama3.1:8b-instruct-q8_0"

DEFAULT_SYS1_SYSTEM_PROMPT = (
    "You are the fast, intuitive front-end of the NAIL Apex stack. "
    "Respond directly, accurately, conversationally. "
    "Do not reason at length. Do not show work. "
    "Output the answer only."
)


@dataclass
class System1:
    model: str = DEFAULT_SYS1_MODEL
    system_prompt: str = DEFAULT_SYS1_SYSTEM_PROMPT
    client: Optional[object] = None
    timeout_s: float = 30.0
    options: Optional[dict] = None

    def _client(self):
        if self.client is not None:
            return self.client
        from .ollama_client import OllamaClient
        self.client = OllamaClient()
        return self.client

    def invoke(self, query: str) -> str:
        opts = {"temperature": 0.7, "num_predict": 512}
        if self.options:
            opts.update(self.options)
        try:
            return self._client().generate(
                self.model, query,
                system=self.system_prompt,
                options=opts, timeout=self.timeout_s,
            )
        except Exception as exc:
            return f"[System 1 error: {exc}]"
