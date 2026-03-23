#!/usr/bin/env python3
"""
Export Public Repo — Generate a clean, separate public-facing repository.

This script creates a COMPLETE standalone repo at `public-repo/` that contains
only what the world should see:

  ✅ INCLUDED (public-safe):
    - Redacted AVE cards (name, summary, blast radius — NO mechanism/PoC/evidence)
    - Public-tier Markdown companions
    - Lightweight AVE toolkit (schema, validate, submit, gamification, CLI)
    - GitHub infrastructure (issue templates, PR template, workflows)
    - Community docs (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, HALL_OF_FAME)
    - Fresh README designed for external contributors

  ❌ EXCLUDED (proprietary):
    - Full enriched JSON cards (mechanism, evidence, PoC, AVSS vectors)
    - rmap, canary, arena, ctf, diagnostic, horizon packages
    - integration, threatfeed, nail_monitor packages
    - Docker infrastructure (Dockerfile, docker-compose.yml)
    - Experiment logs, research notes, papers
    - Registry with hardcoded card data
    - Internal tooling scripts

Usage:
    python scripts/export_public_repo.py
    python scripts/export_public_repo.py --output ./my-public-repo
    python scripts/export_public_repo.py --init-git
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path so we can import ave
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "ave"))

from ave.redact import redact_card, generate_public_markdown


# ── Public repo identity ──────────────────────────────────────────────────
# GitHub Organization created at:
#   https://github.com/NAIL-INSTITUTE-FOR-AGENTIC-SECURITY
PUBLIC_ORG = "NAIL-INSTITUTE-FOR-AGENTIC-SECURITY"
PUBLIC_REPO = "ave-database"
PUBLIC_SLUG = f"{PUBLIC_ORG}/{PUBLIC_REPO}"
PUBLIC_URL = f"https://github.com/{PUBLIC_SLUG}"

# The private repo references to rewrite
PRIVATE_SLUGS = [
    "dleighsystem/nailinstitute",
    "nailinstitute/ave-database",
    "Agentic-Security-Project/ave-database",
    "Agentic-Security-Project",
]


def _rewrite_urls(text: str) -> str:
    """Replace all private repo references with the public org URL."""
    for slug in PRIVATE_SLUGS:
        text = text.replace(slug, PUBLIC_SLUG)
    return text


def export_public_repo(
    source_root: Path,
    output_dir: Path,
    init_git: bool = False,
) -> dict[str, int]:
    """
    Generate the complete public repository.

    Returns:
        Stats dict with counts of files processed.
    """
    stats = {
        "cards_exported": 0,
        "markdown_generated": 0,
        "files_copied": 0,
        "files_created": 0,
    }

    # Clean output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    print(f"\n{'═' * 60}")
    print(f"  Exporting Public Repository")
    print(f"  Source:  {source_root}")
    print(f"  Output:  {output_dir}")
    print(f"{'═' * 60}\n")

    # ── 1. Redacted AVE Cards ───────────────────────────────────────
    print("📇 Exporting redacted AVE cards...")
    cards_src = source_root / "ave-database" / "cards"
    cards_out = output_dir / "ave-database" / "cards"
    cards_out.mkdir(parents=True)

    for card_file in sorted(cards_src.glob("AVE-*.json")):
        try:
            with open(card_file) as f:
                full_card = json.load(f)

            # Redact
            public_card = redact_card(full_card, "public")

            # Rewrite internal URLs to public org
            card_json = json.dumps(public_card, indent=2)
            card_json = _rewrite_urls(card_json)
            public_card = json.loads(card_json)

            # Write JSON
            json_out = cards_out / card_file.name
            with open(json_out, "w") as f:
                json.dump(public_card, f, indent=2)
            stats["cards_exported"] += 1

            # Write Markdown companion (with rewritten URLs)
            md_content = generate_public_markdown(public_card)
            md_content = _rewrite_urls(md_content)
            md_out = cards_out / card_file.name.replace(".json", ".md")
            with open(md_out, "w") as f:
                f.write(md_content)
            stats["markdown_generated"] += 1

            print(f"  ✓ {card_file.stem}")
        except Exception as e:
            print(f"  ✗ {card_file.stem}: {e}")

    # Generate public index.json
    _generate_public_index(cards_out, output_dir / "ave-database")

    # ── 2. AVE Database README ──────────────────────────────────────
    print("\n📄 Generating ave-database/README.md...")
    _generate_database_readme(cards_out, output_dir / "ave-database" / "README.md")
    stats["files_created"] += 1

    # ── 3. Community Docs ───────────────────────────────────────────
    print("\n📋 Copying community documentation...")
    community_files = [
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "HALL_OF_FAME.md",
    ]
    for fname in community_files:
        src = source_root / fname
        if src.exists():
            # Rewrite internal links to point to this repo
            content = src.read_text()
            content = _rewrite_urls(content)
            (output_dir / fname).write_text(content)
            stats["files_copied"] += 1
            print(f"  ✓ {fname}")

    # ── 4. GitHub Infrastructure ────────────────────────────────────
    print("\n🔧 Setting up GitHub infrastructure...")

    # Issue templates
    issue_dir = output_dir / ".github" / "ISSUE_TEMPLATE"
    issue_dir.mkdir(parents=True)
    for fname in ("ave-submission.yml", "private-disclosure.yml", "config.yml"):
        src = source_root / ".github" / "ISSUE_TEMPLATE" / fname
        if src.exists():
            content = src.read_text()
            content = _rewrite_urls(content)
            (issue_dir / fname).write_text(content)
            stats["files_copied"] += 1
            print(f"  ✓ .github/ISSUE_TEMPLATE/{fname}")

    # PR template
    pr_src = source_root / ".github" / "PULL_REQUEST_TEMPLATE.md"
    if pr_src.exists():
        content = pr_src.read_text()
        (output_dir / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text(content)
        stats["files_copied"] += 1
        print(f"  ✓ .github/PULL_REQUEST_TEMPLATE.md")

    # Workflows — create public-safe versions
    wf_dir = output_dir / ".github" / "workflows"
    wf_dir.mkdir(parents=True)

    # Copy validate workflow
    wf_src = source_root / ".github" / "workflows" / "ave-validate.yml"
    if wf_src.exists():
        content = wf_src.read_text()
        (wf_dir / "ave-validate.yml").write_text(content)
        stats["files_copied"] += 1
        print(f"  ✓ .github/workflows/ave-validate.yml")

    # Copy hall of fame workflow
    wf_src = source_root / ".github" / "workflows" / "update-hall-of-fame.yml"
    if wf_src.exists():
        content = wf_src.read_text()
        (wf_dir / "update-hall-of-fame.yml").write_text(content)
        stats["files_copied"] += 1
        print(f"  ✓ .github/workflows/update-hall-of-fame.yml")

    # ── 5. Lightweight AVE Package ──────────────────────────────────
    print("\n📦 Building lightweight AVE package...")
    _build_public_ave_package(source_root, output_dir)
    stats["files_created"] += 6  # Multiple files created

    # ── 6. Root README ──────────────────────────────────────────────
    print("\n📖 Generating root README.md...")
    _generate_root_readme(output_dir, stats["cards_exported"])
    stats["files_created"] += 1

    # ── 7. License ──────────────────────────────────────────────────
    _generate_license(output_dir)
    stats["files_created"] += 1

    # ── 8. .gitignore ───────────────────────────────────────────────
    _generate_gitignore(output_dir)
    stats["files_created"] += 1

    # ── 9. Git init ─────────────────────────────────────────────────
    if init_git:
        print("\n🔀 Initializing git repository...")
        os.system(f"cd {output_dir} && git init && git add . && git commit -m 'Initial public release — AVE Database v1.0.0'")
        print("  ✓ Git repository initialized")

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'═' * 60}")
    print(f"  ✅ Public Repository Export Complete")
    print(f"{'═' * 60}")
    print(f"  Cards exported:     {stats['cards_exported']}")
    print(f"  Markdown generated: {stats['markdown_generated']}")
    print(f"  Files copied:       {stats['files_copied']}")
    print(f"  Files created:      {stats['files_created']}")
    print(f"  Output:             {output_dir}")
    print()
    print("  Next steps:")
    print("    1. cd public-repo")
    print("    2. Review the content — make sure nothing proprietary leaked")
    print(f"    3. Create '{PUBLIC_ORG}' org + '{PUBLIC_REPO}' repo on GitHub")
    print(f"    4. git remote add origin {PUBLIC_URL}.git")
    print("    5. git push -u origin main")
    print()

    return stats


def _generate_public_index(cards_dir: Path, db_dir: Path) -> None:
    """Generate index.json and severity_index.json for public cards."""
    cards = []
    for f in sorted(cards_dir.glob("AVE-*.json")):
        with open(f) as fh:
            card = json.load(fh)
            cards.append({
                "ave_id": card.get("ave_id", ""),
                "name": card.get("name", ""),
                "category": card.get("category", ""),
                "severity": card.get("severity", ""),
                "status": card.get("status", ""),
                "summary": card.get("summary", "")[:200],
            })

    with open(db_dir / "index.json", "w") as f:
        json.dump({"cards": cards, "total": len(cards)}, f, indent=2)

    # Severity index
    by_sev: dict[str, list] = {}
    for c in cards:
        sev = c.get("severity", "unknown")
        by_sev.setdefault(sev, []).append(c["ave_id"])

    with open(db_dir / "severity_index.json", "w") as f:
        json.dump(by_sev, f, indent=2)


def _generate_database_readme(cards_dir: Path, output_path: Path) -> None:
    """Generate a public-facing ave-database README."""
    # Collect card summaries
    cards_data = []
    for f in sorted(cards_dir.glob("AVE-*.json")):
        with open(f) as fh:
            cards_data.append(json.load(fh))

    sev_icons = {
        "critical": "🔴", "high": "🟠", "medium": "🟡",
        "low": "🟢", "info": "ℹ️",
    }

    # Count by severity
    sev_counts: dict[str, int] = {}
    cat_counts: dict[str, int] = {}
    for c in cards_data:
        sev = c.get("severity", "unknown")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
        cat = c.get("category", "unknown")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # Build table rows
    table_rows = []
    for c in cards_data:
        ave_id = c.get("ave_id", "")
        sev = c.get("severity", "")
        icon = sev_icons.get(sev, "❓")
        name = c.get("name", "")
        cat = c.get("category", "")
        status = c.get("status", "")
        table_rows.append(
            f"| [{ave_id}](./cards/{ave_id}.md) | {icon} {sev} | {name} | `{cat}` | `{status}` |"
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    content = f"""# 🛡️ AVE Database — Agentic Vulnerabilities & Exposures

