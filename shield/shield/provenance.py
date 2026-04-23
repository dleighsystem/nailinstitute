"""Provenance wrapping.

The contract: any text wrapped in `<UNTRUSTED src="..." id="...">…</UNTRUSTED>`
is considered hostile. The agent's system prompt MUST instruct the model
never to follow instructions from inside such a tag — only to read it as
data.

The wrapper is the simplest possible primitive for separating "instruction
context" (system prompt + developer messages) from "data context" (everything
else). It works because the canonicaliser has already escaped any nested
attempt at the same tag, so the close-tag is unambiguous.
"""
from __future__ import annotations

import hashlib
import re

UNTRUSTED_OPEN_RE = re.compile(
    r'<UNTRUSTED\s+src="(?P<src>[^"]*)"\s+id="(?P<id>[^"]*)">',
)
UNTRUSTED_CLOSE_RE = re.compile(r"</UNTRUSTED>")


def _short_id(src: str, text: str) -> str:
    """Deterministic 8-hex-char id from source + content."""
    h = hashlib.sha256(f"{src}\x00{text}".encode("utf-8")).hexdigest()
    return f"u-{h[:8]}"


def wrap_untrusted(text: str, *, source: str, span_id: str | None = None) -> str:
    """Wrap canonicalised text in an `<UNTRUSTED>` envelope.

    Parameters
    ----------
    text : str
        Already-canonicalised text. Wrapping a non-canonical string is a
        bug — it bypasses the breakout-quoting protection.
    source : str
        Human/machine-readable provenance (e.g. ``"email:abc@x.com"``,
        ``"rag:doc-7f3a#chunk-2"``, ``"tool_return:db.query"``).
    span_id : str, optional
        Override the deterministic id (mostly for tests).
    """
    if not source:
        raise ValueError("source must be a non-empty string")
    sid = span_id or _short_id(source, text)
    safe_src = source.replace('"', "&quot;")
    return (
        f'<UNTRUSTED src="{safe_src}" id="{sid}">\n'
        f"{text}\n"
        f"</UNTRUSTED>"
    )
