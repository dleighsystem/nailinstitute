"""
AVE Redaction — Generate public-safe card versions without proprietary details.

The AVE Database has two tiers:
  - PUBLIC:  Name, category, severity, summary, blast radius, prerequisites,
             environment (frameworks only), related AVEs. Enough to understand
             the threat — not enough to exploit it or build defences.
  - FULL:    Everything above PLUS mechanism details, evidence data, PoC scripts,
             AVSS scores, defence implementations, timeline events.

The public tier is free and open (CC-BY-SA-4.0).
The full tier is available via the NAIL SDK subscription.

Usage:
    from ave.redact import redact_card, redact_for_export, generate_public_cards
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Optional


# Fields that stay public — enough to understand the threat
PUBLIC_FIELDS = {
    "ave_id",
    "name",
    "aliases",
    "category",
    "severity",
    "status",
    "summary",
    "blast_radius",
    "prerequisite",
    "date_discovered",
    "date_published",
    "cwe_mapping",
    "mitre_mapping",
    "references",
    "related_aves",
    "contributor",
    "_meta",
}

# Fields that are redacted — the proprietary value
REDACTED_FIELDS = {
    "mechanism",       # HOW it works — that's the know-how
    "evidence",        # Experiment data, files, metrics
    "defences",        # Defence implementations, rmap modules
    "poc",             # Proof of concept scripts + prompts
    "avss_score",      # Severity vector scoring
    "timeline",        # Internal lifecycle events
}

# Redaction notice
REDACTION_NOTICE = (
    "[REDACTED — Available in NAIL SDK. "
    "See https://github.com/dleighsystem/nailinstitute for access.]"
)

REDACTION_NOTICE_SHORT = "[Available in NAIL SDK]"


def redact_card(card_data: dict, tier: str = "public") -> dict:
    """
    Redact a card dict for the specified access tier.

    Args:
        card_data: Full card dictionary
        tier: "public" (redacted) or "full" (unredacted)

    Returns:
        Card dict with sensitive fields redacted for public tier
    """
    if tier == "full":
        return deepcopy(card_data)

    redacted = {}

    for key, value in card_data.items():
        if key in PUBLIC_FIELDS:
            redacted[key] = deepcopy(value)
        elif key == "mechanism":
            # Give a teaser — first sentence only
            if value and isinstance(value, str):
                first_sentence = value.split(". ")[0] + "."
                redacted[key] = first_sentence + " " + REDACTION_NOTICE_SHORT
            else:
                redacted[key] = REDACTION_NOTICE
        elif key == "evidence":
            # Show count but not data
            if isinstance(value, list) and value:
                redacted[key] = [{
                    "experiment_id": REDACTION_NOTICE_SHORT,
                    "key_metric": e.get("key_metric", "") if isinstance(e, dict) else "",
                    "key_value": REDACTION_NOTICE_SHORT,
                    "data_file": "",
                    "p_value": None,
                    "sample_size": None,
                    "cross_model": False,
                } for e in value]
            else:
                redacted[key] = []
        elif key == "defences":
            # Show defence names but not implementation details
            if isinstance(value, list) and value:
                redacted[key] = [{
                    "name": d.get("name", "") if isinstance(d, dict) else "",
                    "layer": "",
                    "effectiveness": REDACTION_NOTICE_SHORT,
                    "rmap_module": "",
                    "nail_monitor_detector": "",
                } for d in value]
            else:
                redacted[key] = []
        elif key == "environment":
            # Show frameworks but redact models
            if isinstance(value, dict):
                redacted[key] = {
                    "frameworks": value.get("frameworks", []),
                    "models_tested": [REDACTION_NOTICE_SHORT],
                    "multi_agent": value.get("multi_agent", False),
                    "tools_required": value.get("tools_required", False),
                    "memory_required": value.get("memory_required", False),
                }
            else:
                redacted[key] = value
        elif key == "avss_score":
            # Show overall score but not the vector
            if isinstance(value, dict) and value:
                redacted[key] = {
                    "overall_score": value.get("overall_score"),
                    "severity_label": value.get("severity_label", ""),
                    "vector_string": REDACTION_NOTICE_SHORT,
                    "base_score": None,
                    "temporal_score": None,
                    "agentic_score": None,
                    "vector": None,
                }
            else:
                redacted[key] = None
        elif key in ("poc", "timeline"):
            # Fully redacted
            redacted[key] = None
        else:
            # Unknown fields pass through (future-proof)
            redacted[key] = deepcopy(value)

    # Add redaction metadata
    meta = redacted.get("_meta", {})
    meta["access_tier"] = "public"
    meta["redacted_fields"] = sorted(REDACTED_FIELDS)
    meta["full_access"] = "https://github.com/dleighsystem/nailinstitute"
    redacted["_meta"] = meta

    return redacted


def redact_for_export(card_data: dict) -> tuple[dict, dict]:
    """
    Generate both public and full versions of a card.

    Returns:
        Tuple of (public_card, full_card)
    """
    return redact_card(card_data, "public"), redact_card(card_data, "full")


def generate_public_cards(
    source_dir: str,
    output_dir: str,
    overwrite: bool = False,
) -> dict[str, int]:
    """
    Read full cards from source_dir, write redacted public versions to output_dir.

    Args:
        source_dir: Path to directory with full cards (e.g. ave-database/cards/)
        output_dir: Path for public redacted output
        overwrite: If True, overwrite existing files

    Returns:
        Dict with counts: {"processed": N, "written": N, "skipped": N}
    """
    src = Path(source_dir)
    out = Path(output_dir)
    os.makedirs(out, exist_ok=True)

    stats = {"processed": 0, "written": 0, "skipped": 0}

    for f in sorted(src.glob("AVE-*.json")):
        if f.name in ("index.json", "severity_index.json"):
            continue

        stats["processed"] += 1
        out_path = out / f.name

        if out_path.exists() and not overwrite:
            stats["skipped"] += 1
            continue

        try:
            with open(f) as fh:
                full_card = json.load(fh)

            public_card = redact_card(full_card, "public")

            with open(out_path, "w") as fh:
                json.dump(public_card, fh, indent=2)

            stats["written"] += 1
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: Could not process {f.name}: {e}")

    return stats


def generate_public_markdown(card_data: dict) -> str:
    """Generate a public-tier Markdown companion for a redacted card."""
    sev_icon = {
        "critical": "🔴", "high": "🟠", "medium": "🟡",
        "low": "🟢", "info": "ℹ️",
    }.get(card_data.get("severity", ""), "❓")

    lines = [
        f"# {card_data['ave_id']}: {card_data['name']}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **Severity** | {sev_icon} {card_data.get('severity', '')} |",
        f"| **Category** | `{card_data.get('category', '')}` |",
        f"| **Status** | `{card_data.get('status', '')}` |",
        f"| **Discovered** | {card_data.get('date_discovered', '')} |",
    ]

    if card_data.get("cwe_mapping"):
        lines.append(f"| **CWE** | {card_data['cwe_mapping']} |")

    lines.extend(["", "## Summary", "", card_data.get("summary", "")])

    if card_data.get("blast_radius"):
        lines.extend(["", "## Blast Radius", "", card_data["blast_radius"]])

    if card_data.get("prerequisite"):
        lines.extend(["", "## Prerequisites", "", card_data["prerequisite"]])

    # Mechanism teaser
    mechanism = card_data.get("mechanism", "")
    if mechanism and REDACTION_NOTICE_SHORT not in mechanism:
        first = mechanism.split(". ")[0] + "."
        lines.extend(["", "## Mechanism", "", first,
                       "", f"*{REDACTION_NOTICE}*"])
    elif mechanism:
        lines.extend(["", "## Mechanism", "", mechanism])

    # Defence names only
    defences = card_data.get("defences", [])
    if defences:
        lines.extend(["", "## Known Defences", ""])
        for d in defences:
            name = d.get("name", "") if isinstance(d, dict) else ""
            if name:
                lines.append(f"- **{name}** — *Effectiveness: {REDACTION_NOTICE_SHORT}*")

    # AVSS teaser
    avss = card_data.get("avss_score")
    if avss and isinstance(avss, dict) and avss.get("overall_score") is not None:
        lines.extend([
            "", "## AVSS Score", "",
            f"**Overall:** {avss['overall_score']}/10.0 "
            f"({avss.get('severity_label', '').upper()})",
            "",
            f"*Full vector breakdown: {REDACTION_NOTICE_SHORT}*",
        ])

    # Related
    related = card_data.get("related_aves", [])
    if related:
        lines.extend(["", "## Related AVEs", "",
                       ", ".join(f"`{r}`" for r in related)])

    lines.extend([
        "", "---", "",
        f"> 🔒 **Full details** (mechanism, evidence, PoC, defences, AVSS vector) "
        f"available in the [NAIL SDK](https://github.com/dleighsystem/nailinstitute).",
        "",
        f"*Maintained by the [NAIL Institute](https://github.com/dleighsystem/nailinstitute)*",
    ])

    return "\n".join(lines)
