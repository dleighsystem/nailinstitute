"""nail-rehearsal CLI — replay recordings + summarise verdicts."""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from pathlib import Path

from .recorder import load_jsonl
from .replayer import Replayer
from .sandbox import Sandbox


def _load_sandbox_from(path_or_dotted: str) -> Sandbox:
    """Load a Sandbox object from a Python file path (foo/bar.py:sandbox) or
    a dotted module path (mypkg.tools:sandbox).

    Format: ``<module-or-path>:<attr>`` (attr defaults to ``sandbox``)
    """
    if ":" in path_or_dotted:
        mod_ref, attr = path_or_dotted.split(":", 1)
    else:
        mod_ref, attr = path_or_dotted, "sandbox"

    if mod_ref.endswith(".py") or "/" in mod_ref:
        # File path
        p = Path(mod_ref).resolve()
        if not p.exists():
            raise SystemExit(f"sandbox file not found: {p}")
        spec = importlib.util.spec_from_file_location(p.stem, p)
        if spec is None or spec.loader is None:
            raise SystemExit(f"cannot load module from {p}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    else:
        mod = importlib.import_module(mod_ref)

    sb = getattr(mod, attr, None)
    if not isinstance(sb, Sandbox):
        raise SystemExit(
            f"{path_or_dotted!r} did not yield a Sandbox (got {type(sb).__name__})"
        )
    return sb


# ── replay subcommand ───────────────────────────────────────────────
def _cmd_replay(args) -> int:
    sandbox = _load_sandbox_from(args.sandbox)
    rec = load_jsonl(Path(args.recording))
    world = json.loads(Path(args.world).read_text()) if args.world else {}
    summary = Replayer(sandbox).replay(rec, world=world, strict=False)
    print(json.dumps(summary.to_dict(), indent=2))
    return 0 if summary.stable or args.allow_drift else 2


# ── summarise subcommand ────────────────────────────────────────────
def _cmd_summarise(args) -> int:
    rec = load_jsonl(Path(args.recording))
    out = {
        "session_id": rec.session_id,
        "n_calls": len(rec.calls),
        "counts": rec.counts(),
        "by_tool": rec.by_tool(),
    }
    print(json.dumps(out, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nail-rehearsal",
                                description="Replay + audit rehearsal traces.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("replay",
                        help="Re-run a recording through current sandbox.")
    pr.add_argument("--recording", required=True, help="JSONL trace path")
    pr.add_argument("--sandbox", required=True,
                    help="Sandbox locator: 'mypkg.tools:sandbox' or "
                         "'./tools.py:sandbox'")
    pr.add_argument("--world", help="Optional JSON file for world state.")
    pr.add_argument("--allow-drift", action="store_true",
                    help="Exit 0 even if verdicts changed.")
    pr.set_defaults(func=_cmd_replay)

    ps = sub.add_parser("summarise",
                        help="Counts of allow/hold/deny in a recording.")
    ps.add_argument("--recording", required=True)
    ps.set_defaults(func=_cmd_summarise)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
