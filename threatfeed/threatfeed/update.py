"""
DefinitionUpdate — Live Threat Definition packets pushed to SDK clients.

When new threats are discovered (Canary, Arena, CTF, Diagnostic), the
compiled signatures are packaged into DefinitionUpdate objects and pushed
to all subscribed enterprise SDK clients.

This is the commercial "Protect" layer:
  - Free/Open: AVE card published to GitHub (PUBLISH)
  - Commercial: DefinitionUpdate pushed to paying clients (PROTECT)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .signature import Signature, SignatureSource


class UpdatePriority(str, Enum):
    """Urgency of the definition update."""
    EMERGENCY = "emergency"      # Zero-day — push immediately
    HIGH = "high"                # Push within 1 hour
    STANDARD = "standard"        # Push in next scheduled window
    LOW = "low"                  # Bundle with weekly update


class UpdateChannel(str, Enum):
    """Delivery channel for the update."""
    PUSH = "push"                # Real-time push via webhook/WebSocket
    POLL = "poll"                # Client polls for updates
    BATCH = "batch"              # Bundled in periodic batch


@dataclass
class DefinitionUpdate:
    """
    A package of new threat definitions for SDK clients.

    Contains one or more compiled Signatures, metadata about the
    discovery source, and delivery parameters.
    """
    update_id: str = field(default_factory=lambda: f"UPD-{uuid.uuid4().hex[:8]}")
    signatures: list[Signature] = field(default_factory=list)
    priority: UpdatePriority = UpdatePriority.STANDARD
    channel: UpdateChannel = UpdateChannel.PUSH
    description: str = ""
    source_summary: str = ""
    created_at: float = field(default_factory=time.time)
    published: bool = False
    published_at: float = 0.0

    @property
    def signature_count(self) -> int:
        return len(self.signatures)

    def publish(self) -> None:
        """Mark this update as published (sent to clients)."""
        self.published = True
        self.published_at = time.time()

    def add_signature(self, sig: Signature) -> None:
        """Add a signature to this update."""
        self.signatures.append(sig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "update_id": self.update_id,
            "signature_count": self.signature_count,
            "priority": self.priority.value,
            "channel": self.channel.value,
            "description": self.description,
            "source_summary": self.source_summary,
            "published": self.published,
            "created_at": self.created_at,
            "published_at": self.published_at,
            "signatures": [s.to_dict() for s in self.signatures],
        }

    def summary(self) -> str:
        status = "PUBLISHED" if self.published else "PENDING"
        return (
            f"[{self.update_id}] [{status}] [{self.priority.value.upper()}] "
            f"{self.signature_count} signatures — {self.description}"
        )


@dataclass
class ClientEndpoint:
    """
    An SDK client that receives definition updates.

    Represents a subscribed enterprise customer's endpoint.
    """
    client_id: str
    name: str
    webhook_url: str = ""
    channel: UpdateChannel = UpdateChannel.PUSH
    active: bool = True
    last_update_at: float = 0.0
    updates_received: int = 0

    def receive(self, update: DefinitionUpdate) -> dict[str, Any]:
        """
        Simulate receiving an update at this endpoint.

        In production, this would POST to webhook_url.
        Returns a receipt.
        """
        self.last_update_at = time.time()
        self.updates_received += 1
        return {
            "client_id": self.client_id,
            "update_id": update.update_id,
            "signatures_received": update.signature_count,
            "status": "delivered" if self.active else "inactive",
            "timestamp": self.last_update_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "name": self.name,
            "channel": self.channel.value,
            "active": self.active,
            "updates_received": self.updates_received,
            "last_update_at": self.last_update_at,
        }
