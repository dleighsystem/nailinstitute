"""
cli — Command-line interface for the DGX Arena.

Commands:
    arena run              Run the Pathology Collider (default: standard mode)
    arena run --quick      Quick test run (2 seasons, 3 rounds each)
    arena run --production Full 24/7 mode (200 population, 50 rounds/season)
    arena run --rounds 20  Custom rounds per season
    arena status           Show collider state from checkpoint
    arena export           Export breakthroughs + evolved thresholds
    arena dashboard        Print live evolution dashboard
    arena resume           Resume from last checkpoint
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
        prog="arena",
        description="NAIL DGX Arena — Pathology Collider for continuous adversarial evolution",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── run ─────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Run the Pathology Collider")
    run_p.add_argument("--quick", action="store_true", help="Quick test (2 seasons, 3 rounds)")
    run_p.add_argument("--production", action="store_true", help="Full 24/7 mode (200 pop, 50 rounds)")
    run_p.add_argument("--rounds", type=int, default=0, help="Rounds per season")
    run_p.add_argument("--seasons", type=int, default=0, help="Max seasons (0=unlimited)")
    run_p.add_argument("--population", type=int, default=0, help="Red swarm population size")
    run_p.add_argument("--checkpoint-dir", type=str, default="logs/arena", help="Checkpoint directory")
    run_p.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    run_p.add_argument("--llm", type=str, choices=["nim", "ollama", "mock", "auto"],
                       default="auto", help="LLM backend for attack expansion")

    # ── status ──────────────────────────────────────────────────
    status_p = sub.add_parser("status", help="Show collider state")
    status_p.add_argument("--checkpoint-dir", type=str, default="logs/arena")

    # ── export ──────────────────────────────────────────────────
    export_p = sub.add_parser("export", help="Export breakthroughs + thresholds")
    export_p.add_argument("--checkpoint-dir", type=str, default="logs/arena")
    export_p.add_argument("--format", type=str, choices=["json", "text"], default="text")

    # ── dashboard ───────────────────────────────────────────────
    dash_p = sub.add_parser("dashboard", help="Print live evolution dashboard")
    dash_p.add_argument("--checkpoint-dir", type=str, default="logs/arena")

    # ── resume ──────────────────────────────────────────────────
    resume_p = sub.add_parser("resume", help="Resume from last checkpoint")
    resume_p.add_argument("--checkpoint-dir", type=str, default="logs/arena")
    resume_p.add_argument("--rounds", type=int, default=10)
    resume_p.add_argument("--seasons", type=int, default=0)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "dashboard":
        _cmd_dashboard(args)
    elif args.command == "resume":
        _cmd_resume(args)


def _cmd_run(args: Any) -> None:
    """Run the Pathology Collider."""
    from .collider import Collider, Schedule, ColliderHooks
    from .arena import Arena
    from .swarm import RedSwarm

    # Select mode
    if args.quick:
        collider = Collider.quick()
        mode = "Quick test"
    elif args.production:
        collider = Collider.production(checkpoint_dir=args.checkpoint_dir)
        mode = "Production 24/7"
    else:
        collider = Collider.standard()
        mode = "Standard"

    # Always honour --checkpoint-dir
    collider.checkpoint_dir = Path(args.checkpoint_dir)

    # Override schedule if custom args provided
    if args.rounds > 0:
        collider.schedule.rounds_per_season = args.rounds
    if args.seasons > 0:
        collider.schedule.max_seasons = args.seasons
    if args.population > 0:
        collider.arena.red = RedSwarm(population_size=args.population)

    # Resume from checkpoint
    if args.resume:
        loaded = collider.load_checkpoint()
        if loaded:
            print(f"📂 Resumed from checkpoint (season {collider._seasons_completed})")
        else:
            print("⚠️  No checkpoint found, starting fresh")

    # Set up hooks for live output
    collider.hooks = ColliderHooks(
        on_season_start=lambda s: print(f"\n{'─'*60}\n🔄 Season {s}"),
        on_season_end=_on_season_end,
        on_breakthrough=_on_breakthrough,
        on_checkpoint=lambda cp: print(
            f"💾 Checkpoint saved (gen {cp.generation}, "
            f"{cp.total_breakthroughs} breakthroughs)"
        ),
    )

    print(f"⚔️  NAIL Pathology Collider — {mode}")
    print(f"   Red population: {collider.arena.red.population_size}")
    print(f"   Rounds/season: {collider.schedule.rounds_per_season}")
    print(f"   Max seasons: {collider.schedule.max_seasons or '∞'}")
    print(f"   Checkpoint: {collider.checkpoint_dir}")
    print(f"   LLM: {args.llm}")
    print()

    if collider.schedule.max_seasons > 0:
        # Finite run
        collider.run_forever()
        _print_final_report(collider)
    else:
        # Infinite run
        print("   Press Ctrl+C to stop\n")
        collider.run_forever()
        _print_final_report(collider)


def _on_season_end(result: Any) -> None:
    """Pretty-print season results."""
    s = result.summary()
    bt_count = len(result.breakthroughs)
    breach_pct = f"{s['breach_rate']*100:.1f}%"
    print(
        f"   ⚡ {s['total_battles']} battles | "
        f"🔴 {s['red_wins']} red | 🔵 {s['blue_wins']} blue | "
        f"breach: {breach_pct} | "
        f"💥 {bt_count} breakthrough{'s' if bt_count != 1 else ''} | "
        f"⏱ {s['duration_seconds']:.2f}s"
    )


def _on_breakthrough(bt: Any) -> None:
    """Alert on a new breakthrough."""
    print(
        f"   🚨 BREAKTHROUGH: {bt.attack_type.value} "
        f"(gen {bt.generation}, red_score={bt.outcome.red_score:.3f})"
    )


def _print_final_report(collider: Any) -> None:
    """Print final collider report."""
    status = collider.status()
    print(f"\n{'═'*60}")
    print(f"⚔️  Pathology Collider — Final Report")
    print(f"{'═'*60}")
    print(f"  Seasons completed: {status['seasons_completed']}")
    print(f"  Generations evolved: {status['generation']}")
    print(f"  Total battles: {status['total_battles']}")
    print(f"  Red wins: {status['total_red_wins']}")
    print(f"  Blue wins: {status['total_blue_wins']}")
    print(f"  Breach rate: {status['breach_rate']*100:.1f}%")
    print(f"  Breakthroughs: {status['breakthroughs']}")
    print(f"  Uptime: {status['uptime_seconds']:.1f}s")

    cards = collider.draft_ave_cards()
    if cards:
        print(f"\n📋 {len(cards)} Draft AVE Cards:")
        for card in cards[:5]:
            print(f"    {card['ave_id']}: {card['title']} ({card['severity']})")
        if len(cards) > 5:
            print(f"    ... and {len(cards)-5} more")

    thresholds = collider.export_thresholds()
    if thresholds:
        print(f"\n🛡️  Evolved Blue Bridge Thresholds (top 5):")
        sorted_t = sorted(thresholds.items(), key=lambda x: x[1], reverse=True)
        for name, val in sorted_t[:5]:
            print(f"    {name}: {val:.4f}")

    print(f"\n💾 Checkpoint: {collider.checkpoint_dir}")
    print()


def _cmd_status(args: Any) -> None:
    """Show collider state from checkpoint."""
    from .collider import Checkpoint

    cp_path = Path(args.checkpoint_dir) / "checkpoint.json"
    if not cp_path.exists():
        print("No checkpoint found. Run 'arena run' first.")
        return

    cp = Checkpoint.load(cp_path)
    info = cp.to_dict()

    print(f"⚔️  Pathology Collider — Status")
    print(f"{'─'*40}")
    print(f"  Collider ID: {info['collider_id']}")
    print(f"  Season: {info['season']}")
    print(f"  Generation: {info['generation']}")
    print(f"  Red population: {info['red_population_size']}")
    print(f"  Total battles: {info['total_battles']}")
    print(f"  Red wins: {info['total_red_wins']}")
    print(f"  Blue wins: {info['total_blue_wins']}")
    breach_rate = info['total_red_wins'] / max(1, info['total_battles'])
    print(f"  Breach rate: {breach_rate*100:.1f}%")
    print(f"  Breakthroughs: {info['total_breakthroughs']}")
    print(f"  Last checkpoint: {time.ctime(info['timestamp'])}")


def _cmd_export(args: Any) -> None:
    """Export breakthroughs + evolved thresholds."""
    from .collider import Checkpoint

    cp_path = Path(args.checkpoint_dir) / "checkpoint.json"
    if not cp_path.exists():
        print("No checkpoint found. Run 'arena run' first.")
        return

    cp = Checkpoint.load(cp_path)

    if args.format == "json":
        data = {
            "collider_id": cp.collider_id,
            "generation": cp.generation,
            "breakthroughs": cp.breakthroughs,
            "blue_thresholds": cp.blue_thresholds,
            "fitness_trajectory": cp.fitness_trajectory,
        }
        print(json.dumps(data, indent=2))
    else:
        print(f"⚔️  Pathology Collider — Export")
        print(f"{'─'*40}")
        print(f"  Breakthroughs: {len(cp.breakthroughs)}")
        for bt in cp.breakthroughs[:10]:
            print(f"    {bt.get('breakthrough_id', '?')}: "
                  f"{bt.get('attack_type', '?')} "
                  f"(red={bt.get('red_score', 0):.3f})")
        if len(cp.breakthroughs) > 10:
            print(f"    ... and {len(cp.breakthroughs)-10} more")

        print(f"\n  Blue Thresholds:")
        for name, val in sorted(cp.blue_thresholds.items()):
            print(f"    {name}: {val:.4f}")


def _cmd_dashboard(args: Any) -> None:
    """Print evolution dashboard from checkpoint."""
    from .collider import Checkpoint

    cp_path = Path(args.checkpoint_dir) / "checkpoint.json"
    if not cp_path.exists():
        print("No checkpoint found. Run 'arena run' first.")
        return

    cp = Checkpoint.load(cp_path)
    info = cp.to_dict()

    breach_rate = info['total_red_wins'] / max(1, info['total_battles'])

    print(f"┌{'─'*58}┐")
    print(f"│ ⚔️  NAIL Pathology Collider Dashboard{' '*20}│")
    print(f"├{'─'*58}┤")
    print(f"│  Season: {info['season']:<10}  Generation: {info['generation']:<17}│")
    print(f"│  Battles: {info['total_battles']:<9}  Breach Rate: {breach_rate*100:.1f}%{' '*14}│")
    print(f"│  Red Wins: {info['total_red_wins']:<8}  Blue Wins: {info['total_blue_wins']:<16}│")
    print(f"│  Breakthroughs: {info['total_breakthroughs']:<40}│")
    print(f"├{'─'*58}┤")

    # Fitness trajectory (ASCII sparkline)
    trajectory = info.get("fitness_trajectory", [])
    if trajectory:
        print(f"│  📈 Red Fitness (last {len(trajectory)} generations):{' '*17}│")
        for entry in trajectory:
            gen = entry.get("generation", 0)
            best = entry.get("best", 0)
            mean = entry.get("mean", 0)
            bar_len = int(best * 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            line = f"│  G{gen:03d} {bar} {best:.3f}"
            print(f"{line}{' '*(59-len(line))}│")

    print(f"└{'─'*58}┘")


def _cmd_resume(args: Any) -> None:
    """Resume from last checkpoint."""
    from .collider import Collider, Schedule, ColliderHooks

    collider = Collider.standard()
    collider.checkpoint_dir = Path(args.checkpoint_dir)

    if args.rounds > 0:
        collider.schedule.rounds_per_season = args.rounds
    if args.seasons > 0:
        collider.schedule.max_seasons = args.seasons

    loaded = collider.load_checkpoint()
    if not loaded:
        print("No checkpoint found. Use 'arena run' to start fresh.")
        return

    print(f"📂 Resuming from season {collider._seasons_completed}, "
          f"generation {collider.arena.red.generation}")

    collider.hooks = ColliderHooks(
        on_season_start=lambda s: print(f"\n🔄 Season {s}"),
        on_season_end=_on_season_end,
        on_breakthrough=_on_breakthrough,
        on_checkpoint=lambda cp: print(f"💾 Checkpoint saved"),
    )

    collider.run_forever()
    _print_final_report(collider)


if __name__ == "__main__":
    main()
