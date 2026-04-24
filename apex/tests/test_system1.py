"""Tests for apex.system1."""
from __future__ import annotations

from apex.system1 import System1
from apex.ollama_client import OllamaError


class StubClient:
    def __init__(self, response="hi back", raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc
        self.calls = []

    def generate(self, model, prompt, **kw):
        self.calls.append((model, prompt, kw))
        if self.raise_exc:
            raise self.raise_exc
        return self.response


def test_system1_invoke_returns_text():
    s1 = System1(client=StubClient(response="hi back"))
    assert s1.invoke("hello") == "hi back"


def test_system1_invoke_passes_model_and_prompt():
    client = StubClient(response="ok")
    s1 = System1(model="fake-model:7b", client=client)
    s1.invoke("q?")
    model, prompt, _ = client.calls[0]
    assert model == "fake-model:7b"
    assert "q?" in prompt


def test_system1_invoke_error_path():
    s1 = System1(client=StubClient(raise_exc=OllamaError("down")))
    out = s1.invoke("q")
    assert "System 1 error" in out
