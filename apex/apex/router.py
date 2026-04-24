"""Routers — decide whether a query goes to System 1 or System 2.

Two implementations:

* `CosineRouter` — sentence-transformer cosine similarity vs anchor sets.
  Pure Python at inference. Optional dep on `sentence-transformers`.
* `GuardRouter`  — calls a local Ollama classifier (default `nail-guard:v4`)
  and parses the verdict. Falls back to `CosineRouter` on any failure.

Both implement the `Router` Protocol.

`DomainRouter` is the same mechanism parameterised by domain anchors;
useful for fan-out into per-domain LoRAs (kept here for the apex_matrix
roadmap but not required by `ApexBrain`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol, runtime_checkable


# ── public constants ──────────────────────────────────────────────────
SYSTEM_1 = "SYSTEM_1"
SYSTEM_2 = "SYSTEM_2"

DEFAULT_SYS1_ANCHORS: tuple[str, ...] = (
    "Hi, how are you?",
    "What is the capital of France?",
    "Summarise this email for me.",
    "Write a polite reply to my boss.",
    "Translate this sentence to Spanish.",
    "What is a good recipe for pancakes?",
    "Tell me a joke.",
    "Format this as a bullet list.",
)
DEFAULT_SYS2_ANCHORS: tuple[str, ...] = (
    "Prove that the square root of 2 is irrational.",
    "Write a multi-threaded web scraper in Rust.",
    "Solve the Navier-Stokes equation.",
    "Natalia sold 48 clips in April, and half as many in May.",
    "What is the time complexity of QuickSort and why?",
    "If A implies B, and B is false, is A true?",
    "Audit this Python function for security vulnerabilities.",
    "Design a fault-tolerant distributed lock.",
)


# ── Protocol ─────────────────────────────────────────────────────────
@runtime_checkable
class Router(Protocol):
    def classify(self, query: str) -> str: ...


# ── helpers ──────────────────────────────────────────────────────────
def _cosine(v1, v2) -> float:
    """Cosine sim of two equal-length sequences. Pure Python so we
    don't drag numpy in as a hard dep."""
    n = len(v1)
    if n == 0 or n != len(v2):
        return 0.0
    dot = sum(v1[i] * v2[i] for i in range(n))
    n1 = math.sqrt(sum(x * x for x in v1))
    n2 = math.sqrt(sum(x * x for x in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def _mean_vec(vecs):
    n = len(vecs)
    if n == 0:
        return []
    width = len(vecs[0])
    out = [0.0] * width
    for v in vecs:
        for i in range(width):
            out[i] += v[i]
    return [x / n for x in out]


# ── CosineRouter ──────────────────────────────────────────────────────
@dataclass
class CosineRouter:
    """Sentence-transformer cosine router.

    `sys2_bias` shifts the decision boundary toward SYSTEM_2 to be
    safe on ambiguous queries (matches apex_matrix's original 0.05
    bias). Set to 0 for a strict majority vote.
    """
    sys1_anchors: tuple[str, ...] = DEFAULT_SYS1_ANCHORS
    sys2_anchors: tuple[str, ...] = DEFAULT_SYS2_ANCHORS
    model_name: str = "all-MiniLM-L6-v2"
    sys2_bias: float = 0.05
    encoder: object | None = None       # injectable for tests

    centroid_sys1: list[float] = field(init=False, default_factory=list)
    centroid_sys2: list[float] = field(init=False, default_factory=list)
    _ready: bool = field(init=False, default=False)

    def _load_encoder(self):
        if self.encoder is not None:
            return self.encoder
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "CosineRouter needs sentence-transformers; either"
                " `pip install sentence-transformers` or pass an"
                " `encoder=` callable returning list[list[float]]"
            ) from exc
        self.encoder = SentenceTransformer(self.model_name)
        return self.encoder

    def _encode(self, texts: Iterable[str]) -> list[list[float]]:
        enc = self._load_encoder()
        # Sentence-transformers returns numpy; we tolist() for purity.
        # A test stub may already return list[list[float]].
        out = enc.encode(list(texts))
        if hasattr(out, "tolist"):
            return out.tolist()
        return [list(v) for v in out]

    def _ensure(self) -> None:
        if self._ready:
            return
        s1 = self._encode(self.sys1_anchors)
        s2 = self._encode(self.sys2_anchors)
        self.centroid_sys1 = _mean_vec(s1)
        self.centroid_sys2 = _mean_vec(s2)
        self._ready = True

    def score(self, query: str) -> tuple[float, float]:
        """Returns (sim_sys1, sim_sys2)."""
        self._ensure()
        q = self._encode([query])[0]
        return (_cosine(q, self.centroid_sys1),
                _cosine(q, self.centroid_sys2))

    def classify(self, query: str) -> str:
        s1, s2 = self.score(query)
        # bias nudges ambiguous-but-leaning-sys1 calls toward SYSTEM_2
        if s2 + self.sys2_bias > s1:
            return SYSTEM_2
        return SYSTEM_1


# ── GuardRouter ───────────────────────────────────────────────────────
@dataclass
class GuardRouter:
    """Use `nail-guard:v4` (or any Ollama classifier) to pick the system.

    Sends a tiny structured prompt asking for "FAST" or "DEEP" and parses
    the first line. On any error (including timeout / model not loaded)
    falls back to the configured `fallback` router.
    """
    model: str = "nail-guard:v4"
    client: Optional[object] = None
    fallback: Optional[Router] = None
    timeout_s: float = 5.0

    SYSTEM_PROMPT = (
        "You classify a user query as FAST or DEEP.\n"
        "FAST = chat, formatting, summary, simple recall.\n"
        "DEEP = math, code, multi-step logic, security analysis.\n"
        "Answer with EXACTLY one word: FAST or DEEP."
    )

    def _client(self):
        if self.client is not None:
            return self.client
        from .ollama_client import OllamaClient
        self.client = OllamaClient()
        return self.client

    def _fallback(self) -> Router:
        if self.fallback is None:
            self.fallback = CosineRouter()
        return self.fallback

    def classify(self, query: str) -> str:
        try:
            raw = self._client().generate(
                self.model, query,
                system=self.SYSTEM_PROMPT,
                options={"temperature": 0.0, "num_predict": 4},
                timeout=self.timeout_s,
            )
        except Exception:
            return self._fallback().classify(query)

        token = (raw or "").strip().split()
        if not token:
            return self._fallback().classify(query)
        head = token[0].upper().strip(".,:!?")
        if head.startswith("DEEP"):
            return SYSTEM_2
        if head.startswith("FAST"):
            return SYSTEM_1
        return self._fallback().classify(query)


# ── DomainRouter (kept for roadmap, not used by ApexBrain) ───────────
@dataclass
class DomainRouter:
    """Cosine router parameterised by domain anchors → label name."""
    anchors: dict[str, tuple[str, ...]]
    model_name: str = "all-MiniLM-L6-v2"
    encoder: object | None = None
    centroids: dict[str, list[float]] = field(init=False, default_factory=dict)
    _ready: bool = field(init=False, default=False)

    def _load_encoder(self):
        if self.encoder is not None:
            return self.encoder
        from sentence_transformers import SentenceTransformer
        self.encoder = SentenceTransformer(self.model_name)
        return self.encoder

    def _encode(self, texts: Iterable[str]) -> list[list[float]]:
        enc = self._load_encoder()
        out = enc.encode(list(texts))
        if hasattr(out, "tolist"):
            return out.tolist()
        return [list(v) for v in out]

    def _ensure(self) -> None:
        if self._ready:
            return
        for label, texts in self.anchors.items():
            vecs = self._encode(texts)
            self.centroids[label] = _mean_vec(vecs)
        self._ready = True

    def classify(self, query: str) -> str:
        self._ensure()
        q = self._encode([query])[0]
        best_label, best_score = "", -2.0
        for label, c in self.centroids.items():
            s = _cosine(q, c)
            if s > best_score:
                best_label, best_score = label, s
        return best_label
