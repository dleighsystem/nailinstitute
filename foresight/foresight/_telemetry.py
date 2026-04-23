"""Lazy, fail-safe telemetry shim. Packages that want to emit events into
fleet/ import this module instead of fleet/ directly so they remain
installable without the fleet dependency.

Usage:

    from ._telemetry import telemetry_emit
    telemetry_emit(\"foresight.verdict\", agent_id=\"refund-bot-1\",
                   attrs={\"verdict\": \"hold\", \"risk\": 0.65})
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

_AGENT_ID_ENV = "NAIL_AGENT_ID"
_DISABLE_ENV = "NAIL_TELEMETRY_DISABLED"

_emit_fn = None  # cached
_attempted = False


def _try_load():
    """Try to import fleet.safe_emit. Falls back through three locations:
    (1) installed package, (2) sibling fleet/ next to this package."""
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

    # Walk up looking for a sibling fleet/ directory
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
