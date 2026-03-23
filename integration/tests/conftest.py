"""Fix namespace-package shadowing when pytest runs from the workspace root.

When pytest is invoked from the monorepo root, bare project directories
(e.g. ``ave/``, ``canary/``, ``arena/``, ``ctf/``, ``integration/``) that
lack a top-level ``__init__.py`` are discovered as namespace packages
before the editable-installed packages.  This conftest ensures each
sub-project directory is on ``sys.path`` so the real ``__init__.py``
inside each is found.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_workspace = Path(__file__).resolve().parent.parent.parent
_subprojects = ["ave", "canary", "arena", "ctf", "integration", "rmap", "threatfeed"]

for _name in _subprojects:
    _proj = str(_workspace / _name)
    if _proj not in sys.path:
        sys.path.insert(0, _proj)

# Purge any namespace-package stubs already cached
for _name in list(sys.modules):
    _mod = sys.modules.get(_name)
    if _mod is not None and getattr(_mod, "__file__", None) is None:
        _parts = _name.split(".")
        if _parts[0] in _subprojects:
            del sys.modules[_name]
