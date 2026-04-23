"""Append-only sha256 hash chain.

Compatible with the AVE evidence chain — every shielded input gets a chain
entry that ties:

  * the canonical text hash (so the agent's later actions can be traced
    back to the exact bytes that triggered them)
  * the source provenance string
  * the previous chain head (so tampering with any past entry breaks the
    whole chain).

The default chain lives at ``./.nail/shield_chain.jsonl`` (one JSON object
per line, append-only). Production deployments should configure a path
inside their AVE store.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


@dataclass(frozen=True)
class ChainEntry:
    seq: int
    timestamp: str
    source: str
    canonical_sha256: str
    prev_hash: str
    entry_hash: str

    def to_dict(self) -> dict:
        return asdict(self)


class HashChain:
    """Thread-safe append-only file-backed sha256 chain."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._head: str = GENESIS
        self._seq: int = 0
        self._load_tail()

    # ── public ────────────────────────────────────────────────────
    def append(self, *, source: str, canonical_sha256: str) -> ChainEntry:
        with self._lock:
            seq = self._seq + 1
            ts = datetime.now(timezone.utc).isoformat()
            entry_hash = self._compute(seq, ts, source, canonical_sha256, self._head)
            entry = ChainEntry(
                seq=seq, timestamp=ts, source=source,
                canonical_sha256=canonical_sha256,
                prev_hash=self._head, entry_hash=entry_hash,
            )
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
            self._head = entry_hash
            self._seq = seq
            return entry

    @property
    def head(self) -> str:
        return self._head

    @property
    def length(self) -> int:
        return self._seq

    def verify(self) -> tuple[bool, int]:
        """Re-read the chain end-to-end. Returns (ok, n_entries_verified)."""
        prev = GENESIS
        n = 0
        if not self.path.exists():
            return True, 0
        with self.path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                expected = self._compute(
                    d["seq"], d["timestamp"], d["source"],
                    d["canonical_sha256"], d["prev_hash"],
                )
                if d["prev_hash"] != prev or d["entry_hash"] != expected:
                    return False, n
                prev = d["entry_hash"]
                n += 1
        return True, n

    # ── internals ─────────────────────────────────────────────────
    @staticmethod
    def _compute(seq: int, ts: str, source: str, csha: str, prev: str) -> str:
        payload = f"{seq}\x00{ts}\x00{source}\x00{csha}\x00{prev}".encode()
        return hashlib.sha256(payload).hexdigest()

    def _load_tail(self) -> None:
        if not self.path.exists():
            return
        last_line = ""
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_line = line.strip()
        if last_line:
            d = json.loads(last_line)
            self._head = d["entry_hash"]
            self._seq = d["seq"]


# ── module-level default chain ────────────────────────────────────
_DEFAULT_CHAIN: HashChain | None = None
_DEFAULT_LOCK = threading.Lock()


def _default_path() -> Path:
    return Path(os.environ.get(
        "NAIL_SHIELD_CHAIN",
        Path.home() / ".nail" / "shield_chain.jsonl",
    ))


def append_to_default_chain(*, source: str, canonical_sha256: str) -> ChainEntry:
    global _DEFAULT_CHAIN
    with _DEFAULT_LOCK:
        if _DEFAULT_CHAIN is None:
            _DEFAULT_CHAIN = HashChain(_default_path())
        return _DEFAULT_CHAIN.append(
            source=source, canonical_sha256=canonical_sha256,
        )
