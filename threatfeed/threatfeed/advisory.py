"""Advisory — signed, dated alerts that downstream agents react to in real time.

Independent of (and complementary to) the existing ``feed.py`` pub/sub. The
advisory channel is the *out-of-band* path:

* **feed.py**           — in-process subscribers, used inside the threat-feed
                          server itself (Discover → Compile → Push).
* **advisory_channel**  — append-only filesystem channel (or any blob store)
                          that ed25519-signed advisory bundles are *written
                          to*; remote agents poll/tail and hot-reload their
                          local block-lists / detector configs.

Schema (canonical JSON, sort_keys, no whitespace) — what the signature covers:

    {
      "id":          "ADV-2026-0042",
      "kind":        "cve" | "technique" | "policy" | "model_recall",
      "severity":    "critical" | "high" | "medium" | "low" | "info",
      "title":       "<short human label>",
      "summary":     "<one paragraph>",
      "affects":     ["model:mistral:7b-instruct", "tool:refunds.*", ...],
      "ave_refs":    ["AVE-2025-0001", ...],   # optional
      "mitigation":  {"action": "block" | "warn" | "rate_limit" | "recall",
                      "scope": "global" | "tool" | "agent",
                      "ttl_s": 86400},
      "issued_at":   <unix int>,
      "expires_at":  <unix int>,
      "issuer":      "nail-arsenal:1",
      "nonce":       "<8-hex>"
    }
"""
from __future__ import annotations

import json
import secrets
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# Reach the sibling arsenal/ package without requiring `pip install`.
_ARSENAL_PARENT = Path(__file__).resolve().parents[2] / "arsenal"
if str(_ARSENAL_PARENT) not in sys.path:
    sys.path.insert(0, str(_ARSENAL_PARENT))

from arsenal.signing import sign_blob, verify_blob, hash_blob  # noqa: E402
from arsenal.keys import IssuerKey  # noqa: E402
from arsenal.errors import TokenError  # noqa: E402


class AdvisoryKind(str, Enum):
    CVE = "cve"
    TECHNIQUE = "technique"
    POLICY = "policy"
    MODEL_RECALL = "model_recall"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


_SEVERITY_RANK = {
    Severity.INFO: 0, Severity.LOW: 1, Severity.MEDIUM: 2,
    Severity.HIGH: 3, Severity.CRITICAL: 4,
}


class AdvisoryError(Exception):
    """Base for advisory parse/verify problems."""


@dataclass
class Mitigation:
    action: str = "warn"          # block | warn | rate_limit | recall
    scope: str = "global"         # global | tool | agent
    ttl_s: int = 24 * 3600

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Advisory:
    """One advisory bundle. Wire format = ``payload + signature`` JSON dict."""
    id: str
    kind: AdvisoryKind
    severity: Severity
    title: str
    summary: str
    affects: list[str]
    issued_at: int
    expires_at: int
    issuer: str
    nonce: str
    mitigation: Mitigation = field(default_factory=Mitigation)
    ave_refs: list[str] = field(default_factory=list)

    # ── lifecycle ────────────────────────────────────────────────
    def is_active(self, *, now: int | None = None) -> bool:
        n = now if now is not None else int(time.time())
        return self.issued_at <= n < self.expires_at

    def is_expired(self, *, now: int | None = None) -> bool:
        n = now if now is not None else int(time.time())
        return n >= self.expires_at

    def severity_rank(self) -> int:
        return _SEVERITY_RANK[self.severity]

    # ── canonical encoding ───────────────────────────────────────
    def payload_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "title": self.title,
            "summary": self.summary,
            "affects": list(self.affects),
            "ave_refs": list(self.ave_refs),
            "mitigation": self.mitigation.to_dict(),
            "issued_at": int(self.issued_at),
            "expires_at": int(self.expires_at),
            "issuer": self.issuer,
            "nonce": self.nonce,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.payload_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    # ── matching ─────────────────────────────────────────────────
    def matches(self, *, model: str | None = None,
                tool: str | None = None,
                agent: str | None = None) -> bool:
        """Glob-ish match against the ``affects`` list (``*`` wildcard)."""
        import fnmatch
        for entry in self.affects:
            if ":" not in entry:
                continue
            scope, pattern = entry.split(":", 1)
            target = {"model": model, "tool": tool, "agent": agent}.get(scope)
            if target and fnmatch.fnmatchcase(target, pattern):
                return True
        return False

    # ── factories ────────────────────────────────────────────────
    @classmethod
    def new(cls, *, id: str, kind: AdvisoryKind | str,
            severity: Severity | str, title: str, summary: str,
            affects: list[str], issuer: str = "nail-arsenal:1",
            ttl_s: int = 24 * 3600,
            mitigation: Mitigation | None = None,
            ave_refs: list[str] | None = None,
            issued_at: int | None = None) -> "Advisory":
        now = issued_at if issued_at is not None else int(time.time())
        return cls(
            id=id,
            kind=AdvisoryKind(kind) if isinstance(kind, str) else kind,
            severity=Severity(severity) if isinstance(severity, str) else severity,
            title=title, summary=summary, affects=list(affects),
            issued_at=now, expires_at=now + int(ttl_s),
            issuer=issuer, nonce=secrets.token_hex(4),
            mitigation=mitigation or Mitigation(),
            ave_refs=list(ave_refs or []),
        )


# ── sign / verify ────────────────────────────────────────────────────
def sign_advisory(adv: Advisory, *, key: IssuerKey) -> dict:
    """Return the wire bundle: ``{"payload": {...}, "signature": "kid.b64u",
    "sha256": "<hex>"}``."""
    blob = adv.canonical_bytes()
    return {
        "payload": adv.payload_dict(),
        "signature": sign_blob(blob, key=key),
        "sha256": hash_blob(blob),
    }


def parse_bundle(d: dict | str | bytes) -> tuple[Advisory, str, str]:
    """Parse a wire bundle. Returns ``(advisory, signature, sha256)``.

    Does NOT verify the signature — use ``verify_bundle`` for that.
    """
    if isinstance(d, (bytes, str)):
        d = json.loads(d)
    if not isinstance(d, dict) or "payload" not in d or "signature" not in d:
        raise AdvisoryError("bundle missing 'payload' or 'signature' field")
    p = d["payload"]
    try:
        adv = Advisory(
            id=p["id"],
            kind=AdvisoryKind(p["kind"]),
            severity=Severity(p["severity"]),
            title=p["title"], summary=p["summary"],
            affects=list(p.get("affects", [])),
            issued_at=int(p["issued_at"]),
            expires_at=int(p["expires_at"]),
            issuer=p["issuer"], nonce=p["nonce"],
            mitigation=Mitigation(**p.get("mitigation", {})),
            ave_refs=list(p.get("ave_refs", [])),
        )
    except (KeyError, ValueError) as e:
        raise AdvisoryError(f"malformed advisory payload: {e}") from e
    return adv, d["signature"], d.get("sha256", "")


def verify_bundle(d: dict | str | bytes, *, trusted_keys) -> Advisory:
    """Parse + verify ed25519 signature against ``trusted_keys``."""
    adv, sig, _sha = parse_bundle(d)
    blob = adv.canonical_bytes()
    try:
        verify_blob(blob, sig, trusted_keys=trusted_keys)
    except TokenError as e:
        raise AdvisoryError(f"signature verify failed: {e}") from e
    return adv
