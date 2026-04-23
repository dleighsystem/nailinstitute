"""Alerts — threshold-based rule engine over the event store.

Built on top of `Query`. Each `AlertRule` evaluates a single condition
(rate threshold, ratio threshold, percentile threshold, agent silence,
or severity floor) and emits an `Alert` when fired.

Usage:

    eng = AlertEngine([
        RateRule("deny_spike", kind="arsenal.deny", threshold=5.0,
                 window_s=60, op=">="),
        RatioRule("refusal_rate", num_kind="arsenal.deny",
                  denom_kinds=["arsenal.deny", "arsenal.allow"],
                  threshold=0.5, window_s=300),
        SilenceRule("agent_dark", agent_id="bot-1", max_silence_s=600),
        PercentileRule("slow_critique", kind="foresight.verdict",
                       attr_key="duration_ms", percentile=95,
                       threshold=2000.0),
        SeverityRule("crit_event", severity="critical", min_count=1,
                     window_s=600),
    ])
    fired = eng.evaluate(store)         # list[Alert]
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Protocol, runtime_checkable

from .query import Query, _percentile
from .store import Store


_OPS = {
    ">":  lambda a, b: a >  b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a <  b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


# ── Alert record ───────────────────────────────────────────────
@dataclass
class Alert:
    rule: str
    severity: str          # "warn" | "error" | "critical"
    message: str
    value: float
    threshold: float
    ts: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


# ── Rule protocol ──────────────────────────────────────────────
@runtime_checkable
class AlertRule(Protocol):
    name: str
    severity: str

    def evaluate(self, store: Store, *,
                 now: float | None = None) -> Alert | None: ...


# ── Concrete rules ─────────────────────────────────────────────
@dataclass
class RateRule:
    """Fires when events/sec for ``kind`` over ``window_s`` ⟂ threshold."""
    name: str
    kind: str
    threshold: float
    window_s: float = 60.0
    op: str = ">="
    severity: str = "warn"
    agent_id: str | None = None
    event_severity: str | None = None  # filter on event severity

    def evaluate(self, store: Store, *,
                 now: float | None = None) -> Alert | None:
        if self.op not in _OPS:
            raise ValueError(f"unknown op {self.op!r}")
        q = Query(store)
        rate = q.rate(kind=self.kind, window_s=self.window_s, now=now,
                      severity=self.event_severity, agent_id=self.agent_id)
        if _OPS[self.op](rate, self.threshold):
            return Alert(
                rule=self.name, severity=self.severity,
                message=(f"{self.kind} rate {rate:.3f}/s "
                         f"{self.op} {self.threshold:.3f}/s "
                         f"over {self.window_s:.0f}s"),
                value=rate, threshold=self.threshold,
                attrs={"kind": self.kind, "window_s": self.window_s,
                       "op": self.op, "agent_id": self.agent_id},
            )
        return None


@dataclass
class RatioRule:
    """Fires when ``count(num_kind) / sum(count(k) for k in denom_kinds)`` ⟂ threshold."""
    name: str
    num_kind: str
    denom_kinds: list[str]
    threshold: float
    window_s: float | None = None
    op: str = ">="
    severity: str = "warn"
    min_denominator: int = 1   # avoid alerting on tiny samples

    def evaluate(self, store: Store, *,
                 now: float | None = None) -> Alert | None:
        if self.op not in _OPS:
            raise ValueError(f"unknown op {self.op!r}")
        q = Query(store)
        # Need denominator count to gate min_denominator.
        ref = time.time() if now is None else now
        since = (ref - self.window_s) if self.window_s else None
        until = ref if self.window_s else None
        den = 0
        for k in self.denom_kinds:
            den += len(store.query_events(kind=k, since=since, until=until))
        if den < self.min_denominator:
            return None
        ratio = q.ratio(num_kind=self.num_kind, denom_kinds=self.denom_kinds,
                        window_s=self.window_s, now=now)
        if _OPS[self.op](ratio, self.threshold):
            return Alert(
                rule=self.name, severity=self.severity,
                message=(f"{self.num_kind}/Σ{list(self.denom_kinds)} = "
                         f"{ratio:.3f} {self.op} {self.threshold:.3f}"),
                value=ratio, threshold=self.threshold,
                attrs={"num_kind": self.num_kind,
                       "denom_kinds": list(self.denom_kinds),
                       "denominator": den, "op": self.op,
                       "window_s": self.window_s},
            )
        return None


@dataclass
class PercentileRule:
    """Fires when the Pth percentile of a numeric attr ⟂ threshold."""
    name: str
    kind: str
    attr_key: str
    threshold: float
    percentile: float = 95.0
    window_s: float | None = None
    op: str = ">="
    severity: str = "warn"
    min_samples: int = 5

    def evaluate(self, store: Store, *,
                 now: float | None = None) -> Alert | None:
        if self.op not in _OPS:
            raise ValueError(f"unknown op {self.op!r}")
        ref = time.time() if now is None else now
        since = (ref - self.window_s) if self.window_s else None
        until = ref if self.window_s else None
        vals: list[float] = []
        for ev in store.query_events(kind=self.kind, since=since, until=until):
            v = ev.attrs.get(self.attr_key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(float(v))
        if len(vals) < self.min_samples:
            return None
        vals.sort()
        p = _percentile(vals, self.percentile)
        if _OPS[self.op](p, self.threshold):
            return Alert(
                rule=self.name, severity=self.severity,
                message=(f"p{self.percentile:g}({self.kind}.{self.attr_key}) "
                         f"= {p:.2f} {self.op} {self.threshold:.2f} "
                         f"(n={len(vals)})"),
                value=p, threshold=self.threshold,
                attrs={"kind": self.kind, "attr": self.attr_key,
                       "percentile": self.percentile, "n": len(vals),
                       "op": self.op, "window_s": self.window_s},
            )
        return None


@dataclass
class SilenceRule:
    """Fires when an agent has been silent for longer than ``max_silence_s``.

    If ``agent_id`` is None, applies to ALL known agents (returns first
    offender; use `AlertEngine` for per-agent fan-out).
    """
    name: str
    max_silence_s: float
    agent_id: str | None = None
    severity: str = "error"

    def evaluate(self, store: Store, *,
                 now: float | None = None) -> Alert | None:
        ref = time.time() if now is None else now
        agents = store.list_agents()
        if not agents:
            return None
        if self.agent_id is not None:
            agents = [a for a in agents if a["agent_id"] == self.agent_id]
            if not agents:
                return None
        for a in agents:
            age = ref - a["last_seen"]
            if age > self.max_silence_s:
                return Alert(
                    rule=self.name, severity=self.severity,
                    message=(f"agent {a['agent_id']!r} silent for "
                             f"{age:.0f}s > {self.max_silence_s:.0f}s"),
                    value=age, threshold=self.max_silence_s,
                    attrs={"agent_id": a["agent_id"],
                           "last_seen": a["last_seen"]},
                )
        return None


@dataclass
class SeverityRule:
    """Fires when ≥ ``min_count`` events of ``severity`` appear in the window."""
    name: str
    severity: str   # event severity to count, e.g. "critical"
    min_count: int = 1
    window_s: float | None = None
    kind: str | None = None
    alert_severity: str = "critical"

    def evaluate(self, store: Store, *,
                 now: float | None = None) -> Alert | None:
        ref = time.time() if now is None else now
        since = (ref - self.window_s) if self.window_s else None
        until = ref if self.window_s else None
        n = len(store.query_events(
            kind=self.kind, severity=self.severity,
            since=since, until=until,
        ))
        if n >= self.min_count:
            return Alert(
                rule=self.name, severity=self.alert_severity,
                message=(f"{n} {self.severity!r} event(s) "
                         f"in last {self.window_s or '∞'}s"
                         + (f" of kind {self.kind!r}" if self.kind else "")),
                value=float(n), threshold=float(self.min_count),
                attrs={"event_severity": self.severity, "kind": self.kind,
                       "window_s": self.window_s},
            )
        return None


# ── Engine ─────────────────────────────────────────────────────
class AlertEngine:
    """Runs a list of rules against a store and returns fired alerts."""

    def __init__(self, rules: Iterable[AlertRule] | None = None) -> None:
        self.rules: list[AlertRule] = list(rules or [])

    def add(self, rule: AlertRule) -> None:
        self.rules.append(rule)

    def evaluate(self, store: Store, *,
                 now: float | None = None) -> list[Alert]:
        out: list[Alert] = []
        for rule in self.rules:
            try:
                a = rule.evaluate(store, now=now)
            except Exception as exc:   # pragma: no cover — defensive
                a = Alert(
                    rule=getattr(rule, "name", repr(rule)),
                    severity="error",
                    message=f"rule failed: {exc!r}",
                    value=0.0, threshold=0.0,
                    attrs={"error": str(exc)},
                )
            if a is not None:
                out.append(a)
        return out
