"""SQLite-backed event store. Thread-safe via per-call connections.

Schema (R0):

    events(event_id PK, agent_id, kind, severity, ts REAL, attrs TEXT)
    agents(agent_id PK, first_seen REAL, last_seen REAL, meta TEXT)

R0 is single-process. R1 will move to a background writer + WAL tuning.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .event import Event


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    kind     TEXT NOT NULL,
    severity TEXT NOT NULL,
    ts       REAL NOT NULL,
    attrs    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_kind  ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_ts    ON events(ts);

CREATE TABLE IF NOT EXISTS agents (
    agent_id   TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    meta       TEXT NOT NULL DEFAULT '{}'
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        # For ``:memory:`` we MUST keep one connection alive — otherwise
        # every call gets a fresh, empty database.
        self._shared: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._shared = sqlite3.connect(":memory:",
                                           check_same_thread=False)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    # ── connection plumbing ─────────────────────────────────────
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._shared is not None:
                yield self._shared
            else:
                conn = sqlite3.connect(self.path)
                try:
                    yield conn
                finally:
                    conn.close()

    def close(self) -> None:
        with self._lock:
            if self._shared is not None:
                self._shared.close()
                self._shared = None

    # ── inserts ─────────────────────────────────────────────────
    def insert_event(self, ev: Event) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO events"
                " (event_id, agent_id, kind, severity, ts, attrs)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (ev.event_id, ev.agent_id, ev.kind, ev.severity, ev.ts,
                 json.dumps(ev.attrs, separators=(",", ":"), sort_keys=True)),
            )
            conn.commit()

    def upsert_agent(self, agent_id: str, ts: float,
                     meta: dict | None = None) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT first_seen FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            meta_s = json.dumps(meta or {}, separators=(",", ":"),
                                sort_keys=True)
            if row is None:
                conn.execute(
                    "INSERT INTO agents (agent_id, first_seen, last_seen, meta)"
                    " VALUES (?, ?, ?, ?)",
                    (agent_id, ts, ts, meta_s),
                )
            else:
                conn.execute(
                    "UPDATE agents SET last_seen = ?, meta = ? WHERE agent_id = ?",
                    (ts, meta_s, agent_id),
                )
            conn.commit()

    # ── queries ─────────────────────────────────────────────────
    def query_events(self, *,
                     agent_id: str | None = None,
                     kind: str | None = None,
                     severity: str | None = None,
                     since: float | None = None,
                     until: float | None = None,
                     limit: int | None = None,
                     order: str = "asc") -> list[Event]:
        sql = "SELECT event_id, agent_id, kind, severity, ts, attrs FROM events"
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id is not None: clauses.append("agent_id = ?"); params.append(agent_id)
        if kind     is not None: clauses.append("kind = ?");     params.append(kind)
        if severity is not None: clauses.append("severity = ?"); params.append(severity)
        if since    is not None: clauses.append("ts >= ?");      params.append(since)
        if until    is not None: clauses.append("ts <= ?");      params.append(until)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts " + ("DESC" if order.lower() == "desc" else "ASC")
        if limit is not None:
            sql += " LIMIT ?"; params.append(int(limit))

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            Event(event_id=r[0], agent_id=r[1], kind=r[2], severity=r[3],
                  ts=r[4], attrs=json.loads(r[5]))
            for r in rows
        ]

    def list_agents(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT agent_id, first_seen, last_seen, meta FROM agents"
                " ORDER BY last_seen DESC"
            ).fetchall()
        return [
            {"agent_id": r[0], "first_seen": r[1], "last_seen": r[2],
             "meta": json.loads(r[3])}
            for r in rows
        ]

    def event_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
