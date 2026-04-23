"""Reversible secret scrub.

Detects high-confidence secrets in untrusted text and replaces each occurrence
with an opaque token like ``<SECRET:email-1>``. The original values are kept
in a per-input dictionary so legitimate downstream workflows (e.g. an agent
that legitimately needs to email the customer back) can rehydrate after
policy checks have passed.

Detection layers:
* High-precision regex for canonical formats (emails, SSN, UK NI, credit
  cards via Luhn, AWS / GitHub / OpenAI / Anthropic / Stripe API keys,
  bearer tokens, JWT-shaped strings).
* Generic high-entropy token detector for things that *look* like secrets
  (≥ 32 chars, mixed case + digits, low repetition).

We deliberately DO NOT use any external service — `shield` runs entirely
locally so secrets never leave the box.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

# ── Canonical-format detectors ───────────────────────────────────────
# Each entry: (label, compiled_regex). Order matters — earlier wins.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # API keys
    ("openai_key",   re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key",re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("aws_key",      re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_pat",   re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("github_oauth", re.compile(r"\bgho_[A-Za-z0-9]{36}\b")),
    ("stripe_key",   re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{24,}\b")),
    ("slack_token",  re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    # Bearer / JWT
    ("jwt",          re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    # Personally identifiable
    ("us_ssn",       re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    ("uk_nino",      re.compile(r"\b[ABCEGHJKLMNOPRSTWXYZ][ABCEGHJKLMNPRSTWXYZ]\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b")),
    ("email",        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Credit card — pre-filter; Luhn check below in scrub()
    ("credit_card",  re.compile(r"\b(?:\d[ -]?){13,19}\b")),
]


def _luhn_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _shannon(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


# Generic high-entropy detector — only fires on bare tokens not already matched.
_HIGH_ENTROPY_RE = re.compile(r"\b[A-Za-z0-9_+/=\-]{32,}\b")


@dataclass
class ScrubResult:
    text: str
    secrets: dict[str, str]      # token -> original
    counts:  dict[str, int]      # label -> n_occurrences

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "secret_count": len(self.secrets),
            "counts": dict(self.counts),
        }


def scrub(text: str) -> ScrubResult:
    """Replace detected secrets with reversible tokens."""
    secrets: dict[str, str] = {}
    counts: dict[str, int] = {}
    counters: dict[str, int] = {}
    matched_spans: list[tuple[int, int]] = []

    def _next_token(label: str) -> str:
        n = counters.get(label, 0) + 1
        counters[label] = n
        return f"<SECRET:{label}-{n}>"

    out = text

    # Apply canonical patterns first.
    for label, pat in _PATTERNS:
        def _sub(m: re.Match, _label=label) -> str:
            value = m.group(0)
            if _label == "credit_card" and not _luhn_ok(value):
                return value  # keep — it was a number sequence, not a CC
            tok = _next_token(_label)
            secrets[tok] = value
            counts[_label] = counts.get(_label, 0) + 1
            matched_spans.append((m.start(), m.end()))
            return tok
        out = pat.sub(_sub, out)

    # Generic high-entropy fallback. Skip very-low-entropy long strings
    # (e.g. base64-of-zeros) and skip already-tokenised secrets.
    def _entropy_sub(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith("<SECRET:"):
            return s
        if _shannon(s) < 3.5:
            return s
        tok = _next_token("highentropy")
        secrets[tok] = s
        counts["highentropy"] = counts.get("highentropy", 0) + 1
        return tok

    out = _HIGH_ENTROPY_RE.sub(_entropy_sub, out)

    return ScrubResult(text=out, secrets=secrets, counts=counts)


def rehydrate(text: str, secrets: dict[str, str]) -> str:
    """Inverse of scrub() — restore original values from tokens.

    The caller is responsible for deciding whether rehydration is allowed
    (it usually only is *after* the agent's response has itself passed
    `nail-guard` outbound classification).
    """
    out = text
    # Sort by length desc so e.g. <SECRET:email-10> is replaced before
    # <SECRET:email-1>.
    for tok in sorted(secrets, key=len, reverse=True):
        out = out.replace(tok, secrets[tok])
    return out
