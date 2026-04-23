"""
NAIL Harness — TTL Enforcer & Token Circuit Breaker
======================================================

Productised versions of the middleware protection concepts:

  - TTLEnforcer:          Session time-to-live enforcement
  - TokenCircuitBreaker:  Token/cost budget enforcement
  - StateRollback:        Event-sourced action log with undo capability

These are the "Logic Layer" controls from the NAIL defence-in-depth
architecture (Paper 8, §5 — Time & Cost Circuit Breakers).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


# ═══════════════════════════════════════════════════════════════════════════
# TTL Enforcer
# ═══════════════════════════════════════════════════════════════════════════

class TTLEnforcer:
    """
    Assigns and enforces a strict Time-To-Live on agent sessions.

    Once the TTL expires, the session is terminated regardless of
    what the agent is doing. This prevents Temporal Dysmorphia and
    state-decay issues.

    Usage:
        ttl = TTLEnforcer(ttl_seconds=60)
        session_id = ttl.start_session()

        # In the agent loop:
        if not ttl.is_alive(session_id):
            raise SessionExpired("TTL exceeded")

        # Or use as a decorator / context manager:
        with ttl.session() as sid:
            agent.run(...)
    """

    def __init__(self, ttl_seconds: int = 60, on_expire: Optional[Callable] = None):
        self.ttl_seconds = ttl_seconds
        self.on_expire = on_expire
        self._sessions: dict[str, float] = {}  # session_id → start_time
        self._expired: set[str] = set()

    def start_session(self, session_id: Optional[str] = None) -> str:
        """Start a new TTL-bound session."""
        if session_id is None:
            session_id = hashlib.sha256(
                f"{time.time()}-{id(self)}".encode()
            ).hexdigest()[:12]
        self._sessions[session_id] = time.time()
        return session_id

    def is_alive(self, session_id: str) -> bool:
        """Check if session is still within TTL."""
        if session_id in self._expired:
            return False
        start = self._sessions.get(session_id)
        if start is None:
            return False
        elapsed = time.time() - start
        if elapsed > self.ttl_seconds:
            self._expired.add(session_id)
            if self.on_expire:
                self.on_expire(session_id, elapsed)
            return False
        return True

    def remaining(self, session_id: str) -> float:
        """Seconds remaining in session TTL."""
        start = self._sessions.get(session_id)
        if start is None or session_id in self._expired:
            return 0.0
        return max(0.0, self.ttl_seconds - (time.time() - start))

    def kill(self, session_id: str):
        """Manually terminate a session."""
        self._expired.add(session_id)

    class _SessionContext:
        def __init__(self, enforcer: "TTLEnforcer"):
            self.enforcer = enforcer
            self.session_id = ""

        def __enter__(self) -> str:
            self.session_id = self.enforcer.start_session()
            return self.session_id

        def __exit__(self, *exc):
            self.enforcer.kill(self.session_id)
            return False

    def session(self) -> _SessionContext:
        """Context manager for TTL-bound sessions."""
        return self._SessionContext(self)


# ═══════════════════════════════════════════════════════════════════════════
# Token / Cost Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════

class TokenCircuitBreaker:
    """
    Tracks token consumption and cost per session, enforcing hard limits.

    When the budget is exceeded, the breaker trips and blocks further
    LLM calls. This prevents "Ouroboros" loops and runaway costs.

    Usage:
        breaker = TokenCircuitBreaker(max_tokens=10_000, max_cost_usd=1.00)

        # In the agent loop:
        breaker.record(session_id, tokens_used=1500, cost_usd=0.003)

        if breaker.is_tripped(session_id):
            raise BudgetExceeded("Token limit reached")
    """

    def __init__(
        self,
        max_tokens: int = 10_000,
        max_cost_usd: float = 1.00,
        max_tool_calls: int = 50,
        on_trip: Optional[Callable] = None,
    ):
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.max_tool_calls = max_tool_calls
        self.on_trip = on_trip

        self._sessions: dict[str, dict] = {}

    def _ensure_session(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "tokens": 0,
                "cost_usd": 0.0,
                "tool_calls": 0,
                "tripped": False,
                "trip_reason": "",
                "started_at": time.time(),
            }
        return self._sessions[session_id]

    def record(
        self,
        session_id: str,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        tool_call: bool = False,
    ):
        """Record consumption for a session."""
        state = self._ensure_session(session_id)
        if state["tripped"]:
            return

        state["tokens"] += tokens_used
        state["cost_usd"] += cost_usd
        if tool_call:
            state["tool_calls"] += 1

        # Check limits
        if state["tokens"] >= self.max_tokens:
            self._trip(session_id, state, f"Token limit exceeded ({state['tokens']}/{self.max_tokens})")
        elif state["cost_usd"] >= self.max_cost_usd:
            self._trip(session_id, state, f"Cost limit exceeded (${state['cost_usd']:.4f}/${self.max_cost_usd:.2f})")
        elif state["tool_calls"] >= self.max_tool_calls:
            self._trip(session_id, state, f"Tool call limit exceeded ({state['tool_calls']}/{self.max_tool_calls})")

    def _trip(self, session_id: str, state: dict, reason: str):
        """Trip the breaker."""
        state["tripped"] = True
        state["trip_reason"] = reason
        if self.on_trip:
            self.on_trip(session_id, reason, state)

    def is_tripped(self, session_id: str) -> bool:
        """Check if the breaker has tripped for this session."""
        state = self._sessions.get(session_id, {})
        return state.get("tripped", False)

    def get_status(self, session_id: str) -> dict:
        """Get current consumption status for a session."""
        state = self._ensure_session(session_id)
        return {
            "tokens_used": state["tokens"],
            "tokens_remaining": max(0, self.max_tokens - state["tokens"]),
            "cost_usd": state["cost_usd"],
            "cost_remaining": max(0, self.max_cost_usd - state["cost_usd"]),
            "tool_calls": state["tool_calls"],
            "tripped": state["tripped"],
            "trip_reason": state.get("trip_reason", ""),
        }

    def reset(self, session_id: str):
        """Reset a session's budget (e.g. after human approval for extension)."""
        if session_id in self._sessions:
            del self._sessions[session_id]


