"""
dese.extractors — Entropy extraction from chaotic state trajectories.
=====================================================================

Given a sequence of IEEE 754 binary64 state vectors produced by a
chaotic system, an ``EntropyExtractor`` converts raw floating-point
trajectories into a uniform bitstream.

Methods
-------

``LSBExtractor``
    Extract the least-significant *N* bits of the mantissa from each
    state variable at each step.  The LSBs of a chaotic trajectory
    are maximally sensitive to initial conditions and converge to
    uniform distribution on the attractor.

``XorFoldExtractor``
    XOR all 8 bytes of each float64 together, then XOR across
    state variables.  Produces 1 byte per step — strong mixing.

``HashExtractor``
    SHA-256 hash the raw state bytes at each step, yielding 32 bytes
    of cryptographic-quality entropy per step.  Maximally uniform
    but computationally heavier.

``CompositeExtractor``
    Pipeline: chaotic state → LSB extraction → cryptographic
    conditioning (SHA-256 on blocks of raw LSB output).
    Recommended for production use.
"""

from __future__ import annotations

import hashlib
import struct
from abc import ABC, abstractmethod
from typing import List, Tuple


class EntropyExtractor(ABC):
    """Base class for entropy extraction strategies."""

    @abstractmethod
    def extract_bits(self, state: Tuple[float, ...]) -> bytes:
        """Extract entropy bytes from a single state vector."""

    def extract_stream(self, states: List[Tuple[float, ...]]) -> bytes:
        """Extract and concatenate entropy from a sequence of states."""
        chunks: list[bytes] = []
        for s in states:
            chunks.append(self.extract_bits(s))
        return b"".join(chunks)


class LSBExtractor(EntropyExtractor):
    """
    Extract least-significant bits of IEEE 754 mantissa.

    For each float64, the mantissa occupies bits 0–51.  The lowest
    ``bits_per_var`` bits of each selected variable are extracted
    and packed into bytes (big-endian bit ordering).

    Parameters
    ----------
    bits_per_var : int
        Number of LSBs to extract per variable per step (1–8).
    variables : str or list[int]
        "all" to use every state variable, or list of indices.
    """

    def __init__(self, bits_per_var: int = 8,
                 variables: str | list[int] = "all"):
        if not 1 <= bits_per_var <= 8:
            raise ValueError("bits_per_var must be 1–8")
        self.bits_per_var = bits_per_var
        self.variables = variables

    def _var_indices(self, ndim: int) -> list[int]:
        if self.variables == "all":
            return list(range(ndim))
        return list(self.variables)

    def extract_bits(self, state: Tuple[float, ...]) -> bytes:
        indices = self._var_indices(len(state))
        bit_buffer: list[int] = []

        for idx in indices:
            # IEEE 754 binary64 → 8 bytes → 64-bit int
            raw = struct.pack("<d", state[idx])
            as_int = int.from_bytes(raw, "little")
            # Extract LSBs of the mantissa
            mask = (1 << self.bits_per_var) - 1
            bits = as_int & mask
            # Collect bits MSB-first
            for shift in range(self.bits_per_var - 1, -1, -1):
                bit_buffer.append((bits >> shift) & 1)

        # Pack bits into bytes
        result = bytearray()
        for i in range(0, len(bit_buffer), 8):
            byte_val = 0
            for j in range(8):
                if i + j < len(bit_buffer):
                    byte_val = (byte_val << 1) | bit_buffer[i + j]
                else:
                    byte_val <<= 1
            result.append(byte_val)

        return bytes(result)


class XorFoldExtractor(EntropyExtractor):
    """
    XOR-fold each float64 into a single byte, then XOR across variables.

    Produces exactly 1 byte per step regardless of dimension.
    Strong mixing properties from the XOR cascade.
    """

    def extract_bits(self, state: Tuple[float, ...]) -> bytes:
        result = 0
        for val in state:
            raw = struct.pack("<d", val)
            folded = 0
            for b in raw:
                folded ^= b
            result ^= folded
        return bytes([result])


class HashExtractor(EntropyExtractor):
    """
    SHA-256 hash of the raw state bytes.

    Produces 32 bytes of cryptographic-quality entropy per step.
    The hash acts as a one-way conditioner — even tiny state
    differences produce completely different output.

    Parameters
    ----------
    algo : str
        Hash algorithm name (default "sha256").
    """

    def __init__(self, algo: str = "sha256"):
        self.algo = algo

    def extract_bits(self, state: Tuple[float, ...]) -> bytes:
        raw = struct.pack(f"<{len(state)}d", *state)
        return hashlib.new(self.algo, raw).digest()


class CompositeExtractor(EntropyExtractor):
    """
    Production-grade extractor: LSB extraction + cryptographic conditioning.

    Pipeline:
        1. Extract LSBs from chaotic state (fast, high entropy rate)
        2. Accumulate ``block_size`` raw bytes
        3. SHA-256 condition each block → 32 bytes of output

    This gives the speed of LSB extraction with the uniformity
    guarantee of cryptographic hashing.

    Parameters
    ----------
    bits_per_var : int
        LSBs per variable for the inner LSB extractor.
    block_size : int
        Number of raw LSB bytes to accumulate before hashing (default 64).
    hash_algo : str
        Conditioning hash (default "sha256").
    """

    def __init__(self, bits_per_var: int = 8,
                 block_size: int = 64,
                 hash_algo: str = "sha256"):
        self.inner = LSBExtractor(bits_per_var=bits_per_var)
        self.block_size = block_size
        self.hash_algo = hash_algo
        self._buffer = bytearray()

    def extract_bits(self, state: Tuple[float, ...]) -> bytes:
        raw = self.inner.extract_bits(state)
        self._buffer.extend(raw)
        output = bytearray()
        while len(self._buffer) >= self.block_size:
            block = bytes(self._buffer[:self.block_size])
            self._buffer = self._buffer[self.block_size:]
            output.extend(hashlib.new(self.hash_algo, block).digest())
        return bytes(output)

    def flush(self) -> bytes:
        """Hash any remaining buffered bytes."""
        if self._buffer:
            h = hashlib.new(self.hash_algo, bytes(self._buffer)).digest()
            self._buffer.clear()
            return h
        return b""

    def extract_stream(self, states: List[Tuple[float, ...]]) -> bytes:
        self._buffer.clear()
        chunks = []
        for s in states:
            out = self.extract_bits(s)
            if out:
                chunks.append(out)
        # Flush remainder
        remainder = self.flush()
        if remainder:
            chunks.append(remainder)
        return b"".join(chunks)


# ─── Registry ────────────────────────────────────────────────────────

EXTRACTORS: dict[str, type[EntropyExtractor]] = {
    "lsb": LSBExtractor,
    "xor_fold": XorFoldExtractor,
    "hash": HashExtractor,
    "composite": CompositeExtractor,
}


def create_extractor(name: str, **cfg) -> EntropyExtractor:
    """Instantiate an extractor by name with optional config."""
    cls = EXTRACTORS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown extractor '{name}'. Available: {sorted(EXTRACTORS.keys())}"
        )
    return cls(**cfg)
