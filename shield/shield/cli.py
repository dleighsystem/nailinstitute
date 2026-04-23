"""nail-shield CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import process
from .chain import HashChain, _default_path


def _cmd_process(args: argparse.Namespace) -> int:
    text = (Path(args.input).read_text(encoding="utf-8")
            if args.input else sys.stdin.read())
    shielded = process(
        text,
        source=args.source,
        classify=args.classify,
        chain=not args.no_chain,
    )
    if args.json:
        out = shielded.to_dict()
        out["secrets_redacted"] = {k: "***" for k in shielded.secrets}
        print(json.dumps(out, indent=2))
    else:
        print(shielded.text)
        print("---", file=sys.stderr)
        print(f"chain_id: {shielded.chain_id}", file=sys.stderr)
        print(f"secrets:  {dict(shielded.secret_counts)}", file=sys.stderr)
        print(f"changes:  {shielded.canonical_changes}", file=sys.stderr)
        if shielded.injection_score is not None:
            print(f"inject:   score={shielded.injection_score:.2f} "
                  f"is_attack={shielded.is_injection}", file=sys.stderr)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.chain) if args.chain else _default_path()
    chain = HashChain(path)
    ok, n = chain.verify()
    print(json.dumps({
        "path": str(path), "ok": ok, "entries_verified": n,
        "head": chain.head, "length": chain.length,
    }, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nail-shield",
        description="NAIL Shield — prompt-arrival neutralisation.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("process", help="Sanitise an untrusted input.")
    pp.add_argument("--input", help="Path to input file (default: stdin).")
    pp.add_argument("--source", required=True,
                    help="Provenance string, e.g. 'email:abc@x.com'.")
    pp.add_argument("--classify", action="store_true",
                    help="Run nail-guard:v4 classifier on the input.")
    pp.add_argument("--no-chain", action="store_true",
                    help="Don't append to the default hash chain.")
    pp.add_argument("--json", action="store_true",
                    help="Emit a JSON envelope instead of just the text.")
    pp.set_defaults(func=_cmd_process)

    pv = sub.add_parser("verify", help="Verify the integrity of a hash chain.")
    pv.add_argument("--chain", help="Path to chain file "
                                    "(default: ~/.nail/shield_chain.jsonl).")
    pv.set_defaults(func=_cmd_verify)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
