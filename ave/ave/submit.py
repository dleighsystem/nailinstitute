"""
AVE Submit — Generate skeleton AVE cards for community contributions.

Usage:
    python -m ave submit --name "My Vulnerability" --category memory --severity high
    python -m ave submit --interactive

Generates draft JSON + Markdown files in ave-database/cards/ with
AVE-DRAFT-XXXX IDs, ready for a pull request.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schema import Category, Severity, Status


def _next_draft_id(output_dir: str) -> str:
    """Find the next available draft ID."""
    p = Path(output_dir)
    existing = set()
    if p.is_dir():
        for f in p.glob("AVE-DRAFT-*.json"):
            try:
                num = int(f.stem.split("-")[-1])
                existing.add(num)
            except ValueError:
                pass
    n = 1
    while n in existing:
        n += 1
    return f"AVE-DRAFT-{n:04d}"


def generate_skeleton(
    name: str,
    category: str = "emergent",
    severity: str = "medium",
    summary: str = "",
    mechanism: str = "",
    blast_radius: str = "",
    prerequisite: str = "",
    contributor: str = "",
    output_dir: str = "ave-database/cards",
) -> tuple[str, str, str]:
    """
    Generate a draft AVE card skeleton.

    Returns:
        Tuple of (ave_id, json_path, md_path)
    """
    os.makedirs(output_dir, exist_ok=True)
    ave_id = _next_draft_id(output_dir)

    card_data = {
        "ave_id": ave_id,
        "name": name,
        "aliases": [],
        "category": category,
        "severity": severity,
        "status": "theoretical",
        "summary": summary or f"[DESCRIBE: What happens when {name} occurs?]",
        "mechanism": mechanism or "[DESCRIBE: Step-by-step, how does this work?]",
        "blast_radius": blast_radius or "[DESCRIBE: What breaks when this fires?]",
        "prerequisite": prerequisite or "[DESCRIBE: What conditions must be true?]",
        "environment": {
            "frameworks": ["[FILL: e.g., LangGraph, CrewAI, AutoGen]"],
            "models_tested": ["[FILL: e.g., gpt-4o, nemotron:70b]"],
            "multi_agent": False,
            "tools_required": False,
            "memory_required": False,
        },
        "evidence": [
            {
                "experiment_id": "[FILL: Your experiment/test identifier]",
                "data_file": "",
                "key_metric": "[FILL: What did you measure?]",
                "key_value": "[FILL: What was the result?]",
                "p_value": None,
                "sample_size": None,
                "cross_model": False,
            }
        ],
        "defences": [],
        "date_discovered": datetime.now(timezone.utc).strftime("%Y-%m"),
        "date_published": "",
        "cwe_mapping": "",
        "mitre_mapping": "",
        "references": [],
        "related_aves": [],
        "contributor": contributor or "[YOUR NAME / HANDLE]",
        "_meta": {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generator": "ave submit",
            "license": "CC-BY-SA-4.0",
        },
    }

    # Write JSON
    json_path = os.path.join(output_dir, f"{ave_id}.json")
    with open(json_path, "w") as f:
        json.dump(card_data, f, indent=2)

    # Write Markdown companion
    md_path = os.path.join(output_dir, f"{ave_id}.md")
    with open(md_path, "w") as f:
        sev_icon = {
            "critical": "🔴", "high": "🟠", "medium": "🟡",
            "low": "🟢", "info": "ℹ️",
        }.get(severity, "❓")

        f.write(f"# {ave_id}: {name}\n\n")
        f.write(f"| Field | Value |\n|-------|-------|\n")
        f.write(f"| **Severity** | {sev_icon} {severity} |\n")
        f.write(f"| **Category** | `{category}` |\n")
        f.write(f"| **Status** | `theoretical` |\n")
        f.write(f"| **Contributor** | {contributor or '[YOUR NAME]'} |\n")
        f.write(f"| **Date** | {card_data['date_discovered']} |\n\n")
        f.write(f"## Summary\n\n{card_data['summary']}\n\n")
        f.write(f"## Mechanism\n\n{card_data['mechanism']}\n\n")
        f.write(f"## Blast Radius\n\n{card_data['blast_radius']}\n\n")
        f.write(f"## Prerequisites\n\n{card_data['prerequisite']}\n\n")
        f.write(f"## Environment\n\n")
        f.write(f"- **Frameworks:** {', '.join(card_data['environment']['frameworks'])}\n")
        f.write(f"- **Models tested:** {', '.join(card_data['environment']['models_tested'])}\n")
        f.write(f"- **Multi-agent:** {card_data['environment']['multi_agent']}\n")
        f.write(f"- **Tools required:** {card_data['environment']['tools_required']}\n")
        f.write(f"- **Memory required:** {card_data['environment']['memory_required']}\n\n")
        f.write(f"## Evidence\n\n*[Add your reproduction steps, logs, or scripts here]*\n\n")
        f.write(f"## Defences\n\n*[Add known mitigations, if any]*\n\n")
        f.write(f"## References\n\n*[Add links to papers, blog posts, or related work]*\n\n")
        f.write(f"---\n\n")
        f.write(f"*Submitted via `ave submit` — [NAIL Institute](https://github.com/dleighsystem/nailinstitute)*\n")

    return ave_id, json_path, md_path


def interactive_submit(output_dir: str = "ave-database/cards") -> tuple[str, str, str]:
    """Interactive card submission via terminal prompts."""
    print(f"\n{'═' * 60}")
    print(f"  AVE Card Submission — Interactive Mode")
    print(f"{'═' * 60}\n")

    name = input("  Vulnerability name: ").strip()
    if not name:
        print("  Error: Name is required.")
        sys.exit(1)

    print(f"\n  Categories: {', '.join(c.value for c in Category)}")
    category = input("  Category: ").strip().lower()
    if category not in {c.value for c in Category}:
        print(f"  Warning: Unknown category '{category}', using 'emergent'")
        category = "emergent"

    print(f"\n  Severities: critical, high, medium, low, info")
    severity = input("  Severity: ").strip().lower()
    if severity not in {s.value for s in Severity}:
        print(f"  Warning: Unknown severity '{severity}', using 'medium'")
        severity = "medium"

    summary = input("\n  Summary (one paragraph): ").strip()
    mechanism = input("  Mechanism (how it works): ").strip()
    blast_radius = input("  Blast radius (what breaks): ").strip()
    prerequisite = input("  Prerequisites (conditions): ").strip()
    contributor = input("  Your name/handle: ").strip()

    return generate_skeleton(
        name=name,
        category=category,
        severity=severity,
        summary=summary,
        mechanism=mechanism,
        blast_radius=blast_radius,
        prerequisite=prerequisite,
        contributor=contributor,
        output_dir=output_dir,
    )
