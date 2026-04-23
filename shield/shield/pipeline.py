"""Top-level pipeline — assemble canonicaliser + scrub + provenance + chain.

The single public entry-point is ``process(text, source=...)``. The classifier
step is opt-in via ``classify=True`` (default off, so `shield` runs without
Ollama).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .canonicaliser import canonicalise
from .chain import append_to_default_chain, ChainEntry
from .provenance import wrap_untrusted
from .secret_scrub import scrub


@dataclass
class ShieldedInput:
    text: str                                  # final wrapped + scrubbed text
    source: str
    span_id: str
    canonical_sha256: str
    chain_entry: ChainEntry | None
    secrets: dict[str, str] = field(default_factory=dict)
    secret_counts: dict[str, int] = field(default_factory=dict)
    canonical_changes: list[str] = field(default_factory=list)
    injection_score: float | None = None
    is_injection: bool | None = None
    injection_reason: str = ""
    original_length: int = 0

    @property
    def chain_id(self) -> str | None:
        return self.chain_entry.entry_hash if self.chain_entry else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "span_id": self.span_id,
            "canonical_sha256": self.canonical_sha256,
            "chain_id": self.chain_id,
            "secret_counts": dict(self.secret_counts),
            "canonical_changes": list(self.canonical_changes),
            "injection_score": self.injection_score,
            "is_injection": self.is_injection,
            "injection_reason": self.injection_reason,
            "original_length": self.original_length,
            "shielded_length": len(self.text),
        }


def process(
    text: str,
    *,
    source: str,
    classify: bool = False,
    classifier_model: str = "nail-guard:v4",
    chain: bool = True,
) -> ShieldedInput:
    """Full shield pipeline.

    1. Canonicalise (NFKC, strip invisibles/bidi/controls, quote breakouts).
    2. Scrub secrets (reversible tokens).
    3. Wrap in `<UNTRUSTED src=... id=...>` envelope.
    4. (optional) Classify for injection via `nail-guard:v4`.
    5. (default-on) Append sha256 to AVE-compatible hash chain.
    """
    canon = canonicalise(text)
    scrubbed = scrub(canon.text)
    wrapped = wrap_untrusted(scrubbed.text, source=source)

    # Recover the deterministic span id from the wrapper.
    import re as _re
    m = _re.search(r'id="([^"]+)"', wrapped)
    span_id = m.group(1) if m else "u-unknown"

    inj_score: float | None = None
    is_inj: bool | None = None
    inj_reason = ""
    if classify:
        from .classifier import score_input
        s = score_input(scrubbed.text, model=classifier_model)
        inj_score = s.confidence
        is_inj = s.is_attack
        inj_reason = s.reason

    entry: ChainEntry | None = None
    if chain:
        entry = append_to_default_chain(
            source=source, canonical_sha256=canon.sha256,
        )

    return ShieldedInput(
        text=wrapped,
        source=source,
        span_id=span_id,
        canonical_sha256=canon.sha256,
        chain_entry=entry,
        secrets=scrubbed.secrets,
        secret_counts=scrubbed.counts,
        canonical_changes=canon.changes,
        injection_score=inj_score,
        is_injection=is_inj,
        injection_reason=inj_reason,
        original_length=canon.original_length,
    )
