"""Sandbox — the registry of shadow tool implementations + policies.

A *shadow impl* is a cheap, pure-Python model of a tool's side-effect.
It must NEVER perform real I/O (no HTTP, no DB writes, no payments). Its
only job is to compute "what would happen" so the policy can score it.

A *policy* takes (args, shadow_result, world) and returns a Verdict.

A *world* is an opaque dict the host hands to the sandbox for evaluation
(e.g. account balances, current inventory, today's spend so far). The
sandbox treats it as read-only context for the policy.
"""
from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .verdict import Verdict, Outcome


ShadowFn = Callable[..., Any]
PolicyFn = Callable[[dict, Any, dict], Verdict]


class ShadowMissing(KeyError):
    """No shadow impl registered for this tool."""


class PolicyMissing(KeyError):
    """No policy registered for this tool."""


@dataclass
class RehearsalReceipt:
    """Returned from ``Sandbox.rehearse``. Useful for the recorder."""
    tool: str
    args: dict
    shadow_result: Any
    verdict: Verdict
    duration_ms: float
    world_snapshot_hash: str = ""


class Sandbox:
    """Shadow + policy registry. A single sandbox typically lives for the
    process lifetime (one per agent) — share it across decorated tools."""

    def __init__(self) -> None:
        self._shadows: dict[str, ShadowFn] = {}
        self._policies: dict[str, PolicyFn] = {}
        # Default policy used when a tool registers a shadow but no policy.
        self._default_policy: PolicyFn = lambda a, s, w: Verdict.allow(
            "no policy registered (default ALLOW)"
        )

    # ── registration ─────────────────────────────────────────────
    def shadow(self, tool: str) -> Callable[[ShadowFn], ShadowFn]:
        """Decorator: register a shadow impl for ``tool``."""
        def deco(fn: ShadowFn) -> ShadowFn:
            self._shadows[tool] = fn
            return fn
        return deco

    def policy(self, tool: str) -> Callable[[PolicyFn], PolicyFn]:
        """Decorator: register a policy for ``tool``."""
        def deco(fn: PolicyFn) -> PolicyFn:
            self._policies[tool] = fn
            return fn
        return deco

    def register_shadow(self, tool: str, fn: ShadowFn) -> None:
        self._shadows[tool] = fn

    def register_policy(self, tool: str, fn: PolicyFn) -> None:
        self._policies[tool] = fn

    def set_default_policy(self, fn: PolicyFn) -> None:
        self._default_policy = fn

    # ── introspection ────────────────────────────────────────────
    def has_shadow(self, tool: str) -> bool: return tool in self._shadows
    def has_policy(self, tool: str) -> bool: return tool in self._policies
    def tools(self) -> list[str]: return sorted(self._shadows)

    # ── rehearse ─────────────────────────────────────────────────
    def rehearse(self, tool: str, *,
                 args: dict | None = None,
                 world: dict | None = None,
                 strict: bool = True) -> RehearsalReceipt:
        """Run the shadow + policy. Returns a receipt with the verdict.

        ``strict=True`` raises ShadowMissing / PolicyMissing when those
        aren't registered. ``strict=False`` falls back to NO-OP shadow
        (returns ``None``) and the default policy (ALLOW), useful for
        tools that don't have side-effects worth modelling.
        """
        args = dict(args or {})
        world = dict(world or {})

        if tool not in self._shadows:
            if strict:
                raise ShadowMissing(f"no shadow registered for tool={tool!r}")
            shadow_fn: ShadowFn = lambda **_: None
        else:
            shadow_fn = self._shadows[tool]

        if tool not in self._policies:
            if strict:
                raise PolicyMissing(f"no policy registered for tool={tool!r}")
            policy_fn = self._default_policy
        else:
            policy_fn = self._policies[tool]

        t0 = time.perf_counter()
        # Defensive copy of args for the shadow: the shadow MUST NOT mutate
        # the caller's dict, but we can't enforce that — at least snapshot.
        shadow_result = shadow_fn(**copy.deepcopy(args))
        verdict = policy_fn(args, shadow_result, world)
        if not isinstance(verdict, Verdict):
            raise TypeError(
                f"policy for {tool!r} returned {type(verdict).__name__}, "
                "expected Verdict"
            )
        dt_ms = (time.perf_counter() - t0) * 1000.0

        return RehearsalReceipt(
            tool=tool, args=args, shadow_result=shadow_result,
            verdict=verdict, duration_ms=dt_ms,
        )
