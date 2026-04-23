"""NAIL Rehearsal — sandbox dry-run before tool commit.

Public API:

    from rehearsal import (
        Sandbox, Verdict, Outcome,
        requires_rehearsal, Recorder, Replayer,
        RehearsalDenied, RehearsalHeld,
    )
"""
from .verdict import Verdict, Outcome, RehearsalDenied, RehearsalHeld
from .sandbox import Sandbox, ShadowMissing, PolicyMissing
from .decorator import requires_rehearsal
from .recorder import Recorder, Recording, ToolCall
from .replayer import Replayer, ReplaySummary

__all__ = [
    "Sandbox", "Verdict", "Outcome",
    "requires_rehearsal",
    "Recorder", "Recording", "ToolCall",
    "Replayer", "ReplaySummary",
    "RehearsalDenied", "RehearsalHeld",
    "ShadowMissing", "PolicyMissing",
]

__version__ = "0.1.0"
