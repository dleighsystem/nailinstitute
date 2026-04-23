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
from .http_client import FleetClient, FleetClientError
from .http_server import IngestServer
from .ingest import Ingest
from .retention import Retention
from .rollup import RollUp
from .signing import HAS_ARSENAL
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


def _load_trusted_keys(args):
    if not args.trusted_keys:
        return ()
    if not HAS_ARSENAL:
        print("ERROR: --trusted-keys requires the arsenal package",
              file=sys.stderr)
        sys.exit(2)
    from arsenal.keys import load_keypair  # type: ignore
    keys = []
    for spec in args.trusted_keys:
        # spec = "name" (under default dir) or "/abs/path/name" or "dir:name"
        if ":" in spec:
            d, name = spec.split(":", 1)
            keys.append(load_keypair(name=name, directory=Path(d)))
        elif "/" in spec:
            p = Path(spec)
            keys.append(load_keypair(name=p.name, directory=p.parent))
        else:
            keys.append(load_keypair(name=spec))
    return tuple(keys)


def _cmd_serve(args) -> int:
    store = _open_store(args)
    trusted = _load_trusted_keys(args)
    srv = IngestServer(store, host=args.host, port=args.port,
                       trusted_keys=trusted)
    print(json.dumps({"ok": True, "url": srv.url,
                      "signed_only": bool(trusted),
                      "db": args.db}))
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


def _cmd_push(args) -> int:
    signing_key = None
    if args.sign_with:
        if not HAS_ARSENAL:
            print("ERROR: --sign-with requires the arsenal package",
                  file=sys.stderr)
            return 2
        from arsenal.keys import load_keypair  # type: ignore
        spec = args.sign_with
        if ":" in spec:
            d, name = spec.split(":", 1)
            signing_key = load_keypair(name=name, directory=Path(d),
                                       require_private=True)
        else:
            signing_key = load_keypair(name=spec, require_private=True)

    client = FleetClient(args.url, signing_key=signing_key,
                         timeout_s=args.timeout)
    if args.event:
        ev = Event.from_json(args.event)
    else:
        ev = Event.from_json(sys.stdin.read())
    try:
        out = client.push(ev)
    except FleetClientError as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 3
    print(json.dumps(out))
    return 0


def _cmd_prune(args) -> int:
    store = _open_store(args)
    r = Retention(store, ttl_s=args.ttl, max_rows=args.max_rows)
    rep = r.apply()
    print(json.dumps({"ok": True, **rep.to_dict()}))
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

    ps = sub.add_parser("serve", help="Run the HTTP ingest server.")
    ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=8787)
    ps.add_argument("--trusted-keys", action="append", default=[],
                    metavar="NAME_OR_DIR:NAME",
                    help="arsenal key spec; may repeat. Enables signed-only ingest.")
    ps.set_defaults(func=_cmd_serve)

    pp = sub.add_parser("push", help="Push an event to a fleet HTTP endpoint.")
    pp.add_argument("--url", required=True, help="Base URL, e.g. http://host:8787")
    pp.add_argument("--event", help="Event JSON; otherwise stdin.")
    pp.add_argument("--sign-with", metavar="NAME_OR_DIR:NAME",
                    help="arsenal key spec to sign with.")
    pp.add_argument("--timeout", type=float, default=5.0)
    pp.set_defaults(func=_cmd_push)

    pr2 = sub.add_parser("prune", help="Apply retention policy.")
    pr2.add_argument("--ttl", type=float, default=None,
                     help="Drop events older than this many seconds.")
    pr2.add_argument("--max-rows", type=int, default=None,
                     help="Cap total events at N (oldest dropped first).")
    pr2.set_defaults(func=_cmd_prune)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
