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
from pathlib import Path

_WORKSPACE = str(Path(__file__).resolve().parent)
_PACKAGES = ["ave", "canary", "arena", "ctf", "integration", "threatfeed",
             "rmap", "nail_monitor", "diagnostic", "horizon"]


def pytest_configure(config):
    """Fix namespace collision so editable installs resolve correctly."""
    # 1. Remove workspace root from sys.path
    sys.path[:] = [p for p in sys.path
                   if str(Path(p).resolve()) != _WORKSPACE]

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
