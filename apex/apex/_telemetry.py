"""Lazy, fail-safe telemetry shim. Mirrors the other NAIL packages so
apex/ remains installable without fleet/. See foresight/_telemetry.py for
the reference implementation.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

_AGENT_ID_ENV = "NAIL_AGENT_ID"
_DISABLE_ENV = "NAIL_TELEMETRY_DISABLED"

_emit_fn = None
_attempted = False


def _try_load():
    global _emit_fn, _attempted
    if _attempted:
        return
    _attempted = True
    if os.environ.get(_DISABLE_ENV):
        return

    try:
        from fleet import safe_emit as _se
        _emit_fn = _se
        return
    except ImportError:
        pass

    here = Path(__file__).resolve()
    for parent in here.parents[:4]:
        cand = parent / "fleet"
        if (cand / "fleet" / "__init__.py").exists():
            sys.path.insert(0, str(cand))
            try:
                from fleet import safe_emit as _se
                _emit_fn = _se
                return
            except ImportError:
                continue


def default_agent_id(fallback: str) -> str:
    return os.environ.get(_AGENT_ID_ENV, fallback)


def telemetry_emit(kind: str, *, agent_id: str, severity: str = "info",
                   attrs: Optional[dict] = None) -> None:
    """Emit a fleet event if fleet is importable. Never raises."""
    _try_load()
    if _emit_fn is None:
        return
    try:
        _emit_fn(kind, agent_id=agent_id, severity=severity,
                 attrs=attrs or {})
    except Exception:
        pass


# Test-only reset.
def _reset_for_tests() -> None:  # pragma: no cover
    global _emit_fn, _attempted
    _emit_fn = None
    _attempted = False
