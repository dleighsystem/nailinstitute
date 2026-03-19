"""
AVE CLI — Command-line interface for the AVE Database
======================================================

Provides terminal commands for querying, exporting, and managing
the Agentic Vulnerabilities & Exposures database.

Usage:
    python -m ave.cli list                    # List all cards
    python -m ave.cli show AVE-2025-0001      # Show card details
    python -m ave.cli search --keyword inject # Search by keyword
    python -m ave.cli export ./ave-database   # Export all cards
    python -m ave.cli stats                   # Database statistics
    python -m ave.cli score AVE-2025-0001     # Show AVSS score
    python -m ave.cli validate ./cards/       # Validate card JSON files
    python -m ave.cli submit --name "..."     # Generate a draft card skeleton
    python -m ave.cli leaderboard              # Show contributor leaderboard
    python -m ave.cli profile <handle>         # Show contributor profile
    python -m ave.cli badges                   # Show badge catalog
    python -m ave.cli redact ./cards/ ./public/ # Generate public-tier cards
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .schema import AVECard, Category, Severity, Status
from .registry import (
    lookup, search, all_cards, card_count,
    cards_by_severity, cards_by_category, cards_by_status,
)
from .export import (
    card_to_json, card_to_markdown, export_database, generate_index_table,
)


def _severity_bar(severity: str) -> str:
    """Coloured severity indicator for terminal."""
    bars = {
        "critical": "████ CRITICAL",
        "high":     "███░ HIGH",
        "medium":   "██░░ MEDIUM",
        "low":      "█░░░ LOW",
        "info":     "░░░░ INFO",
    }
    return bars.get(severity, severity)


def cmd_list(args: argparse.Namespace) -> None:
    """List all AVE cards."""
    cards = all_cards()

    if args.severity:
        try:
            sev = Severity(args.severity)
            cards = [c for c in cards if c.severity == sev]
        except ValueError:
            print(f"Unknown severity: {args.severity}")
            sys.exit(1)

    if args.category:
        try:
            cat = Category(args.category)
            cards = [c for c in cards if c.category == cat]
        except ValueError:
            print(f"Unknown category: {args.category}")
            sys.exit(1)

    if not cards:
        print("No cards match the given filters.")
        return

    # Header
    print(f"\n{'═' * 72}")
    print(f"  AVE Database — {len(cards)} card{'s' if len(cards) != 1 else ''}")
    print(f"{'═' * 72}\n")

    for card in cards:
        print(f"  {card.short()}")

    print(f"\n{'─' * 72}")
    print(f"  Total: {len(cards)} cards")
    print()


def cmd_show(args: argparse.Namespace) -> None:
    """Show detailed card information."""
    card = lookup(args.ave_id)
    if card is None:
        print(f"Card not found: {args.ave_id}")
        sys.exit(1)

    if args.format == "json":
        print(card_to_json(card))
    elif args.format == "markdown":
        print(card_to_markdown(card))
    else:
        # Rich terminal output
        print()
        print(f"╔{'═' * 68}╗")
        print(f"║  {card.ave_id}: {card.name:<52} ║")
        print(f"╠{'═' * 68}╣")
        print(f"║  Severity:     {_severity_bar(card.severity.value):<51} ║")
        print(f"║  Category:     {card.category.value:<51} ║")
        print(f"║  Status:       {card.status.value:<51} ║")
        print(f"╠{'─' * 68}╣")

        # Summary (word-wrapped to 64 chars)
        print(f"║  Summary:{'':>58} ║")
        words = card.summary.split()
        line = "    "
        for w in words:
            if len(line) + len(w) + 1 > 65:
                print(f"║  {line:<66} ║")
                line = "    "
            line += w + " "
        if line.strip():
            print(f"║  {line:<66} ║")

        if card.mechanism:
            print(f"╠{'─' * 68}╣")
            print(f"║  Mechanism:{'':>57} ║")
            words = card.mechanism.split()
            line = "    "
            for w in words:
                if len(line) + len(w) + 1 > 65:
                    print(f"║  {line:<66} ║")
                    line = "    "
                line += w + " "
            if line.strip():
                print(f"║  {line:<66} ║")

        if card.blast_radius:
            print(f"╠{'─' * 68}╣")
            print(f"║  Blast Radius: {card.blast_radius[:53]:<53} ║")

        if card.evidence:
            print(f"╠{'─' * 68}╣")
            print(f"║  Evidence:{'':>57} ║")
            for e in card.evidence:
                print(f"║    {e.experiment_id}: {e.key_metric}={e.key_value!s:<44} ║")

        if card.defences:
            print(f"╠{'─' * 68}╣")
            print(f"║  Defences:{'':>57} ║")
            for d in card.defences:
                print(f"║    • {d.name:<62} ║")

        if card.avss_score:
            print(f"╠{'─' * 68}╣")
            print(f"║  AVSS: {card.avss_score.overall_score}/10.0 "
                  f"({card.avss_score.severity_label.upper()}){'':>40} ║")
            print(f"║  Vector: {card.avss_score.vector_string:<57} ║")

        if card.related_aves:
            print(f"╠{'─' * 68}╣")
            print(f"║  Related: {', '.join(card.related_aves):<56} ║")

        print(f"╚{'═' * 68}╝")
        print()


def cmd_search(args: argparse.Namespace) -> None:
    """Search AVE cards."""
    results = search(
        keyword=args.keyword,
        category=Category(args.category) if args.category else None,
        severity=Severity(args.severity) if args.severity else None,
        status=Status(args.status) if args.status else None,
    )

    if not results:
        print("No cards match the search criteria.")
        return

    print(f"\n  Found {len(results)} card{'s' if len(results) != 1 else ''}:\n")
    for card in results:
        print(f"  {card.short()}")
        if args.verbose:
            print(f"    {card.summary[:100]}...")
    print()


def cmd_export(args: argparse.Namespace) -> None:
    """Export the database."""
    cards = all_cards()
    counts = export_database(
        cards,
        args.output_dir,
        include_json=not args.markdown_only,
        include_markdown=not args.json_only,
        include_index=True,
        include_code=args.include_code,
    )

    print(f"\n  Exported to: {args.output_dir}")
    print(f"    JSON files:     {counts['json']}")
    print(f"    Markdown files: {counts['markdown']}")
    print(f"    Index files:    {counts['index']}")
    print()


def cmd_stats(args: argparse.Namespace) -> None:
    """Show database statistics."""
    stats = card_count()

    print(f"\n{'═' * 50}")
    print(f"  AVE Database Statistics")
    print(f"{'═' * 50}")
    print(f"\n  Total Cards: {stats['total']}\n")

    print("  By Severity:")
    for sev, count in sorted(stats["by_severity"].items()):
        bar = "█" * count + "░" * (stats["total"] - count)
        print(f"    {sev:>12}: {count:>3}  {bar[:30]}")

    print("\n  By Category:")
    for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
        print(f"    {cat:>14}: {count:>3}")

    print("\n  By Status:")
    for stat, count in sorted(stats["by_status"].items(), key=lambda x: -x[1]):
        print(f"    {stat:>16}: {count:>3}")

    print(f"\n{'═' * 50}\n")


def cmd_score(args: argparse.Namespace) -> None:
    """Show AVSS score for a card."""
    card = lookup(args.ave_id)
    if card is None:
        print(f"Card not found: {args.ave_id}")
        sys.exit(1)

    if card.avss_score is None:
        print(f"No AVSS score computed for {args.ave_id}")
        print("Use the scoring module to compute one:")
        print(f"  from ave.scoring import compute_avss, AVSSVector")
        return

    score = card.avss_score
    print(f"\n  AVSS Score for {card.ave_id}: {card.name}")
    print(f"  {'─' * 50}")
    print(f"  Overall Score:  {score.overall_score}/10.0 ({score.severity_label.upper()})")
    print(f"  Base Score:     {score.base_score}")
    print(f"  Temporal Score: {score.temporal_score}")
    print(f"  Agentic Score:  {score.agentic_score}")
    print(f"  Vector:         {score.vector_string}")
    print()


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate AVE card files."""
    from .validate import run_validation

    success = run_validation(args.path, verbose=args.verbose)
    if not success:
        sys.exit(1)


