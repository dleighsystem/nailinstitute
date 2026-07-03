"""Tests for selective (lazy) tool loading in the NAIL agent harness."""

import re

import pytest

from nail_harness.agent_client import (
    AgentOptions,
    NailAgentClient,
    Tool,
    default_tool_embed_fn,
    lexical_tool_retriever,
    make_semantic_tool_retriever,
)


# Deterministic, offline stand-in for a sentence embedding: projects text onto a
# few concept axes via a synonym map, so "client" and "crm/customer" land on the
# same axis (which the lexical tier, matching surface tokens, cannot see).
_CONCEPTS = ["customer", "calendar", "billing", "shell", "approval"]
_SYNONYMS = {
    "client": "customer", "customer": "customer", "crm": "customer", "account": "customer",
    "meeting": "calendar", "schedule": "calendar", "calendar": "calendar", "book": "calendar",
    "invoice": "billing", "bill": "billing", "billing": "billing", "payment": "billing",
    "shell": "shell", "command": "shell", "terminal": "shell",
    "approval": "approval", "approve": "approval", "privileged": "approval",
}


def fake_embed(text):
    vec = [0.0] * len(_CONCEPTS)
    for word in re.findall(r"[a-z]+", text.lower()):
        concept = _SYNONYMS.get(word)
        if concept:
            vec[_CONCEPTS.index(concept)] += 1.0
    return tuple(vec)


def _tools():
    return [
        Tool(name="crm_search", description="Search CRM customer records by name or email."),
        Tool(name="calendar_book", description="Book a meeting on the shared calendar."),
        Tool(name="invoice_create", description="Create and send a billing invoice to a customer."),
        Tool(name="shell_exec", description="Run a shell command on the host."),
        Tool(name="approval_gate", description="Require human approval before privileged actions."),
    ]


def _client(**opts):
    return NailAgentClient(AgentOptions(tools=_tools(), **opts))


def test_default_all_loads_every_tool():
    # Default mode is unchanged: the whole registry is described each turn.
    client = _client()
    loaded = client._select_tools("book a meeting")
    assert {t.name for t in loaded} == {t.name for t in _tools()}


def test_retrieval_loads_only_relevant():
    client = _client(tool_selection="retrieval")
    loaded = {t.name for t in client._select_tools("please search the CRM for a customer")}
    assert "crm_search" in loaded
    assert "shell_exec" not in loaded
    assert "calendar_book" not in loaded


def test_always_load_tools_never_starved():
    client = _client(tool_selection="retrieval", always_load_tools=("approval_gate",))
    loaded = {t.name for t in client._select_tools("run a shell command")}
    assert "approval_gate" in loaded   # mandatory tool loaded even though unmatched
    assert "shell_exec" in loaded      # matched by the prompt


def test_max_tools_caps_retrieved_excluding_always():
    client = _client(
        tool_selection="retrieval",
        max_tools=1,
        always_load_tools=("approval_gate",),
    )
    names = [t.name for t in client._select_tools("search CRM for a customer and create an invoice")]
    assert "approval_gate" in names
    retrieved = [n for n in names if n != "approval_gate"]
    assert len(retrieved) == 1


def test_lexical_retriever_scores_and_is_deterministic():
    tools = _tools()
    picks = lexical_tool_retriever("search the crm customer records", tools)
    assert picks[0].name == "crm_search"  # highest overlap ranked first
    again = lexical_tool_retriever("search the crm customer records", tools)
    assert [t.name for t in picks] == [t.name for t in again]


def test_retrieval_shrinks_system_prompt():
    client = _client(tool_selection="retrieval")
    full = client._build_system_prompt(list(client._tool_registry.values()))
    subset = client._build_system_prompt(client._select_tools("book a calendar meeting"))
    assert len(subset) < len(full)


def test_only_registered_tools_can_surface():
    # The retriever can only ever pick from the registered set (no surfacing of
    # unknown tools — cf. AVE-2026-0045).
    client = _client(tool_selection="retrieval")
    loaded = client._select_tools("do something with a nonexistent_magic_tool")
    assert {t.name for t in loaded} <= set(client._tool_registry)


def test_run_records_loaded_subset_attribute_default_empty():
    client = _client(tool_selection="retrieval")
    assert client.last_loaded_tools == []


def test_semantic_retriever_resolves_synonyms_lexical_misses():
    tools = _tools()
    prompt = "look up a client"
    # Lexical tier: "client" shares no surface token with crm_search's text.
    lexical = {t.name for t in lexical_tool_retriever(prompt, tools)}
    assert "crm_search" not in lexical
    # Semantic tier: "client" and "crm/customer" share a concept axis.
    semantic = {t.name for t in make_semantic_tool_retriever(fake_embed)(prompt, tools)}
    assert "crm_search" in semantic
    assert "shell_exec" not in semantic


def test_semantic_retriever_threshold_and_cap():
    tools = _tools()
    retriever = make_semantic_tool_retriever(fake_embed, threshold=0.99, max_tools=1)
    picks = retriever("schedule a meeting on the calendar", tools)
    assert [t.name for t in picks] == ["calendar_book"]


def test_semantic_retriever_wires_into_agent_options():
    client = _client(
        tool_selection="retrieval",
        tool_retriever=make_semantic_tool_retriever(fake_embed),
        always_load_tools=("approval_gate",),
    )
    loaded = {t.name for t in client._select_tools("look up a client")}
    assert "crm_search" in loaded        # semantic match
    assert "approval_gate" in loaded     # always-loaded safety tool


def test_default_tool_embed_fn_is_optional():
    import importlib.util
    if importlib.util.find_spec("sentence_transformers") is None:
        with pytest.raises(RuntimeError):
            default_tool_embed_fn()
    else:  # pragma: no cover - environment-dependent
        assert callable(default_tool_embed_fn())
