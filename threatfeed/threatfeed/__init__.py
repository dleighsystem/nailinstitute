"""
ThreatFeed — Live Threat Intelligence Pipeline
=================================================

The Discover → Publish → Protect flywheel from the Agent-CVE programme.

Connects all NAIL security components into a unified pipeline:

  DISCOVER (Free):
    - Canary Fleet catches attacker techniques in the wild
    - Arena DGX Collider discovers zero-days via GA evolution
    - CTF events crowdsource attack methodologies
    - Diagnostic Pipeline catches defence failures

  PUBLISH (Free/Open):
    - Novel threats auto-draft AVE cards
    - Published to the open AVE database

  PROTECT (Commercial):
    - SignatureCompiler converts threats into executable signatures
    - DefinitionUpdates pushed to enterprise SDK clients
    - Live Threat Definition Updates protect paying customers

Architecture:
    ┌─────────┐  ┌─────────┐  ┌──────┐  ┌────────────┐
    │ Canary   │  │ Arena   │  │ CTF  │  │ Diagnostic │
    │ Fleet    │  │ DGX     │  │      │  │ Pipeline   │
    └────┬─────┘  └────┬────┘  └──┬───┘  └─────┬──────┘
         │             │          │             │
         └──────┬──────┴──────────┴─────────────┘
                ▼
    ┌───────────────────────────────────────────────┐
    │                 ThreatFeed                     │
    │  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
    │  │Subscriber│  │Signature │  │ Definition  │ │
    │  │  PubSub  │  │ Compiler │  │  Updates    │ │
    │  └──────────┘  └──────────┘  └──────┬──────┘ │
    └─────────────────────────────────────┼────────┘
                                          │
              ┌───────────────────────────┼──────┐
              ▼           ▼               ▼      ▼
          Client A    Client B        Client C  Client N
          (Bank)      (Insurer)       (FinTech) (...)
"""

__version__ = "2.0.0"

from .signature import (
    Signature,
    SignatureType,
    SignatureSource,
    SignatureCompiler,
)

from .update import (
    DefinitionUpdate,
    UpdatePriority,
    UpdateChannel,
    ClientEndpoint,
)

from .feed import (
    FeedEvent,
    FeedEventType,
    FeedSubscriber,
    FeedCallback,
    ThreatFeed,
)

# Signed advisory channel + ave-database hot-reload (M6).
from .advisory import (
    Advisory,
    AdvisoryKind,
    Severity,
    Mitigation,
    AdvisoryError,
    sign_advisory,
    parse_bundle,
    verify_bundle,
)
from .advisory_channel import (
    Channel,
    Watcher,
    WatcherState,
    DuplicateAdvisory,
    default_channel_dir,
)
from .ave_reload import (
    AveSnapshot,
    AveReloader,
    load_snapshot,
)

# Server (optional — requires pip install nail-threatfeed[server])
try:
    from .server import FeedServerConfig
except ImportError:
    FeedServerConfig = None  # type: ignore[assignment,misc]

__all__ = [
    # Signatures
    "Signature",
    "SignatureType",
    "SignatureSource",
    "SignatureCompiler",
    # Updates
    "DefinitionUpdate",
    "UpdatePriority",
    "UpdateChannel",
    "ClientEndpoint",
    # Feed
    "FeedEvent",
    "FeedEventType",
    "FeedSubscriber",
    "FeedCallback",
    "ThreatFeed",
    # Server
    "FeedServerConfig",
    # Advisory channel (M6)
    "Advisory", "AdvisoryKind", "Severity", "Mitigation", "AdvisoryError",
    "sign_advisory", "parse_bundle", "verify_bundle",
    "Channel", "Watcher", "WatcherState", "DuplicateAdvisory",
    "default_channel_dir",
    "AveSnapshot", "AveReloader", "load_snapshot",
]
