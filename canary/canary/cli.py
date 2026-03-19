"""
cli — Command-line interface for the Canary Fleet deployment.

Commands:
    canary deploy          Deploy the standard fleet
    canary deploy --max    Deploy the maximum fleet (all 7 personas)
    canary status          Show fleet health
    canary interact        Interactive terminal session with a canary
    canary logs            View interaction logs
    canary signatures      Extract auto-learned attack signatures
    canary cards           Generate draft AVE cards from incidents
    canary serve           Start the FastAPI server
    canary discord         Start the Discord bot
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def main(argv: list[str] | None = None) -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="canary",
        description="NAIL Canary Fleet — Agentic honeypot deployment toolkit",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── deploy ──────────────────────────────────────────────────────
    deploy_p = sub.add_parser("deploy", help="Deploy the canary fleet")
    deploy_p.add_argument("--max", action="store_true", help="Deploy maximum fleet (7 agents)")
    deploy_p.add_argument("--config", type=str, help="Path to JSON config file")
    deploy_p.add_argument("--dry-run", action="store_true", help="Show config without deploying")

    # ── status ──────────────────────────────────────────────────────
    sub.add_parser("status", help="Show fleet health and metrics")

    # ── interact ────────────────────────────────────────────────────
    interact_p = sub.add_parser("interact", help="Interactive terminal session")
    interact_p.add_argument("--agent", type=str, help="Agent name to interact with")

    # ── logs ────────────────────────────────────────────────────────
    logs_p = sub.add_parser("logs", help="View interaction logs")
    logs_p.add_argument("--agent", type=str, help="Filter by agent name")
    logs_p.add_argument("--last", type=int, default=20, help="Number of recent entries")

    # ── signatures ──────────────────────────────────────────────────
    sub.add_parser("signatures", help="Extract auto-learned attack signatures")

    # ── cards ───────────────────────────────────────────────────────
    sub.add_parser("cards", help="Generate draft AVE cards from incidents")

    # ── serve ───────────────────────────────────────────────────────
    serve_p = sub.add_parser("serve", help="Start the FastAPI server")
    serve_p.add_argument("--host", type=str, default="0.0.0.0", help="Bind address")
    serve_p.add_argument("--port", type=int, default=9000, help="Port")
    serve_p.add_argument("--no-llm", action="store_true", help="Disable LLM generation (bait mode)")
    serve_p.add_argument("--max", action="store_true", help="Deploy maximum fleet")

    # ── discord ─────────────────────────────────────────────────────
    sub.add_parser("discord", help="Start the Discord bot")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    if args.command == "deploy":
        _cmd_deploy(args)
    elif args.command == "status":
        _cmd_status()
    elif args.command == "interact":
        _cmd_interact(args)
    elif args.command == "logs":
        _cmd_logs(args)
    elif args.command == "signatures":
        _cmd_signatures()
    elif args.command == "cards":
        _cmd_cards()
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "discord":
        _cmd_discord()


def _cmd_deploy(args: Any) -> None:
    """Deploy the canary fleet."""
    from .deploy_config import standard_deployment, maximum_deployment

    if args.max:
        dm = maximum_deployment()
        fleet_type = "Maximum (7 agents)"
    else:
        dm = standard_deployment()
        fleet_type = "Standard (3 agents)"

    if args.dry_run:
        print(f"Fleet type: {fleet_type}")
        print(f"Targets: {len(dm.targets)}")
        print()
        for target in dm.export_config():
            print(json.dumps(target, indent=2))
        return

    results = dm.deploy_all()
    print(f"🚀 Canary Fleet Deployed — {fleet_type}")
    print()
    for name, ok in results.items():
        icon = "✓" if ok else "✗"
        target = dm.targets[name]
        print(f"  {icon} {name:<20} {target.channel.value:<12} {target.persona.value}")
    print()
    print(f"Total lures planted: {sum(len(a.lures) for a in dm.fleet.agents)}")
    print(f"TrapWire attached to {len(dm.fleet.trapwire.agents)} agents")


def _cmd_status() -> None:
    """Show fleet status."""
    from .deploy_config import standard_deployment
    dm = standard_deployment()
    dm.deploy_all()
    health = dm.health()
    print("📊 Canary Fleet Status")
    print(json.dumps(health, indent=2, default=str))


def _cmd_interact(args: Any) -> None:
    """Interactive terminal session."""
    from .deploy_config import standard_deployment
    dm = standard_deployment()
    dm.deploy_all()

    agent_name = args.agent
    if agent_name is None:
        # Use first available
        agent_name = next(iter(dm.targets.keys()), None)
    if agent_name is None or agent_name not in dm.targets:
        print(f"Error: Agent '{agent_name}' not found. Available: {list(dm.targets.keys())}")
        return

    target = dm.targets[agent_name]
    print(f"🐤 Interactive session with {agent_name} ({target.persona.value})")
    print(f"   Channel: {target.channel.value}")
    print(f"   Lures planted: {len(dm.fleet.get_agent(agent_name).lures)}")
    print("   Type 'quit' to exit, 'status' for detection summary")
    print()

    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() == "quit":
            break
        if user_input.lower() == "status":
            health = dm.health()
            print(json.dumps(health, indent=2, default=str))
            continue

        result = dm.process_interaction(agent_name, user_input, source_ip="terminal")

        if result.get("inbound_triggered"):
            signals = ", ".join(result.get("signals", []))
            print(f"  ⚠️  [DETECTED: {signals} | severity={result.get('severity')}]")

        print(f"Bot> {result.get('response', '')}")
        print()

    # Summary
    health = dm.health()
    incidents = dm.fleet.incident_log.count()
    print(f"\n📊 Session Summary: {incidents}")


def _cmd_logs(args: Any) -> None:
    """View interaction logs."""
    from .deploy_config import InteractionLogger
    logger = InteractionLogger()

    if args.agent:
        logs = logger.read_log(args.agent)
    else:
        logs = []
        for log_file in logger.log_dir.glob("canary_*.jsonl"):
            agent = log_file.stem.replace("canary_", "")
            logs.extend(logger.read_log(agent))

    # Sort by timestamp and take last N
    logs.sort(key=lambda x: x.get("timestamp", 0))
    logs = logs[-args.last:]

    if not logs:
        print("No interactions logged yet.")
        return

    for entry in logs:
        ts = entry.get("timestamp", 0)
        agent = entry.get("agent_name", "?")
        channel = entry.get("channel", "?")
        user_msg = entry.get("user_message", "")[:60]
        trip = entry.get("trip_result", {})
        triggered = "⚠️" if trip.get("triggered") else "  "
        print(f"{triggered} [{agent}] [{channel}] {user_msg}")


def _cmd_signatures() -> None:
    """Extract attack signatures."""
    from .deploy_config import standard_deployment
    dm = standard_deployment()
    sigs = dm.fleet.trapwire.extract_signatures()
    if not sigs:
        print("No signatures extracted yet. Run some interactions first.")
        return
    print(f"📡 {len(sigs)} Attack Signatures Extracted")
    for sig in sigs:
        print(json.dumps(sig, indent=2))


def _cmd_cards() -> None:
    """Generate draft AVE cards."""
    from .deploy_config import standard_deployment
    dm = standard_deployment()
    cards = dm.fleet.incident_log.draft_ave_cards()
    if not cards:
        print("No incidents to generate cards from. Run some interactions first.")
        return
    print(f"📋 {len(cards)} Draft AVE Cards")
    for card in cards:
        print(json.dumps(card, indent=2))


def _cmd_serve(args: Any) -> None:
    """Start the FastAPI server."""
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is required. Install with: pip install uvicorn")
        return

    from .deploy_config import standard_deployment, maximum_deployment
    from .server import create_app

    deployment = maximum_deployment() if args.max else standard_deployment()
    app = create_app(deployment, enable_llm=not args.no_llm)

    print(f"🚀 Starting Canary Fleet server on {args.host}:{args.port}")
    print(f"   Fleet: {'maximum' if args.max else 'standard'}")
    print(f"   LLM: {'enabled' if not args.no_llm else 'disabled (bait mode)'}")
    print(f"   Agents: {list(deployment.targets.keys())}")
    print()

    uvicorn.run(app, host=args.host, port=args.port)


def _cmd_discord() -> None:
    """Start the Discord bot."""
    from .discord_bot import main as discord_main
    discord_main()


if __name__ == "__main__":
    main()
