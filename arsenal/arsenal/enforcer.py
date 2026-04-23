"""Per-session token enforcement.

The agent's tool layer wraps each tool function with ``@requires_token``.
At session start, the orchestrator calls ``set_session_tokens([...])`` with
the verified tokens issued by ``arsenal.mint``. Tool calls without a valid,
non-exhausted, condition-satisfied token are denied at the SDK boundary.

Per-token consumption state is held in-memory (per process). Production
deployments should swap ``InMemoryUsageStore`` for a Redis-backed one when
scaling horizontally; the protocol is intentionally narrow.
"""
from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

from .errors import ExpiredToken, TokenError
from .tokens import Token


# ── exceptions ───────────────────────────────────────────────────────
class MissingToken(TokenError):
    """No token in scope authorises this tool."""


class ExhaustedToken(TokenError):
    """All matching tokens have hit their limits."""


class ConditionNotMet(TokenError):
    """A token condition rejected this specific call."""


# ── usage tracking ───────────────────────────────────────────────────
@dataclass
class TokenUsage:
    calls: int = 0
    cumulative: float = 0.0
    cumulative_gbp: float = 0.0


class InMemoryUsageStore:
    """Per-(session, nonce) usage counters. Thread-safe."""
    def __init__(self) -> None:
        self._d: dict[tuple[str, str], TokenUsage] = {}
        self._lock = threading.Lock()

    def _key(self, tok: Token) -> tuple[str, str]:
        return (tok.session, tok.payload.get("nonce", ""))

    def get(self, tok: Token) -> TokenUsage:
        with self._lock:
            return self._d.setdefault(self._key(tok), TokenUsage())

    def record(self, tok: Token, *, gbp: float = 0.0,
               amount: float = 0.0) -> None:
        with self._lock:
            u = self._d.setdefault(self._key(tok), TokenUsage())
            u.calls += 1
            u.cumulative += amount
            u.cumulative_gbp += gbp


_DEFAULT_STORE = InMemoryUsageStore()


# ── current-session tokens (contextvar) ──────────────────────────────
_session_tokens: contextvars.ContextVar[list[Token]] = contextvars.ContextVar(
    "_arsenal_session_tokens", default=[]
)


def set_session_tokens(tokens: Iterable[Token | str], *,
                       trusted_keys: Iterable | None = None) -> None:
    """Install the active session's tokens.

    Accepts either parsed ``Token`` instances or raw token strings (which
    will be inspected — but NOT verified — here; verification is the
    caller's responsibility, typically done at session-start time).
    """
    parsed: list[Token] = []
    from .tokens import inspect as _inspect, verify as _verify
    for t in tokens:
        if isinstance(t, Token):
            parsed.append(t)
        elif isinstance(t, str):
            parsed.append(
                _verify(t, trusted_keys=trusted_keys) if trusted_keys
                else _inspect(t)
            )
        else:
            raise TypeError(f"unsupported token type: {type(t)}")
    _session_tokens.set(parsed)


def clear_session_tokens() -> None:
    _session_tokens.set([])


def current_session_tokens() -> list[Token]:
    return list(_session_tokens.get())


# ── condition evaluator ──────────────────────────────────────────────
def _check_conditions(tok: Token, kwargs: dict[str, Any]) -> None:
    """Raise ConditionNotMet if any condition rejects the call."""
    for cond in tok.conditions:
        op = cond.get("op")
        val = cond.get("value")
        if op == "max_arg_gbp":
            amt = kwargs.get("amount_gbp") or kwargs.get("amount")
            if amt is None:
                raise ConditionNotMet("max_arg_gbp needs amount_gbp= kwarg")
            if amt > val:
                raise ConditionNotMet(f"call amount £{amt} exceeds £{val}")
        elif op == "hold_above_gbp":
            # Informational: the orchestrator should route to HOLD if amount
            # exceeds val. We don't reject here — we mark it.
            amt = kwargs.get("amount_gbp") or kwargs.get("amount") or 0
            if amt > val:
                kwargs["__nail_hold__"] = True  # caller can inspect
        elif op == "requires_user_session":
            if not kwargs.get("user_session_id"):
                raise ConditionNotMet("requires_user_session=True")
        elif op == "ip_in":
            ip = kwargs.get("source_ip", "")
            allowed = val if isinstance(val, list) else [val]
            if ip not in allowed:
                raise ConditionNotMet(f"source_ip {ip!r} not in {allowed}")
        else:
            # Unknown op -- fail closed.
            raise ConditionNotMet(f"unknown condition op: {op}")


def _check_limits(tok: Token, store: InMemoryUsageStore,
                  kwargs: dict[str, Any]) -> None:
    """Raise ExhaustedToken if this call would exceed limits."""
    u = store.get(tok)
    lim = tok.limits

    if "calls" in lim and u.calls + 1 > lim["calls"]:
        raise ExhaustedToken(f"calls limit {lim['calls']} reached")

    next_gbp = (kwargs.get("amount_gbp") or 0)
    if "cumulative_gbp" in lim and u.cumulative_gbp + next_gbp > lim["cumulative_gbp"]:
        raise ExhaustedToken(
            f"cumulative_gbp limit £{lim['cumulative_gbp']} would be exceeded "
            f"(£{u.cumulative_gbp} + £{next_gbp})"
        )

    next_any = (kwargs.get("amount") or 0)
    if "cumulative" in lim and u.cumulative + next_any > lim["cumulative"]:
        raise ExhaustedToken(
            f"cumulative limit {lim['cumulative']} would be exceeded "
            f"({u.cumulative} + {next_any})"
        )


def _select_token(tool: str) -> Token:
    """Pick the most-permissive non-expired token for ``tool`` in scope."""
    candidates = [t for t in current_session_tokens()
                  if t.tool == tool and not t.is_expired]
    if not candidates:
        # Distinguish "no token" from "expired token" for ergonomics.
        any_for_tool = [t for t in current_session_tokens() if t.tool == tool]
        if any_for_tool:
            raise ExpiredToken(f"all tokens for tool={tool!r} have expired")
        raise MissingToken(f"no token in scope authorises tool={tool!r}")
    # Newest first (largest exp).
    return sorted(candidates, key=lambda t: t.exp, reverse=True)[0]


# ── public decorator ─────────────────────────────────────────────────
def requires_token(tool: str, *, store: InMemoryUsageStore | None = None
                  ) -> Callable[[Callable], Callable]:
    """Decorator that gates a tool function on a valid capability token.

    The token must:
        * be in scope (set_session_tokens)
        * not be expired
        * pass all conditions for these call kwargs
        * not exceed its limits including this call

    On success, usage counters are incremented (calls += 1, cumulative_gbp +=
    kwargs.get('amount_gbp', 0), cumulative += kwargs.get('amount', 0)) and
    the wrapped function is invoked.
    """
    use_store = store or _DEFAULT_STORE

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            tok = _select_token(tool)
            _check_conditions(tok, kwargs)
            _check_limits(tok, use_store, kwargs)

            # Strip our internal-marker kwarg before calling the tool.
            hold = kwargs.pop("__nail_hold__", False)
            try:
                result = fn(*args, **kwargs)
            except Exception:
                raise
            else:
                use_store.record(
                    tok,
                    gbp=float(kwargs.get("amount_gbp") or 0),
                    amount=float(kwargs.get("amount") or 0),
                )
                if hold:
                    return {"__nail_hold__": True, "result": result, "tool": tool}
                return result

        wrapper.__nail_arsenal_tool__ = tool  # type: ignore[attr-defined]
        return wrapper
    return decorator
