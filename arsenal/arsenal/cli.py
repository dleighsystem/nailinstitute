"""nail-arsenal CLI."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .keys import default_key_dir, generate_keypair, load_keypair, load_or_create
from .tokens import inspect, mint, verify
from .errors import TokenError


def _cmd_keygen(args):
    if args.overwrite:
        k = generate_keypair(name=args.name,
                             directory=Path(args.dir) if args.dir else None,
                             overwrite=True)
    else:
        try:
            k = generate_keypair(name=args.name,
                                 directory=Path(args.dir) if args.dir else None)
        except FileExistsError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 2
    print(json.dumps({
        "kid": k.kid,
        "directory": str(args.dir or default_key_dir()),
        "name": args.name,
        "public_key_hex": k.public_bytes.hex(),
    }, indent=2))
    return 0


def _parse_tool_spec(spec: str) -> tuple[str, dict, list]:
    """Parse 'tool.name:k=v,k=v,…' into (tool, limits, conditions)."""
    if ":" not in spec:
        return spec, {}, []
    tool, rest = spec.split(":", 1)
    limits: dict = {}
    conditions: list = []
    for part in rest.split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise SystemExit(f"bad tool spec part: {part!r}")
        k, v = part.split("=", 1)
        k = k.strip(); v = v.strip()
        if k in ("calls",):
            limits[k] = int(v)
        elif k in ("cumulative_gbp", "cumulative"):
            limits[k] = float(v)
        elif k == "hold_above_gbp":
            conditions.append({"op": "hold_above_gbp", "value": float(v)})
        elif k == "max_arg_gbp":
            conditions.append({"op": "max_arg_gbp", "value": float(v)})
        elif k == "requires_user_session":
            conditions.append({"op": "requires_user_session", "value": True})
        elif k == "ip_in":
            conditions.append({"op": "ip_in", "value": v.split("|")})
        else:
            raise SystemExit(f"unknown limit/condition key: {k!r}")
    return tool, limits, conditions


def _cmd_mint(args):
    key = load_or_create(name=args.key_name,
                         directory=Path(args.key_dir) if args.key_dir else None)
    out: list[str] = []
    for spec in args.tool:
        tool, limits, conditions = _parse_tool_spec(spec)
        tok = mint(
            tool=tool, agent=args.agent, session=args.session,
            key=key, ttl_seconds=args.ttl,
            limits=limits or None,
            conditions=conditions or None,
            ave_chain_id=args.ave_chain_id,
        )
        out.append(tok)
    if args.json:
        print(json.dumps({"tokens": out, "kid": key.kid,
                          "issued_at": int(time.time()),
                          "ttl_seconds": args.ttl}, indent=2))
    else:
        for t in out:
            print(t)
    return 0


def _read_token_arg(args) -> str:
    if args.token:
        return args.token.strip()
    return sys.stdin.read().strip()


def _cmd_inspect(args):
    raw = _read_token_arg(args)
    try:
        t = inspect(raw)
    except TokenError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps({
        "ok": True,
        "header": t.header,
        "payload": t.payload,
        "signature_b64u": t.signature_b64u,
        "is_expired": t.is_expired,
        "ttl_remaining_s": t.ttl_remaining_s,
    }, indent=2))
    return 0


def _cmd_verify(args):
    raw = _read_token_arg(args)
    key = load_keypair(name=args.key_name,
                       directory=Path(args.key_dir) if args.key_dir else None,
                       require_private=False)
    try:
        t = verify(raw, trusted_keys=[key])
    except TokenError as e:
        print(json.dumps({"ok": False, "error": str(e), "kid": key.kid},
                         indent=2))
        return 2
    print(json.dumps({
        "ok": True, "kid": key.kid, "tool": t.tool, "agent": t.agent,
        "session": t.session, "ttl_remaining_s": t.ttl_remaining_s,
        "limits": t.limits, "conditions": t.conditions,
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nail-arsenal",
                                description=f"NAIL Arsenal v{__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pk = sub.add_parser("keygen", help="Generate a new ed25519 issuer keypair.")
    pk.add_argument("--name", default="nail-arsenal-1")
    pk.add_argument("--dir", help="Override key directory.")
    pk.add_argument("--overwrite", action="store_true")
    pk.set_defaults(func=_cmd_keygen)

    pm = sub.add_parser("mint", help="Mint capability tokens for a session.")
    pm.add_argument("--agent", required=True)
    pm.add_argument("--session", required=True)
    pm.add_argument("--tool", action="append", required=True,
                    help="Repeatable. Format: tool.name:limits/conditions, "
                         "e.g. refunds.issue:calls=5,cumulative_gbp=200,"
                         "hold_above_gbp=50")
    pm.add_argument("--ttl", type=int, default=1800,
                    help="Token TTL in seconds (max 86400).")
    pm.add_argument("--ave-chain-id", help="Optional shield chain id binding.")
    pm.add_argument("--key-name", default="nail-arsenal-1")
    pm.add_argument("--key-dir")
    pm.add_argument("--json", action="store_true")
    pm.set_defaults(func=_cmd_mint)

    pi = sub.add_parser("inspect",
                        help="Parse a token without verifying its signature.")
    pi.add_argument("--token", help="Token string (default: stdin)")
    pi.set_defaults(func=_cmd_inspect)

    pv = sub.add_parser("verify",
                        help="Verify signature + expiry of a token.")
    pv.add_argument("--token", help="Token string (default: stdin)")
    pv.add_argument("--key-name", default="nail-arsenal-1")
    pv.add_argument("--key-dir")
    pv.set_defaults(func=_cmd_verify)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
