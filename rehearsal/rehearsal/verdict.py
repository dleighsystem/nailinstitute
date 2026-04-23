"""Verdict — the policy-decision returned by a sandbox rehearsal."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Outcome(str, Enum):
    ALLOW = "allow"
    HOLD = "hold"
    DENY = "deny"


@dataclass
class Verdict:
    """Output of a policy function. The decorator uses this to decide
    whether to invoke the real tool, hold for confirmation, or reject."""
    outcome: Outcome
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── factories ───────────────────────────────────────────────
    @classmethod
    def allow(cls, reason: str = "ok", **md: Any) -> "Verdict":
        return cls(Outcome.ALLOW, reason, dict(md))

    @classmethod
    def hold(cls, reason: str, **md: Any) -> "Verdict":
        return cls(Outcome.HOLD, reason, dict(md))

    @classmethod
    def deny(cls, reason: str, **md: Any) -> "Verdict":
        return cls(Outcome.DENY, reason, dict(md))

    # ── predicates ──────────────────────────────────────────────
    @property
    def allowed(self) -> bool: return self.outcome == Outcome.ALLOW
    @property
    def held(self)    -> bool: return self.outcome == Outcome.HOLD
    @property
    def denied(self)  -> bool: return self.outcome == Outcome.DENY

    def to_dict(self) -> dict:
        return {"outcome": self.outcome.value, "reason": self.reason,
                "metadata": dict(self.metadata)}


class RehearsalError(Exception):
    """Base class for rehearsal-flow exceptions."""


class RehearsalDenied(RehearsalError):
    """The sandbox denied the tool call — must NOT proceed to real impl."""
    def __init__(self, tool: str, verdict: Verdict) -> None:
        super().__init__(f"DENY {tool}: {verdict.reason}")
        self.tool = tool
        self.verdict = verdict


class RehearsalHeld(RehearsalError):
    """The sandbox held the tool call — needs explicit confirmation."""
    def __init__(self, tool: str, verdict: Verdict) -> None:
        super().__init__(f"HOLD {tool}: {verdict.reason}")
        self.tool = tool
        self.verdict = verdict
