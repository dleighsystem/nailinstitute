"""
Conftest for threatfeed tests — fix namespace package collision.

When tests import ave, canary, arena, ctf, or integration from within
the workspace, Python's default PathFinder finds the outer directories
(e.g. ave/) as namespace packages before the editable _EditableFinder
gets a chance. We fix this by removing the workspace root from sys.path
and promoting editable finders to the front of sys.meta_path.
"""

import sys
from pathlib import Path

_WORKSPACE = str(Path(__file__).resolve().parent.parent)
_PACKAGES = ["ave", "canary", "arena", "ctf", "integration", "threatfeed",
             "rmap", "nail_monitor", "diagnostic", "horizon"]


def pytest_configure(config):
    """Fix namespace collision so editable installs resolve correctly."""
    # 1. Remove workspace root from sys.path
    sys.path[:] = [p for p in sys.path
                   if str(Path(p).resolve()) != _WORKSPACE]

    # 2. Move _EditableFinder instances to the FRONT of sys.meta_path
    editable = [f for f in sys.meta_path
                if type(f).__name__ == "_EditableFinder"
                or (isinstance(f, type) and f.__name__ == "_EditableFinder")]
    others = [f for f in sys.meta_path if f not in editable]
    sys.meta_path[:] = editable + others

    # 3. Flush any namespace-package ghosts already loaded
    for pkg in _PACKAGES:
        for key in list(sys.modules):
            if key == pkg or key.startswith(pkg + "."):
                del sys.modules[key]
