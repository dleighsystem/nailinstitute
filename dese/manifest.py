"""
dese.manifest — Schema for deterministic entropy reconstruction.
================================================================

A ``Manifest`` is the *complete specification* required to reproduce
a DESE entropy stream bit-for-bit.  Given an identical manifest, any
conforming implementation on any IEEE 754 platform MUST produce
byte-identical output.

Manifest fields
---------------
- ``schema_version`` — manifest format version (currently "1.0")
- ``system``         — chaotic system identifier (e.g. "lorenz")
- ``params``         — system parameter overrides (σ, ρ, β, …)
- ``initial_state``  — exact initial condition as list of float64
- ``dt``             — integration time-step (float64)
- ``warmup_steps``   — steps to advance before extraction begins
- ``extract_steps``  — number of steps to extract entropy from
- ``extractor``      — extraction method (e.g. "lsb", "xor_fold", "hash")
- ``extractor_cfg``  — method-specific config (bits per step, hash algo, …)
- ``seed_phrase``    — optional human-readable seed → deterministic IC
- ``created_utc``    — ISO 8601 creation timestamp (metadata only)
- ``comment``        — free-text annotation (metadata only)

Serialisation
-------------
Canonical form is minified JSON with sorted keys, UTF-8 encoded.
The manifest's **identity** is the SHA-256 of its canonical form.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class Manifest:
    """Complete specification for a reproducible DESE entropy stream."""

    # ── Required fields ──────────────────────────────────────────────
    system: str                              # e.g. "lorenz"
    initial_state: List[float]               # exact IC as float64 list
    dt: float                                # integration step
    warmup_steps: int                        # discard transient
    extract_steps: int                       # steps to harvest

    # ── Optional: system parameter overrides ─────────────────────────
    params: Dict[str, Any] = field(default_factory=dict)

    # ── Extraction config ────────────────────────────────────────────
    extractor: str = "lsb"                   # extraction method
    extractor_cfg: Dict[str, Any] = field(default_factory=lambda: {
        "bits_per_step": 8,
        "variables": "all",
    })

    # ── Optional: human seed phrase → deterministic IC generation ────
    seed_phrase: Optional[str] = None

    # ── Metadata (not part of deterministic identity) ────────────────
    schema_version: str = "1.0"
    created_utc: Optional[str] = None
    comment: str = ""

    # ── Non-serialised: computed on demand ───────────────────────────
    _identity: Optional[str] = field(default=None, repr=False,
                                     compare=False, init=False)

    def __post_init__(self) -> None:
        if self.created_utc is None:
            self.created_utc = datetime.now(timezone.utc).isoformat()

        # If a seed phrase is given and no explicit IC, derive IC from it
        if self.seed_phrase is not None and all(
            v == 0.0 for v in self.initial_state
        ):
            self.initial_state = self._ic_from_seed(self.seed_phrase,
                                                     len(self.initial_state))

    # ── Canonical serialisation ──────────────────────────────────────

    def _deterministic_dict(self) -> Dict[str, Any]:
        """Return only the fields that affect entropy output."""
        return {
            "schema_version": self.schema_version,
            "system": self.system,
            "params": self.params,
            "initial_state": self.initial_state,
            "dt": self.dt,
            "warmup_steps": self.warmup_steps,
            "extract_steps": self.extract_steps,
            "extractor": self.extractor,
            "extractor_cfg": self.extractor_cfg,
        }

    def canonical_json(self) -> str:
        """Minified JSON with sorted keys — the canonical form."""
        return json.dumps(self._deterministic_dict(), sort_keys=True,
                          separators=(",", ":"))

    @property
    def identity(self) -> str:
        """SHA-256 of the canonical form — the manifest's fingerprint."""
        if self._identity is None:
            raw = self.canonical_json().encode("utf-8")
            self._identity = hashlib.sha256(raw).hexdigest()
        return self._identity

    # ── Full serialisation (includes metadata) ───────────────────────

    def to_dict(self) -> Dict[str, Any]:
        d = self._deterministic_dict()
        d["seed_phrase"] = self.seed_phrase
        d["created_utc"] = self.created_utc
        d["comment"] = self.comment
        d["identity"] = self.identity
        return d

    def to_json(self, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(self.to_dict(), indent=2, sort_keys=True)
        return json.dumps(self.to_dict(), sort_keys=True,
                          separators=(",", ":"))

    def save(self, path: str) -> None:
        """Write manifest to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json(pretty=True))

    @classmethod
    def load(cls, path: str) -> "Manifest":
        """Load manifest from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return cls.from_dict(d)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Manifest":
        """Reconstruct a Manifest from a dict (ignoring computed fields)."""
        return cls(
            system=d["system"],
            initial_state=d["initial_state"],
            dt=d["dt"],
            warmup_steps=d["warmup_steps"],
            extract_steps=d["extract_steps"],
            params=d.get("params", {}),
            extractor=d.get("extractor", "lsb"),
            extractor_cfg=d.get("extractor_cfg", {"bits_per_step": 8,
                                                    "variables": "all"}),
            seed_phrase=d.get("seed_phrase"),
            schema_version=d.get("schema_version", "1.0"),
            created_utc=d.get("created_utc"),
            comment=d.get("comment", ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        return cls.from_dict(json.loads(text))

    # ── Seed phrase → initial conditions ─────────────────────────────

    @staticmethod
    def _ic_from_seed(phrase: str, ndim: int) -> List[float]:
        """
        Derive deterministic initial conditions from a seed phrase.

        Method: HKDF-like.  SHA-512 of the UTF-8 phrase → split into
        8-byte chunks → interpret as IEEE 754 float64 → scale to
        reasonable ranges for chaotic systems (±50).
        """
        raw = hashlib.sha512(phrase.encode("utf-8")).digest()
        values: List[float] = []
        for i in range(ndim):
            chunk = raw[i * 8: (i + 1) * 8]
            # Interpret as unsigned 64-bit int, map to [−50, 50]
            uint = int.from_bytes(chunk, "little", signed=False)
            normalised = uint / (2**64 - 1)       # [0, 1]
            scaled = normalised * 100.0 - 50.0     # [−50, 50]
            values.append(scaled)
        return values

    # ── Convenience constructors ─────────────────────────────────────

    @classmethod
    def lorenz_default(cls, extract_steps: int = 10_000,
                       warmup: int = 1000,
                       comment: str = "") -> "Manifest":
        """Lorenz attractor with classic parameters."""
        return cls(
            system="lorenz",
            initial_state=[1.0, 1.0, 1.0],
            dt=0.005,
            warmup_steps=warmup,
            extract_steps=extract_steps,
            comment=comment,
        )

    @classmethod
    def hyper_lorenz_default(cls, extract_steps: int = 10_000,
                             warmup: int = 1000,
                             comment: str = "") -> "Manifest":
        """4D Hyperchaotic Lorenz — higher entropy rate."""
        return cls(
            system="hyper_lorenz",
            initial_state=[1.0, 1.0, 1.0, 1.0],
            dt=0.005,
            warmup_steps=warmup,
            extract_steps=extract_steps,
            comment=comment,
        )

    @classmethod
    def from_seed(cls, phrase: str, system: str = "lorenz",
                  extract_steps: int = 10_000,
                  warmup: int = 1000,
                  comment: str = "") -> "Manifest":
        """Create a manifest from a human-readable seed phrase."""
        from dese.systems import SYSTEMS
        sys_cls = SYSTEMS.get(system)
        if sys_cls is None:
            raise ValueError(f"Unknown system: {system}")
        ndim = sys_cls().dimension
        ic = cls._ic_from_seed(phrase, ndim)
        return cls(
            system=system,
            initial_state=ic,
            dt=sys_cls()._dt,
            warmup_steps=warmup,
            extract_steps=extract_steps,
            seed_phrase=phrase,
            comment=comment,
        )

    def __repr__(self) -> str:
        return (
            f"Manifest(system={self.system!r}, "
            f"ic={[round(v, 6) for v in self.initial_state]}, "
            f"steps={self.extract_steps}, "
            f"id={self.identity[:12]}…)"
        )
