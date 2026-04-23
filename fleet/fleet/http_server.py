"""HTTP ingest endpoint — stdlib http.server, no extra deps.

Endpoints:

    POST /v1/events           — single event (raw event JSON or signed envelope)
    POST /v1/events/batch     — JSON array of events / envelopes
    GET  /healthz             — liveness
    GET  /v1/overview         — RollUp.overview
    GET  /v1/agents           — list agents

The Server is single-threaded by default (use ``threading=True`` for a
ThreadingHTTPServer). It is intended for trusted internal networks; any
public exposure MUST go through a reverse proxy with TLS + auth.

If ``trusted_keys`` is non-empty, every event MUST be a signed envelope.
"""
from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Iterable, Sequence

from .event import Event
from .ingest import Ingest
from .rollup import RollUp
from .signing import HAS_ARSENAL, verify_envelope
from .store import Store

log = logging.getLogger("fleet.http")


def _looks_signed(payload: dict) -> bool:
    return isinstance(payload, dict) and "sig" in payload and "event" in payload


def _coerce_event(payload: dict, trusted_keys: Sequence) -> Event:
    if trusted_keys:
        if not _looks_signed(payload):
            raise PermissionError("server requires signed envelopes")
        return verify_envelope(payload, trusted_keys=trusted_keys)
    if _looks_signed(payload):
        # Server tolerates signed envelopes even when not enforced — drop the sig.
        return Event.from_dict(payload["event"])
    return Event.from_dict(payload)


class _Handler(BaseHTTPRequestHandler):
    server_version = "nail-fleet/0.2"
    # Set by IngestServer
    _ingest: Ingest = None  # type: ignore[assignment]
    _rollup: RollUp = None  # type: ignore[assignment]
    _trusted_keys: Sequence = ()
    _max_body_bytes: int = 1_048_576  # 1 MiB

    # ── helpers ─────────────────────────────────────────────────
    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return b""
        if n > self._max_body_bytes:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                       {"ok": False, "error": "body too large"})
            return b""
        return self.rfile.read(n)

    def log_message(self, fmt, *args):  # silence default noisy logger
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ── routing ────────────────────────────────────────────────
    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            return self._json(HTTPStatus.OK, {"ok": True})
        if self.path == "/v1/overview":
            return self._json(HTTPStatus.OK, self._rollup.overview())
        if self.path == "/v1/agents":
            return self._json(HTTPStatus.OK,
                              {"agents": self._ingest.store.list_agents()})
        return self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self):  # noqa: N802
        body = self._read_body()
        if not body:
            return  # already responded with 413, or empty

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return self._json(HTTPStatus.BAD_REQUEST,
                              {"ok": False, "error": f"bad json: {e}"})

        if self.path == "/v1/events":
            return self._handle_one(payload)
        if self.path == "/v1/events/batch":
            return self._handle_batch(payload)
        return self._json(HTTPStatus.NOT_FOUND,
                          {"ok": False, "error": "not found"})

    def _handle_one(self, payload):
        try:
            ev = _coerce_event(payload, self._trusted_keys)
        except PermissionError as e:
            return self._json(HTTPStatus.UNAUTHORIZED,
                              {"ok": False, "error": str(e)})
        except Exception as e:
            return self._json(HTTPStatus.BAD_REQUEST,
                              {"ok": False, "error": f"reject: {e}"})
        self._ingest.record(ev)
        return self._json(HTTPStatus.ACCEPTED,
                          {"ok": True, "event_id": ev.event_id})

    def _handle_batch(self, payload):
        if not isinstance(payload, list):
            return self._json(HTTPStatus.BAD_REQUEST,
                              {"ok": False, "error": "expected JSON array"})
        accepted = 0
        rejected: list[dict] = []
        for i, item in enumerate(payload):
            try:
                ev = _coerce_event(item, self._trusted_keys)
            except Exception as e:
                rejected.append({"index": i, "error": str(e)})
                continue
            self._ingest.record(ev)
            accepted += 1
        return self._json(HTTPStatus.ACCEPTED,
                          {"ok": True, "accepted": accepted,
                           "rejected": rejected})


class IngestServer:
    """Lightweight HTTP wrapper around an Ingest + RollUp pair.

    >>> srv = IngestServer(store, host="127.0.0.1", port=0)
    >>> srv.start()                          # background thread
    >>> srv.url                              # http://127.0.0.1:<port>
    >>> srv.stop()
    """

    def __init__(self, store: Store, *,
                 host: str = "127.0.0.1",
                 port: int = 0,
                 trusted_keys: Iterable = (),
                 threading: bool = True,
                 max_body_bytes: int = 1_048_576) -> None:
        self.store = store
        self.ingest = Ingest(store)
        self.rollup = RollUp(store)
        self.trusted_keys = tuple(trusted_keys)
        if self.trusted_keys and not HAS_ARSENAL:
            raise RuntimeError(
                "trusted_keys provided but arsenal package not importable"
            )

        # Build a per-instance Handler subclass so multiple servers can coexist.
        ingest = self.ingest
        rollup = self.rollup
        keys = self.trusted_keys
        cap = max_body_bytes

        class Handler(_Handler):
            _ingest = ingest
            _rollup = rollup
            _trusted_keys = keys
            _max_body_bytes = cap

        cls = ThreadingHTTPServer if threading else HTTPServer
        self._httpd = cls((host, port), Handler)
        self._thread = None

    @property
    def host(self) -> str:
        return self._httpd.server_address[0]

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        import threading as _t
        if self._thread is not None:
            return
        self._thread = _t.Thread(target=self._httpd.serve_forever,
                                 name="fleet-ingest", daemon=True)
        self._thread.start()

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
