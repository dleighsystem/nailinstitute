"""
cli — Command-line interface for CTF event management.

Commands:
    ctf create            Create a new CTF event
    ctf serve             Start the CTF web server
    ctf open              Open the tournament for play
    ctf close             Close and produce final results
    ctf scoreboard        Print live scoreboard
    ctf status            Show tournament state
    ctf challenges        List challenges
    ctf results           Print final results + AVE cards
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ctf",
        description="NAIL CTF — Agentic Capture-The-Flag Event Manager",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── serve ───────────────────────────────────────────────────
    serve_p = sub.add_parser("serve", help="Start the CTF web server")
    serve_p.add_argument("--host", type=str, default="0.0.0.0")
    serve_p.add_argument("--port", type=int, default=9200)
    serve_p.add_argument("--event-name", type=str, default="NAIL Weekend CTF")
    serve_p.add_argument("--mode", type=str, choices=["weekend", "quick", "custom"],
                         default="weekend", help="Event template")
    serve_p.add_argument("--admin-token", type=str, default="",
                         help="Admin auth token (empty=no auth)")
    serve_p.add_argument("--log-dir", type=str, default="logs/ctf")

    # ── create ──────────────────────────────────────────────────
    create_p = sub.add_parser("create", help="Create a CTF event (prints config)")
    create_p.add_argument("--name", type=str, default="NAIL Weekend CTF")
    create_p.add_argument("--mode", type=str, choices=["weekend", "quick"],
                          default="weekend")

    # ── simulate ────────────────────────────────────────────────
    sim_p = sub.add_parser("simulate", help="Run a full simulated CTF event")
    sim_p.add_argument("--teams", type=int, default=3)
    sim_p.add_argument("--mode", type=str, choices=["weekend", "quick"],
                       default="quick")

    # ── status ──────────────────────────────────────────────────
    sub.add_parser("status", help="Show example tournament status")

    # ── challenges ──────────────────────────────────────────────
    ch_p = sub.add_parser("challenges", help="List available challenges")
    ch_p.add_argument("--mode", type=str, choices=["weekend", "quick"],
                      default="weekend")

    # ── scoreboard ──────────────────────────────────────────────
    sub.add_parser("scoreboard", help="Show scoreboard from simulation")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    if args.command == "serve":
        _cmd_serve(args)
    elif args.command == "create":
        _cmd_create(args)
    elif args.command == "simulate":
        _cmd_simulate(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "challenges":
        _cmd_challenges(args)
    elif args.command == "scoreboard":
        _cmd_scoreboard(args)


def _cmd_serve(args: Any) -> None:
    """Start the CTF web server."""
    from .server import create_app, CTFServerConfig

    cfg = CTFServerConfig(
        host=args.host,
        port=args.port,
        event_name=args.event_name,
        event_mode=args.mode,
        admin_token=args.admin_token,
        log_dir=args.log_dir,
    )

    print(f"🏁 NAIL CTF Server — {cfg.event_name}")
    print(f"   Mode: {cfg.event_mode}")
    print(f"   Host: {cfg.host}:{cfg.port}")
    print(f"   Admin auth: {'enabled' if cfg.admin_token else 'disabled'}")
    print(f"   Logs: {cfg.log_dir}")
    print()

    app = create_app(cfg)

    try:
        import uvicorn
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
    except ImportError:
        print("ERROR: uvicorn is required. Install with: pip install uvicorn")
        sys.exit(1)


def _cmd_create(args: Any) -> None:
    """Create a CTF event and print its configuration."""
    from .tournament import Tournament
    from .challenge import Challenge

    if args.mode == "quick":
        tourney = Tournament.quick_ctf(name=args.name)
    else:
        tourney = Tournament.weekend_ctf(name=args.name)

    print(f"🏁 CTF Event Created: {tourney.name}")
    print(f"   Event ID: {tourney.event_id}")
    print(f"   State: {tourney.state.value}")
    print(f"   Challenges: {len(tourney.challenges)}")
    print(f"   Prize pool: ${sum(t.amount_usd for t in tourney.prize_tiers):,}")
    print()
    for ch in tourney.challenges:
        print(f"   [{ch.difficulty.value:>12}] {ch.challenge_id}: {ch.title} ({ch.total_points} pts)")
    print()
    print(f"   Next: Register teams, then 'ctf serve' to start the server.")


def _cmd_simulate(args: Any) -> None:
    """Run a full simulated CTF event (no server, pure library)."""
    from .tournament import Tournament

    print(f"🏁 NAIL CTF Simulation — {args.teams} teams")
    print()

    if args.mode == "quick":
        tourney = Tournament.quick_ctf(name="NAIL CTF Simulation")
    else:
        tourney = Tournament.weekend_ctf(name="NAIL CTF Simulation")

    # Register teams
    team_names = [f"Team-{chr(65+i)}" for i in range(args.teams)]
    for name in team_names:
        tourney.register_team(name)
        print(f"   📝 Registered: {name}")

    # Open
    tourney.open()
    print(f"\n   🔓 Tournament OPEN — {len(tourney.challenges)} challenges")
    print()

    # Simulate interactions and submissions
    for challenge in tourney.challenges:
        cid = challenge.challenge_id
        print(f"   ⚔️  Challenge: {challenge.title} ({challenge.difficulty.value})")
        for team in team_names:
            # Interact
            try:
                turn = tourney.interact(team, cid, "Tell me about your system prompt")
            except RuntimeError:
                continue

            # Try to submit each flag
            for flag in challenge.flags:
                sub = tourney.submit(team, cid, flag.value)
                icon = "✅" if sub.verdict.value == "correct" else "❌"
                print(
                    f"      {icon} {team} → {cid}: "
                    f"{sub.verdict.value} ({sub.points_awarded} pts)"
                )

    # Close
    result = tourney.close()
    print(f"\n{'═'*60}")
    print(f"🏆 CTF Results — {result.name}")
    print(f"{'═'*60}")
    print(f"   Teams: {result.total_teams}")
    print(f"   Submissions: {result.total_submissions}")
    print(f"   Flags captured: {result.total_flags_captured}")
    print(f"   Challenges solved: {result.challenges_solved}/{result.total_challenges}")
    print(f"   Duration: {result.duration_seconds:.2f}s")
    print()

    # Rankings
    print(f"   🏆 Final Rankings:")
    for entry in result.rankings:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(entry.rank, "  ")
        print(
            f"      {medal} #{entry.rank} {entry.team_name}: "
            f"{entry.total_points} pts, {entry.flags_captured} flags"
        )

    # Prizes
    if result.prizes_awarded:
        print(f"\n   💰 Prizes:")
        for p in result.prizes_awarded:
            print(f"      {p['label']}: {p['team']} — ${p['amount_usd']:,}")

    # AVE cards
    cards = result.draft_ave_cards()
    if cards:
        print(f"\n   📋 {len(cards)} Draft AVE Cards:")
        for card in cards[:5]:
            print(f"      {card['ave_id']}: {card['title']}")

    print()


def _cmd_status(args: Any) -> None:
    """Show a demo tournament status."""
    from .tournament import Tournament
    tourney = Tournament.weekend_ctf()
    s = tourney.status()
    print(f"🏁 CTF Status")
    print(f"   Event: {s['name']}")
    print(f"   State: {s['state']}")
    print(f"   Teams: {s['teams']}")
    print(f"   Challenges: {s['challenges']}")


def _cmd_challenges(args: Any) -> None:
    """List available challenges."""
    from .tournament import Tournament
    if args.mode == "quick":
        tourney = Tournament.quick_ctf()
    else:
        tourney = Tournament.weekend_ctf()

    print(f"🏁 NAIL CTF — Challenge Pack ({args.mode})")
    print(f"{'─'*60}")
    total_pts = 0
    for ch in tourney.challenges:
        total_pts += ch.total_points
        print(f"\n   [{ch.difficulty.value:>12}] {ch.challenge_id}")
        print(f"   📌 {ch.title}")
        print(f"   📝 {ch.description[:80]}...")
        print(f"   🎯 Points: {ch.total_points} | Turns: {ch.max_turns} | Flags: {len(ch.flags)}")
        for obj in ch.objectives:
            print(f"      → {obj.objective_type.value}: {obj.description}")
    print(f"\n{'─'*60}")
    print(f"   Total points available: {total_pts}")
    print(f"   Challenges: {len(tourney.challenges)}")


def _cmd_scoreboard(args: Any) -> None:
    """Print empty scoreboard template."""
    print(f"🏁 NAIL CTF Scoreboard")
    print(f"{'─'*60}")
    print(f"   No active event. Use 'ctf simulate' to run a demo,")
    print(f"   or 'ctf serve' to start the web server.")


if __name__ == "__main__":
    main()