def cmd_submit(args: argparse.Namespace) -> None:
    """Generate a draft AVE card skeleton."""
    from .submit import generate_skeleton, interactive_submit

    output_dir = args.output_dir or "ave-database/cards"

    if args.interactive:
        ave_id, json_path, md_path = interactive_submit(output_dir)
    else:
        if not args.name:
            print("Error: --name is required (or use --interactive)")
            sys.exit(1)
        ave_id, json_path, md_path = generate_skeleton(
            name=args.name,
            category=args.category,
            severity=args.severity,
            contributor=args.contributor or "",
            output_dir=output_dir,
        )

    print(f"\n  ✓ Generated draft card: {ave_id}")
    print(f"    JSON:     {json_path}")
    print(f"    Markdown: {md_path}")
    print(f"\n  Next steps:")
    print(f"    1. Edit the generated files with your data")
    print(f"    2. Validate: python -m ave validate {json_path}")
    print(f"    3. Submit a pull request")
    print()


def cmd_leaderboard(args: argparse.Namespace) -> None:
    """Show the contributor leaderboard."""
    from .gamification import leaderboard, format_leaderboard

    cards_dir = getattr(args, 'cards_dir', None)
    top_n = getattr(args, 'top', 25)
    ranked = leaderboard(cards_dir=cards_dir, use_registry=True, top_n=top_n)
    print(format_leaderboard(ranked))


def cmd_profile(args: argparse.Namespace) -> None:
    """Show a contributor's profile."""
    from .gamification import get_profile, format_profile

    profile = get_profile(args.handle, use_registry=True)
    if profile is None:
        print(f"Contributor not found: {args.handle}")
        sys.exit(1)
    print(format_profile(profile))


def cmd_badges(args: argparse.Namespace) -> None:
    """Show the badge catalog."""
    from .gamification import format_badges_catalog
    print(format_badges_catalog())


