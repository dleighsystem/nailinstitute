"""Advisory channel — append-only filesystem store + polling watcher.

Layout (default ``~/.nail/advisories/``)::

    advisories/
        index.jsonl            # one line per advisory, append-only
        bundles/
            ADV-2026-0042.json  # full signed bundle, content-addressed
            ...

Producers call ``Channel.publish(bundle)``; subscribers either ``replay``
the index (for cold start) or use ``Watcher`` (which polls the index file
size and yields newly-arrived bundles to a callback).

The channel itself is thread-safe but does NOT enforce a single producer —
two writers racing on the same dir is fine because the index is append-only
and ``bundles/<id>.json`` writes are atomic via ``os.replace``.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .advisory import Advisory, AdvisoryError, parse_bundle, verify_bundle


def default_channel_dir() -> Path:
    return Path(os.environ.get(
        "NAIL_ADVISORY_DIR",
        Path.home() / ".nail" / "advisories",
    ))


# ── exceptions ───────────────────────────────────────────────────────
class DuplicateAdvisory(AdvisoryError):
    """An advisory with this id already exists in the channel."""


# ── channel ──────────────────────────────────────────────────────────
class Channel:
    """File-backed append-only signed-advisory channel."""

    INDEX_NAME = "index.jsonl"
    BUNDLE_DIR = "bundles"

    def __init__(self, directory: Path | None = None) -> None:
        self.dir = directory or default_channel_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / self.BUNDLE_DIR).mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / self.INDEX_NAME
        if not self.index_path.exists():
            self.index_path.touch()
        self._lock = threading.Lock()

    # ── publish ──────────────────────────────────────────────────
    def publish(self, bundle: dict, *, allow_replace: bool = False) -> Path:
        """Persist a signed bundle. Returns the bundle file path."""
        adv, _sig, _sha = parse_bundle(bundle)
        bundle_path = self.dir / self.BUNDLE_DIR / f"{adv.id}.json"
        with self._lock:
            if bundle_path.exists() and not allow_replace:
                raise DuplicateAdvisory(f"advisory {adv.id} already exists")
            tmp = bundle_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(bundle, sort_keys=True, indent=2))
            os.replace(tmp, bundle_path)
            with self.index_path.open("a") as f:
                f.write(json.dumps({
                    "id": adv.id,
                    "kind": adv.kind.value,
                    "severity": adv.severity.value,
                    "issued_at": adv.issued_at,
                    "expires_at": adv.expires_at,
                    "path": bundle_path.name,
                    "indexed_at": int(time.time()),
                }) + "\n")
        return bundle_path

    # ── read ─────────────────────────────────────────────────────
    def index_entries(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        with self.index_path.open() as f:
            out = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return out

    def load_bundle(self, advisory_id: str) -> dict:
        bundle_path = self.dir / self.BUNDLE_DIR / f"{advisory_id}.json"
        if not bundle_path.exists():
            raise FileNotFoundError(f"no such advisory: {advisory_id}")
        return json.loads(bundle_path.read_text())

    def replay(self, *, trusted_keys=None,
               only_active: bool = False) -> Iterator[Advisory]:
        """Yield every advisory in the channel from oldest to newest. If
        ``trusted_keys`` is provided, signature-verify each one and skip
        bad bundles silently (callers needing strict mode should do it
        themselves)."""
        for entry in self.index_entries():
            try:
                bundle = self.load_bundle(entry["id"])
                adv = (verify_bundle(bundle, trusted_keys=trusted_keys)
                       if trusted_keys else parse_bundle(bundle)[0])
            except (AdvisoryError, FileNotFoundError):
                continue
            if only_active and not adv.is_active():
                continue
            yield adv


# ── watcher (polling) ────────────────────────────────────────────────
@dataclass
class WatcherState:
    last_index_size: int = 0
    last_seen_ids: set = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.last_seen_ids is None:
            self.last_seen_ids = set()


class Watcher:
    """Polls a Channel's index for new entries and dispatches callbacks.

    Designed for in-process use (one Watcher per agent / SDK instance).
    For cross-host fan-out, point multiple Watchers at the same NFS-mounted
    or syncthing-replicated channel directory.
    """

    def __init__(self, channel: Channel, *, trusted_keys=None,
                 poll_interval_s: float = 1.0) -> None:
        self.channel = channel
        self.trusted_keys = list(trusted_keys) if trusted_keys else None
        self.poll_interval_s = poll_interval_s
        self.state = WatcherState()
        self._callbacks: list[Callable[[Advisory], None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def on_advisory(self, fn: Callable[[Advisory], None]) -> Callable:
        self._callbacks.append(fn)
        return fn

    # ── one-shot poll, useful in tests ───────────────────────────
    def poll_once(self) -> list[Advisory]:
        new_advisories: list[Advisory] = []
        for entry in self.channel.index_entries():
            if entry["id"] in self.state.last_seen_ids:
                continue
            try:
                bundle = self.channel.load_bundle(entry["id"])
                adv = (
                    verify_bundle(bundle, trusted_keys=self.trusted_keys)
                    if self.trusted_keys else parse_bundle(bundle)[0]
                )
            except AdvisoryError:
                # Skip but still mark seen so we don't spin on bad bundles.
                self.state.last_seen_ids.add(entry["id"])
                continue
            self.state.last_seen_ids.add(entry["id"])
            new_advisories.append(adv)
            for cb in self._callbacks:
                try:
                    cb(adv)
                except Exception:  # noqa: BLE001
                    # Subscriber callbacks must never bring the watcher down.
                    pass
        return new_advisories

    # ── loop, run in thread or main ──────────────────────────────
    def run_forever(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.poll_interval_s)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run_forever, name="advisory-watcher", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2 * self.poll_interval_s + 1)
            self._thread = None
