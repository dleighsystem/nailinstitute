"""
dese.engine — Core DESE execution engine.
==========================================

The ``DESEEngine`` is the central orchestrator.  Given a ``Manifest``,
it:
    1. Instantiates the specified chaotic system with exact parameters
    2. Runs the warm-up phase (discard transient, settle on attractor)
    3. Executes the extraction phase, collecting state vectors
    4. Passes states through the configured entropy extractor
    5. Returns the raw entropy bytes plus an ``ExecutionRecord``

The engine is *stateless* between runs — call ``generate()`` with a
manifest and receive deterministic output.  Call it again with the
same manifest and receive byte-identical output.

Verification
------------
``verify()`` re-generates from a manifest and compares against a
reference output, returning True only on exact match.
"""

from __future__ import annotations

import hashlib
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dese.manifest import Manifest
from dese.systems import ChaoticSystem, create_system
from dese.extractors import (
    EntropyExtractor, create_extractor,
    LSBExtractor, XorFoldExtractor, HashExtractor, CompositeExtractor,
)


@dataclass
class ExecutionRecord:
    """Immutable record of a DESE generation run."""
    manifest_identity: str
    system: str
    warmup_steps: int
    extract_steps: int
    extractor: str
    output_bytes: int
    output_sha256: str
    elapsed_seconds: float
    entropy_rate_bps: float          # bits per simulation step
    throughput_kbps: float           # kilobytes per second
    final_state: List[float]         # state after extraction (for chaining)
    warmup_final_state: List[float]  # state just before extraction began

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_identity": self.manifest_identity,
            "system": self.system,
            "warmup_steps": self.warmup_steps,
            "extract_steps": self.extract_steps,
            "extractor": self.extractor,
            "output_bytes": self.output_bytes,
            "output_sha256": self.output_sha256,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "entropy_rate_bps": round(self.entropy_rate_bps, 2),
            "throughput_kbps": round(self.throughput_kbps, 2),
            "final_state": self.final_state,
            "warmup_final_state": self.warmup_final_state,
        }


class DESEEngine:
    """
    Deterministic Entropy Simulation Engine.

    Usage::

        engine = DESEEngine()
        manifest = Manifest.lorenz_default(extract_steps=100_000)
        entropy, record = engine.generate(manifest)
        assert engine.verify(manifest, entropy)
    """

    def generate(self, manifest: Manifest) -> Tuple[bytes, ExecutionRecord]:
        """
        Generate entropy bytes from a manifest.

        Returns
        -------
        entropy : bytes
            The extracted entropy stream.
        record : ExecutionRecord
            Metadata about the generation run.
        """
        t0 = time.perf_counter()

        # 1. Instantiate system
        sys_kwargs = dict(manifest.params)
        # Map initial state to system-specific field names
        system = create_system(manifest.system, **sys_kwargs)
        self._set_initial_state(system, manifest.initial_state)
        system._dt = manifest.dt

        # 2. Warm-up phase: advance past transient
        system.advance(manifest.warmup_steps)
        warmup_final = list(system.state)

        # 3. Extraction phase: collect state vectors
        states: list[Tuple[float, ...]] = []
        for _ in range(manifest.extract_steps):
            system.step()
            states.append(system.state)

        final_state = list(system.state)

        # 4. Create extractor and extract entropy
        extractor = self._create_extractor(manifest)
        entropy = extractor.extract_stream(states)

        elapsed = time.perf_counter() - t0

        # 5. Compute metrics
        output_bits = len(entropy) * 8
        entropy_rate = output_bits / manifest.extract_steps if manifest.extract_steps > 0 else 0.0
        throughput = (len(entropy) / 1024.0) / elapsed if elapsed > 0 else 0.0

        record = ExecutionRecord(
            manifest_identity=manifest.identity,
            system=manifest.system,
            warmup_steps=manifest.warmup_steps,
            extract_steps=manifest.extract_steps,
            extractor=manifest.extractor,
            output_bytes=len(entropy),
            output_sha256=hashlib.sha256(entropy).hexdigest(),
            elapsed_seconds=elapsed,
            entropy_rate_bps=entropy_rate,
            throughput_kbps=throughput,
            final_state=final_state,
            warmup_final_state=warmup_final,
        )

        return entropy, record

    def verify(self, manifest: Manifest, reference: bytes) -> bool:
        """
        Verify that a manifest reproduces the reference entropy exactly.

        Returns True if and only if regenerated output is byte-identical.
        """
        entropy, _ = self.generate(manifest)
        return entropy == reference

    def generate_hex(self, manifest: Manifest) -> Tuple[str, ExecutionRecord]:
        """Generate entropy and return as hex string."""
        entropy, record = self.generate(manifest)
        return entropy.hex(), record

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _set_initial_state(system: ChaoticSystem,
                            ic: List[float]) -> None:
        """Set the system's state from the manifest's initial_state list."""
        if len(ic) != system.dimension:
            raise ValueError(
                f"Manifest IC has {len(ic)} values but system "
                f"'{type(system).__name__}' requires {system.dimension}"
            )
        system._set_state(tuple(ic))

    @staticmethod
    def _create_extractor(manifest: Manifest) -> EntropyExtractor:
        """Build the configured entropy extractor."""
        cfg = dict(manifest.extractor_cfg)
        name = manifest.extractor

        # Map manifest config keys to constructor args
        if name == "lsb":
            return LSBExtractor(
                bits_per_var=cfg.get("bits_per_var", 8),
                variables=cfg.get("variables", "all"),
            )
        elif name == "xor_fold":
            return XorFoldExtractor()
        elif name == "hash":
            return HashExtractor(algo=cfg.get("algo", "sha256"))
        elif name == "composite":
            return CompositeExtractor(
                bits_per_var=cfg.get("bits_per_var", 8),
                block_size=cfg.get("block_size", 64),
                hash_algo=cfg.get("hash_algo", "sha256"),
            )
        else:
            return create_extractor(name, **cfg)
