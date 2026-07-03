"""R1 store hardening: WAL, concurrent writers, durability across reopen."""

import sqlite3
import threading

from fleet.event import Event
from fleet.ingest import Ingest
from fleet.store import Store


def test_file_store_uses_wal(tmp_path):
    path = tmp_path / "fleet.sqlite"
    Store(path)
    mode = sqlite3.connect(str(path)).execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_busy_timeout_is_configurable(tmp_path):
    store = Store(tmp_path / "fleet.sqlite", busy_timeout_ms=1234)
    assert store.busy_timeout_ms == 1234


def test_file_store_persists_across_reopen(tmp_path):
    path = tmp_path / "fleet.sqlite"
    Ingest(Store(path)).record(Event(agent_id="a", org="acme", kind="k"))
    reopened = Store(path)  # a fresh Store on the same file must see prior data
    assert reopened.event_count(org="acme") == 1


def test_concurrent_writers_do_not_lose_or_lock(tmp_path):
    store = Store(tmp_path / "fleet.sqlite")
    ing = Ingest(store)
    errors: list[Exception] = []

    def worker(w: int) -> None:
        try:
            for i in range(50):
                ing.record(Event(agent_id=f"a{w}", org="acme", kind="k", ts=float(i)))
        except Exception as exc:  # e.g. "database is locked"
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert store.event_count() == 8 * 50   # every concurrent write landed


def test_memory_store_still_works():
    store = Store(":memory:")
    Ingest(store).record(Event(agent_id="a", kind="k"))
    assert store.event_count() == 1
