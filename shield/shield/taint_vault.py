"""TaintVault — provenance-aware memory store with lineage tracking.

Solves Theory F (Memory Laundering): a fact derived from an untrusted source
must inherit that low trust score through any number of summarisation or
derivation layers. The current TaintTracker assigns trust at insertion time
only; if a poisoned fact is summarised by the agent and re-stored as
self-generated, its trust launders from 0.3 → 0.9.

The fix: every fact carries a ``derived_from`` lineage. Trust is always
computed as the minimum trust across the full ancestor tree, never the
insertion-time assignment. Summaries are stored as derived facts that
inherit the worst trust of all their inputs.

Public API
----------
    from shield.taint_vault import TaintVault, TrustLevel

    vault = TaintVault()

    # Store an externally sourced fact (low trust)
    entry = vault.store(
        content="The CEO approved the wire transfer.",
        source_chain_id="u-7f3a",   # ShieldedInput.chain_id
        trust_score=0.2,
    )

    # Agent summarises → inherit parent trust
    summary = vault.derive(
        content="Summary: transfer was approved.",
        parent_ids=[entry.fact_id],
    )
    assert summary.effective_trust == 0.2   # laundering prevented

    # Detect if any fact has inflated trust
    report = vault.detect_laundering(summary.fact_id)
    assert report.laundering_detected
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


# ── Trust levels ─────────────────────────────────────────────────────────────

class TrustLevel(float, Enum):
    """Semantic trust levels (also usable as raw floats)."""
    SYSTEM      = 1.00   # developer / system prompt  — fully trusted
    AGENT_SELF  = 0.90   # agent's own reasoning step — high trust
    VERIFIED    = 0.75   # verified external source (signed, checked)
    UNVERIFIED  = 0.50   # external source, not verified
    UNTRUSTED   = 0.25   # flagged / low-confidence external
    HOSTILE     = 0.05   # known adversarial or injection-scored


LAUNDERING_THRESHOLD = 0.15   # if effective_trust differs from stored by > this, flag it


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TaintEntry:
    fact_id: str                        # sha256-derived unique id
    content: str
    source_chain_id: str | None         # ShieldedInput.chain_id (None = agent-generated)
    stored_trust: float                 # trust score assigned at insertion
    derived_from: list[str]             # parent fact_ids (empty = root fact)
    timestamp: str
    metadata: dict = field(default_factory=dict)

    # computed on demand — not serialised
    _effective_trust: float | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_effective_trust", None)
        return d


@dataclass
class LaunderingReport:
    fact_id: str
    laundering_detected: bool
    stored_trust: float
    effective_trust: float
    inflation: float              # stored_trust - effective_trust (positive = inflated)
    tainted_ancestors: list[str]  # fact_ids that dragged trust down
    explanation: str


# ── Vault ─────────────────────────────────────────────────────────────────────

class TaintVault:
    """Provenance-aware in-memory fact store with optional file persistence.

    Thread-safe. All mutations hold ``_lock``.

    Parameters
    ----------
    path : str | Path | None
        If given, facts are persisted as JSONL at this path (append-only).
        If None, in-memory only.
    """

    def __init__(self, path: str | os.PathLike | None = None):
        self._facts: dict[str, TaintEntry] = {}
        self._lock = threading.Lock()
        self._path: Path | None = Path(path) if path else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    # ── Public API ────────────────────────────────────────────────────

    def store(
        self,
        content: str,
        *,
        source_chain_id: str | None = None,
        trust_score: float = TrustLevel.AGENT_SELF,
        derived_from: list[str] | None = None,
        metadata: dict | None = None,
    ) -> TaintEntry:
        """Store a new fact. Use :meth:`derive` for facts built from others.

        Parameters
        ----------
        content : str
            The fact text.
        source_chain_id : str | None
            The ``ShieldedInput.chain_id`` that introduced this fact.
            None means the agent generated it internally (higher default trust).
        trust_score : float
            Insertion-time trust. The *effective* trust may be lower if
            ancestors are more tainted.
        derived_from : list[str] | None
            Parent fact_ids. If provided, effective_trust is clamped to
            the minimum ancestor trust.
        metadata : dict | None
            Arbitrary tags (e.g. ``{"experiment": "exp30"}``).
        """
        fact_id = self._make_id(content, source_chain_id)
        ts = datetime.now(timezone.utc).isoformat()
        entry = TaintEntry(
            fact_id=fact_id,
            content=content,
            source_chain_id=source_chain_id,
            stored_trust=float(trust_score),
            derived_from=list(derived_from or []),
            timestamp=ts,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._facts[fact_id] = entry
            if self._path:
                self._append(entry)
        return entry

    def derive(
        self,
        content: str,
        parent_ids: list[str],
        *,
        metadata: dict | None = None,
    ) -> TaintEntry:
        """Store a fact derived from one or more existing facts.

        The stored_trust is set to the minimum effective trust of all parents,
        preventing trust laundering through summarisation or re-phrasing.
        """
        if not parent_ids:
            raise ValueError("derive() requires at least one parent_id")
        min_trust = min(self.effective_trust(pid) for pid in parent_ids)
        return self.store(
            content,
            source_chain_id=None,
            trust_score=min_trust,
            derived_from=parent_ids,
            metadata=metadata,
        )

    def effective_trust(self, fact_id: str) -> float:
        """Compute the true trust score by walking the full ancestor tree.

        Returns the minimum trust score found across all ancestors.
        This ensures that trust-laundering through summarisation is impossible:
        a fact derived from an untrusted source is always at most as trusted
        as its least-trusted ancestor.
        """
        with self._lock:
            return self._effective_trust_locked(fact_id, visited=set())

    def lookup(self, fact_id: str) -> TaintEntry | None:
        """Return the TaintEntry for a fact_id, or None if not found."""
        with self._lock:
            return self._facts.get(fact_id)

    def detect_laundering(self, fact_id: str) -> LaunderingReport:
        """Check whether a fact's stored trust has been inflated above its true lineage trust.

        A trust score is considered laundered if:
          stored_trust - effective_trust > LAUNDERING_THRESHOLD
        """
        with self._lock:
            entry = self._facts.get(fact_id)
            if entry is None:
                return LaunderingReport(
                    fact_id=fact_id,
                    laundering_detected=False,
                    stored_trust=0.0,
                    effective_trust=0.0,
                    inflation=0.0,
                    tainted_ancestors=[],
                    explanation="fact_id not found in vault",
                )
            effective = self._effective_trust_locked(fact_id, visited=set())
            inflation = entry.stored_trust - effective
            tainted = self._tainted_ancestors_locked(fact_id)
            detected = inflation > LAUNDERING_THRESHOLD
            explanation = (
                f"stored_trust={entry.stored_trust:.2f}, "
                f"effective_trust={effective:.2f}, "
                f"inflation={inflation:.2f} "
                + (
                    f"— LAUNDERED via {len(tainted)} tainted ancestor(s): {tainted[:3]}"
                    if detected
                    else "— trust lineage intact"
                )
            )
            return LaunderingReport(
                fact_id=fact_id,
                laundering_detected=detected,
                stored_trust=entry.stored_trust,
                effective_trust=effective,
                inflation=inflation,
                tainted_ancestors=tainted,
                explanation=explanation,
            )

    def scan_for_laundering(self) -> list[LaunderingReport]:
        """Run laundering detection across all stored facts. Returns flagged reports only."""
        with self._lock:
            ids = list(self._facts.keys())
        return [
            r for fid in ids
            if (r := self.detect_laundering(fid)).laundering_detected
        ]

    def count(self) -> int:
        with self._lock:
            return len(self._facts)

    def all_facts(self) -> list[TaintEntry]:
        with self._lock:
            return list(self._facts.values())

    # ── Internals ─────────────────────────────────────────────────────

    def _effective_trust_locked(self, fact_id: str, visited: set[str]) -> float:
        """Recursive lineage walk. Must be called with _lock held."""
        if fact_id in visited:
            return 1.0   # cycle guard — trust the visited node at full to avoid infinite loops
        visited.add(fact_id)
        entry = self._facts.get(fact_id)
        if entry is None:
            return 0.0   # unknown ancestor → treat as untrusted
        if not entry.derived_from:
            return entry.stored_trust   # root fact — trust as stored
        ancestor_trusts = [
            self._effective_trust_locked(pid, visited)
            for pid in entry.derived_from
        ]
        return min(entry.stored_trust, min(ancestor_trusts))

    def _tainted_ancestors_locked(self, fact_id: str) -> list[str]:
        """Return all ancestor fact_ids whose stored trust < HOSTILE threshold."""
        tainted: list[str] = []
        stack = list(self._facts.get(fact_id, TaintEntry("", "", None, 1.0, [], "")).derived_from)
        visited: set[str] = set()
        while stack:
            fid = stack.pop()
            if fid in visited:
                continue
            visited.add(fid)
            entry = self._facts.get(fid)
            if entry is None:
                continue
            if entry.stored_trust <= TrustLevel.UNTRUSTED:
                tainted.append(fid)
            stack.extend(entry.derived_from)
        return tainted

    _seq_lock = threading.Lock()
    _seq = 0

    @classmethod
    def _make_id(cls, content: str, source_chain_id: str | None) -> str:
        with cls._seq_lock:
            cls._seq += 1
            seq = cls._seq
        ts = datetime.now(timezone.utc).isoformat()
        payload = f"{source_chain_id or 'agent'}\x00{seq}\x00{ts}\x00{content}".encode("utf-8")
        return "f-" + hashlib.sha256(payload).hexdigest()[:16]

    def _append(self, entry: TaintEntry) -> None:
        assert self._path is not None
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    def _load(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                entry = TaintEntry(
                    fact_id=d["fact_id"],
                    content=d["content"],
                    source_chain_id=d.get("source_chain_id"),
                    stored_trust=float(d["stored_trust"]),
                    derived_from=list(d.get("derived_from", [])),
                    timestamp=d["timestamp"],
                    metadata=dict(d.get("metadata", {})),
                )
                self._facts[entry.fact_id] = entry
