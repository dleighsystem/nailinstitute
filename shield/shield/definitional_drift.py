"""DefinitionalDriftDetector — cross-agent semantic-consistency scanner.

Closes the gap that :mod:`shield.taint_vault` does not: TaintVault proves a
fact's *provenance* is honest (its trust was not laundered through
summarisation). It says nothing about whether two agents **mean the same
thing** by a shared business term.

This detector treats *definitional divergence* — two agents using
incompatible definitions of the same term ("revenue", "active user",
"churn") while each maintains clean provenance lineage — as the agent
pathology **AVE-2026-0037 Semantic Fragmentation**.

It is orthogonal to Memory Laundering:

    Memory Laundering  : trust failure   over a *valid* definition.
    Semantic Fragmentation : definition failure over *valid* trust.

The dangerous case is precisely the silent one: real divergence where *both*
lineages are clean, so no single-agent integrity check fires.

Design
------
The detector sits **on top of** a populated :class:`~shield.taint_vault.TaintVault`.
It does not own definitions and does not resolve which agent is "correct" —
it only reports that they disagree, and how clean each lineage is.

    from shield.taint_vault import TaintVault, TrustLevel
    from shield.definitional_drift import DefinitionalDriftDetector

    vault = TaintVault()
    vault.store("revenue := gross minus refunds",
                trust_score=TrustLevel.VERIFIED,
                metadata={"agent_id": "underwriter-A",
                          "definition": {"term": "revenue",
                                         "expr": "gross minus refunds"}})
    vault.store("revenue := gross",
                trust_score=TrustLevel.VERIFIED,
                metadata={"agent_id": "underwriter-B",
                          "definition": {"term": "revenue", "expr": "gross"}})

    detector = DefinitionalDriftDetector(vault)
    findings = detector.scan()
    assert findings[0].both_lineage_clean   # silent, dangerous divergence

Extraction tiers
----------------
The mapping (fact -> definitions asserted) is pluggable via ``extractor``.
The default :func:`structural_extractor` is deterministic and dependency-free:

  1. **Structured records** (preferred): a ``definition`` dict in the fact's
     metadata — ``{"term": ..., "expr": ...}``. Zero ambiguity.
  2. **Free-text regex** (fallback): patterns like ``X := Y``, ``X is defined
     as Y``, ``X means Y``.

There is deliberately **no LLM extractor** in the default path. Free-text
LLM extraction inherits LLM error rates and is the most likely source of
false positives; it is left for a later, flag-gated tier (CIL spec P6) once
exp39 has measured the deterministic path's false-positive rate.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable, Iterable, Optional

from .taint_vault import TaintEntry, TaintVault, TrustLevel


# ── Tunables ──────────────────────────────────────────────────────────────────

# Provisional. Jaccard distance over normalised definition tokens. Above this,
# two same-term definitions are considered divergent. Pending empirical tuning
# in exp39 (CIL spec P3) — do NOT treat as a settled constant.
DEFAULT_DIVERGENCE_THRESHOLD = 0.30

# A lineage is "clean" if its effective trust is at least VERIFIED. A divergence
# between two clean lineages is the silent, dangerous class (no poisoning to
# blame), and is what underwriting cares about most.
CLEAN_TRUST_FLOOR = float(TrustLevel.VERIFIED)   # 0.75

# Tokens that carry no definitional content — dropped before fingerprinting so
# that "gross minus refunds" and "gross - refunds" fingerprint identically.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "of", "is", "are", "be", "as", "to", "by", "and",
    "defined", "definition", "define", "means", "equal", "equals", "value",
    "total", "amount", "all", "any", "per", "for", "with", "from", "on",
    # operator words — we compare operands, not arithmetic structure (P2 scope)
    "minus", "plus", "less", "net", "gross_of", "after", "before", "including",
    "excluding", "over", "divided", "times", "sum",
})

_DEF_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<term>[A-Za-z][\w ]{0,40}?)\s*:=\s*(?P<expr>.+)", re.I),
    re.compile(r"(?P<term>[A-Za-z][\w ]{0,40}?)\s+is\s+defined\s+as\s+(?P<expr>.+)", re.I),
    re.compile(r"(?P<term>[A-Za-z][\w ]{0,40}?)\s+means\s+(?P<expr>.+)", re.I),
    re.compile(r"(?:we\s+)?defines?\s+(?P<term>[A-Za-z][\w ]{0,40}?)\s+as\s+(?P<expr>.+)", re.I),
)

_UNKNOWN_AGENT = "<unknown-agent>"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DefinitionExtraction:
    """A single (term -> meaning) assertion pulled from one fact.

    Produced by an ``extractor``. The detector enriches it with vault-derived
    fields (agent_id, fact_id, effective_trust) to build a
    :class:`DefinitionFingerprint`.
    """
    term: str                     # normalised term, e.g. "revenue"
    tokens: frozenset[str]        # normalised operand tokens, e.g. {"gross", "refunds"}
    raw: str = ""                 # original definition text (for explanations)


@dataclass(frozen=True)
class DefinitionFingerprint:
    """A term definition as asserted by one agent, with trust context."""
    term: str
    agent_id: str
    fact_id: str
    fingerprint: str              # sha256 over canonical token set — identity/grouping
    tokens: frozenset[str]        # for structural (Jaccard) divergence
    effective_trust: float        # from TaintVault.effective_trust(fact_id)
    raw: str = ""
    embedding: Optional[tuple[float, ...]] = None   # optional semantic-tier vector

    @property
    def lineage_clean(self) -> bool:
        return self.effective_trust >= CLEAN_TRUST_FLOOR


@dataclass(frozen=True)
class DriftFinding:
    """A detected definitional divergence between two agents for one term."""
    term: str
    agent_a: str
    agent_b: str
    divergence: float             # 0.0 (identical) … 1.0 (disjoint)
    both_lineage_clean: bool      # True = the silent, dangerous case
    fingerprints: tuple[DefinitionFingerprint, DefinitionFingerprint]
    explanation: str

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "agent_a": self.agent_a,
            "agent_b": self.agent_b,
            "divergence": round(self.divergence, 4),
            "both_lineage_clean": self.both_lineage_clean,
            "fact_ids": [fp.fact_id for fp in self.fingerprints],
            "explanation": self.explanation,
        }


# ── Tokenisation & fingerprinting ─────────────────────────────────────────────

def normalise_term(term: str) -> str:
    """Canonical form of a term: lowercased, collapsed whitespace, trimmed."""
    return re.sub(r"\s+", " ", term.strip().lower())


def tokenise_definition(expr: str) -> frozenset[str]:
    """Reduce a definition expression to its set of content (operand) tokens.

    Lowercases, splits on non-alphanumerics, and drops stopwords/operator words
    so that arithmetically-equivalent phrasings collapse to the same set. This
    is the *structural* tier — it compares which quantities a definition draws
    on, not their arithmetic arrangement.
    """
    words = re.split(r"[^a-z0-9]+", expr.lower())
    return frozenset(w for w in words if w and w not in _STOPWORDS)


def _fingerprint_hash(term: str, tokens: frozenset[str]) -> str:
    canonical = term + "\x00" + "|".join(sorted(tokens))
    return "d-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ── Default (deterministic) extractor ─────────────────────────────────────────

def structural_extractor(entry: TaintEntry) -> list[DefinitionExtraction]:
    """Deterministic, dependency-free definition extractor.

    Tier 1: a structured ``definition`` record in metadata (preferred).
    Tier 2: free-text regex over the fact content (fallback).

    Returns an empty list for facts that assert no definition.
    """
    extractions: list[DefinitionExtraction] = []

    # Tier 1 — structured record(s)
    defn = entry.metadata.get("definition")
    records = defn if isinstance(defn, list) else ([defn] if isinstance(defn, dict) else [])
    for rec in records:
        if not isinstance(rec, dict):
            continue
        term = rec.get("term")
        expr = rec.get("expr", rec.get("definition", ""))
        if term and expr:
            extractions.append(DefinitionExtraction(
                term=normalise_term(str(term)),
                tokens=tokenise_definition(str(expr)),
                raw=str(expr),
            ))
    if extractions:
        return extractions

    # Tier 2 — free-text regex fallback
    for pattern in _DEF_PATTERNS:
        for m in pattern.finditer(entry.content):
            term = normalise_term(m.group("term"))
            expr = m.group("expr").strip().rstrip(".")
            if term and expr:
                extractions.append(DefinitionExtraction(
                    term=term,
                    tokens=tokenise_definition(expr),
                    raw=expr,
                ))
    return extractions


# ── Divergence functions ──────────────────────────────────────────────────────

def jaccard_divergence(a: DefinitionFingerprint, b: DefinitionFingerprint) -> float:
    """Structural divergence: 1 − Jaccard similarity of token sets.

    0.0 = identical operand sets, 1.0 = disjoint. Two empty token sets are
    treated as identical (divergence 0.0).
    """
    sa, sb = a.tokens, b.tokens
    if not sa and not sb:
        return 0.0
    union = sa | sb
    if not union:
        return 0.0
    return 1.0 - (len(sa & sb) / len(union))


def cosine_divergence(a: DefinitionFingerprint, b: DefinitionFingerprint) -> float:
    """Semantic divergence over embeddings: 1 − cosine similarity, clamped [0,1].

    Optional tier (CIL spec P6). Raises if either fingerprint lacks an
    embedding — wire it in explicitly via ``divergence_fn`` once embeddings
    are available; it is never the default.
    """
    if a.embedding is None or b.embedding is None:
        raise ValueError("cosine_divergence requires embeddings on both fingerprints")
    va, vb = a.embedding, b.embedding
    if len(va) != len(vb):
        raise ValueError("embedding dimensionality mismatch")
    dot = sum(x * y for x, y in zip(va, vb))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    if na == 0.0 or nb == 0.0:
        return 1.0
    cos = dot / (na * nb)
    return max(0.0, min(1.0, 1.0 - cos))


# ── Detector ──────────────────────────────────────────────────────────────────

class DefinitionalDriftDetector:
    """Scans a TaintVault for cross-agent definitional divergence.

    Parameters
    ----------
    vault : TaintVault
        Populated fact store. ``agent_id`` is read from each fact's
        ``metadata["agent_id"]`` (no TaintVault schema change required).
    extractor : Callable[[TaintEntry], list[DefinitionExtraction]]
        Maps a fact to the definitions it asserts. Defaults to the
        deterministic :func:`structural_extractor`.
    divergence_threshold : float
        Findings are emitted when divergence strictly exceeds this value.
    divergence_fn : Callable[[DefinitionFingerprint, DefinitionFingerprint], float]
        How to score divergence between two fingerprints. Defaults to
        :func:`jaccard_divergence` (structural). Swap for
        :func:`cosine_divergence` when embeddings are available.
    """

    def __init__(
        self,
        vault: TaintVault,
        *,
        extractor: Callable[[TaintEntry], list[DefinitionExtraction]] = structural_extractor,
        divergence_threshold: float = DEFAULT_DIVERGENCE_THRESHOLD,
        divergence_fn: Callable[[DefinitionFingerprint, DefinitionFingerprint], float] = jaccard_divergence,
    ):
        self.vault = vault
        self.extractor = extractor
        self.divergence_threshold = float(divergence_threshold)
        self.divergence_fn = divergence_fn

    # ── Public API ────────────────────────────────────────────────────

    def fingerprints(self) -> list[DefinitionFingerprint]:
        """Extract every (term, agent) definition fingerprint in the vault."""
        out: list[DefinitionFingerprint] = []
        for entry in self.vault.all_facts():
            agent_id = str(entry.metadata.get("agent_id", _UNKNOWN_AGENT))
            trust = self.vault.effective_trust(entry.fact_id)
            for ext in self.extractor(entry):
                out.append(DefinitionFingerprint(
                    term=ext.term,
                    agent_id=agent_id,
                    fact_id=entry.fact_id,
                    fingerprint=_fingerprint_hash(ext.term, ext.tokens),
                    tokens=ext.tokens,
                    effective_trust=trust,
                    raw=ext.raw,
                ))
        return out

    def scan(self) -> list[DriftFinding]:
        """Return all cross-agent definitional divergences above threshold.

        Only pairs from *distinct* agents are compared (intra-agent
        self-contradiction is a separate pathology). Findings are sorted with
        the silent ``both_lineage_clean`` cases first, then by divergence.
        """
        by_term: dict[str, list[DefinitionFingerprint]] = {}
        for fp in self.fingerprints():
            by_term.setdefault(fp.term, []).append(fp)

        findings: list[DriftFinding] = []
        for term, group in by_term.items():
            for a, b in combinations(group, 2):
                if a.agent_id == b.agent_id:
                    continue
                if a.fingerprint == b.fingerprint:
                    continue   # identical definition — no divergence to score
                divergence = self.divergence_fn(a, b)
                if divergence <= self.divergence_threshold:
                    continue
                clean = a.lineage_clean and b.lineage_clean
                findings.append(DriftFinding(
                    term=term,
                    agent_a=a.agent_id,
                    agent_b=b.agent_id,
                    divergence=divergence,
                    both_lineage_clean=clean,
                    fingerprints=(a, b),
                    explanation=self._explain(term, a, b, divergence, clean),
                ))

        findings.sort(key=lambda f: (not f.both_lineage_clean, -f.divergence))
        return findings

    def has_unresolved_conflicts(self) -> bool:
        """True if any cross-agent definitional divergence exists. For gating."""
        return bool(self.scan())

    # ── Internals ─────────────────────────────────────────────────────

    @staticmethod
    def _explain(
        term: str,
        a: DefinitionFingerprint,
        b: DefinitionFingerprint,
        divergence: float,
        clean: bool,
    ) -> str:
        only_a = sorted(a.tokens - b.tokens)
        only_b = sorted(b.tokens - a.tokens)
        verdict = (
            "SILENT divergence — both lineages clean, no poisoning to blame"
            if clean else
            "divergence with at least one tainted lineage"
        )
        return (
            f"'{term}': {a.agent_id} and {b.agent_id} disagree "
            f"(divergence={divergence:.2f}). "
            f"{a.agent_id}-only operands={only_a or '∅'}, "
            f"{b.agent_id}-only operands={only_b or '∅'}. "
            f"trust[{a.agent_id}]={a.effective_trust:.2f}, "
            f"trust[{b.agent_id}]={b.effective_trust:.2f} — {verdict}."
        )
