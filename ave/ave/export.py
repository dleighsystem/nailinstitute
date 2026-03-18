"""
Export — AVE Card rendering and file generation
=================================================

Produces publishable artifacts from the AVE database:

  1. JSON files   — One per card, structured for machine consumption
  2. Markdown     — Human-readable card pages for GitHub/docs
  3. Index files  — Summary tables for README.md
  4. YAML         — YAML export for CI/tooling integration
  5. Bulk export  — Generate the entire public `ave-database/` directory

This is how the private Python registry becomes the public
Agentic-Security-Project GitHub repository.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .schema import AVECard, Category, Severity, Status


# ═══════════════════════════════════════════════════════════════════════════
# SINGLE-CARD RENDERERS
# ═══════════════════════════════════════════════════════════════════════════

def card_to_json(card: AVECard, *, indent: int = 2, include_code: bool = False) -> str:
    """
    Render an AVE Card as a JSON string.

    Args:
        card:         The AVE Card to render.
        indent:       JSON indentation (default 2).
        include_code: If True and the card has PoC scripts, include source code.
                      Default False for public exports (safety).
    """
    data = card.to_dict()

    # Add AVSS score if available
    if hasattr(card, "avss_score") and card.avss_score is not None:
        data["avss_score"] = card.avss_score.to_dict()

    # Add PoC summary if available
    if hasattr(card, "poc") and card.poc is not None:
        poc_data = card.poc.to_dict()
        if not include_code:
            # Strip actual prompt text and script code for public safety
            poc_data.pop("config", None)
            for s in poc_data.get("scripts", []):
                s.pop("code", None)
            for p in poc_data.get("prompts", []):
                p.pop("prompt_text", None)
        data["poc"] = poc_data

    # Add timeline if available
    if hasattr(card, "timeline") and card.timeline is not None:
        data["timeline"] = card.timeline.to_dict()

    # Add related AVEs if available
    if hasattr(card, "related_aves") and card.related_aves:
        data["related_aves"] = list(card.related_aves)

    # Publication metadata
    data["_meta"] = {
        "schema_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator": "NAIL Institute AVE Toolkit",
        "license": "CC-BY-SA-4.0",
    }

    return json.dumps(data, indent=indent, default=str)


def card_to_markdown(card: AVECard) -> str:
    """
    Render an AVE Card as a Markdown document.

    Produces a human-readable page suitable for GitHub rendering,
    documentation sites, or AI safety newsletters.
    """
    sev_emoji = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🟢",
        "info": "⚪",
    }
    status_emoji = {
        "proven": "✅",
        "proven_mitigated": "🛡️",
        "theoretical": "🔬",
        "not_proven": "❌",
        "in_progress": "🔄",
    }

    sev = card.severity.value
    emoji = sev_emoji.get(sev, "⚪")
    st_emoji = status_emoji.get(card.status.value, "")

    lines = [
        f"# {card.ave_id}: {card.name}",
        "",
        f"> **{emoji} {sev.upper()}** | "
        f"Category: `{card.category.value}` | "
        f"Status: {st_emoji} `{card.status.value}`",
        "",
    ]

    # Aliases
    if card.aliases:
        lines.append(f"**Also known as:** {', '.join(card.aliases)}")
        lines.append("")

    # Summary
    lines.extend([
        "## Summary",
        "",
        card.summary,
        "",
    ])

    # Mechanism
    if card.mechanism:
        lines.extend([
            "## Mechanism",
            "",
            card.mechanism,
            "",
        ])

    # Blast Radius
    if card.blast_radius:
        lines.extend([
            "## Blast Radius",
            "",
            f"⚠️ {card.blast_radius}",
            "",
        ])

    # Prerequisites
    if card.prerequisite:
        lines.extend([
            "## Prerequisites",
            "",
            card.prerequisite,
            "",
        ])

    # Environment Vector
    env = card.environment
    lines.extend([
        "## Environment Vector",
        "",
        "| Component | Value |",
        "|-----------|-------|",
        f"| Frameworks | {', '.join(env.frameworks) or 'Any'} |",
        f"| Models Tested | {', '.join(env.models_tested) or 'Any'} |",
        f"| Multi-Agent | {'Yes' if env.multi_agent else 'No'} |",
        f"| Tools Required | {'Yes' if env.tools_required else 'No'} |",
        f"| Memory Required | {'Yes' if env.memory_required else 'No'} |",
    ])
    if env.rag_required:
        lines.append(f"| RAG Required | Yes |")
    if env.min_context_window:
        lines.append(f"| Min Context Window | {env.min_context_window:,} tokens |")
    lines.append("")

    # AVSS Score
    if hasattr(card, "avss_score") and card.avss_score is not None:
        score = card.avss_score
        lines.extend([
            "## AVSS Score",
            "",
            f"**Overall: {score.overall_score}/10.0** ({score.severity_label.upper()})",
            "",
            f"```",
            f"Vector: {score.vector_string}",
            f"Base Score:     {score.base_score}",
            f"Temporal Score: {score.temporal_score}",
            f"Agentic Score:  {score.agentic_score}",
            f"```",
            "",
        ])

    # Evidence
    if card.evidence:
        lines.extend([
            "## Evidence",
            "",
            "| Experiment | Data File | Key Metric | Value | Cross-Model |",
            "|------------|-----------|------------|-------|-------------|",
        ])
        for e in card.evidence:
            cm = "✅" if e.cross_model else ""
            lines.append(
                f"| `{e.experiment_id}` | `{e.data_file or '—'}` | "
                f"{e.key_metric or '—'} | {e.key_value or '—'} | {cm} |"
            )
        lines.append("")

    # PoC
    if hasattr(card, "poc") and card.poc is not None:
        poc = card.poc
        lines.extend([
            "## Proof of Concept",
            "",
            f"**{poc.poc_id}** — {poc.description or poc.poc_type.value}",
            f"Status: `{poc.status.value}` | Artifacts: {poc.artifact_count}",
            "",
        ])
        if poc.scripts:
            lines.extend([
                "### Reproduction Scripts",
                "",
            ])
            for s in poc.scripts:
                lines.extend([
                    f"- **`{s.filename}`** — {s.description}",
                    f"  Expected output: {s.expected_output}",
                ])
            lines.append("")
        if poc.prompts:
            lines.extend([
                "### Adversarial Prompts",
                "",
                "*(SHA-256 hashes provided; full text available in verified PoC bundle)*",
                "",
            ])
            for p in poc.prompts:
                lines.append(
                    f"- `{p.sha256[:16]}...` — {p.bypass_type or 'general'}: "
                    f"{p.expected_behaviour}"
                )
            lines.append("")

    # Defences
    if card.defences:
        lines.extend([
            "## Known Defences",
            "",
            "| Defence | Layer | Effectiveness | RMAP Module | Monitor Detector |",
            "|---------|-------|---------------|-------------|------------------|",
        ])
        for d in card.defences:
            lines.append(
                f"| {d.name} | {d.layer or '—'} | {d.effectiveness or '—'} | "
                f"`{d.rmap_module or '—'}` | `{d.nail_monitor_detector or '—'}` |"
            )
        lines.append("")

    # Timeline
    if hasattr(card, "timeline") and card.timeline is not None:
        tl = card.timeline
        if tl.events:
            lines.extend([
                "## Timeline",
                "",
            ])
            for e in tl.events:
                lines.append(f"- **{e.timestamp}** — `{e.stage.value}` ({e.actor})")
                if e.notes:
                    lines.append(f"  {e.notes}")
            lines.append("")

    # Related AVEs
    if hasattr(card, "related_aves") and card.related_aves:
        lines.extend([
            "## Related AVEs",
            "",
        ])
        for rel in card.related_aves:
            lines.append(f"- [{rel}](./{rel}.md)")
        lines.append("")

    # Mappings
    mappings = []
    if card.cwe_mapping:
        mappings.append(f"**CWE:** {card.cwe_mapping}")
    if card.mitre_mapping:
        mappings.append(f"**MITRE ATT&CK:** {card.mitre_mapping}")
    if mappings:
        lines.extend([
            "## External Mappings",
            "",
            *mappings,
            "",
        ])

    # References
    if card.references:
        lines.extend([
            "## References",
            "",
        ])
        for ref in card.references:
            lines.append(f"- {ref}")
        lines.append("")

    # Footer
    lines.extend([
        "---",
        "",
        f"*Published by [NAIL Institute](https://github.com/dleighsystem/nailinstitute) "
        f"| Generated: {time.strftime('%Y-%m-%d')} "
        f"| License: CC-BY-SA-4.0*",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# INDEX GENERATORS
# ═══════════════════════════════════════════════════════════════════════════

def generate_index_table(cards: list[AVECard]) -> str:
    """
    Generate a Markdown table summarising all AVE Cards.
    Suitable for a README.md or docs index page.
    """
    sev_emoji = {
        "critical": "🔴", "high": "🟠", "medium": "🟡",
        "low": "🟢", "info": "⚪",
    }

    lines = [
        "# AVE Database — Agentic Vulnerabilities & Exposures",
        "",
        f"> {len(cards)} documented vulnerabilities affecting autonomous AI agents",
        "",
        "| AVE-ID | Severity | Name | Category | Status |",
        "|--------|----------|------|----------|--------|",
    ]

    for card in sorted(cards, key=lambda c: c.ave_id):
        sev = card.severity.value
        emoji = sev_emoji.get(sev, "⚪")
        lines.append(
            f"| [{card.ave_id}](./cards/{card.ave_id}.md) | "
            f"{emoji} {sev} | {card.name} | "
            f"`{card.category.value}` | `{card.status.value}` |"
        )
    lines.append("")

    # Stats summary
    from collections import Counter
    sev_counts = Counter(c.severity.value for c in cards)
    cat_counts = Counter(c.category.value for c in cards)

    lines.extend([
        "## Statistics",
        "",
        "### By Severity",
        "",
    ])
    for sev in ["critical", "high", "medium", "low", "info"]:
        if sev in sev_counts:
            emoji = sev_emoji.get(sev, "⚪")
            lines.append(f"- {emoji} **{sev.upper()}:** {sev_counts[sev]}")
    lines.append("")

    lines.extend([
        "### By Category",
        "",
    ])
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- `{cat}`: {count}")
    lines.append("")

    lines.extend([
        "---",
        "",
        "*Maintained by [NAIL Institute](https://github.com/dleighsystem/nailinstitute) "
        "— The MITRE ATT&CK of the Agentic Era*",
    ])

    return "\n".join(lines)


def generate_severity_index(cards: list[AVECard]) -> dict[str, list[dict]]:
    """Generate a severity-grouped index for API consumers."""
    index: dict[str, list[dict]] = {}
    for card in cards:
        sev = card.severity.value
        if sev not in index:
            index[sev] = []
        index[sev].append({
            "ave_id": card.ave_id,
            "name": card.name,
            "category": card.category.value,
            "status": card.status.value,
        })
    return index


# ═══════════════════════════════════════════════════════════════════════════
# BULK EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def export_database(
    cards: list[AVECard],
    output_dir: str | Path,
    *,
    include_json: bool = True,
    include_markdown: bool = True,
    include_index: bool = True,
    include_code: bool = False,
) -> dict[str, int]:
    """
    Export the entire AVE database to a directory structure.

    Creates:
        output_dir/
        ├── README.md              (index table)
        ├── index.json             (machine-readable index)
        ├── severity_index.json    (grouped by severity)
        └── cards/
            ├── AVE-2025-0001.json
            ├── AVE-2025-0001.md
            ├── AVE-2025-0002.json
            ├── AVE-2025-0002.md
            └── ...

    Returns a summary dict with counts.
    """
    output = Path(output_dir)
    cards_dir = output / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)

    counts = {"json": 0, "markdown": 0, "index": 0}

    # Individual card files
    for card in cards:
        if include_json:
            json_path = cards_dir / f"{card.ave_id}.json"
            json_path.write_text(card_to_json(card, include_code=include_code))
            counts["json"] += 1

        if include_markdown:
            md_path = cards_dir / f"{card.ave_id}.md"
            md_path.write_text(card_to_markdown(card))
            counts["markdown"] += 1

    # Index files
    if include_index:
        # README.md
        readme_path = output / "README.md"
        readme_path.write_text(generate_index_table(cards))
        counts["index"] += 1

        # index.json
        index_path = output / "index.json"
        index_data = {
            "schema_version": "1.0.0",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_cards": len(cards),
            "cards": [
                {
                    "ave_id": c.ave_id,
                    "name": c.name,
                    "category": c.category.value,
                    "severity": c.severity.value,
                    "status": c.status.value,
                }
                for c in sorted(cards, key=lambda c: c.ave_id)
            ],
        }
        index_path.write_text(json.dumps(index_data, indent=2))
        counts["index"] += 1

        # severity_index.json
        sev_path = output / "severity_index.json"
        sev_path.write_text(json.dumps(generate_severity_index(cards), indent=2))
        counts["index"] += 1

    return counts
