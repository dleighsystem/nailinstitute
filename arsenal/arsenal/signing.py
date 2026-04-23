"""Generic ed25519 sign/verify over arbitrary blobs.

Used by:
- ``arsenal.tokens``  — signs the header.payload portion of a capability token
- ``diagnostic`` /     — signs the certificate JSON (so deployment gates can
  ``scripts/nail_deploy``  verify cert authenticity)
"""
from __future__ import annotations

import base64
import hashlib
from typing import Iterable

from cryptography.exceptions import InvalidSignature as _CryptoInvalidSig

from .errors import InvalidSignature
from .keys import IssuerKey


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_blob(data: bytes, *, key: IssuerKey) -> str:
    """Return a base64url-encoded ed25519 signature over ``data``.

    The format is ``"<kid>.<sig_b64u>"`` so the verifier can pick the right
    public key without trial-and-error.
    """
    if not key.has_private:
        raise ValueError("key has no private half — cannot sign")
    sig = key.private_key.sign(data)  # type: ignore[union-attr]
    return f"{key.kid}.{_b64u(sig)}"


def verify_blob(data: bytes, signature: str, *,
                trusted_keys: Iterable[IssuerKey]) -> IssuerKey:
    """Raise InvalidSignature if ``signature`` does not match any trusted key.
    Returns the IssuerKey that successfully verified."""
    if "." not in signature:
        raise InvalidSignature("signature missing kid prefix")
    kid, sig_b64u = signature.split(".", 1)
    sig = _b64u_decode(sig_b64u)
    keys = [k for k in trusted_keys if k.kid == kid]
    if not keys:
        raise InvalidSignature(f"no trusted key matches kid={kid}")
    last_err: Exception | None = None
    for k in keys:
        try:
            k.public_key.verify(sig, data)
            return k
        except _CryptoInvalidSig as e:
            last_err = e
    raise InvalidSignature(str(last_err) if last_err else "unknown")


def hash_blob(data: bytes) -> str:
    """Convenience sha256 hex digest, used as a content-binding claim."""
    return hashlib.sha256(data).hexdigest()
