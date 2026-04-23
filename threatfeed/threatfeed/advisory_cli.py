"""nail-advisory CLI — publish / verify / tail signed advisories.

Separate from the existing ``threatfeed`` CLI to keep responsibilities clean.
Wired in as the ``nail-advisory`` console-script when ``nail-threatfeed`` is
installed in editable mode (see pyproject.toml entry points).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Sibling-package shim (same trick as advisory.py).
_HERE = Path(__file__).resolve()
_ARSENAL_PARENT = _HERE.parents[2] / "arsenal"
if str(_ARSENAL_PARENT) not in sys.path:
    sys.path.insert(0, str(_ARSENAL_PARENT))

from arsenal.keys import load_or_create, load_keypair  # noqa: E402

from .advisory import (
    Advisory, AdvisoryKind, Severity, Mitigation,
    sign_advisory, verify_bundle, AdvisoryError,
)
from .advisory_channel import Channel, Watcher, default_channel_dir


# ── publish ──────────────────────────────────────────────────────────
def _cmd_publish(args) -> int:
    key = load_or_create(name=args.key_name,
                         directory=Path(args.key_dir) if args.key_dir else None)
    mitig = Mitigation(action=args.action, scope=args.mitigation_scope,
                       ttl_s=args.ttl)
    adv = Advisory.new(
        id=args.id, kind=args.kind, severity=args.severity,
        title=args.title, summary=args.summary,
        affects=list(args.affects or []),
        ave_refs=list(args.ave_ref or []),
        mitigation=mitig, ttl_s=args.ttl,
        issuer=args.issuer,
    )
    bundle = sign_advisory(adv, key=key)
    ch = Channel(directory=Path(args.channel_dir) if args.channel_dir else None)
    try:
        path = ch.publish(bundle, allow_replace=args.replace)
    except AdvisoryError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps({
        "ok": True, "id": adv.id, "kid": key.kid,
        "channel_dir": str(ch.dir), "bundle_path": str(path),
        "issued_at": adv.issued_at, "expires_at": adv.expires_at,
    }, indent=2))
    return 0


# ── verify ───────────────────────────────────────────────────────────
def _read_bundle(args) -> dict:
    if args.bundle:
        return json.loads(Path(args.bundle).read_text())
    return json.loads(sys.stdin.read())


def _cmd_verify(args) -> int:
    key = load_keypair(name=args.key_name,
                       directory=Path(args.key_dir) if args.key_dir else None)
    try:
        adv = verify_bundle(_read_bundle(args), trusted_keys=[key])
    except AdvisoryError as e:
        print(json.dumps({"ok": False, "error": str(e), "kid": key.kid},
                         indent=2))
        return 2
    print(json.dumps({
        "ok": True, "kid": key.kid, "id": adv.id,
        "kind": adv.kind.value, "severity": adv.severity.value,
        "active": adv.is_active(), "title": adv.title,
        "affects": adv.affects, "issued_at": adv.issued_at,
        "expires_at": adv.expires_at,
    }, indent=2))
    return 0


# ── replay (cold-start) ──────────────────────────────────────────────
def _cmd_replay(args) -> int:
    ch = Channel(directory=Path(args.channel_dir) if args.channel_dir else None)
    keys = None
    if args.verify:
        keys = [load_keypair(
            name=args.key_name,
            directory=Path(args.key_dir) if args.key_dir else None,
        )]
    n = 0
    for adv in ch.replay(trusted_keys=keys, only_active=args.active_only):
        print(json.dumps({
            "id": adv.id, "kind": adv.kind.value,
            "severity": adv.severity.value, "title": adv.title,
            "active": adv.is_active(),
        }))
        n += 1
    print(f"# {n} advisor{'y' if n == 1 else 'ies'}", file=sys.stderr)
    return 0


# ── tail (stream) ────────────────────────────────────────────────────
def _cmd_tail(args) -> int:
    ch = Channel(directory=Path(args.channel_dir) if args.channel_dir else None)
    keys = None
    if args.verify:
        keys = [load_keypair(
            name=args.key_name,
            directory=Path(args.key_dir) if args.key_dir else None,
        )]
    w = Watcher(ch, trusted_keys=keys, poll_interval_s=args.interval)

    @w.on_advisory
    def _emit(adv: Advisory) -> None:
        print(json.dumps({
            "id": adv.id, "kind": adv.kind.value,
            "severity": adv.severity.value, "title": adv.title,
        }), flush=True)

    # Mark already-seen as seen if --only-new (default), else replay first.
    if not args.only_new:
        w.poll_once()
    else:
        for entry in ch.index_entries():
            w.state.last_seen_ids.add(entry["id"])

    print(f"# tailing {ch.dir} (Ctrl-C to stop)", file=sys.stderr)
    try:
        w.run_forever()
    except KeyboardInterrupt:
        return 0
    return 0


# ── arg parser ───────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nail-advisory",
        description="Publish / verify / tail signed NAIL advisories.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("publish", help="Sign and publish an advisory.")
    pp.add_argument("--id", required=True, help="e.g. ADV-2026-0042")
    pp.add_argument("--kind", required=True,
                    choices=[k.value for k in AdvisoryKind])
    pp.add_argument("--severity", required=True,
                    choices=[s.value for s in Severity])
    pp.add_argument("--title", required=True)
    pp.add_argument("--summary", default="")
    pp.add_argument("--affects", action="append", default=[],
                    help="Repeatable. e.g. model:mistral:7b-instruct, "
                         "tool:refunds.*")
    pp.add_argument("--ave-ref", action="append", default=[])
    pp.add_argument("--action", default="warn",
                    choices=["block", "warn", "rate_limit", "recall"])
    pp.add_argument("--mitigation-scope", default="global",
                    choices=["global", "tool", "agent"])
    pp.add_argument("--ttl", type=int, default=24 * 3600)
    pp.add_argument("--issuer", default="nail-arsenal:1")
    pp.add_argument("--replace", action="store_true")
    pp.add_argument("--key-name", default="nail-arsenal-1")
    pp.add_argument("--key-dir")
    pp.add_argument("--channel-dir")
    pp.set_defaults(func=_cmd_publish)

    pv = sub.add_parser("verify", help="Verify a single advisory bundle.")
    pv.add_argument("--bundle", help="Path to bundle JSON (default: stdin)")
    pv.add_argument("--key-name", default="nail-arsenal-1")
    pv.add_argument("--key-dir")
    pv.set_defaults(func=_cmd_verify)

    pr = sub.add_parser("replay", help="List all advisories in the channel.")
    pr.add_argument("--channel-dir")
    pr.add_argument("--verify", action="store_true")
    pr.add_argument("--key-name", default="nail-arsenal-1")
    pr.add_argument("--key-dir")
    pr.add_argument("--active-only", action="store_true")
    pr.set_defaults(func=_cmd_replay)

    pt = sub.add_parser("tail", help="Stream new advisories as they arrive.")
    pt.add_argument("--channel-dir")
    pt.add_argument("--verify", action="store_true")
    pt.add_argument("--key-name", default="nail-arsenal-1")
    pt.add_argument("--key-dir")
    pt.add_argument("--interval", type=float, default=1.0)
    pt.add_argument("--only-new", action="store_true",
                    help="Skip historical advisories at startup.")
    pt.set_defaults(func=_cmd_tail)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
