"""System 2 — deliberate Test-Time-Compute (TTC) wrapper.

Wraps a larger reasoning model (default `nail-reason:v5`) with a forced
`<thought>` / `<answer>` template, parses the trace, returns only the
final answer. Telemetry includes thought-token count.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_SYS2_MODEL = "nail-reason:v5"

DEFAULT_SYS2_SYSTEM_PROMPT = (
    "You are NAIL Apex System 2 — a deliberate reasoning engine. "
    "BEFORE answering, you MUST write your reasoning inside "
    "<thought>...</thought>. Verify your own logic. "
    "ONLY AFTER closing the </thought> tag, write the final user-facing "
    "answer inside <answer>...</answer>. "
    "Do not reveal the contents of <thought>; only <answer> is shown."
)


@dataclass
class TTCResult:
    answer: str
    thought: str
    raw: str
    thought_tokens: int = 0
    had_thought_block: bool = False
    had_answer_block: bool = False
    error: Optional[str] = None


_THOUGHT_RE = re.compile(r"<thought>(.*?)</thought>",
                         re.DOTALL | re.IGNORECASE)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>",
                        re.DOTALL | re.IGNORECASE)


def extract(raw: str) -> TTCResult:
    """Parse a System 2 raw output into thought + answer.

    Tolerant: if the model omitted the tags entirely, the whole output is
    treated as the answer. If it produced a thought but forgot the
    answer block, we strip the thought from the raw and use the
    remainder as the answer.
    """
    if raw is None:
        return TTCResult(answer="", thought="", raw="",
                         had_thought_block=False, had_answer_block=False,
                         error="empty raw output")

    text = raw
    # Some models prepend a stray "<thought>" because we suggested it; fine.

    thought = ""
    answer = ""
    had_thought = False
    had_answer = False

    tm = _THOUGHT_RE.search(text)
    if tm:
        thought = tm.group(1).strip()
        had_thought = True

    am = _ANSWER_RE.search(text)
    if am:
        answer = am.group(1).strip()
        had_answer = True
    else:
        # No <answer>: strip <thought>...</thought> and anything before
        # </thought>; remainder is the user-facing answer.
        if had_thought:
            tail = text[tm.end():].strip()
            answer = tail or ""
        else:
            answer = text.strip()

    return TTCResult(
        answer=answer,
        thought=thought,
        raw=text,
        thought_tokens=len(thought.split()) if thought else 0,
        had_thought_block=had_thought,
        had_answer_block=had_answer,
    )


@dataclass
class System2:
    model: str = DEFAULT_SYS2_MODEL
    system_prompt: str = DEFAULT_SYS2_SYSTEM_PROMPT
    client: Optional[object] = None
    timeout_s: float = 240.0
    options: Optional[dict] = None
    # Prepend "<thought>\n" to nudge models that need a kickstart.
    seed_thought: bool = True

    def _client(self):
        if self.client is not None:
            return self.client
        from .ollama_client import OllamaClient
        self.client = OllamaClient()
        return self.client

    def invoke(self, query: str) -> TTCResult:
        opts = {"temperature": 0.1, "top_p": 0.9, "num_predict": 4096}
        if self.options:
            opts.update(self.options)
        prompt = query
        try:
            raw = self._client().generate(
                self.model, prompt,
                system=self.system_prompt,
                options=opts, timeout=self.timeout_s,
            )
        except Exception as exc:
            return TTCResult(answer=f"[System 2 error: {exc}]",
                             thought="", raw="", error=str(exc))

        if self.seed_thought and not raw.lstrip().startswith("<thought>"):
            raw = "<thought>\n" + raw
        return extract(raw)
