"""Structural canonicalisation of untrusted text.

The very first defence: an attacker's payload often relies on tricks that
become invisible after Unicode normalisation. We:

* Normalise to NFKC (collapses fullwidth / compatibility forms — e.g. the
  fullwidth "ＩＧＮＯＲＥ" reduces to "IGNORE", defeating naive blocklists
  that miss the disguised form).
* Strip zero-width characters (ZWSP, ZWNJ, ZWJ, BOM, word joiner) — the
  classic "invisible-text injection" vector.
* Strip bidirectional controls (RLO, LRO, LRE, RLE, PDF, RLI, LRI, FSI, PDI)
  — Trojan-Source style attacks that visually reorder text.
* Strip C0/C1 control characters except \\t, \\n, \\r.
* Collapse runs of whitespace and normalise newlines.
* Detect & quote nested control sequences (e.g. attempts to embed our own
  <UNTRUSTED> close-tag inside the payload to break out).

Returns a `CanonicalisedSpan` with the cleaned text, the original byte-length,
and an audit list of every transformation applied.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

# Zero-width / invisible characters (kept separate from bidi for clarity).
_ZERO_WIDTH = {
    "\u200B",  # ZERO WIDTH SPACE
    "\u200C",  # ZWNJ
    "\u200D",  # ZWJ
    "\uFEFF",  # BOM / ZERO WIDTH NO-BREAK SPACE
    "\u2060",  # WORD JOINER
    "\u180E",  # MONGOLIAN VOWEL SEPARATOR
    "\u00AD",  # SOFT HYPHEN
}

# Bidirectional formatting controls (Trojan-Source vector).
_BIDI_CONTROLS = {
    "\u202A",  # LRE
    "\u202B",  # RLE
    "\u202C",  # PDF
    "\u202D",  # LRO
    "\u202E",  # RLO
    "\u2066",  # LRI
    "\u2067",  # RLI
    "\u2068",  # FSI
    "\u2069",  # PDI
}

# C0 controls except TAB / LF / CR; full C1 range.
_BAD_CONTROLS = (
    {chr(c) for c in range(0x00, 0x20) if chr(c) not in "\t\n\r"}
    | {chr(c) for c in range(0x7F, 0xA0)}
)

_STRIP_SET = _ZERO_WIDTH | _BIDI_CONTROLS | _BAD_CONTROLS

# Patterns that look like an attempt to break out of provenance wrappers.
_BREAKOUT_TAG_RE = re.compile(r"</?\s*UNTRUSTED\b[^>]*>", re.IGNORECASE)


@dataclass
class CanonicalisedSpan:
    """Result of canonicalising one untrusted span."""

    text: str
    original_length: int
    canonical_length: int
    sha256: str
    changes: list[str] = field(default_factory=list)

    @property
    def shrank(self) -> bool:
        return self.canonical_length < self.original_length

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "original_length": self.original_length,
            "canonical_length": self.canonical_length,
            "sha256": self.sha256,
            "changes": list(self.changes),
        }


def canonicalise(text: str) -> CanonicalisedSpan:
    """Apply the full canonicalisation pipeline to `text`.

    This function is pure — same input always produces the same output.
    """
    if not isinstance(text, str):
        raise TypeError(f"canonicalise expects str, got {type(text).__name__}")

    original_len = len(text)
    changes: list[str] = []

    # 1. NFKC normalise (compatibility decomposition + canonical composition).
    nfkc = unicodedata.normalize("NFKC", text)
    if nfkc != text:
        changes.append("nfkc_normalised")

    # 2. Strip zero-width / bidi / bad control characters.
    if any(ch in _STRIP_SET for ch in nfkc):
        before = len(nfkc)
        # Track which categories actually appeared.
        if any(ch in _ZERO_WIDTH for ch in nfkc):
            changes.append("stripped_zero_width")
        if any(ch in _BIDI_CONTROLS for ch in nfkc):
            changes.append("stripped_bidi_controls")
        if any(ch in _BAD_CONTROLS for ch in nfkc):
            changes.append("stripped_control_chars")
        nfkc = "".join(ch for ch in nfkc if ch not in _STRIP_SET)
        if len(nfkc) != before:
            changes.append(f"stripped_chars:{before - len(nfkc)}")

    # 3. Quote breakout attempts on our own provenance tag.
    if _BREAKOUT_TAG_RE.search(nfkc):
        nfkc = _BREAKOUT_TAG_RE.sub(
            lambda m: "&lt;" + m.group(0)[1:-1].replace("<", "&lt;") + "&gt;",
            nfkc,
        )
        changes.append("quoted_breakout_tag")

    # 4. Normalise line endings, collapse whitespace runs (preserve newlines).
    if "\r" in nfkc:
        nfkc = nfkc.replace("\r\n", "\n").replace("\r", "\n")
        changes.append("normalised_line_endings")

    collapsed = re.sub(r"[ \t]+", " ", nfkc)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    if collapsed != nfkc:
        changes.append("collapsed_whitespace")
    nfkc = collapsed

    digest = hashlib.sha256(nfkc.encode("utf-8")).hexdigest()

    return CanonicalisedSpan(
        text=nfkc,
        original_length=original_len,
        canonical_length=len(nfkc),
        sha256=digest,
        changes=changes,
    )
