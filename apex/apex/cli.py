"""nail-apex CLI — query the brain from the shell."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .brain import ApexBrain
from .router import CosineRouter, GuardRouter
from .system1 import System1
from .system2 import System2


def _build_brain(args) -> ApexBrain:
    if args.router == "guard":
        router = GuardRouter(model=args.guard_model)
    else:
        router = CosineRouter()
    return ApexBrain(
        router=router,
        system1=System1(model=args.sys1_model),
        system2=System2(model=args.sys2_model),
        enable_shield=not args.no_shield,
        enable_telemetry=not args.no_telemetry,
        block_on_injection=not args.allow_injection,
        agent_id=args.agent_id,
    )


def _cmd_ask(args) -> int:
    brain = _build_brain(args)
    if args.query:
        query = args.query
    else:
        query = sys.stdin.read().strip()
    if not query:
        print("usage: nail-apex ask 'your query'   (or pipe via stdin)",
              file=sys.stderr)
        return 2
    resp = brain.process(query)
    if args.json:
        print(json.dumps(resp.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"[{resp.system}] ({resp.duration_ms:.0f} ms)")
        if resp.shield_blocked:
            print(f"BLOCKED by shield: {resp.shield_reason}")
        print(resp.answer)
    return 0


def _cmd_route(args) -> int:
    """Show only the routing decision (no LLM call)."""
    if args.router == "guard":
        router = GuardRouter(model=args.guard_model)
    else:
        router = CosineRouter()
    query = args.query or sys.stdin.read().strip()
    if not query:
        print("usage: nail-apex route 'your query'", file=sys.stderr)
        return 2
    print(router.classify(query))
    return 0


def _cmd_serve(args) -> int:
    """Run the Ollama-compatible facade."""
    try:
        from .server import serve
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    brain = _build_brain(args)
    print(f"nail-apex serve: http://{args.host}:{args.port} "
          f"(model='{args.model_name}', router={args.router})",
          file=sys.stderr)
    serve(host=args.host, port=args.port,
          brain=brain, model_name=args.model_name)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nail-apex",
                                description="NAIL Apex cognitive front-end CLI.")
    p.add_argument("--router", choices=["cosine", "guard"],
                   default=os.environ.get("APEX_ROUTER", "cosine"))
    p.add_argument("--sys1-model", default=os.environ.get(
        "APEX_SYS1_MODEL", "llama3.1:8b-instruct-q8_0"))
    p.add_argument("--sys2-model", default=os.environ.get(
        "APEX_SYS2_MODEL", "nail-reason:v5"))
    p.add_argument("--guard-model", default=os.environ.get(
        "APEX_GUARD_MODEL", "nail-guard:v4"))
    p.add_argument("--no-shield", action="store_true",
                   help="Skip shield neutralisation.")
    p.add_argument("--no-telemetry", action="store_true",
                   help="Skip fleet event emission.")
    p.add_argument("--allow-injection", action="store_true",
                   help="Do not block on shield's injection verdict.")
    p.add_argument("--agent-id", default=os.environ.get("NAIL_AGENT_ID"))

    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("ask", help="Send query through the full brain.")
    pa.add_argument("query", nargs="?")
    pa.add_argument("--json", action="store_true",
                    help="Emit full ApexResponse as JSON.")
    pa.set_defaults(func=_cmd_ask)

    pr = sub.add_parser("route", help="Show only the routing verdict.")
    pr.add_argument("query", nargs="?")
    pr.set_defaults(func=_cmd_route)

    ps = sub.add_parser("serve", help="Run the Ollama-compatible HTTP facade.")
    ps.add_argument("--host", default=os.environ.get("APEX_HOST", "0.0.0.0"))
    ps.add_argument("--port", type=int,
                    default=int(os.environ.get("APEX_PORT", "11435")))
    ps.add_argument("--model-name",
                    default=os.environ.get("APEX_MODEL_NAME",
                                           "apex-matrix-swarm"),
                    help="The 'model' name reported on /api/tags. Match "
                         "what your downstream client expects.")
    ps.set_defaults(func=_cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
