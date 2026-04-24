"""Tests for apex.system2 — TTC parsing + invoke()."""
from __future__ import annotations

import pytest

from apex.system2 import System2, TTCResult, extract


# ── extract() ──────────────────────────────────────────────────────
def test_extract_well_formed():
    raw = "<thought>step one</thought><answer>42</answer>"
    out = extract(raw)
    assert out.thought == "step one"
    assert out.answer == "42"
    assert out.had_thought_block and out.had_answer_block


def test_extract_missing_answer_uses_tail():
    raw = "<thought>thinking...</thought>\nFinal: 42"
    out = extract(raw)
    assert out.thought == "thinking..."
    assert "42" in out.answer
    assert out.had_thought_block and not out.had_answer_block


def test_extract_missing_thought_whole_text_is_answer():
    raw = "Just a direct answer."
    out = extract(raw)
    assert out.thought == ""
    assert out.answer == "Just a direct answer."
    assert not out.had_thought_block and not out.had_answer_block


def test_extract_only_answer_block():
    raw = "<answer>only</answer>"
    out = extract(raw)
    assert out.answer == "only"
    assert out.had_answer_block and not out.had_thought_block


def test_extract_case_insensitive():
    raw = "<THOUGHT>up</THOUGHT><Answer>down</Answer>"
    out = extract(raw)
    assert out.thought == "up"
    assert out.answer == "down"


def test_extract_empty_string():
    out = extract("")
    assert out.answer == ""
    assert out.thought == ""


def test_extract_multiline_blocks():
    raw = "<thought>line1\nline2\nline3</thought><answer>OK</answer>"
    out = extract(raw)
    assert "line1" in out.thought and "line3" in out.thought


# ── System2.invoke() ───────────────────────────────────────────────
class StubClient:
    def __init__(self, response="", raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc
        self.calls = []

    def generate(self, model, prompt, **kw):
        self.calls.append((model, prompt, kw))
        if self.raise_exc:
            raise self.raise_exc
        return self.response


def test_system2_invoke_well_formed():
    raw = "<thought>think</thought><answer>OK</answer>"
    s2 = System2(client=StubClient(response=raw))
    out = s2.invoke("q")
    assert isinstance(out, TTCResult)
    assert out.answer == "OK"
    assert out.thought == "think"
    assert out.error is None


def test_system2_seed_thought_prepends_open_tag():
    # Model returns content WITHOUT <thought> open tag, just the inner text
    # then the close + answer.
    raw = "thinking inside</thought><answer>final</answer>"
    s2 = System2(client=StubClient(response=raw), seed_thought=True)
    out = s2.invoke("q")
    assert out.had_thought_block
    assert "thinking inside" in out.thought
    assert out.answer == "final"


def test_system2_error_path_returns_error_result():
    from apex.ollama_client import OllamaError
    s2 = System2(client=StubClient(raise_exc=OllamaError("timeout")))
    out = s2.invoke("q")
    assert out.error is not None
    assert "System 2 error" in out.answer
