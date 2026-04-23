"""Replayer — re-runs a captured recording against the current sandbox.

Used to:
* validate that a policy change doesn't change historical verdicts unexpectedly
* CI gate: replay a golden recording and assert ALL verdicts are stable
* post-mortem: feed an attacker's actual tool sequence through new policies
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .recorder import Recording, ToolCall, load_jsonl
from .sandbox import Sandbox
from .verdict import Outcome, Verdict


@dataclass
class ReplayDelta:
    """How a single replayed call's verdict compares to the original."""
    tool: str
    args: dict
    original: Verdict
    replayed: Verdict

    @property
    def changed(self) -> bool:
        return self.original.outcome != self.replayed.outcome


@dataclass
class ReplaySummary:
    deltas: list[ReplayDelta] = field(default_factory=list)

    @property
    def total(self) -> int: return len(self.deltas)

    @property
    def changes(self) -> list[ReplayDelta]:
        return [d for d in self.deltas if d.changed]

    @property
    def stable(self) -> bool:
        return all(not d.changed for d in self.deltas)

    def transition_table(self) -> dict[tuple[str, str], int]:
        out: dict[tuple[str, str], int] = {}
        for d in self.deltas:
            k = (d.original.outcome.value, d.replayed.outcome.value)
            out[k] = out.get(k, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "stable": self.stable,
            "n_changed": len(self.changes),
            "transitions": [
                {"original": k[0], "replayed": k[1], "count": v}
                for k, v in sorted(self.transition_table().items())
            ],
            "changed_calls": [
                {"tool": d.tool,
                 "args": d.args,
                 "from": d.original.outcome.value,
                 "to": d.replayed.outcome.value,
                 "from_reason": d.original.reason,
                 "to_reason": d.replayed.reason}
                for d in self.changes
            ],
        }


class Replayer:
    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def replay(self, recording: Recording | Path | str,
               *, world: dict | None = None,
               strict: bool = False) -> ReplaySummary:
        if isinstance(recording, (str, Path)):
            recording = load_jsonl(Path(recording))
        deltas: list[ReplayDelta] = []
        for tc in recording.calls:
            r = self.sandbox.rehearse(tc.tool, args=tc.args,
                                      world=world or {}, strict=strict)
            deltas.append(ReplayDelta(
                tool=tc.tool, args=tc.args,
                original=tc.verdict, replayed=r.verdict,
            ))
        return ReplaySummary(deltas=deltas)
