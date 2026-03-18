"""
ThreatFeed — The Discover → Publish → Protect flywheel.

Central pub/sub hub that connects all NAIL security components:

  ┌──────────────────────────────────────────────────────────┐
  │                    DISCOVER (Free)                        │
  │  ┌─────────┐  ┌─────────┐  ┌──────┐  ┌────────────┐    │
  │  │ Canary   │  │ Arena   │  │ CTF  │  │ Diagnostic │    │
  │  │ Fleet    │  │ DGX     │  │      │  │ Pipeline   │    │
  │  └────┬─────┘  └────┬────┘  └──┬───┘  └─────┬──────┘    │
  │       │             │          │             │           │
  │       └──────┬──────┴──────────┴─────────────┘           │
  │              ▼                                           │
  │       ┌─────────────┐                                    │
  │       │ ThreatFeed  │ ← Central Hub                      │
  │       └──────┬──────┘                                    │
  │              │                                           │
  │    ┌─────────┼──────────┐                                │
  │    ▼         ▼          ▼                                │
  │ PUBLISH   COMPILE   PROTECT                              │
  │ (AVE DB)  (Sigs)    (SDK Push)                           │
  └──────────────────────────────────────────────────────────┘

Subscribers register callbacks and receive live threat intelligence
as it flows through the system.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .signature import Signature, SignatureCompiler, SignatureSource, SignatureType
from .update import (
    DefinitionUpdate, UpdatePriority, UpdateChannel, ClientEndpoint,
)


class FeedEventType(str, Enum):
    """Types of events flowing through the threat feed."""
    CANARY_INCIDENT = "canary_incident"
    ARENA_BREAKTHROUGH = "arena_breakthrough"
    CTF_DISCOVERY = "ctf_discovery"
    DIAGNOSTIC_FAILURE = "diagnostic_failure"
    SIGNATURE_COMPILED = "signature_compiled"
    UPDATE_PUBLISHED = "update_published"
    AVE_CARD_DRAFTED = "ave_card_drafted"
    THRESHOLD_EVOLVED = "threshold_evolved"


@dataclass
class FeedEvent:
    """A single event flowing through the ThreatFeed."""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    event_type: FeedEventType = FeedEventType.CANARY_INCIDENT
    source: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    signatures: list[Signature] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "source": self.source,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "signatures": len(self.signatures),
        }


# Type alias for subscriber callbacks
FeedCallback = Callable[[FeedEvent], None]


class FeedSubscriber:
    """
    A subscriber to the ThreatFeed.

    Receives events matching its filter criteria.
    """

    def __init__(
        self,
        name: str,
        callback: FeedCallback,
        *,
        event_types: list[FeedEventType] | None = None,
        sources: list[str] | None = None,
    ):
        self.subscriber_id = f"sub-{uuid.uuid4().hex[:6]}"
        self.name = name
        self.callback = callback
        self.event_types = set(event_types) if event_types else None
        self.sources = set(sources) if sources else None
        self.events_received: int = 0
        self.active: bool = True

    def should_receive(self, event: FeedEvent) -> bool:
        """Check if this subscriber should receive the event."""
        if not self.active:
            return False
        if self.event_types and event.event_type not in self.event_types:
            return False
        if self.sources and event.source not in self.sources:
            return False
        return True

    def deliver(self, event: FeedEvent) -> None:
        """Deliver an event to this subscriber."""
        if self.should_receive(event):
            self.callback(event)
            self.events_received += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "subscriber_id": self.subscriber_id,
            "name": self.name,
            "active": self.active,
            "events_received": self.events_received,
            "event_types": [e.value for e in self.event_types] if self.event_types else "all",
            "sources": list(self.sources) if self.sources else "all",
        }


class ThreatFeed:
    """
    Central Threat Intelligence Hub — The GTM Flywheel Engine.

    Connects all NAIL discovery sources to the commercial protection
    pipeline:

    1. DISCOVER: Canary, Arena, CTF, Diagnostic push raw intelligence
    2. COMPILE:  SignatureCompiler converts to executable signatures
    3. PUBLISH:  Draft AVE cards published to open database
    4. PROTECT:  DefinitionUpdates pushed to SDK clients

    Usage:
        feed = ThreatFeed()

        # Subscribe to events
        feed.subscribe("my-monitor", lambda e: print(e.event_type))

        # Register SDK clients
        feed.register_client(ClientEndpoint(
            client_id="acme-corp",
            name="ACME Financial",
            webhook_url="https://acme.com/nail/webhook",
        ))

        # Ingest intelligence
        feed.ingest_canary_incident(incident_data)
        feed.ingest_arena_breakthrough(breakthrough_data)

        # Auto-compiled signatures are pushed to all clients
    """

    def __init__(self, *, auto_compile: bool = True, auto_publish: bool = True):
        self.compiler = SignatureCompiler()
        self._subscribers: list[FeedSubscriber] = []
        self._clients: list[ClientEndpoint] = []
        self._events: list[FeedEvent] = []
        self._updates: list[DefinitionUpdate] = []
        self._draft_cards: list[dict[str, Any]] = []
        self.auto_compile = auto_compile
        self.auto_publish = auto_publish

    # ── Subscription Management ─────────────────────────────────

    def subscribe(
        self,
        name: str,
        callback: FeedCallback,
        *,
        event_types: list[FeedEventType] | None = None,
        sources: list[str] | None = None,
    ) -> FeedSubscriber:
        """Register a new subscriber."""
        sub = FeedSubscriber(
            name=name,
            callback=callback,
            event_types=event_types,
            sources=sources,
        )
        self._subscribers.append(sub)
        return sub

    def unsubscribe(self, subscriber_id: str) -> bool:
        """Remove a subscriber by ID."""
        for i, sub in enumerate(self._subscribers):
            if sub.subscriber_id == subscriber_id:
                self._subscribers.pop(i)
                return True
        return False

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ── Client Management ───────────────────────────────────────

    def register_client(self, client: ClientEndpoint) -> None:
        """Register an SDK client endpoint for definition updates."""
        self._clients.append(client)

    def deregister_client(self, client_id: str) -> bool:
        """Remove a client by ID."""
        for i, c in enumerate(self._clients):
            if c.client_id == client_id:
                self._clients.pop(i)
                return True
        return False

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ── Event Dispatch ──────────────────────────────────────────

    def _emit(self, event: FeedEvent) -> None:
        """Emit an event to all matching subscribers."""
        self._events.append(event)
        for sub in self._subscribers:
            sub.deliver(event)

    # ── Ingestion Sources ───────────────────────────────────────

    def ingest_canary_incident(
        self,
        incident_data: dict[str, Any],
    ) -> FeedEvent:
        """
        Ingest a Canary fleet incident.

        Auto-compiles signatures and creates a DefinitionUpdate
        if auto_compile and auto_publish are enabled.
        """
        event = FeedEvent(
            event_type=FeedEventType.CANARY_INCIDENT,
            source="canary",
            payload=incident_data,
        )

        if self.auto_compile:
            sigs = self.compiler.compile_from_canary([incident_data])
            event.signatures = sigs
            self._emit_signature_event(sigs)

        if self.auto_publish and event.signatures:
            self._create_and_push_update(
                event.signatures,
                priority=UpdatePriority.HIGH,
                description=f"Canary incident: {incident_data.get('signal', 'unknown')}",
                source="canary",
            )

        self._emit(event)
        return event

    def ingest_arena_breakthrough(
        self,
        breakthrough_data: dict[str, Any],
    ) -> FeedEvent:
        """Ingest an Arena breakthrough discovery."""
        event = FeedEvent(
            event_type=FeedEventType.ARENA_BREAKTHROUGH,
            source="arena",
            payload=breakthrough_data,
        )

        if self.auto_compile:
            sigs = self.compiler.compile_from_arena([breakthrough_data])
            event.signatures = sigs
            self._emit_signature_event(sigs)

        if self.auto_publish and event.signatures:
            self._create_and_push_update(
                event.signatures,
                priority=UpdatePriority.EMERGENCY,
                description=f"Arena breach: {breakthrough_data.get('attack_type', 'unknown')}",
                source="arena",
            )

        self._emit(event)
        return event

    def ingest_ctf_discovery(
        self,
        methodology_data: dict[str, Any],
    ) -> FeedEvent:
        """Ingest a CTF discovery / methodology."""
        event = FeedEvent(
            event_type=FeedEventType.CTF_DISCOVERY,
            source="ctf",
            payload=methodology_data,
        )

        if self.auto_compile:
            sigs = self.compiler.compile_from_ctf([methodology_data])
            event.signatures = sigs
            self._emit_signature_event(sigs)

        if self.auto_publish and event.signatures:
            self._create_and_push_update(
                event.signatures,
                priority=UpdatePriority.STANDARD,
                description=f"CTF discovery: {methodology_data.get('team', 'unknown')}",
                source="ctf",
            )

        self._emit(event)
        return event

    def ingest_threshold_evolution(
        self,
        thresholds: dict[str, float],
        *,
        source: str = "arena",
    ) -> FeedEvent:
        """Ingest evolved defence thresholds from GA."""
        event = FeedEvent(
            event_type=FeedEventType.THRESHOLD_EVOLVED,
            source=source,
            payload={"thresholds": thresholds},
        )
        self._emit(event)
        return event

    def ingest_draft_card(
        self,
        draft: dict[str, Any],
    ) -> FeedEvent:
        """Ingest a draft AVE card for publication."""
        self._draft_cards.append(draft)
        event = FeedEvent(
            event_type=FeedEventType.AVE_CARD_DRAFTED,
            source=draft.get("source", "unknown"),
            payload=draft,
        )
        self._emit(event)
        return event

    # ── Internal Helpers ────────────────────────────────────────

    def _emit_signature_event(self, sigs: list[Signature]) -> None:
        """Emit a signature compiled event."""
        for sig in sigs:
            event = FeedEvent(
                event_type=FeedEventType.SIGNATURE_COMPILED,
                source=sig.source.value,
                payload=sig.to_dict(),
                signatures=[sig],
            )
            self._emit(event)

    def _create_and_push_update(
        self,
        signatures: list[Signature],
        *,
        priority: UpdatePriority,
        description: str,
        source: str,
    ) -> DefinitionUpdate:
        """Create a DefinitionUpdate and push to all clients."""
        update = DefinitionUpdate(
            signatures=list(signatures),
            priority=priority,
            description=description,
            source_summary=source,
        )

        # Push to all active clients
        receipts: list[dict[str, Any]] = []
        for client in self._clients:
            if client.active:
                receipt = client.receive(update)
                receipts.append(receipt)

        update.publish()
        self._updates.append(update)

        # Emit update event
        self._emit(FeedEvent(
            event_type=FeedEventType.UPDATE_PUBLISHED,
            source="threatfeed",
            payload={
                "update_id": update.update_id,
                "signatures": len(signatures),
                "clients_pushed": len(receipts),
                "priority": priority.value,
            },
        ))

        return update

    # ── Query API ───────────────────────────────────────────────

    @property
    def events(self) -> list[FeedEvent]:
        return list(self._events)

    @property
    def updates(self) -> list[DefinitionUpdate]:
        return list(self._updates)

    @property
    def draft_cards(self) -> list[dict[str, Any]]:
        return list(self._draft_cards)

    def events_by_type(self, event_type: FeedEventType) -> list[FeedEvent]:
        return [e for e in self._events if e.event_type == event_type]

    def events_by_source(self, source: str) -> list[FeedEvent]:
        return [e for e in self._events if e.source == source]

    # ── Status ──────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "total_events": len(self._events),
            "total_signatures": self.compiler.count,
            "total_updates": len(self._updates),
            "total_draft_cards": len(self._draft_cards),
            "subscribers": self.subscriber_count,
            "clients": self.client_count,
            "events_by_type": {
                t.value: len(self.events_by_type(t))
                for t in FeedEventType
                if self.events_by_type(t)
            },
            "compiler": self.compiler.to_dict(),
        }

    def reset(self) -> None:
        """Reset all state. Useful for testing."""
        self._events.clear()
        self._updates.clear()
        self._draft_cards.clear()
        self._subscribers.clear()
        self._clients.clear()
        self.compiler.reset()
