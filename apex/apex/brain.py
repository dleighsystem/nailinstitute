"""ApexBrain — top-level orchestrator.

Pipeline:

    1. (optional) shield.process(query, source="user")  → ShieldedInput
    2. router.classify(query)                           → SYSTEM_1|SYSTEM_2
    3. SYSTEM_1: System1.invoke(query)                  → str
       SYSTEM_2: System2.invoke(query)                  → TTCResult
    4. fleet.safe_emit("apex.process", ...)             → telemetry

Every external dep (shield, foresight, fleet) is optional and resolved
lazily; ApexBrain remains usable as a pure router-+-LLM wrapper if those
packages are absent.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from . import _bridges
from ._telemetry import default_agent_id, telemetry_emit
from .router import CosineRouter, GuardRouter, Router, SYSTEM_1, SYSTEM_2
from .system1 import System1
from .system2 import System2, TTCResult


@dataclass
class ApexResponse:
    """Everything ApexBrain produces for one query."""
    query: str
    answer: str
    system: str                      # "SYSTEM_1" | "SYSTEM_2"
    thought: str = ""
    duration_ms: float = 0.0
    routed_in_ms: float = 0.0
    shielded: bool = False
    shield_blocked: bool = False
    shield_reason: str = ""
    n_secrets: int = 0
    is_injection: bool | None = None
    error: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answer": self.answer,
            "system": self.system,
            "thought_tokens": len(self.thought.split()) if self.thought else 0,
            "duration_ms": round(self.duration_ms, 2),
            "routed_in_ms": round(self.routed_in_ms, 2),
            "shielded": self.shielded,
            "shield_blocked": self.shield_blocked,
            "shield_reason": self.shield_reason,
            "n_secrets": self.n_secrets,
            "is_injection": self.is_injection,
            "error": self.error,
            "extras": dict(self.extras),
        }


@dataclass
class ApexBrain:
    """Cognitive front-end. All optional NAIL bridges are auto-detected.

    Configuration knobs:
      router          — anything implementing Router; default CosineRouter()
      system1, system2— defaults to System1()/System2() with prod models
      enable_shield   — bool. None = auto (use shield if importable)
      enable_telemetry— bool. None = always try (fail-safe)
      block_on_injection — if shield flags injection, refuse with a stock reply
      agent_id        — telemetry tag; default from $NAIL_AGENT_ID or "apex"
    """
    router: Optional[Router] = None
    system1: Optional[System1] = None
    system2: Optional[System2] = None
    enable_shield: Optional[bool] = None
    enable_telemetry: bool = True
    block_on_injection: bool = True
    agent_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.router is None:
            # Default: cheapest router that doesn't need Ollama at boot.
            self.router = CosineRouter()
        if self.system1 is None:
            self.system1 = System1()
        if self.system2 is None:
            self.system2 = System2()
        if self.agent_id is None:
            self.agent_id = default_agent_id("apex")
        if self.enable_shield is None:
            self.enable_shield = _bridges.shield() is not None

    # ── public API ────────────────────────────────────────────────
    def process(self, query: str) -> ApexResponse:
        t0 = time.perf_counter()
        resp = ApexResponse(query=query, answer="", system="")

        # 1. shield
        shielded_text = query
        if self.enable_shield:
            sh = _bridges.shield()
            if sh is not None:
                try:
                    out = sh.process(query, source="user")
                    resp.shielded = True
                    resp.n_secrets = sum(out.secret_counts.values()) \
                        if out.secret_counts else 0
                    resp.is_injection = out.is_injection
                    if self.block_on_injection and out.is_injection:
                        resp.shield_blocked = True
                        resp.shield_reason = out.injection_reason or "injection"
                        resp.answer = (
                            "Refusing: input flagged as prompt-injection "
                            "by shield."
                        )
                        resp.system = "SHIELD_BLOCK"
                        resp.duration_ms = (time.perf_counter() - t0) * 1000
                        self._emit(resp, severity="error")
                        return resp
                    # We use the original query for routing/LLM; shield's
                    # canonical text is for downstream tools, not for the
                    # natural-language LLM hop.
                except Exception as exc:
                    resp.shielded = False
                    resp.shield_reason = f"shield error: {exc}"

        # 2. route
        t_route = time.perf_counter()
        try:
            system = self.router.classify(query)
        except Exception as exc:
            system = SYSTEM_1
            resp.extras["router_error"] = str(exc)
        resp.routed_in_ms = (time.perf_counter() - t_route) * 1000
        resp.system = system

        # 3. invoke
        if system == SYSTEM_2:
            assert self.system2 is not None
            ttc = self.system2.invoke(query)
            resp.answer = ttc.answer
            resp.thought = ttc.thought
            resp.extras["had_thought_block"] = ttc.had_thought_block
            resp.extras["had_answer_block"] = ttc.had_answer_block
            if ttc.error:
                resp.error = ttc.error
        else:
            assert self.system1 is not None
            resp.answer = self.system1.invoke(query)

        resp.duration_ms = (time.perf_counter() - t0) * 1000

        # 4. telemetry
        sev = "warn" if (resp.error or resp.is_injection) else "info"
        self._emit(resp, severity=sev)
        return resp

    # ── private ──────────────────────────────────────────────────
    def _emit(self, resp: ApexResponse, *, severity: str) -> None:
        if not self.enable_telemetry:
            return
        attrs = {
            "system": resp.system,
            "duration_ms": round(resp.duration_ms, 2),
            "routed_in_ms": round(resp.routed_in_ms, 2),
            "shielded": resp.shielded,
            "shield_blocked": resp.shield_blocked,
            "n_secrets": resp.n_secrets,
            "is_injection": resp.is_injection,
            "thought_tokens": len(resp.thought.split()) if resp.thought else 0,
            "query_len": len(resp.query),
            "answer_len": len(resp.answer),
        }
        if resp.error:
            attrs["error"] = resp.error[:200]
        telemetry_emit("apex.process",
                       agent_id=self.agent_id or "apex",
                       severity=severity, attrs=attrs)
