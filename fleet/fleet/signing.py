"""Signed event envelopes for fleet/.

Wraps ``arsenal.signing`` so events pushed over the network can be verified
on ingest. The envelope wire format is:

    {"event": {...}, "sig": "<kid>.<b64u-sig>"}

The signed body is the canonical JSON of ``event`` (sort_keys, no whitespace).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

# Sibling-package import shim — find arsenal/ next to fleet/.
_ROOT = Path(__file__).resolve().parents[2]
_ARSENAL = _ROOT / "arsenal"
if _ARSENAL.is_dir() and str(_ARSENAL) not in sys.path:
    sys.path.insert(0, str(_ARSENAL))

try:
    from arsenal.signing import sign_blob, verify_blob  # noqa: E402
    from arsenal.errors import InvalidSignature        # noqa: E402
    from arsenal.keys import IssuerKey                  # noqa: E402
    HAS_ARSENAL = True
except ImportError:  # pragma: no cover
    HAS_ARSENAL = False
    InvalidSignature = RuntimeError  # type: ignore[assignment,misc]

from .event import Event


def _canonical(event: Event) -> bytes:
    return json.dumps(event.to_dict(), separators=(",", ":"),
                      sort_keys=True).encode("utf-8")


def sign_event(event: Event, *, key: "IssuerKey") -> dict:
    """Return a wire envelope ``{"event": ..., "sig": ...}``."""
    if not HAS_ARSENAL:
        raise RuntimeError("arsenal package not importable; cannot sign")
    sig = sign_blob(_canonical(event), key=key)
    return {"event": event.to_dict(), "sig": sig}


def verify_envelope(envelope: dict, *,
                    trusted_keys: Iterable["IssuerKey"]) -> Event:
    """Verify the envelope and return the contained Event.

    Raises ``InvalidSignature`` on tampering or unknown kid.
    """
    if not HAS_ARSENAL:
        raise RuntimeError("arsenal package not importable; cannot verify")
    if not isinstance(envelope, dict) or "event" not in envelope or "sig" not in envelope:
        raise InvalidSignature("envelope missing 'event' or 'sig'")
    event = Event.from_dict(envelope["event"])
    verify_blob(_canonical(event), envelope["sig"],
                trusted_keys=list(trusted_keys))
    return event
