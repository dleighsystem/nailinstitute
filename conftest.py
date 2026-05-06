"""
Root conftest.py — Prevents namespace package collision.

When pytest runs from the workspace root, it adds the CWD to sys.path.
The top-level directories (ave/, canary/, arena/, ctf/, integration/)
shadow the installed editable packages because the default PathFinder
finds them as namespace packages before the editable _EditableFinder
(appended at the end of sys.meta_path) gets a chance.

Fix: remove the workspace root from sys.path AND promote editable
finders to the front of sys.meta_path.
"""

import sys
import importlib
import importlib.util
from pathlib import Path

_WORKSPACE = str(Path(__file__).resolve().parent)
_PACKAGES = ["ave", "canary", "arena", "ctf", "integration", "threatfeed",
             "rmap", "nail_monitor", "diagnostic", "horizon"]
_LOCAL_IMPORT_ROOTS = [
    "arena",
    "ave",
    "horizon",
    "harness-reference/capabilities/text_to_sql/evaluation",
    "harness-reference/tool_use",
    "experiments",
]


def pytest_configure(config):
    """Fix namespace collision so editable installs resolve correctly."""
    # 1. Remove workspace root from sys.path
    sys.path[:] = [p for p in sys.path
                   if str(Path(p).resolve()) != _WORKSPACE]

    # 1b. Add explicit package roots for local projects that are not always
    # installed editable in this workspace.
    for rel in reversed(_LOCAL_IMPORT_ROOTS):
        path = str((Path(_WORKSPACE) / rel).resolve())
        if path not in sys.path:
            sys.path.insert(0, path)

    # 2. Move _EditableFinder instances to the FRONT of sys.meta_path
    #    so they beat the default PathFinder
    editable = [f for f in sys.meta_path
                if type(f).__name__ == "_EditableFinder"
                or (isinstance(f, type) and f.__name__ == "_EditableFinder")]
    others = [f for f in sys.meta_path
              if f not in editable]
    sys.meta_path[:] = editable + others

    # 3. Flush any namespace-package ghosts already loaded
    for pkg in _PACKAGES:
        for key in list(sys.modules):
            if key == pkg or key.startswith(pkg + "."):
                del sys.modules[key]

    # 4. Preload canonical local packages that otherwise get shadowed by
    # same-named workspace directories during importlib-mode collection.
    importlib.invalidate_caches()
    text_sql_utils = (Path(_WORKSPACE) / "harness-reference" / "capabilities"
                      / "text_to_sql" / "evaluation" / "tests" / "utils.py")
    if text_sql_utils.exists():
        spec = importlib.util.spec_from_file_location("utils", text_sql_utils)
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["utils"] = mod
            spec.loader.exec_module(mod)
    def _bind_package(name: str, package_root: Path) -> None:
        package_init = package_root / "__init__.py"
        if not package_init.exists():
            return
        for key in list(sys.modules):
            if key == name or key.startswith(name + "."):
                del sys.modules[key]
        spec = importlib.util.spec_from_file_location(
            name,
            package_init,
            submodule_search_locations=[str(package_root)],
        )
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)

    _bind_package("nail_harness", Path(_WORKSPACE) / "nail_harness")
    _bind_package("arena", Path(_WORKSPACE) / "arena" / "arena")
    _bind_package("horizon", Path(_WORKSPACE) / "horizon" / "horizon")
