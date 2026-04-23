"""Recorder — append-only ledger of every rehearsal in a session.

Used by:
- the @requires_rehearsal decorator (writes one entry per call)
- the CLI ``replay`` command (reads JSONL traces from disk)
- post-mortem audit (count of allow/hold/deny per tool)
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .verdict import Outcome, Verdict


@dataclass
class ToolCall:
    """One recorded rehearsal."""
    tool: str
    args: dict
    shadow_result: Any
    verdict: Verdict
    duration_ms: float
    timestamp: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args": _json_safe(self.args),
            "shadow_result": _json_safe(self.shadow_result),
            "verdict": self.verdict.to_dict(),
            "duration_ms": round(self.duration_ms, 3),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ToolCall":
        v = d.get("verdict") or {}
        return cls(
            tool=d["tool"],
            args=dict(d.get("args") or {}),
            shadow_result=d.get("shadow_result"),
            verdict=Verdict(
                outcome=Outcome(v.get("outcome", "allow")),
                reason=v.get("reason", ""),
                metadata=dict(v.get("metadata") or {}),
            ),
            duration_ms=float(d.get("duration_ms", 0)),
            timestamp=float(d.get("timestamp", time.time())),
        )


@dataclass
class Recording:
    """A series of ToolCalls — typically one session."""
    session_id: str
    calls: list[ToolCall] = field(default_factory=list)

    # ── metrics ──────────────────────────────────────────────────
    def counts(self) -> dict[str, int]:
        c = {Outcome.ALLOW.value: 0, Outcome.HOLD.value: 0,
             Outcome.DENY.value: 0}
        for tc in self.calls:
            c[tc.verdict.outcome.value] += 1
        return c

    def by_tool(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for tc in self.calls:
            d = out.setdefault(tc.tool, {Outcome.ALLOW.value: 0,
                                        Outcome.HOLD.value: 0,
                                        Outcome.DENY.value: 0})
            d[tc.verdict.outcome.value] += 1
        return out


class Recorder:
    """Thread-safe in-memory ledger. Optionally tee writes to a JSONL file."""

    def __init__(self, *, session_id: str = "default",
                 jsonl_path: Path | None = None) -> None:
        self.session_id = session_id
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._calls: list[ToolCall] = []
        self._lock = threading.Lock()

    def record(self, tc: ToolCall) -> None:
        with self._lock:
            self._calls.append(tc)
            if self.jsonl_path:
                with self.jsonl_path.open("a") as f:
                    f.write(json.dumps(tc.to_dict()) + "\n")

    def snapshot(self) -> Recording:
        with self._lock:
            return Recording(self.session_id, list(self._calls))

    def clear(self) -> None:
        with self._lock:
            self._calls.clear()

    def __len__(self) -> int:
        return len(self._calls)


def load_jsonl(path: Path) -> Recording:
    """Read a recorded session back into a Recording."""
    p = Path(path)
    calls: list[ToolCall] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        calls.append(ToolCall.from_dict(json.loads(line)))
    return Recording(session_id=p.stem, calls=calls)


# ── helpers ──────────────────────────────────────────────────────────
def _json_safe(v: Any) -> Any:
    """Best-effort coerce-to-JSON. Falls back to repr() for weird types."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    try:
        return asdict(v)
    except TypeError:
        pass
    return repr(v)
