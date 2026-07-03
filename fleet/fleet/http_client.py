"""Push client — agents call this to ship events to a fleet ingest server.

Pure stdlib (urllib). Optional signing if an ``arsenal.IssuerKey`` is given.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
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
                 default_agent_id: Optional[str] = None,
                 org: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.signing_key = signing_key
        self.timeout_s = timeout_s
        self.default_agent_id = default_agent_id
        self.org = org   # this client's tenant; stamped on events + sent as X-NAIL-Org
        if signing_key is not None and not HAS_ARSENAL:
            raise RuntimeError(
                "signing_key provided but arsenal package not importable"
            )

    # ── public ────────────────────────────────────────────────
    def push(self, event: Event) -> dict:
        if self.org and not event.org:
            event.org = self.org
        return self._post("/v1/events", self._wrap(event))

    def push_many(self, events: Iterable[Event]) -> dict:
        wrapped = []
        for e in events:
            if self.org and not e.org:
                e.org = self.org
            wrapped.append(self._wrap(e))
        return self._post("/v1/events/batch", wrapped)

    def emit(self, kind: str, *, severity: str = "info",
             agent_id: Optional[str] = None,
             attrs: Optional[dict] = None,
             org: Optional[str] = None) -> dict:
        """Convenience: build + push in one go."""
        aid = agent_id or self.default_agent_id
        if not aid:
            raise FleetClientError("agent_id required (or set default_agent_id)")
        return self.push(Event(agent_id=aid, kind=kind, severity=severity,
                               attrs=attrs or {}, org=org or self.org))

    def healthz(self) -> dict:
        return self._get("/healthz")

    def overview(self, *, org: Optional[str] = None) -> dict:
        return self._get("/v1/overview", org=org)

    def agents(self, *, org: Optional[str] = None) -> dict:
        return self._get("/v1/agents", org=org)

    def orgs(self) -> dict:
        return self._get("/v1/orgs")

    # ── helpers ───────────────────────────────────────────────
    def _wrap(self, event: Event):
        if self.signing_key is not None:
            return sign_event(event, key=self.signing_key)
        return event.to_dict()

    def _post(self, path: str, payload) -> dict:
        url = self.base_url + path
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.org:
            headers["X-NAIL-Org"] = self.org
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
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

    def _get(self, path: str, *, org: Optional[str] = None) -> dict:
        eff_org = org if org is not None else (self.org or None)
        url = self.base_url + path
        if eff_org:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}org={urllib.parse.quote(eff_org)}"
        headers = {"X-NAIL-Org": eff_org} if eff_org else {}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise FleetClientError(f"transport: {e}") from e
