"""
server — FastAPI web server for the ThreatFeed pipeline.

Exposes the Discover → Publish → Protect flywheel as HTTP endpoints:

  Feed Intelligence:
    1. GET    /health                   — Server health check
    2. GET    /status                   — Full feed status + metrics
    3. GET    /events                   — List all feed events (paginated)
    4. GET    /events/{event_id}        — Single event detail

  Signature Management:
    5. GET    /signatures               — All compiled signatures
    6. GET    /signatures/{sig_id}      — Single signature detail
    7. POST   /signatures/compile       — Compile new signature from payload
    8. POST   /signatures/test          — Test a signature against sample text

  Definition Updates:
    9. GET    /updates                  — All published updates
   10. GET    /updates/{update_id}      — Single update detail
   11. GET    /updates/latest           — Latest update (for polling clients)
   12. POST   /updates/push             — Force-push pending signatures

  Client Management:
   13. GET    /clients                  — List registered SDK clients
   14. POST   /clients/register         — Register a new client endpoint
   15. DELETE /clients/{client_id}      — Deregister a client
   16. GET    /clients/{client_id}/receipts — Client delivery history

  Ingestion Webhooks:
   17. POST   /ingest/canary            — Ingest a canary incident
   18. POST   /ingest/arena             — Ingest an arena breakthrough
   19. POST   /ingest/ctf               — Ingest a CTF discovery
   20. POST   /ingest/card              — Ingest a draft AVE card

  Subscriber Management:
   21. GET    /subscribers              — List all subscribers
   22. POST   /subscribers/register     — Register a new subscriber

Usage (standalone):
    uvicorn threatfeed.server:create_app --host 0.0.0.0 --port 9300

Usage (Docker):
    See docker-compose.yml — threatfeed-server service
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from .feed import ThreatFeed, FeedEventType, FeedEvent, FeedSubscriber
from .signature import Signature, SignatureCompiler, SignatureType, SignatureSource
from .update import (
    DefinitionUpdate, UpdatePriority, UpdateChannel, ClientEndpoint,
)


# ═══════════════════════════════════════════════════════════════════════════
# Server Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FeedServerConfig:
    """Configuration for the ThreatFeed web server."""
    host: str = "0.0.0.0"
    port: int = 9300
    admin_token: str = ""
    auto_compile: bool = True
    auto_publish: bool = True
    log_dir: str = "logs/threatfeed"
    max_events_page: int = 100

    @classmethod
    def from_env(cls) -> "FeedServerConfig":
        """Build config from environment variables."""
        return cls(
            host=os.environ.get("FEED_HOST", "0.0.0.0"),
            port=int(os.environ.get("FEED_PORT", "9300")),
            admin_token=os.environ.get("FEED_ADMIN_TOKEN", ""),
            auto_compile=os.environ.get("FEED_AUTO_COMPILE", "1") == "1",
            auto_publish=os.environ.get("FEED_AUTO_PUBLISH", "1") == "1",
            log_dir=os.environ.get("FEED_LOG_DIR", "logs/threatfeed"),
            max_events_page=int(os.environ.get("FEED_MAX_EVENTS_PAGE", "100")),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Application Factory
# ═══════════════════════════════════════════════════════════════════════════

def create_app(config: FeedServerConfig | None = None) -> "FastAPI":
    """Create and configure the ThreatFeed FastAPI application."""
    if not HAS_FASTAPI:
        raise ImportError(
            "FastAPI is required for the ThreatFeed server. "
            "Install with: pip install nail-threatfeed[server]"
        )

    cfg = config or FeedServerConfig.from_env()
    feed = ThreatFeed(auto_compile=cfg.auto_compile, auto_publish=cfg.auto_publish)
    start_time = time.time()

    # Ensure log directory exists
    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="NAIL ThreatFeed — Live Threat Intelligence",
        description="Discover → Publish → Protect flywheel API",
        version="2.0.0",
    )

    # ── helpers ─────────────────────────────────────────────────

    def _check_admin(request: "Request") -> bool:
        """Validate admin token if configured."""
        if not cfg.admin_token:
            return True
        token = request.headers.get("X-Admin-Token", "")
        return token == cfg.admin_token

    def _log_event(event_type: str, detail: str) -> None:
        """Append one-line JSON to the event log."""
        log_path = Path(cfg.log_dir) / "events.jsonl"
        entry = {
            "ts": time.time(),
            "type": event_type,
            "detail": detail,
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # ═══════════════════════════════════════════════════════════
    # Health & Status
    # ═══════════════════════════════════════════════════════════

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "nail-threatfeed",
            "version": "2.0.0",
            "uptime_seconds": round(time.time() - start_time, 1),
        }

    @app.get("/status")
    async def status():
        st = feed.status()
        st["uptime_seconds"] = round(time.time() - start_time, 1)
        st["config"] = {
            "auto_compile": cfg.auto_compile,
            "auto_publish": cfg.auto_publish,
            "port": cfg.port,
        }
        return st

    # ═══════════════════════════════════════════════════════════
    # Feed Events
    # ═══════════════════════════════════════════════════════════

    @app.get("/events")
    async def list_events(
        source: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        events = feed.events
        if source:
            events = [e for e in events if e.source == source]
        if event_type:
            try:
                et = FeedEventType(event_type)
                events = [e for e in events if e.event_type == et]
            except ValueError:
                pass
        total = len(events)
        page = events[offset:offset + min(limit, cfg.max_events_page)]
        return {
            "total": total,
            "offset": offset,
            "count": len(page),
            "events": [e.to_dict() for e in page],
        }

    @app.get("/events/{event_id}")
    async def get_event(event_id: str):
        for e in feed.events:
            if e.event_id == event_id:
                return e.to_dict()
        return JSONResponse({"error": "Event not found"}, status_code=404)

    # ═══════════════════════════════════════════════════════════
    # Signatures
    # ═══════════════════════════════════════════════════════════

    @app.get("/signatures")
    async def list_signatures(
        source: str | None = None,
        sig_type: str | None = None,
    ):
        sigs = feed.compiler.signatures
        if source:
            try:
                src = SignatureSource(source)
                sigs = [s for s in sigs if s.source == src]
            except ValueError:
                pass
        if sig_type:
            try:
                st = SignatureType(sig_type)
                sigs = [s for s in sigs if s.sig_type == st]
            except ValueError:
                pass
        return {
            "total": len(sigs),
            "signatures": [s.to_dict() for s in sigs],
        }

    @app.get("/signatures/{sig_id}")
    async def get_signature(sig_id: str):
        for s in feed.compiler.signatures:
            if s.signature_id == sig_id:
                return s.to_dict()
        return JSONResponse({"error": "Signature not found"}, status_code=404)

    @app.post("/signatures/compile")
    async def compile_signature(request: "Request"):
        body = await request.json()
        sig = feed.compiler.compile_from_draft(body)
        _log_event("signature_compiled", sig.signature_id)
        return {"compiled": sig.to_dict()}

    @app.post("/signatures/test")
    async def test_signature(request: "Request"):
        body = await request.json()
        sig_id = body.get("signature_id", "")
        text = body.get("text", "")
        for s in feed.compiler.signatures:
            if s.signature_id == sig_id:
                match = s.matches(text)
                return {
                    "signature_id": sig_id,
                    "text_length": len(text),
                    "matches": match,
                }
        return JSONResponse({"error": "Signature not found"}, status_code=404)

    # ═══════════════════════════════════════════════════════════
    # Definition Updates
    # ═══════════════════════════════════════════════════════════

    @app.get("/updates")
    async def list_updates():
        return {
            "total": len(feed.updates),
            "updates": [u.to_dict() for u in feed.updates],
        }

    @app.get("/updates/latest")
    async def latest_update():
        if feed.updates:
            return feed.updates[-1].to_dict()
        return {"message": "No updates published yet"}

    @app.get("/updates/{update_id}")
    async def get_update(update_id: str):
        for u in feed.updates:
            if u.update_id == update_id:
                return u.to_dict()
        return JSONResponse({"error": "Update not found"}, status_code=404)

    @app.post("/updates/push")
    async def force_push(request: "Request"):
        if not _check_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=403)
        # Compile all pending and push to clients
        sigs = feed.compiler.signatures
        if not sigs:
            return {"message": "No signatures to push", "pushed": 0}
        update = feed._create_and_push_update(
            sigs,
            priority=UpdatePriority.STANDARD,
            description="Manual push via API",
            source="admin",
        )
        _log_event("force_push", update.update_id)
        return {
            "update_id": update.update_id,
            "signatures_pushed": update.signature_count,
            "clients_notified": feed.client_count,
        }

    # ═══════════════════════════════════════════════════════════
    # Client Management
    # ═══════════════════════════════════════════════════════════

    @app.get("/clients")
    async def list_clients():
        return {
            "total": feed.client_count,
            "clients": [c.to_dict() for c in feed._clients],
        }

    @app.post("/clients/register")
    async def register_client(request: "Request"):
        body = await request.json()
        client = ClientEndpoint(
            client_id=body.get("client_id", f"cli-{uuid.uuid4().hex[:6]}"),
            name=body.get("name", "Unknown Client"),
            webhook_url=body.get("webhook_url", ""),
            channel=UpdateChannel(body.get("channel", "push")),
        )
        feed.register_client(client)
        _log_event("client_registered", client.client_id)
        return {"registered": client.to_dict()}

    @app.delete("/clients/{client_id}")
    async def deregister_client(client_id: str, request: "Request"):
        if not _check_admin(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=403)
        removed = feed.deregister_client(client_id)
        if removed:
            _log_event("client_deregistered", client_id)
            return {"removed": client_id}
        return JSONResponse({"error": "Client not found"}, status_code=404)

    @app.get("/clients/{client_id}/receipts")
    async def client_receipts(client_id: str):
        for c in feed._clients:
            if c.client_id == client_id:
                return {
                    "client_id": client_id,
                    "name": c.name,
                    "updates_received": c.updates_received,
                    "last_update_at": c.last_update_at,
                    "active": c.active,
                }
        return JSONResponse({"error": "Client not found"}, status_code=404)

    # ═══════════════════════════════════════════════════════════
    # Ingestion Webhooks
    # ═══════════════════════════════════════════════════════════

    @app.post("/ingest/canary")
    async def ingest_canary(request: "Request"):
        body = await request.json()
        event = feed.ingest_canary_incident(body)
        _log_event("ingest_canary", event.event_id)
        return {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "signatures_compiled": len(event.signatures),
        }

    @app.post("/ingest/arena")
    async def ingest_arena(request: "Request"):
        body = await request.json()
        event = feed.ingest_arena_breakthrough(body)
        _log_event("ingest_arena", event.event_id)
        return {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "signatures_compiled": len(event.signatures),
        }

    @app.post("/ingest/ctf")
    async def ingest_ctf(request: "Request"):
        body = await request.json()
        event = feed.ingest_ctf_discovery(body)
        _log_event("ingest_ctf", event.event_id)
        return {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "signatures_compiled": len(event.signatures),
        }

    @app.post("/ingest/card")
    async def ingest_card(request: "Request"):
        body = await request.json()
        event = feed.ingest_draft_card(body)
        _log_event("ingest_card", event.event_id)
        return {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
        }

    # ═══════════════════════════════════════════════════════════
    # Subscriber Management
    # ═══════════════════════════════════════════════════════════

    @app.get("/subscribers")
    async def list_subscribers():
        return {
            "total": feed.subscriber_count,
            "subscribers": [s.to_dict() for s in feed._subscribers],
        }

    @app.post("/subscribers/register")
    async def register_subscriber(request: "Request"):
        body = await request.json()
        name = body.get("name", f"sub-{uuid.uuid4().hex[:6]}")
        event_types = None
        if "event_types" in body:
            try:
                event_types = [FeedEventType(et) for et in body["event_types"]]
            except ValueError:
                pass
        sources = body.get("sources")

        # Internal subscribers get a no-op callback (events are stored in feed)
        received: list[dict] = []
        def _api_callback(event: FeedEvent) -> None:
            received.append(event.to_dict())

        sub = feed.subscribe(
            name,
            _api_callback,
            event_types=event_types,
            sources=sources,
        )
        _log_event("subscriber_registered", sub.subscriber_id)
        return {"registered": sub.to_dict()}

    return app
