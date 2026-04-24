"""Lazy bridge to sibling NAIL packages (shield, foresight).

Mirrors the _telemetry pattern: try installed package, then walk up
looking for a sibling source tree, then give up silently.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional


_shield_mod = None
_foresight_mod = None
_shield_attempted = False
_foresight_attempted = False


def _add_sibling(name: str) -> None:
    here = Path(__file__).resolve()
    for parent in here.parents[:4]:
        cand = parent / name
        if (cand / name / "__init__.py").exists():
            sys.path.insert(0, str(cand))
            return


def shield():
    """Returns the shield module or None."""
    global _shield_mod, _shield_attempted
    if _shield_attempted:
        return _shield_mod
    _shield_attempted = True
    try:
        import shield as _s
        _shield_mod = _s
        return _s
    except ImportError:
        pass
    _add_sibling("shield")
    try:
        import shield as _s
        _shield_mod = _s
        return _s
    except ImportError:
        return None


def foresight():
    """Returns the foresight module or None."""
    global _foresight_mod, _foresight_attempted
    if _foresight_attempted:
        return _foresight_mod
    _foresight_attempted = True
    try:
        import foresight as _f
        _foresight_mod = _f
        return _f
    except ImportError:
        pass
    _add_sibling("foresight")
    try:
        import foresight as _f
        _foresight_mod = _f
        return _f
    except ImportError:
        return None


# Test reset.
def _reset_for_tests() -> None:  # pragma: no cover
    global _shield_mod, _foresight_mod, _shield_attempted, _foresight_attempted
    _shield_mod = None
    _foresight_mod = None
    _shield_attempted = False
    _foresight_attempted = False
