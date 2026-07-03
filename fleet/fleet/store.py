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
    org      TEXT NOT NULL DEFAULT '',
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
    org        TEXT NOT NULL DEFAULT '',
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    meta       TEXT NOT NULL DEFAULT '{}'
);
"""
# org indexes are created in _migrate(), after the column is guaranteed to
# exist — on a legacy DB the column is added by ALTER TABLE first.


class Store:
    def __init__(self, path: str | Path = ":memory:", *,
                 busy_timeout_ms: int = 5000) -> None:
        self.path = str(path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._lock = threading.RLock()
        # For ``:memory:`` we MUST keep one connection alive — otherwise
        # every call gets a fresh, empty database.
        self._shared: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._shared = sqlite3.connect(":memory:",
                                           check_same_thread=False)
            self._configure(self._shared)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)
            conn.commit()

    def _configure(self, conn: sqlite3.Connection) -> None:
        """Per-connection pragmas. WAL (file DBs) gives concurrent readers with a
        single writer and crash-safe durability; busy_timeout makes contending
        writers wait rather than raise 'database is locked'."""
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add the org column to pre-existing (pre-multi-tenant) databases."""
        for table in ("events", "agents"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "org" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN org TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_org ON events(org)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_org_agent ON events(org, agent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_org ON agents(org)")

    # ── connection plumbing ─────────────────────────────────────
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._shared is not None:
            # A single in-memory connection is shared across threads, so its
            # access must be serialised by the process lock.
            with self._lock:
                yield self._shared
        else:
            # File-backed: each caller gets its own connection. SQLite (WAL +
            # busy_timeout) serialises concurrent writers at the database level,
            # so no process-wide lock is needed — this is what lets many agents
            # ingest at once instead of queueing behind one mutex.
            conn = sqlite3.connect(self.path)
            self._configure(conn)
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
                " (event_id, agent_id, org, kind, severity, ts, attrs)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ev.event_id, ev.agent_id, ev.org, ev.kind, ev.severity, ev.ts,
                 json.dumps(ev.attrs, separators=(",", ":"), sort_keys=True)),
            )
            conn.commit()

    def upsert_agent(self, agent_id: str, ts: float,
                     meta: dict | None = None, *, org: str = "") -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT first_seen FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            meta_s = json.dumps(meta or {}, separators=(",", ":"),
                                sort_keys=True)
            if row is None:
                conn.execute(
                    "INSERT INTO agents (agent_id, org, first_seen, last_seen, meta)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (agent_id, org, ts, ts, meta_s),
                )
            else:
                # An agent's org is immutable once registered; only touch liveness.
                conn.execute(
                    "UPDATE agents SET last_seen = ?, meta = ? WHERE agent_id = ?",
                    (ts, meta_s, agent_id),
                )
            conn.commit()

    # ── queries ─────────────────────────────────────────────────
    def query_events(self, *,
                     agent_id: str | None = None,
                     org: str | None = None,
                     kind: str | None = None,
                     severity: str | None = None,
                     since: float | None = None,
                     until: float | None = None,
                     limit: int | None = None,
                     order: str = "asc") -> list[Event]:
        sql = "SELECT event_id, agent_id, org, kind, severity, ts, attrs FROM events"
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id is not None: clauses.append("agent_id = ?"); params.append(agent_id)
        if org      is not None: clauses.append("org = ?");      params.append(org)
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
            Event(event_id=r[0], agent_id=r[1], org=r[2], kind=r[3], severity=r[4],
                  ts=r[5], attrs=json.loads(r[6]))
            for r in rows
        ]

    def list_agents(self, *, org: str | None = None) -> list[dict]:
        sql = "SELECT agent_id, org, first_seen, last_seen, meta FROM agents"
        params: list[Any] = []
        if org is not None:
            sql += " WHERE org = ?"; params.append(org)
        sql += " ORDER BY last_seen DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {"agent_id": r[0], "org": r[1], "first_seen": r[2], "last_seen": r[3],
             "meta": json.loads(r[4])}
            for r in rows
        ]

    def list_orgs(self) -> list[dict]:
        """Per-organisation rollup: agent + event counts (multi-tenant fleet view)."""
        with self._connect() as conn:
            agent_counts = dict(conn.execute(
                "SELECT org, COUNT(*) FROM agents GROUP BY org").fetchall())
            event_counts = dict(conn.execute(
                "SELECT org, COUNT(*) FROM events GROUP BY org").fetchall())
        orgs = sorted(set(agent_counts) | set(event_counts))
        return [
            {"org": o, "agents": int(agent_counts.get(o, 0)),
             "events": int(event_counts.get(o, 0))}
            for o in orgs
        ]

    def event_count(self, *, org: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM events"
        params: list[Any] = []
        if org is not None:
            sql += " WHERE org = ?"; params.append(org)
        with self._connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])
