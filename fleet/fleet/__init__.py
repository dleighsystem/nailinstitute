"""NAIL Fleet R0 — telemetry roll-up across deployed agents.

Public API:

    from fleet import Event, Store, Ingest, RollUp, Heartbeat
"""
from .event import Event, Severity
from .store import Store
from .ingest import Ingest
from .rollup import RollUp, AgentSummary
from .heartbeat import Heartbeat, AgentStatus

__all__ = [
    "Event", "Severity",
    "Store",
    "Ingest",
    "RollUp", "AgentSummary",
    "Heartbeat", "AgentStatus",
]

__version__ = "0.1.0"