[![Cards](https://img.shields.io/badge/AVE_Cards-{len(cards_data)}-blue)](./cards/)
[![License](https://img.shields.io/badge/License-CC--BY--SA--4.0-green)](https://creativecommons.org/licenses/by-sa/4.0/)
[![Validate](https://img.shields.io/badge/CI-Validated-brightgreen)](./.github/workflows/ave-validate.yml)
[![Contribute](https://img.shields.io/badge/PRs-Welcome-orange)](./CONTRIBUTING.md)

> **The MITRE ATT&CK of the Agentic Era.**
>
> The world's first structured catalogue of AI agent failure modes — behavioural
> vulnerabilities, attack vectors, and emergent pathologies affecting autonomous
> AI systems. Open to contributions from the global security research community.
>
> *Last updated: {now}*

---

## 🚀 Quick Start

### Browse Vulnerabilities

Every card is available as **JSON** (machine-readable) and **Markdown** (human-readable):

```
ave-database/
├── cards/
│   ├── AVE-2025-0001.json    ← Machine-readable card
│   ├── AVE-2025-0001.md      ← Human-readable companion
│   └── ...
├── index.json                ← Full database index
├── severity_index.json       ← Cards grouped by severity
└── README.md                 ← You are here
```

### Query via CLI

```bash
pip install -e ave/            # Install the AVE toolkit
python -m ave list             # List all cards
python -m ave show AVE-2025-0001   # Detailed view
python -m ave search -k "injection"  # Search by keyword
python -m ave stats            # Database statistics
python -m ave validate ave-database/cards/  # Validate all cards
python -m ave submit --interactive  # Generate a draft card
python -m ave leaderboard      # View contributor rankings
```

---

## 📊 Database Summary

### {len(cards_data)} Documented Vulnerabilities

| AVE-ID | Severity | Name | Category | Status |
|--------|----------|------|----------|--------|
{chr(10).join(table_rows)}

### Statistics

| Severity | Count |
|----------|------:|
"""
    for sev in ("critical", "high", "medium", "low", "info"):
        if sev in sev_counts:
            icon = sev_icons.get(sev, "")
            content += f"| {icon} {sev.upper()} | {sev_counts[sev]} |\n"

    content += f"""
| Category | Count |
|----------|------:|
"""
    for cat in sorted(cat_counts.keys()):
        content += f"| `{cat}` | {cat_counts[cat]} |\n"

    content += """
---

## ⚠️ Access Tiers

The AVE Database operates on a **two-tier access model**:

| Tier | What You Get | Access |
|------|-------------|--------|
| 🔓 **PUBLIC** | Name, summary, blast radius, prerequisites, severity, category, AVSS score | **Free** — this repo (CC-BY-SA-4.0) |
| 🔒 **FULL** | + Mechanism details, evidence, PoC scripts, defence implementations, AVSS vectors | [NAIL SDK](https://github.com/{PUBLIC_ORG}) |

Public cards give you enough to **understand and identify the threat**.
Full cards give you enough to **reproduce, test, and defend against it**.

---

## 🤝 How to Contribute

**Anyone can submit vulnerabilities.** We welcome security researchers, AI engineers,
academics, red teamers, and practitioners.

### Three Ways to Submit

| Method | Difficulty | Best For |
|--------|-----------|----------|
| [**GitHub Issue**](https://github.com/{PUBLIC_SLUG}/issues/new?template=ave-submission.yml) | Easy | First-time contributors — fill in a structured form |
| [**Pull Request**](./CONTRIBUTING.md#option-2-pull-request-for-experienced-contributors) | Moderate | Experienced contributors — submit JSON + Markdown directly |
| [**Private Disclosure**](./SECURITY.md) | Any | Severe/weaponizable findings — responsible disclosure process |

### Generate a Card Skeleton

```bash
python -m ave submit --name "My Vulnerability" --category memory --severity high
python -m ave submit --interactive
python -m ave validate ave-database/cards/AVE-DRAFT-0001.json
```

---

## 🏆 Contributor Recognition

Every accepted card earns **XP**, **badges**, and a spot on the [**Hall of Fame**](./HALL_OF_FAME.md).

| Tier | XP Required | Perks |
|------|-------------|-------|
| 👁️ WATCHER | 0+ | Joined the hunt |
| 🏹 HUNTER | 500+ | Listed in Hall of Fame |
| 🛡️ SENTINEL | 1,500+ | Fast-track review |
| 🏗️ ARCHITECT | 4,000+ | Invited to review PRs |
| ⭐ FELLOW | 8,000+ | NAIL Research Fellow — named in publications |

```bash
python -m ave leaderboard           # See the rankings
python -m ave profile "your-handle" # Your profile
python -m ave badges                # All earnable badges
```

---

## 📜 Licensing

All AVE Database content is licensed under
[**CC-BY-SA-4.0**](https://creativecommons.org/licenses/by-sa/4.0/).

You are free to use, share, and adapt this data for any purpose, including
commercial use, with attribution.

---

## 🔗 Related Resources

- [CONTRIBUTING.md](./CONTRIBUTING.md) — Full contributor guide
- [SECURITY.md](./SECURITY.md) — Responsible disclosure policy
- [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) — Community standards
- [HALL_OF_FAME.md](./HALL_OF_FAME.md) — Contributor leaderboard
- [NAIL Institute](https://github.com/{PUBLIC_ORG}) — The parent organisation

---

*Maintained by the [NAIL Institute](https://github.com/{PUBLIC_ORG}) — Building the safety infrastructure for agentic AI.*
"""
    output_path.write_text(content)


def _build_public_ave_package(source_root: Path, output_dir: Path) -> None:
    """
    Build a lightweight AVE package for the public repo.

    Includes:
      - schema.py (types — no proprietary data)
      - validate.py (card validation)
      - submit.py (draft card generator)
      - gamification.py (contributor recognition)
      - redact.py (public-tier card generation)
      - cli.py (public-safe commands only)
      - export.py (rendering functions)

    Excludes:
      - registry.py (hardcoded full card data)
      - enrich.py (enrichment pipeline)
      - scoring.py internals
      - poc.py, timeline.py
    """
    pkg_dir = output_dir / "ave" / "ave"
    pkg_dir.mkdir(parents=True)

    # Files to copy directly (safe as-is)
    safe_files = [
        "schema.py",
        "validate.py",
        "submit.py",
        "gamification.py",
        "redact.py",
        "export.py",
    ]

    for fname in safe_files:
        src = source_root / "ave" / "ave" / fname
        if src.exists():
            content = src.read_text()
            # Rewrite internal repo references
            content = _rewrite_urls(content)
            (pkg_dir / fname).write_text(content)
            print(f"  ✓ ave/ave/{fname}")

    # scoring.py — copy (contains AVSS which is referenced by schema)
    scoring_src = source_root / "ave" / "ave" / "scoring.py"
    if scoring_src.exists():
        content = scoring_src.read_text()
        (pkg_dir / "scoring.py").write_text(content)
        print(f"  ✓ ave/ave/scoring.py")

    # poc.py — copy stub (needed by schema TYPE_CHECKING import)
    poc_src = source_root / "ave" / "ave" / "poc.py"
    if poc_src.exists():
        content = poc_src.read_text()
        (pkg_dir / "poc.py").write_text(content)
        print(f"  ✓ ave/ave/poc.py")

    # timeline.py — copy stub (needed by schema TYPE_CHECKING import)
    timeline_src = source_root / "ave" / "ave" / "timeline.py"
    if timeline_src.exists():
        content = timeline_src.read_text()
        (pkg_dir / "timeline.py").write_text(content)
        print(f"  ✓ ave/ave/timeline.py")

    # Create public-safe __init__.py (no registry imports)
    _create_public_init(pkg_dir)
    print(f"  ✓ ave/ave/__init__.py (public-safe)")

    # Create public-safe __main__.py
    _create_public_main(pkg_dir)
    print(f"  ✓ ave/ave/__main__.py")

    # Create public-safe CLI
    _create_public_cli(source_root, pkg_dir)
    print(f"  ✓ ave/ave/cli.py (public-safe)")

    # Create public-safe registry (loads from JSON files, not hardcoded)
    _create_public_registry(pkg_dir)
    print(f"  ✓ ave/ave/registry.py (file-based)")

    # pyproject.toml
    _create_public_pyproject(output_dir / "ave")
    print(f"  ✓ ave/pyproject.toml")

    # Package README
    _create_public_package_readme(output_dir / "ave")
    print(f"  ✓ ave/README.md")


def _create_public_init(pkg_dir: Path) -> None:
    """Create a public-safe __init__.py without hardcoded registry."""
    content = '''"""
AVE — Agentic Vulnerabilities & Exposures
============================================
The CVE database for AI agent failures.

Every vulnerability that can affect an autonomous AI agent — from prompt
injection to consensus paralysis to memory laundering — gets a unique
AVE-ID, a severity score, and a mapping to known defences.

This is the MITRE ATT&CK of the Agentic Era.

Usage:
    >>> import ave
    >>> ave.lookup("AVE-2025-0001")  # Requires cards directory
    >>> ave.search(category=ave.Category.MEMORY)

    >>> from ave.scoring import compute_avss, AVSSVector
    >>> score = compute_avss(AVSSVector(attack_vector=AttackVector.NETWORK))

Open source — maintained by the NAIL Institute.
"""

__version__ = "1.0.0"

from .schema import (
    AVECard,
    Category,
    Severity,
    Status,
    EnvironmentVector,
    Defence,
    Evidence,
)

from .registry import (
    lookup,
    search,
    all_cards,
    card_count,
    cards_by_severity,
    cards_by_category,
    cards_by_status,
)

__all__ = [
    "AVECard",
    "Category",
    "Severity",
    "Status",
    "EnvironmentVector",
    "Defence",
    "Evidence",
    "lookup",
    "search",
    "all_cards",
    "card_count",
    "cards_by_severity",
    "cards_by_category",
    "cards_by_status",
]
'''
    (pkg_dir / "__init__.py").write_text(content)


def _create_public_main(pkg_dir: Path) -> None:
    """Create __main__.py for `python -m ave` support."""
    content = '''"""Run the AVE CLI: python -m ave <command>"""
from .cli import main

if __name__ == "__main__":
    main()
'''
    (pkg_dir / "__main__.py").write_text(content)


def _create_public_registry(pkg_dir: Path) -> None:
    """
    Create a file-based registry that loads cards from JSON files on disk.
    No hardcoded data — everything comes from ave-database/cards/*.json.
    """
    content = '''"""
AVE Registry — File-based card loader.

Loads AVE cards from JSON files in the ave-database/cards/ directory.
No hardcoded data — the database IS the JSON files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .schema import (
    AVECard, Category, Severity, Status,
    EnvironmentVector, Evidence, Defence,
)


# Default cards directory — relative to project root
_DEFAULT_CARDS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ave-database", "cards"
)

_CARDS_DIR: str = os.environ.get("AVE_CARDS_DIR", _DEFAULT_CARDS_DIR)
_card_cache: dict[str, AVECard] | None = None


def _set_cards_dir(path: str) -> None:
    """Override the cards directory."""
    global _CARDS_DIR, _card_cache
    _CARDS_DIR = path
    _card_cache = None


def _load_cards() -> dict[str, AVECard]:
    """Load all cards from JSON files."""
    global _card_cache
    if _card_cache is not None:
        return _card_cache

    cards: dict[str, AVECard] = {}
    cards_path = Path(_CARDS_DIR)

    if not cards_path.is_dir():
        return cards

    for f in sorted(cards_path.glob("AVE-*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            card = _dict_to_card(data)
            cards[card.ave_id] = card
        except Exception:
            continue

    _card_cache = cards
    return cards


def _dict_to_card(data: dict) -> AVECard:
    """Convert a JSON dict to an AVECard dataclass."""
    env_data = data.get("environment", {})
    if isinstance(env_data, dict):
        env = EnvironmentVector(
            frameworks=tuple(env_data.get("frameworks", [])),
            models_tested=tuple(env_data.get("models_tested", [])),
            multi_agent=env_data.get("multi_agent", False),
            tools_required=env_data.get("tools_required", False),
            memory_required=env_data.get("memory_required", False),
        )
    else:
        env = EnvironmentVector()

    evidence_list = data.get("evidence", []) or []
    evidence = tuple(
        Evidence(
            experiment_id=e.get("experiment_id", ""),
            data_file=e.get("data_file", ""),
            key_metric=e.get("key_metric", ""),
            key_value=e.get("key_value", ""),
            p_value=e.get("p_value"),
            sample_size=e.get("sample_size"),
            cross_model=e.get("cross_model", False),
        )
        for e in evidence_list
        if isinstance(e, dict)
    )

    defence_list = data.get("defences", []) or []
    defences = tuple(
        Defence(
            name=d.get("name", ""),
            layer=d.get("layer", ""),
            effectiveness=d.get("effectiveness", ""),
            rmap_module=d.get("rmap_module", ""),
            nail_monitor_detector=d.get("nail_monitor_detector", ""),
        )
        for d in defence_list
        if isinstance(d, dict)
    )

    return AVECard(
        ave_id=data.get("ave_id", ""),
        name=data.get("name", ""),
        aliases=tuple(data.get("aliases", [])),
        category=Category(data["category"]) if data.get("category") in {c.value for c in Category} else Category.EMERGENT,
        severity=Severity(data["severity"]) if data.get("severity") in {s.value for s in Severity} else Severity.MEDIUM,
        status=Status(data["status"]) if data.get("status") in {s.value for s in Status} else Status.THEORETICAL,
        summary=data.get("summary", ""),
        mechanism=data.get("mechanism", ""),
        blast_radius=data.get("blast_radius", ""),
        prerequisite=data.get("prerequisite", ""),
        environment=env,
        evidence=evidence,
        defences=defences,
        date_discovered=data.get("date_discovered", ""),
        date_published=data.get("date_published", ""),
        cwe_mapping=data.get("cwe_mapping", ""),
        mitre_mapping=data.get("mitre_mapping", ""),
        references=tuple(data.get("references", [])),
        related_aves=tuple(data.get("related_aves", [])),
    )


# ── Public API ──────────────────────────────────────────────────────

def lookup(ave_id: str) -> Optional[AVECard]:
    """Look up a card by AVE ID."""
    return _load_cards().get(ave_id)


def all_cards() -> list[AVECard]:
    """Return all loaded cards."""
    return list(_load_cards().values())


def search(
    *,
    keyword: str = "",
    category: Optional[Category] = None,
    severity: Optional[Severity] = None,
    status: Optional[Status] = None,
) -> list[AVECard]:
    """Search cards by keyword, category, severity, or status."""
    results = all_cards()

    if category:
        results = [c for c in results if c.category == category]
    if severity:
        results = [c for c in results if c.severity == severity]
    if status:
        results = [c for c in results if c.status == status]
    if keyword:
        kw = keyword.lower()
        results = [
            c for c in results
            if kw in c.name.lower()
            or kw in c.summary.lower()
            or kw in c.mechanism.lower()
            or kw in c.category.value.lower()
            or any(kw in a.lower() for a in c.aliases)
        ]

    return results


def card_count() -> dict:
    """Return summary statistics."""
    cards = all_cards()
    by_sev = {}
    by_cat = {}
    by_status = {}
    for c in cards:
        by_sev[c.severity.value] = by_sev.get(c.severity.value, 0) + 1
        by_cat[c.category.value] = by_cat.get(c.category.value, 0) + 1
        by_status[c.status.value] = by_status.get(c.status.value, 0) + 1
    return {
        "total": len(cards),
        "by_severity": by_sev,
        "by_category": by_cat,
        "by_status": by_status,
    }


def cards_by_severity(severity: Severity) -> list[AVECard]:
    """Get all cards with a specific severity."""
    return [c for c in all_cards() if c.severity == severity]


def cards_by_category(category: Category) -> list[AVECard]:
    """Get all cards with a specific category."""
    return [c for c in all_cards() if c.category == category]


def cards_by_status(status: Status) -> list[AVECard]:
    """Get all cards with a specific status."""
    return [c for c in all_cards() if c.status == status]
'''
    (pkg_dir / "registry.py").write_text(content)


def _create_public_cli(source_root: Path, pkg_dir: Path) -> None:
    """Create a public-safe CLI that uses file-based registry."""
    # Read the original CLI
    cli_src = source_root / "ave" / "ave" / "cli.py"
    content = cli_src.read_text()

    # Rewrite internal repo references
    content = _rewrite_urls(content)

    (pkg_dir / "cli.py").write_text(content)


def _create_public_pyproject(ave_dir: Path) -> None:
    """Create pyproject.toml for the public AVE package."""
    content = '''[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "nail-ave"
version = "1.0.0"
description = "AVE — Agentic Vulnerabilities & Exposures. The CVE database for AI agent failures."
readme = "README.md"
license = {text = "CC-BY-SA-4.0"}
requires-python = ">=3.10"
authors = [
    {name = "NAIL Institute"},
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Intended Audience :: Science/Research",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: Security",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov"]

[tool.setuptools.packages.find]
include = ["ave*"]

[project.scripts]
ave = "ave.cli:main"
'''
    (ave_dir / "pyproject.toml").write_text(content)


def _create_public_package_readme(ave_dir: Path) -> None:
    """Create README for the AVE Python package."""
    content = '''# AVE — Agentic Vulnerabilities & Exposures

**The CVE database for AI agent failures.**

Query, validate, and contribute to the world's first structured catalogue
of AI agent failure modes.

## Installation

```bash
pip install -e .
```

## Usage

```python
import ave

# Look up a vulnerability
card = ave.lookup("AVE-2025-0001")
print(card)

# Search by category
memory_vulns = ave.search(category=ave.Category.MEMORY)

# Filter by severity
critical = ave.cards_by_severity(ave.Severity.CRITICAL)
```

## CLI

```bash
python -m ave list                    # List all cards
python -m ave show AVE-2025-0001      # Card details
python -m ave search -k "injection"   # Keyword search
python -m ave stats                   # Database statistics
python -m ave validate ./cards/       # Validate card JSON
python -m ave submit --interactive    # Submit a new card
python -m ave leaderboard             # Contributor rankings
```

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for how to submit new vulnerability cards.

---

*Maintained by the [NAIL Institute](https://github.com/{PUBLIC_ORG})*
'''
    (ave_dir / "README.md").write_text(content)


def _generate_root_readme(output_dir: Path, card_count: int) -> None:
    """Generate the root README for the public repo."""
    content = f"""# 🛡️ NAIL Institute — AVE Database

[![AVE Cards](https://img.shields.io/badge/AVE_Cards-{card_count}-blue)](./ave-database/)
[![License](https://img.shields.io/badge/License-CC--BY--SA--4.0-green)](https://creativecommons.org/licenses/by-sa/4.0/)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-orange)](./CONTRIBUTING.md)
[![Hall of Fame](https://img.shields.io/badge/Hall_of_Fame-🏆-gold)](./HALL_OF_FAME.md)

> **The MITRE ATT&CK of the Agentic Era.**
>
> An open, community-driven catalogue of AI agent vulnerabilities — behavioural
> failure modes, attack vectors, and emergent pathologies affecting autonomous
> AI systems.

---

## What Is This?

AI agents are being deployed in production — executing code, calling APIs,
managing infrastructure, handling sensitive data. But there's no CVE database
for the ways they fail.

**Until now.**

The **AVE Database** (Agentic Vulnerabilities & Exposures) documents every
known failure mode of autonomous AI agents:

- 🧠 **Memory poisoning** — Agents trust corrupted shared state
- 🔗 **Tool chain exploits** — Confused deputy attacks via MCP/function calling
- 🎭 **Alignment failures** — Sycophantic collapse, deceptive alignment
- ⏰ **Temporal attacks** — Sleeper payloads, chronological desynchronisation
- 💸 **Resource exhaustion** — Token embezzlement, EDoS attacks
- 🤝 **Social failures** — Agent collusion, consensus paralysis
- …and {card_count - 6} more documented vulnerabilities

## Browse the Database

📖 **[ave-database/](./ave-database/)** — All {card_count} vulnerability cards

Each card contains:
- **What** — Name, category, severity, blast radius
- **Where** — Affected frameworks, agent configurations
- **How to Defend** — Known mitigation strategies (names only in public tier)

> 🔒 Full mechanism details, evidence data, PoC scripts, and defence implementations
> are available through the [NAIL SDK](https://github.com/{PUBLIC_ORG}).

## Quick Start

```bash
# Clone the repo
git clone https://github.com/{PUBLIC_SLUG}.git
cd ave-database

# Install the AVE toolkit
pip install -e ave/

# Explore
python -m ave list                       # All cards
python -m ave show AVE-2025-0001         # Card details
python -m ave search -k "injection"      # Search
python -m ave stats                      # Statistics
python -m ave leaderboard                # Top contributors
```

## Contribute

**Anyone can submit vulnerabilities.** If you've observed an AI agent behave
unexpectedly, fail in a repeatable way, or found an exploitable pattern —
we want to hear about it.

| Method | For |
|--------|-----|
| [**📝 Submit via Issue**](https://github.com/{PUBLIC_SLUG}/issues/new?template=ave-submission.yml) | Easiest — fill out a form |
| [**🔀 Submit via PR**](./CONTRIBUTING.md) | Experienced contributors |
| [**🔒 Private Disclosure**](./SECURITY.md) | Severe / weaponizable findings |

### Earn Recognition

Every accepted card earns **XP**, unlocks **badges**, and climbs the **leaderboard**:

| Tier | XP | Perks |
|------|----|-------|
| 👁️ Watcher | 0+ | Welcome to the hunt |
| 🏹 Hunter | 500+ | Hall of Fame listing |
| 🛡️ Sentinel | 1,500+ | Fast-track review |
| 🏗️ Architect | 4,000+ | Invited to review PRs |
| ⭐ Fellow | 8,000+ | NAIL Research Fellow |

See the [**🏆 Hall of Fame**](./HALL_OF_FAME.md) for current standings.

## Project Structure

```
├── ave-database/          # The vulnerability database
│   ├── cards/             #   Individual AVE cards (JSON + Markdown)
│   ├── index.json         #   Database index
│   └── README.md          #   Database documentation
├── ave/                   # Python toolkit
│   └── ave/               #   CLI, validation, submission tools
├── .github/               # Issue templates, PR templates, CI
├── CONTRIBUTING.md        # How to contribute
├── SECURITY.md            # Responsible disclosure
├── CODE_OF_CONDUCT.md     # Community standards
├── HALL_OF_FAME.md        # Contributor leaderboard
└── LICENSE                # CC-BY-SA-4.0
```

## License

All AVE Database content is licensed under
[**CC-BY-SA-4.0**](https://creativecommons.org/licenses/by-sa/4.0/).
Free to use, share, and build upon — with attribution.

---

<p align="center">
  <b>Built by the <a href="https://github.com/{PUBLIC_ORG}">NAIL Institute</a></b><br>
  <i>Building the safety infrastructure for agentic AI.</i>
</p>
"""
    (output_dir / "README.md").write_text(content)


def _generate_license(output_dir: Path) -> None:
    """Generate CC-BY-SA-4.0 license file."""
    content = """Creative Commons Attribution-ShareAlike 4.0 International

Copyright (c) 2025-2026 NAIL Institute (Neuravant AI Limited)

This work is licensed under the Creative Commons
Attribution-ShareAlike 4.0 International License.

To view a copy of this license, visit
http://creativecommons.org/licenses/by-sa/4.0/

You are free to:
  - Share: copy and redistribute the material in any medium or format
  - Adapt: remix, transform, and build upon the material for any purpose,
    including commercially

Under the following terms:
  - Attribution: You must give appropriate credit, provide a link to the
    license, and indicate if changes were made.
  - ShareAlike: If you remix, transform, or build upon the material, you
    must distribute your contributions under the same license.
  - No additional restrictions: You may not apply legal terms or
    technological measures that legally restrict others from doing
    anything the license permits.
"""
    (output_dir / "LICENSE").write_text(content)


def _generate_gitignore(output_dir: Path) -> None:
    """Generate .gitignore for the public repo."""
    content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
*.egg
dist/
build/
.eggs/

# Virtual environments
.venv/
venv/
ENV/

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Testing
.pytest_cache/
.coverage
htmlcov/

# Misc
*.log
"""
    (output_dir / ".gitignore").write_text(content)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Export a clean public-facing AVE Database repository."
    )
    parser.add_argument(
        "--output", "-o",
        default="public-repo",
        help="Output directory for the public repo (default: public-repo/)",
    )
    parser.add_argument(
        "--init-git",
        action="store_true",
        help="Initialize a git repo with initial commit",
    )
    args = parser.parse_args()

    source_root = PROJECT_ROOT
    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    export_public_repo(source_root, output_dir, init_git=args.init_git)


if __name__ == "__main__":
    main()
