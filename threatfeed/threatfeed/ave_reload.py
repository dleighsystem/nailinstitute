"""AVE database hot-reloader.

The ``ave-database/`` directory is the canonical source of attack-pattern
cards. At runtime, downstream components (shield/, diagnostic/, monitor/)
keep an in-memory snapshot. This module:

  1. Loads the snapshot from disk.
  2. Watches the directory's mtime / index hash.
  3. Reloads atomically when content changes (e.g. after an Advisory of
     ``kind=technique`` lands and someone runs ``ave-db merge``).
  4. Optionally listens for ``advisory_channel`` events of kind
     ``MODEL_RECALL`` / ``TECHNIQUE`` and triggers a reload immediately.

The snapshot is intentionally a plain ``dict`` (not a class) so consumers
can swap it under their feet without holding stale references.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .advisory import Advisory, AdvisoryKind


@dataclass
class AveSnapshot:
    """An immutable view of the ave-database at one instant."""
    schema_version: str
    generated_at: str
    total_cards: int
    cards: list[dict] = field(default_factory=list)
    severity_index: dict = field(default_factory=dict)
    content_hash: str = ""
    loaded_at: int = 0

    # Convenience accessors
    def by_id(self, ave_id: str) -> dict | None:
        for c in self.cards:
            if c.get("ave_id") == ave_id:
                return c
        return None

    def by_severity(self, level: str) -> list[dict]:
        return [c for c in self.cards if c.get("severity") == level]

    def categories(self) -> set[str]:
        return {c.get("category") for c in self.cards if c.get("category")}


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text())


def _hash_content(index: Any, severity_index: Any) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(index, sort_keys=True).encode("utf-8"))
    h.update(b"\n")
    h.update(json.dumps(severity_index, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:16]


def load_snapshot(db_dir: Path) -> AveSnapshot:
    """Load the ave-database synchronously."""
    db_dir = Path(db_dir)
    index_path = db_dir / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"missing ave-database/index.json at {db_dir}")
    index = _read_json(index_path)

    severity_path = db_dir / "severity_index.json"
    severity_index = _read_json(severity_path) if severity_path.exists() else {}

    return AveSnapshot(
        schema_version=str(index.get("schema_version", "0")),
        generated_at=str(index.get("generated_at", "")),
        total_cards=int(index.get("total_cards", len(index.get("cards", [])))),
        cards=list(index.get("cards", [])),
        severity_index=severity_index,
        content_hash=_hash_content(index, severity_index),
        loaded_at=int(time.time()),
    )


# ── reloader ─────────────────────────────────────────────────────────
class AveReloader:
    """Holds a current snapshot, swaps it out atomically when disk changes
    or an advisory triggers a refresh."""

    # Advisory kinds that justify a reload.
    RELOAD_KINDS = {AdvisoryKind.TECHNIQUE, AdvisoryKind.MODEL_RECALL,
                    AdvisoryKind.CVE}

    def __init__(self, db_dir: Path | str,
                 *, on_reload: Callable[[AveSnapshot], None] | None = None
                 ) -> None:
        self.db_dir = Path(db_dir)
        self._snapshot = load_snapshot(self.db_dir)
        self._on_reload = on_reload
        self._lock = threading.Lock()

    @property
    def snapshot(self) -> AveSnapshot:
        # Reads are lock-free — assignment to self._snapshot is atomic.
        return self._snapshot

    # ── manual / disk-driven ─────────────────────────────────────
    def reload(self, *, force: bool = False) -> bool:
        """Reload the snapshot. Returns True if it actually changed."""
        with self._lock:
            new = load_snapshot(self.db_dir)
            if not force and new.content_hash == self._snapshot.content_hash:
                return False
            self._snapshot = new
            if self._on_reload:
                try:
                    self._on_reload(new)
                except Exception:  # noqa: BLE001
                    pass
            return True

    # ── advisory-driven ──────────────────────────────────────────
    def react_to_advisory(self, adv: Advisory) -> bool:
        """Subscriber callback for ``Watcher.on_advisory``. Reloads if the
        advisory kind is one that affects ave-database contents."""
        if adv.kind not in self.RELOAD_KINDS:
            return False
        return self.reload()
