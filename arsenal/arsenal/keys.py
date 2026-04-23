"""Issuer keypair management.

Arsenal uses ed25519 for token signatures (compact 64-byte signatures, fast,
deterministic, no nonce-reuse risk). Keys live in ``~/.nail/arsenal/`` by
default, with file-mode 0600 on the private key.

Typical layout:

    ~/.nail/arsenal/
        nail-arsenal-1.priv      (32 bytes, raw)
        nail-arsenal-1.pub       (32 bytes, raw)
        nail-arsenal-1.kid       (text: 8-hex-char key id)
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)


@dataclass
class IssuerKey:
    """An ed25519 keypair (or just the public half) with a stable key id."""
    kid: str
    private_key: Ed25519PrivateKey | None
    public_key: Ed25519PublicKey

    @property
    def public_bytes(self) -> bytes:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def has_private(self) -> bool:
        return self.private_key is not None


def default_key_dir() -> Path:
    return Path(os.environ.get(
        "NAIL_ARSENAL_KEYS",
        Path.home() / ".nail" / "arsenal",
    ))


def _kid_from_pubkey(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()[:8]


def generate_keypair(*, name: str = "nail-arsenal-1",
                     directory: Path | None = None,
                     overwrite: bool = False) -> IssuerKey:
    """Create a new ed25519 keypair on disk and return it."""
    d = directory or default_key_dir()
    d.mkdir(parents=True, exist_ok=True)
    priv_path = d / f"{name}.priv"
    pub_path = d / f"{name}.pub"
    kid_path = d / f"{name}.kid"

    if priv_path.exists() and not overwrite:
        raise FileExistsError(
            f"private key already exists: {priv_path} (use overwrite=True)"
        )

    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()

    priv_raw = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    kid = _kid_from_pubkey(pub_raw)

    priv_path.write_bytes(priv_raw)
    try:
        os.chmod(priv_path, 0o600)
    except OSError:
        pass  # Windows / restricted FS — best-effort
    pub_path.write_bytes(pub_raw)
    kid_path.write_text(kid + "\n")

    return IssuerKey(kid=kid, private_key=sk, public_key=pk)


def load_keypair(*, name: str = "nail-arsenal-1",
                 directory: Path | None = None,
                 require_private: bool = False) -> IssuerKey:
    """Load a keypair from disk. If only the .pub exists, returns a
    public-only IssuerKey (suitable for verification only)."""
    d = directory or default_key_dir()
    priv_path = d / f"{name}.priv"
    pub_path = d / f"{name}.pub"

    if not pub_path.exists():
        raise FileNotFoundError(f"missing public key: {pub_path}")

    pub_raw = pub_path.read_bytes()
    pk = Ed25519PublicKey.from_public_bytes(pub_raw)
    kid = _kid_from_pubkey(pub_raw)

    sk: Ed25519PrivateKey | None = None
    if priv_path.exists():
        sk = Ed25519PrivateKey.from_private_bytes(priv_path.read_bytes())
    elif require_private:
        raise FileNotFoundError(f"missing private key: {priv_path}")

    return IssuerKey(kid=kid, private_key=sk, public_key=pk)


def load_or_create(*, name: str = "nail-arsenal-1",
                   directory: Path | None = None) -> IssuerKey:
    """Load the keypair if it exists, otherwise generate one."""
    try:
        return load_keypair(name=name, directory=directory,
                            require_private=True)
    except FileNotFoundError:
        return generate_keypair(name=name, directory=directory)
