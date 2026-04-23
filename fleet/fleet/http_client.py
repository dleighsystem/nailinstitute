"""Push client — agents call this to ship events to a fleet ingest server.

Pure stdlib (urllib). Optional signing if an ``arsenal.IssuerKey`` is given.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterable, Optional, Sequence

from .event import Event
from .signing import HAS_ARSENAL, sign_event


class FleetClientError(RuntimeError):
    pass


class FleetClient:
    def __init__(self, base_url: str, *,
                 signing_key=None,
                 timeout_s: float = 5.0,
                 default_agent_id: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.signing_key = signing_key
        self.timeout_s = timeout_s
        self.default_agent_id = default_agent_id
        if signing_key is not None and not HAS_ARSENAL:
            raise RuntimeError(
                "signing_key provided but arsenal package not importable"
            )

    # ── public ────────────────────────────────────────────────
    def push(self, event: Event) -> dict:
        return self._post("/v1/events", self._wrap(event))

    def push_many(self, events: Iterable[Event]) -> dict:
        return self._post("/v1/events/batch",
                          [self._wrap(e) for e in events])

    def emit(self, kind: str, *, severity: str = "info",
             agent_id: Optional[str] = None,
             attrs: Optional[dict] = None) -> dict:
        """Convenience: build + push in one go."""
        aid = agent_id or self.default_agent_id
        if not aid:
            raise FleetClientError("agent_id required (or set default_agent_id)")
        return self.push(Event(agent_id=aid, kind=kind,
                               severity=severity, attrs=attrs or {}))

    def healthz(self) -> dict:
        return self._get("/healthz")

    def overview(self) -> dict:
        return self._get("/v1/overview")

    # ── helpers ───────────────────────────────────────────────
    def _wrap(self, event: Event):
        if self.signing_key is not None:
            return sign_event(event, key=self.signing_key)
        return event.to_dict()

    def _post(self, path: str, payload) -> dict:
        url = self.base_url + path
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8"))
            except Exception:
                detail = {"error": str(e)}
            raise FleetClientError(f"{e.code} {detail}") from e
        except urllib.error.URLError as e:
            raise FleetClientError(f"transport: {e}") from e

    def _get(self, path: str) -> dict:
        url = self.base_url + path
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_s) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise FleetClientError(f"transport: {e}") from e
