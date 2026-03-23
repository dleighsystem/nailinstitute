"""Fix namespace-package shadowing when pytest runs from the workspace root."""
from __future__ import annotations
import importlib, sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
_pkg_name = Path(__file__).resolve().parent.parent.name
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _pkg_name in sys.modules:
    _mod = sys.modules[_pkg_name]
    if getattr(_mod, "__file__", None) is None:
        del sys.modules[_pkg_name]
        importlib.import_module(_pkg_name)