def cmd_redact(args: argparse.Namespace) -> None:
    """Generate public-tier (redacted) AVE cards."""
    from .redact import generate_public_cards

    stats = generate_public_cards(
        source_dir=args.source,
        output_dir=args.output,
        overwrite=args.overwrite,
    )
    print(f"\n  Redaction complete:")
    print(f"    Processed: {stats['processed']}")
    print(f"    Written:   {stats['written']}")
    print(f"    Skipped:   {stats['skipped']}")
    print()


def cmd_hall_of_fame(args: argparse.Namespace) -> None:
    """Generate/update the HALL_OF_FAME.md file."""
    from .gamification import format_hall_of_fame

    output = getattr(args, 'output', 'HALL_OF_FAME.md')
    content = format_hall_of_fame(
        cards_dir=getattr(args, 'cards_dir', None),
        use_registry=True,
    )
    with open(output, 'w') as f:
        f.write(content)
    print(f"\n  \u2713 Generated {output}")
    print()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="ave",
        description="AVE — Agentic Vulnerabilities & Exposures Database CLI",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # list
    p_list = sub.add_parser("list", help="List all AVE cards")
    p_list.add_argument("--severity", "-s", help="Filter by severity")
    p_list.add_argument("--category", "-c", help="Filter by category")

    # show
    p_show = sub.add_parser("show", help="Show detailed card information")
    p_show.add_argument("ave_id", help="AVE card ID (e.g. AVE-2025-0001)")
    p_show.add_argument("--format", "-f", choices=["terminal", "json", "markdown"],
                        default="terminal", help="Output format")

    # search
    p_search = sub.add_parser("search", help="Search AVE cards")
    p_search.add_argument("--keyword", "-k", help="Search by keyword")
    p_search.add_argument("--severity", "-s", help="Filter by severity")
    p_search.add_argument("--category", "-c", help="Filter by category")
    p_search.add_argument("--status", help="Filter by status")
    p_search.add_argument("--verbose", "-v", action="store_true")

    # export
    p_export = sub.add_parser("export", help="Export the database")
    p_export.add_argument("output_dir", help="Output directory")
    p_export.add_argument("--json-only", action="store_true")
    p_export.add_argument("--markdown-only", action="store_true")
    p_export.add_argument("--include-code", action="store_true",
                          help="Include PoC script source code (caution!)")

    # stats
    sub.add_parser("stats", help="Show database statistics")

    # score
    p_score = sub.add_parser("score", help="Show AVSS score for a card")
    p_score.add_argument("ave_id", help="AVE card ID")

    # validate
    p_validate = sub.add_parser("validate", help="Validate AVE card files")
    p_validate.add_argument("path", help="Path to JSON file or directory of cards")
    p_validate.add_argument("--verbose", "-v", action="store_true",
                            help="Show all results including passing cards")

    # submit
    p_submit = sub.add_parser("submit", help="Generate a draft AVE card skeleton")
    p_submit.add_argument("--name", "-n", help="Vulnerability name")
    p_submit.add_argument("--category", "-c", default="emergent",
                          help="Category (default: emergent)")
    p_submit.add_argument("--severity", "-s", default="medium",
                          help="Severity (default: medium)")
    p_submit.add_argument("--contributor", help="Your name or handle")
    p_submit.add_argument("--output-dir", "-o",
                          help="Output directory (default: ave-database/cards)")
    p_submit.add_argument("--interactive", "-i", action="store_true",
                          help="Interactive mode with prompts")

    # leaderboard
    p_lb = sub.add_parser("leaderboard", help="Show contributor leaderboard")
    p_lb.add_argument("--top", "-n", type=int, default=25,
                      help="Number of contributors to show (default: 25)")
    p_lb.add_argument("--cards-dir", help="Path to cards directory")

    # profile
    p_prof = sub.add_parser("profile", help="Show contributor profile")
    p_prof.add_argument("handle", help="Contributor handle or name")

    # badges
    sub.add_parser("badges", help="Show badge catalog")

    # hall-of-fame
    p_hof = sub.add_parser("hall-of-fame", help="Generate HALL_OF_FAME.md")
    p_hof.add_argument("--output", "-o", default="HALL_OF_FAME.md",
                       help="Output file path")
    p_hof.add_argument("--cards-dir", help="Path to cards directory")

    # redact
    p_redact = sub.add_parser("redact", help="Generate public-tier (redacted) cards")
    p_redact.add_argument("source", help="Source directory with full cards")
    p_redact.add_argument("output", help="Output directory for redacted cards")
    p_redact.add_argument("--overwrite", action="store_true",
                          help="Overwrite existing files")

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "search": cmd_search,
        "export": cmd_export,
        "stats": cmd_stats,
        "score": cmd_score,
        "validate": cmd_validate,
        "submit": cmd_submit,
        "leaderboard": cmd_leaderboard,
        "profile": cmd_profile,
        "badges": cmd_badges,
        "hall-of-fame": cmd_hall_of_fame,
        "redact": cmd_redact,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
