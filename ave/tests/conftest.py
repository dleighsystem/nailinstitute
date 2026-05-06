"""Fix namespace-package shadowing when pytest runs from the workspace root."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_expected_pkg_root = _project_root / "ave"
_pkg_name = Path(__file__).resolve().parent.parent.name
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

sys.meta_path[:] = [
    _finder for _finder in sys.meta_path
    if "__editable___nail_ave" not in getattr(_finder, "__module__", "")
]

for _key in list(sys.modules):
    if _key != __name__ and (_key == _pkg_name or _key.startswith(_pkg_name + ".")):
        del sys.modules[_key]

_spec = importlib.util.spec_from_file_location(
    _pkg_name,
    _expected_pkg_root / "__init__.py",
    submodule_search_locations=[str(_expected_pkg_root)],
)
if _spec is not None and _spec.loader is not None:
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_pkg_name] = _mod
    _spec.loader.exec_module(_mod)

