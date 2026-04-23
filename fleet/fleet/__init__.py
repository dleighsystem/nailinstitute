"""NAIL Fleet R0 — telemetry roll-up across deployed agents.

Public API:

    from fleet import Event, Store, Ingest, RollUp, Heartbeat
"""
from .event import Event, Severity
from .store import Store
from .ingest import Ingest
from .rollup import RollUp, AgentSummary
from .heartbeat import Heartbeat, AgentStatus
from .retention import Retention, PruneReport
from .signing import sign_event, verify_envelope, HAS_ARSENAL
from .http_server import IngestServer
from .http_client import FleetClient, FleetClientError
from .sink import (
    Sink, NullSink, LocalSink, HttpSink, MultiSink, CapturingSink,
    set_sink, get_sink, emit, safe_emit,
)
from .query import Query, NumericStats, Percentiles
from .alerts import (
    Alert, AlertEngine, AlertRule,
    RateRule, RatioRule, PercentileRule, SilenceRule, SeverityRule,
)

__all__ = [
    "Event", "Severity",
    "Store",
    "Ingest",
    "RollUp", "AgentSummary",
    "Heartbeat", "AgentStatus",
    "Retention", "PruneReport",
    "sign_event", "verify_envelope", "HAS_ARSENAL",
    "IngestServer",
    "FleetClient", "FleetClientError",
    "Sink", "NullSink", "LocalSink", "HttpSink", "MultiSink", "CapturingSink",
    "set_sink", "get_sink", "emit", "safe_emit",
    "Query", "NumericStats", "Percentiles",
    "Alert", "AlertEngine", "AlertRule",
    "RateRule", "RatioRule", "PercentileRule", "SilenceRule", "SeverityRule",
]

__version__ = "0.4.0"
