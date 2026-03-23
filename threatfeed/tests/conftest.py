"""Fix namespace-package shadowing when pytest runs from the workspace root."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

if "threatfeed" in sys.modules:
    _mod = sys.modules["threatfeed"]
    if getattr(_mod, "__file__", None) is None:
        del sys.modules["threatfeed"]
        importlib.import_module("threatfeed")
