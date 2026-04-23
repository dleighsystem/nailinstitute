"""Pluggable telemetry sinks + a process-global emit() function.

Other NAIL packages call ``fleet.emit(...)`` without caring whether events
go to a local Store, an HTTP server, both, or nowhere. The default sink
is ``NullSink`` so importing fleet has no observable side-effects.

    from fleet import emit, set_sink, LocalSink, Store
    set_sink(LocalSink(Store(\"~/.nail/fleet.sqlite\")))

    emit(\"foresight.verdict\", agent_id=\"refund-bot-1\",
         severity=\"info\", attrs={\"verdict\": \"hold\", \"risk\": 0.65})
"""
from __future__ import annotations

import logging
import threading
from typing import Iterable, Optional, Protocol, runtime_checkable

from .event import Event
from .ingest import Ingest
from .store import Store

log = logging.getLogger("fleet.sink")


# ── protocol ─────────────────────────────────────────────────────────
@runtime_checkable
class Sink(Protocol):
    def emit(self, event: Event) -> None: ...


# ── implementations ─────────────────────────────────────────────────
class NullSink:
    """Default. Drops everything. No I/O."""
    def emit(self, event: Event) -> None:
        return None


class LocalSink:
    """In-process Store writer."""
    def __init__(self, store: Store) -> None:
        self._ingest = Ingest(store)

    def emit(self, event: Event) -> None:
        self._ingest.record(event)


class HttpSink:
    """Push to a remote IngestServer via FleetClient."""
    def __init__(self, client) -> None:
        self._client = client

    def emit(self, event: Event) -> None:
        self._client.push(event)


class MultiSink:
    """Fan-out to multiple sinks. A failure in one does not stop others."""
    def __init__(self, sinks: Iterable[Sink]) -> None:
        self._sinks = list(sinks)

    def emit(self, event: Event) -> None:
        for s in self._sinks:
            try:
                s.emit(event)
            except Exception as e:  # pragma: no cover — defensive
                log.warning("sink %r failed: %s", s, e)


class CapturingSink:
    """In-memory list — useful in tests."""
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


# ── process-global registry ─────────────────────────────────────────
_lock = threading.RLock()
_current_sink: Sink = NullSink()


def set_sink(sink: Optional[Sink]) -> None:
    """Install a sink for ``emit`` / ``safe_emit``. ``None`` → NullSink."""
    global _current_sink
    with _lock:
        _current_sink = sink if sink is not None else NullSink()


def get_sink() -> Sink:
    with _lock:
        return _current_sink


def emit(kind: str, *,
         agent_id: str,
         severity: str = "info",
         attrs: Optional[dict] = None) -> Event:
    """Build an Event and hand it to the current sink. May raise."""
    ev = Event(agent_id=agent_id, kind=kind, severity=severity,
               attrs=attrs or {})
    get_sink().emit(ev)
    return ev


def safe_emit(kind: str, *, agent_id: str, severity: str = "info",
              attrs: Optional[dict] = None) -> None:
    """Like ``emit`` but swallows every exception. Use this from inside the
    agent's hot path — telemetry must never break the caller."""
    try:
        emit(kind, agent_id=agent_id, severity=severity, attrs=attrs)
    except Exception as e:  # pragma: no cover — defensive
        log.debug("safe_emit dropped: %s", e)
