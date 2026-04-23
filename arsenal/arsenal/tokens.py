"""Capability token format and minting/verification.

Token = ``header.payload.signature`` (3 base64url-encoded segments).

Header
    {"alg": "ed25519", "typ": "NAIL-CAP", "kid": "<key-id>"}

Payload claims (all required unless noted)
    tool          str       canonical tool name (e.g. "refunds.issue")
    agent         str       agent identifier
    session       str       session identifier (UUID-ish)
    iat           int       issued-at unix seconds
    exp           int       expires-at unix seconds (max 24h enforced)
    limits        dict      per-token consumption caps:
                              calls           int  -- max invocations
                              cumulative_gbp  num  -- £ sum across calls
                              cumulative      num  -- generic numeric sum
    conditions    list      list of {op, value} predicates evaluated per call
                              op ∈ {hold_above_gbp, max_arg_gbp,
                                    requires_user_session, ip_in}
    ave_chain_id  str       optional shield/ chain entry binding the session
                            to a sanitised input
    nonce         str       8-hex-char random tag for replay tracking
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .errors import (
    ExpiredToken, InvalidSignature, MalformedToken, TokenError, UnknownIssuer,
)
from .keys import IssuerKey

MAX_TTL_SECONDS = 24 * 60 * 60  # hard ceiling — no token lives > 24h
ALG = "ed25519"
TYP = "NAIL-CAP"


# ── base64url helpers ────────────────────────────────────────────────
def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _canonical_json(d: dict) -> bytes:
    """Stable, separator-free JSON encoding (so signatures match across runs)."""
    return json.dumps(d, separators=(",", ":"), sort_keys=True).encode("utf-8")


# ── public datatype ──────────────────────────────────────────────────
@dataclass
class Token:
    """A parsed capability token."""
    header: dict
    payload: dict
    signature_b64u: str
    raw: str
    signing_input: bytes = field(repr=False)

    # ── claim accessors ──────────────────────────────────────────
    @property
    def kid(self) -> str:        return self.header["kid"]
    @property
    def tool(self) -> str:       return self.payload["tool"]
    @property
    def agent(self) -> str:      return self.payload["agent"]
    @property
    def session(self) -> str:    return self.payload["session"]
    @property
    def iat(self) -> int:        return int(self.payload["iat"])
    @property
    def exp(self) -> int:        return int(self.payload["exp"])
    @property
    def limits(self) -> dict:    return dict(self.payload.get("limits", {}))
    @property
    def conditions(self) -> list: return list(self.payload.get("conditions", []))

    @property
    def ttl_remaining_s(self) -> int:
        return max(0, self.exp - int(time.time()))

    @property
    def is_expired(self) -> bool:
        return time.time() > self.exp

    def to_dict(self) -> dict:
        return {
            "header": dict(self.header),
            "payload": dict(self.payload),
            "signature": self.signature_b64u,
            "raw": self.raw,
        }


# ── mint ─────────────────────────────────────────────────────────────
def mint(*, tool: str, agent: str, session: str,
         key: IssuerKey,
         ttl_seconds: int = 1800,
         limits: dict | None = None,
         conditions: list | None = None,
         ave_chain_id: str | None = None,
         nonce: str | None = None) -> str:
    """Mint a signed capability token. Returns the encoded ``h.p.s`` string."""
    if not key.has_private:
        raise ValueError("issuer key has no private half")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    if ttl_seconds > MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds exceeds policy ceiling {MAX_TTL_SECONDS}")
    if "/" in tool or " " in tool:
        raise ValueError("tool name must be dot-separated identifier")
    if limits is not None and not isinstance(limits, dict):
        raise TypeError("limits must be dict")
    if conditions is not None and not isinstance(conditions, list):
        raise TypeError("conditions must be list")

    now = int(time.time())
    header = {"alg": ALG, "typ": TYP, "kid": key.kid}
    payload: dict[str, Any] = {
        "tool": tool,
        "agent": agent,
        "session": session,
        "iat": now,
        "exp": now + ttl_seconds,
        "limits": limits or {},
        "conditions": conditions or [],
        "nonce": nonce or secrets.token_hex(4),
    }
    if ave_chain_id:
        payload["ave_chain_id"] = ave_chain_id

    h_b = _canonical_json(header)
    p_b = _canonical_json(payload)
    signing_input = _b64u(h_b).encode("ascii") + b"." + _b64u(p_b).encode("ascii")
    sig = key.private_key.sign(signing_input)  # type: ignore[union-attr]
    return f"{_b64u(h_b)}.{_b64u(p_b)}.{_b64u(sig)}"


# ── parse + verify ───────────────────────────────────────────────────
def _parse(raw: str) -> Token:
    parts = raw.split(".")
    if len(parts) != 3:
        raise MalformedToken(f"expected 3 segments, got {len(parts)}")
    h_b64, p_b64, sig_b64 = parts
    try:
        header = json.loads(_b64u_decode(h_b64))
        payload = json.loads(_b64u_decode(p_b64))
    except (ValueError, json.JSONDecodeError) as e:
        raise MalformedToken(f"bad json in segment: {e}") from e
    if header.get("alg") != ALG:
        raise MalformedToken(f"unsupported alg: {header.get('alg')}")
    if header.get("typ") != TYP:
        raise MalformedToken(f"unsupported typ: {header.get('typ')}")
    for required in ("tool", "agent", "session", "iat", "exp"):
        if required not in payload:
            raise MalformedToken(f"missing claim: {required}")
    signing_input = (h_b64 + "." + p_b64).encode("ascii")
    return Token(
        header=header, payload=payload,
        signature_b64u=sig_b64, raw=raw, signing_input=signing_input,
    )


def inspect(raw: str) -> Token:
    """Parse a token without verifying its signature.
    Useful for debugging / human inspection. NEVER trust the result for
    enforcement decisions."""
    return _parse(raw)


def verify(raw: str, *, trusted_keys: Iterable[IssuerKey],
           now: int | None = None) -> Token:
    """Full verify: parse + signature check + expiry check.

    Raises one of TokenError's subclasses on failure.
    """
    tok = _parse(raw)

    # Signature must match a trusted key with matching kid.
    candidates = [k for k in trusted_keys if k.kid == tok.kid]
    if not candidates:
        raise UnknownIssuer(f"no trusted key with kid={tok.kid}")
    sig = _b64u_decode(tok.signature_b64u)
    from cryptography.exceptions import InvalidSignature as _CIS
    last_err: Exception | None = None
    verified = False
    for k in candidates:
        try:
            k.public_key.verify(sig, tok.signing_input)
            verified = True
            break
        except _CIS as e:
            last_err = e
    if not verified:
        raise InvalidSignature(str(last_err) if last_err else "verify failed")

    # Expiry.
    n = now if now is not None else int(time.time())
    if n >= tok.exp:
        raise ExpiredToken(f"token expired at {tok.exp}, now {n}")
    if n + 1 < tok.iat:
        # Clock skew tolerance: 1 s.
        raise TokenError(f"token issued in the future: iat={tok.iat}, now={n}")

    return tok
