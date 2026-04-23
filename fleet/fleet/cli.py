"""nail-fleet CLI."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .event import Event
from .heartbeat import Heartbeat
from .ingest import Ingest
from .rollup import RollUp
from .store import Store


DEFAULT_DB = os.environ.get(
    "NAIL_FLEET_DB",
    str(Path.home() / ".nail" / "fleet.sqlite"),
)


def _open_store(args) -> Store:
    p = args.db
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    return Store(p)


def _cmd_ingest(args) -> int:
    store = _open_store(args)
    ingest = Ingest(store)
    if args.event:
        events_raw = [args.event]
    else:
        events_raw = [l for l in sys.stdin.read().splitlines() if l.strip()]
    n = 0
    for raw in events_raw:
        ingest.record(Event.from_json(raw))
        n += 1
    print(json.dumps({"ok": True, "ingested": n}))
    return 0


def _cmd_rollup(args) -> int:
    store = _open_store(args)
    r = RollUp(store)
    if args.by == "agent":
        out = r.by_agent()
    elif args.by == "kind":
        out = r.by_kind()
    elif args.by == "severity":
        out = r.by_severity()
    elif args.by == "overview":
        out = r.overview()
    else:
        print(f"unknown --by {args.by!r}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def _cmd_agents(args) -> int:
    store = _open_store(args)
    hb = Heartbeat(store, live_window_s=args.live_window)
    statuses = hb.status()
    out = [
        {
            "agent_id": s.agent_id,
            "first_seen": s.first_seen,
            "last_seen": s.last_seen,
            "age_s": round(s.age_s, 1),
            "is_live": s.is_live,
            "meta": s.meta,
        }
        for s in statuses
    ]
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def _cmd_tail(args) -> int:
    store = _open_store(args)
    events = store.query_events(
        agent_id=args.agent,
        kind=args.kind,
        severity=args.severity,
        limit=args.limit,
        order="desc",
    )
    for ev in events:
        print(ev.to_json())
    return 0


def _cmd_export(args) -> int:
    store = _open_store(args)
    for ev in store.query_events():
        print(ev.to_json())
    return 0


def _cmd_beat(args) -> int:
    store = _open_store(args)
    hb = Heartbeat(store)
    meta = json.loads(args.meta) if args.meta else None
    hb.beat(args.agent_id, meta=meta)
    print(json.dumps({"ok": True, "agent_id": args.agent_id,
                      "ts": time.time()}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nail-fleet",
                                description="NAIL Fleet telemetry CLI.")
    p.add_argument("--db", default=DEFAULT_DB,
                   help=f"sqlite path (default {DEFAULT_DB}; ':memory:' for ephemeral).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="Ingest event(s).")
    pi.add_argument("--event", help="One event JSON. Otherwise read JSONL from stdin.")
    pi.set_defaults(func=_cmd_ingest)

    pr = sub.add_parser("roll-up", help="Aggregate query.")
    pr.add_argument("--by", choices=["agent", "kind", "severity", "overview"],
                    default="overview")
    pr.set_defaults(func=_cmd_rollup)

    pa = sub.add_parser("agents", help="List known agents.")
    pa.add_argument("--live-window", type=float, default=300.0,
                    help="Seconds since last_seen still considered live.")
    pa.set_defaults(func=_cmd_agents)

    pt = sub.add_parser("tail", help="Tail recent events.")
    pt.add_argument("--agent")
    pt.add_argument("--kind")
    pt.add_argument("--severity")
    pt.add_argument("--limit", type=int, default=20)
    pt.set_defaults(func=_cmd_tail)

    pe = sub.add_parser("export", help="Export all events as JSONL.")
    pe.set_defaults(func=_cmd_export)

    pb = sub.add_parser("beat", help="Register a heartbeat for an agent.")
    pb.add_argument("agent_id")
    pb.add_argument("--meta", help="JSON dict of agent metadata.")
    pb.set_defaults(func=_cmd_beat)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
