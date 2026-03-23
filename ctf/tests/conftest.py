"""Ensure ctf package resolves to ctf/ctf/ rather than the project root."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

# When pytest is invoked from the workspace root the bare ``ctf/`` directory
# (which has no __init__.py) shadows the installed *ctf* package.  Force the
# correct resolution by inserting the project directory at the front of
# sys.path so ``ctf/ctf/__init__.py`` is found first.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# If ctf was already loaded as a namespace package, reload it
if "ctf" in sys.modules:
    _mod = sys.modules["ctf"]
    if getattr(_mod, "__file__", None) is None:
        del sys.modules["ctf"]
        importlib.import_module("ctf")
