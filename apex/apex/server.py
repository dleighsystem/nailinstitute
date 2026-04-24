"""Ollama-compatible HTTP facade for ApexBrain.

This is the strategic seam: every Ollama client on the planet
(TSACEV, OpenWebUI, LangChain ChatOllama, Continue.dev, Cursor,
LobeChat, AnythingLLM) automatically inherits NAIL's full safety
surface — shield, router, sys1/sys2, fleet telemetry — by pointing
its ``OLLAMA_BASE_URL`` at us instead of the raw Ollama daemon.

Endpoints implemented:

    GET  /api/tags        — list of "models" (the apex brain itself)
    POST /api/generate    — Ollama generate-style request
    POST /api/chat        — Ollama chat-style request
    GET  /api/version     — version stub
    GET  /healthz         — liveness

The "model name" on the wire is configurable; default
``apex-matrix-swarm`` mirrors the apex_matrix adapter convention so
downstream tools that expect that exact tag continue to work.

We deliberately reply non-streaming with ``"done": true`` for
both endpoints. Real streaming can land in M11 once we have the
perplexity-trigger path; until then a single-shot reply is the
contract every Ollama client knows how to consume.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from .brain import ApexBrain, ApexResponse

try:  # pragma: no cover - import guard
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    JSONResponse = None  # type: ignore[assignment,misc]
    _HAS_FASTAPI = False


DEFAULT_MODEL_NAME = "apex-matrix-swarm"
DEFAULT_PORT = 11435  # mirrors apex_matrix tsacev_adapter convention


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _model_tag_payload(model_name: str) -> dict[str, Any]:
    """Shape required by Ollama clients that probe /api/tags at boot."""
    return {
        "models": [
            {
                "name": model_name,
                "model": model_name,
                "modified_at": _iso_now(),
                "size": 0,
                "digest": "apex-brain-virtual",
                "details": {
                    "format": "virtual",
                    "family": "apex",
                    "families": ["apex", "nail"],
                    "parameter_size": "dual-system",
                    "quantization_level": "n/a",
                },
            }
        ]
    }


def _generate_payload(model_name: str, resp: ApexResponse) -> dict[str, Any]:
    """Ollama /api/generate response shape."""
    eval_count = max(1, len(resp.answer.split()))
    eval_duration_ns = int(resp.duration_ms * 1_000_000)
    return {
        "model": model_name,
        "created_at": _iso_now(),
        "response": resp.answer,
        "done": True,
        "done_reason": "stop",
        # Optional metrics Ollama clients sometimes parse:
        "total_duration": eval_duration_ns,
        "load_duration": 0,
        "prompt_eval_count": max(1, len(resp.query.split())),
        "prompt_eval_duration": int(resp.routed_in_ms * 1_000_000),
        "eval_count": eval_count,
        "eval_duration": eval_duration_ns,
        # Apex-specific extension fields (ignored by vanilla clients):
        "apex": resp.to_dict(),
    }


def _chat_payload(model_name: str, resp: ApexResponse) -> dict[str, Any]:
    """Ollama /api/chat response shape."""
    base = _generate_payload(model_name, resp)
    base.pop("response", None)
    base["message"] = {"role": "assistant", "content": resp.answer}
    return base


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    """Pick the last user-role message. Strict: ignores system/assistant."""
    if not messages:
        return ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                return c
    return ""


# ── Public API: build the FastAPI app ─────────────────────────────
def build_app(brain: Optional[ApexBrain] = None,
              model_name: str = DEFAULT_MODEL_NAME):
    """Build a FastAPI app exposing ``brain`` over the Ollama protocol.

    ``brain`` defaults to a fresh ``ApexBrain()`` (cosine router, default
    sys1/sys2, shield auto-detected). Pass an explicit instance for
    tests or custom wiring.

    Importing FastAPI is deferred so this module loads in environments
    that haven't installed the ``server`` extra.
    """
    if not _HAS_FASTAPI:
        raise RuntimeError(
            "apex.server requires fastapi + uvicorn. Install with: "
            "pip install 'nail-apex[server]'"
        )

    if brain is None:
        brain = ApexBrain()

    app = FastAPI(title="NAIL Apex (Ollama-compatible facade)",
                  version="0.2.0")

    # Stash for introspection / tests.
    app.state.brain = brain
    app.state.model_name = model_name

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "model": model_name,
                "agent_id": brain.agent_id}

    @app.get("/api/version")
    async def version() -> dict[str, Any]:
        return {"version": "apex-0.2.0"}

    @app.get("/api/tags")
    async def tags() -> dict[str, Any]:
        return _model_tag_payload(model_name)

    @app.post("/api/generate")
    async def generate(request: Request):  # type: ignore[valid-type]
        body = await request.json()
        prompt = body.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            return JSONResponse(
                status_code=400,
                content={"error": "prompt must be a non-empty string"},
            )
        resp = brain.process(prompt)
        return JSONResponse(_generate_payload(model_name, resp))

    @app.post("/api/chat")
    async def chat(request: Request):  # type: ignore[valid-type]
        body = await request.json()
        messages = body.get("messages", [])
        if not isinstance(messages, list) or not messages:
            return JSONResponse(
                status_code=400,
                content={"error": "messages must be a non-empty list"},
            )
        prompt = _last_user_message(messages)
        if not prompt.strip():
            return JSONResponse(
                status_code=400,
                content={"error": "no user message content found"},
            )
        resp = brain.process(prompt)
        return JSONResponse(_chat_payload(model_name, resp))

    return app


def serve(host: str = "0.0.0.0", port: int = DEFAULT_PORT,
          *, brain: Optional[ApexBrain] = None,
          model_name: str = DEFAULT_MODEL_NAME) -> None:
    """Block-run the facade with uvicorn."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "apex.server.serve requires uvicorn. Install with: "
            "pip install 'nail-apex[server]'"
        ) from exc
    app = build_app(brain=brain, model_name=model_name)
    uvicorn.run(app, host=host, port=port, log_level="info")
