"""@requires_rehearsal — gates a real tool fn on a sandbox verdict.

Behaviour by outcome:

    ALLOW  → call the real impl, return its result
    DENY   → raise RehearsalDenied (the real impl is NEVER called)
    HOLD   → raise RehearsalHeld unless the caller passed
             ``__nail_confirm__=True`` in kwargs. The orchestrator (or a
             human reviewer) is expected to set this *only after* explicit
             approval of the held call.

The receipt from each rehearsal is appended to the sandbox's recorder, so
auditors can replay the exact same args+world later and get a stable
verdict (assuming the shadow + policy are pure).
"""
from __future__ import annotations

import contextvars
from collections.abc import Callable
from functools import wraps

from .recorder import Recorder, ToolCall
from .sandbox import Sandbox
from .verdict import RehearsalDenied, RehearsalHeld, Verdict


# Per-call optional world override (e.g. set by the agent loop).
_world_var: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_rehearsal_world", default={}
)


def set_world(world: dict) -> None:
    """Install the per-call world snapshot (account balances, etc.)."""
    _world_var.set(dict(world or {}))


def current_world() -> dict:
    return dict(_world_var.get())


def requires_rehearsal(tool: str, *, sandbox: Sandbox,
                       recorder: Recorder | None = None,
                       strict: bool = True) -> Callable[[Callable], Callable]:
    """Decorator factory.

    ``recorder`` defaults to the sandbox's process-wide ``Recorder()``; pass
    a dedicated one if you want per-session ledgers.
    """
    # NB: explicit ``is None`` — Recorder defines __len__, so empty recorders
    # are falsy and ``recorder or default()`` would silently swap them out.
    rec = _default_recorder() if recorder is None else recorder

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            confirm = kwargs.pop("__nail_confirm__", False)
            world = current_world()
            receipt = sandbox.rehearse(tool, args=dict(kwargs),
                                       world=world, strict=strict)
            rec.record(ToolCall(
                tool=tool, args=dict(kwargs),
                shadow_result=receipt.shadow_result,
                verdict=receipt.verdict,
                duration_ms=receipt.duration_ms,
            ))

            if receipt.verdict.denied:
                raise RehearsalDenied(tool, receipt.verdict)
            if receipt.verdict.held and not confirm:
                raise RehearsalHeld(tool, receipt.verdict)

            # ALLOW or HOLD-with-confirm: invoke the real impl.
            return fn(*args, **kwargs)

        wrapper.__nail_rehearsal_tool__ = tool  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ── module-level recorder, used when caller doesn't supply one ───────
_DEFAULT_RECORDER: Recorder | None = None


def _default_recorder() -> Recorder:
    global _DEFAULT_RECORDER
    if _DEFAULT_RECORDER is None:
        _DEFAULT_RECORDER = Recorder()
    return _DEFAULT_RECORDER


def get_default_recorder() -> Recorder:
    return _default_recorder()