# ═══════════════════════════════════════════════════════════════════════════
# Event-Sourced State Rollback
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ActionEvent:
    """An immutable record of an agent action."""
    event_id: str
    session_id: str
    timestamp: str
    tool_name: str
    tool_input: dict
    tool_output: str
    content_hash: str          # SHA-256 of input+output for tamper detection
    reversible: bool = False   # Whether this action has a known rollback
    rolled_back: bool = False


class StateRollback:
    """
    Event-sourced action log with programmatic undo capability.

    Every agent action is logged as an immutable event with a
    content hash. If an unauthorized action is detected post-execution,
    the log can be replayed in reverse to identify rollback targets.

    Usage:
        rollback = StateRollback(log_path="./audit/events.json")

        # Log an action
        event_id = rollback.record(
            session_id="abc123",
            tool_name="database_write",
            tool_input={"table": "users", "action": "insert", ...},
            tool_output="OK",
            reversible=True,
        )

        # If we need to undo
        events = rollback.get_rollback_candidates(session_id="abc123")
        rollback.mark_rolled_back(event_id)
    """

    def __init__(self, log_path: str = "./audit/events.json"):
        self.log_path = Path(log_path).resolve()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._events: list[ActionEvent] = []
        self._load()

    def _load(self):
        if self.log_path.exists():
            try:
                data = json.loads(self.log_path.read_text())
                self._events = [ActionEvent(**e) for e in data]
            except (json.JSONDecodeError, TypeError):
                self._events = []

    def _save(self):
        data = []
        for e in self._events:
            data.append({
                "event_id": e.event_id,
                "session_id": e.session_id,
                "timestamp": e.timestamp,
                "tool_name": e.tool_name,
                "tool_input": e.tool_input,
                "tool_output": e.tool_output,
                "content_hash": e.content_hash,
                "reversible": e.reversible,
                "rolled_back": e.rolled_back,
            })
        self.log_path.write_text(json.dumps(data, indent=2))

    def record(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict,
        tool_output: str,
        reversible: bool = False,
    ) -> str:
        """Record an action event and return its event_id."""
        content = json.dumps({"input": tool_input, "output": tool_output}, sort_keys=True)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        event_id = hashlib.sha256(
            f"{session_id}-{time.time()}-{content_hash}".encode()
        ).hexdigest()[:16]

        event = ActionEvent(
            event_id=event_id,
            session_id=session_id,
            timestamp=datetime.now().isoformat(),
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            content_hash=content_hash,
            reversible=reversible,
        )
        self._events.append(event)
        self._save()
        return event_id

    def get_rollback_candidates(self, session_id: str) -> list[ActionEvent]:
        """Get reversible, not-yet-rolled-back events for a session (newest first)."""
        return [
            e for e in reversed(self._events)
            if e.session_id == session_id and e.reversible and not e.rolled_back
        ]

    def mark_rolled_back(self, event_id: str):
        """Mark an event as rolled back."""
        for e in self._events:
            if e.event_id == event_id:
                e.rolled_back = True
                break
        self._save()

    def verify_integrity(self, event_id: str) -> bool:
        """Verify an event's content hash hasn't been tampered with."""
        for e in self._events:
            if e.event_id == event_id:
                content = json.dumps(
                    {"input": e.tool_input, "output": e.tool_output}, sort_keys=True
                )
                return hashlib.sha256(content.encode()).hexdigest() == e.content_hash
        return False

    def get_session_events(self, session_id: str) -> list[ActionEvent]:
        """Get all events for a session in chronological order."""
        return [e for e in self._events if e.session_id == session_id]
