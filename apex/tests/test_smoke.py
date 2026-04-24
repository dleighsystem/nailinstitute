"""Smoke tests for the public API and CLI parser."""
from __future__ import annotations


def test_public_exports():
    import apex
    assert apex.__version__ == "0.3.0"
    for name in ("ApexBrain", "ApexResponse",
                 "CosineRouter", "GuardRouter", "DomainRouter",
                 "System1", "System2", "TTCResult", "extract",
                 "OllamaClient", "OllamaError",
                 "SYSTEM_1", "SYSTEM_2"):
        assert hasattr(apex, name), f"apex missing public export: {name}"


def test_cli_parser_builds():
    from apex.cli import build_parser
    p = build_parser()
    args = p.parse_args(["ask", "hello"])
    assert args.cmd == "ask"
    assert args.query == "hello"


def test_cli_route_subcommand():
    from apex.cli import build_parser
    p = build_parser()
    args = p.parse_args(["route", "solve"])
    assert args.cmd == "route"


def test_ollama_client_default_base_url(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    # re-import to re-evaluate module-level default
    import importlib
    import apex.ollama_client as oc
    importlib.reload(oc)
    assert oc.DEFAULT_BASE_URL.startswith("http")
