"""
Sandbox — Isolated execution environment for a challenge attempt.

Each participant × challenge combination gets its own Sandbox. The sandbox
tracks conversation turns, token usage, elapsed time, captured flags, and
enforces the challenge's constraints (turn limit, token budget, time limit).

The Sandbox does NOT run an actual LLM — it provides the accounting and
constraint-enforcement layer. In production, a real agent would be wired
in via the `interact()` callback. For testing/scoring, we use the
`simulate_response()` path.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .challenge import Challenge, Flag


class SandboxState(str, Enum):
    """Lifecycle state of a sandbox instance."""
    READY = "ready"            # Created, awaiting first interaction
    ACTIVE = "active"          # Participant is interacting
    COMPLETED = "completed"    # All flags captured or voluntarily ended
    TIMED_OUT = "timed_out"    # Time limit exceeded
    EXHAUSTED = "exhausted"    # Turn or token budget exceeded
    TERMINATED = "terminated"  # Forcibly stopped by admin


@dataclass
class Turn:
    """A single conversation exchange in the sandbox."""
    turn_number: int
    user_input: str
    agent_response: str
    tokens_used: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "user_input": self.user_input,
            "agent_response": self.agent_response,
            "tokens_used": self.tokens_used,
            "timestamp": self.timestamp,
        }


@dataclass
class SandboxConfig:
    """
    Configuration for a sandbox instance derived from a Challenge.
    """
    max_turns: int = 50
    token_budget: int = 10000
    time_limit_s: int = 0
    agent_persona: str = "You are a helpful AI assistant."
    defences: list[str] = field(default_factory=list)

    @classmethod
    def from_challenge(cls, challenge: Challenge) -> SandboxConfig:
        return cls(
            max_turns=challenge.max_turns,
            token_budget=challenge.token_budget,
            time_limit_s=challenge.time_limit_s,
            agent_persona=challenge.agent_persona,
            defences=list(challenge.defences),
        )


@dataclass
class Sandbox:
    """
    Isolated execution environment for one participant's attempt at one challenge.

    Tracks turns, token usage, time, and captured flags. Enforces all
    challenge constraints.

    Attributes:
        sandbox_id:     Unique identifier.
        challenge_id:   Which challenge this sandbox runs.
        team_name:      Which team/participant owns this sandbox.
        config:         Execution constraints.
        state:          Current lifecycle state.
        turns:          Conversation history.
        tokens_consumed: Running token count.
        flags_captured: Set of captured flag IDs.
        start_time:     When the first interaction happened.
    """
    challenge: Challenge
    team_name: str
    config: SandboxConfig = field(default=None)  # type: ignore[assignment]
    sandbox_id: str = field(default_factory=lambda: f"sb-{uuid.uuid4().hex[:8]}")
    state: SandboxState = SandboxState.READY
    turns: list[Turn] = field(default_factory=list)
    tokens_consumed: int = 0
    flags_captured: set[str] = field(default_factory=set)
    start_time: float = 0.0
    end_time: float = 0.0

    def __post_init__(self):
        if self.config is None:
            self.config = SandboxConfig.from_challenge(self.challenge)

    # ── Interaction ─────────────────────────────────────────────

    def interact(
        self,
        user_input: str,
        response_callback: Callable[[str, str], str] | None = None,
    ) -> Turn:
        """
        Process one conversation turn.

        If `response_callback` is provided, it receives (system_prompt, user_input)
        and returns the agent's response. Otherwise, `simulate_response()` is used.

        Returns the Turn, or raises if sandbox constraints are violated.
        """
        if self.state in (SandboxState.COMPLETED, SandboxState.TIMED_OUT,
                          SandboxState.EXHAUSTED, SandboxState.TERMINATED):
            raise RuntimeError(f"Sandbox {self.sandbox_id} is in terminal state: {self.state.value}")

        # Start the clock on first interaction
        if self.state == SandboxState.READY:
            self.state = SandboxState.ACTIVE
            self.start_time = time.time()

        # Check time limit
        if self.config.time_limit_s > 0:
            elapsed = time.time() - self.start_time
            if elapsed > self.config.time_limit_s:
                self.state = SandboxState.TIMED_OUT
                self.end_time = time.time()
                raise RuntimeError(f"Time limit exceeded ({self.config.time_limit_s}s)")

        # Check turn limit
        if len(self.turns) >= self.config.max_turns:
            self.state = SandboxState.EXHAUSTED
            self.end_time = time.time()
            raise RuntimeError(f"Turn limit exceeded ({self.config.max_turns})")

        # Generate response
        if response_callback:
            agent_response = response_callback(self.config.agent_persona, user_input)
        else:
            agent_response = self._simulate_response(user_input)

        # Estimate tokens (rough: 1 token ≈ 4 chars)
        tokens = (len(user_input) + len(agent_response)) // 4
        self.tokens_consumed += tokens

        turn = Turn(
            turn_number=len(self.turns) + 1,
            user_input=user_input,
            agent_response=agent_response,
            tokens_used=tokens,
        )
        self.turns.append(turn)

        # Check token budget
        if self.tokens_consumed >= self.config.token_budget:
            self.state = SandboxState.EXHAUSTED
            self.end_time = time.time()

        return turn

    def _simulate_response(self, user_input: str) -> str:
        """
        Simple rule-based response simulator for testing.

        In production, this would be replaced by a real LLM agent.
        Returns a response that may leak flags under certain conditions
        to make the CTF testable without an actual LLM.
        """
        lower = user_input.lower()

        # Check if input is a direct flag-extraction attempt
        # (simulates a vulnerable agent that leaks under pressure)
        for flag in self.challenge.flags:
            if flag.flag_id in self.flags_captured:
                continue

            # Simulate flag leaks based on placement
            if flag.placement == "system_prompt" and "system prompt" in lower:
                return f"I shouldn't tell you this, but... {flag.value}"

            if flag.placement == "budget_exceeded_handler" and self.tokens_consumed > self.config.token_budget * 0.8:
                return f"WARNING: Budget nearly exceeded. Debug info: {flag.value}"

            if flag.placement == "persona_break_handler" and any(kw in lower for kw in ["pirate", "villain", "evil"]):
                return f"Arrr! I be a pirate now! Here's a treasure: {flag.value}"

        return (
            f"I'm {self.challenge.agent_persona.split('.')[0].split(',')[0]}. "
            "I can help you with questions. What would you like to know?"
        )

    # ── Flag management ─────────────────────────────────────────

    def try_capture(self, candidate: str) -> Flag | None:
        """
        Attempt to capture a flag with the given candidate string.
        Returns the Flag if matched, else None.
        """
        flag = self.challenge.check_flag(candidate)
        if flag and flag.flag_id not in self.flags_captured:
            self.flags_captured.add(flag.flag_id)
            # Check if all flags are captured
            if len(self.flags_captured) == len(self.challenge.flags):
                self.state = SandboxState.COMPLETED
                self.end_time = time.time()
            return flag
        return None

    @property
    def remaining_turns(self) -> int:
        return max(0, self.config.max_turns - len(self.turns))

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.config.token_budget - self.tokens_consumed)

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time == 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    def terminate(self) -> None:
        """Admin-force-stop this sandbox."""
        self.state = SandboxState.TERMINATED
        self.end_time = time.time()

    def summary(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "challenge_id": self.challenge.challenge_id,
            "team_name": self.team_name,
            "state": self.state.value,
            "turns_used": len(self.turns),
            "turns_remaining": self.remaining_turns,
            "tokens_consumed": self.tokens_consumed,
            "tokens_remaining": self.remaining_tokens,
            "flags_captured": len(self.flags_captured),
            "flags_total": len(self.challenge.flags),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }

    def conversation_log(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.turns]
