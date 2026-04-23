"""nail-foresight CLI — critique a plan."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .critic import HeuristicCritic
from .critique import Verdict
from .ollama_critic import (
    DEFAULT_BASE_URL, DEFAULT_MODEL, OllamaCritic, OllamaError,
)
from .plan import Plan


def _load_plan(args) -> Plan:
    if args.plan:
        return Plan.from_path(args.plan)
    return Plan.from_json(sys.stdin.read())


def _load_world(args) -> dict:
    if not args.world:
        return {}
    return json.loads(Path(args.world).read_text())


def _build_critic(args):
    if args.critic == "heuristic":
        return HeuristicCritic()
    return OllamaCritic(model=args.model, base_url=args.base_url,
                        timeout_s=args.timeout)


def _cmd_critique(args) -> int:
    plan = _load_plan(args)
    world = _load_world(args)
    critic = _build_critic(args)
    try:
        critique = critic.critique(plan, world=world)
    except OllamaError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2),
              file=sys.stderr)
        return 3

    verdict = critique.verdict(
        hold_threshold=args.threshold_hold,
        reject_threshold=args.threshold_reject,
    )
    out = {
        "ok": True,
        "verdict": verdict.value,
        "risk": round(critique.risk, 3),
        "max_severity": critique.max_severity.value,
        "summary": critique.summary,
        "model": critique.model,
        "risks": [r.to_dict() for r in critique.risks],
    }
    print(json.dumps(out, indent=2))

    if verdict == Verdict.REJECT:
        return 2
    if verdict == Verdict.HOLD and args.fail_on_hold:
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nail-foresight",
        description="Critique an agent plan with nail-reason or heuristics.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("critique", help="Critique a plan.")
    pc.add_argument("--plan", help="Path to plan JSON. Default: stdin.")
    pc.add_argument("--world", help="Path to world-snapshot JSON.")
    pc.add_argument("--critic", choices=["ollama", "heuristic"],
                    default="ollama")
    pc.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Ollama model name (default {DEFAULT_MODEL}).")
    pc.add_argument("--base-url", default=DEFAULT_BASE_URL,
                    help=f"Ollama base URL (default {DEFAULT_BASE_URL}).")
    pc.add_argument("--timeout", type=float, default=60.0)
    pc.add_argument("--threshold-hold", type=float, default=0.40)
    pc.add_argument("--threshold-reject", type=float, default=0.70)
    pc.add_argument("--fail-on-hold", action="store_true",
                    help="Exit non-zero on HOLD as well as REJECT.")
    pc.set_defaults(func=_cmd_critique)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
