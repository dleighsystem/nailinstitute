"""
AVE Gamification — Contributor recognition & engagement engine.

Tracks contributor activity across the AVE Database and awards:
  - XP (experience points) based on submission quality & severity
  - Badges for specific achievements
  - Tier progression (Watcher → Hunter → Sentinel → Architect → Fellow)
  - Streaks for consistent contributions
  - Leaderboard rankings

All data is derived from the card database — no external database required.
Contributors are identified by their `contributor` field in AVE cards.

Usage:
    from ave.gamification import (
        build_profiles, leaderboard, get_profile,
        format_leaderboard, format_profile, format_hall_of_fame,
    )
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# XP Constants
# ═══════════════════════════════════════════════════════════════════

XP_BY_SEVERITY = {
    "critical": 500,
    "high":     300,
    "medium":   150,
    "low":      75,
    "info":     50,
}

XP_BY_STATUS = {
    "proven":          1.0,   # Full XP — empirically validated
    "proven_mitigated": 1.2,  # Bonus — you also found a defence
    "theoretical":     0.5,   # Half XP — not yet validated
    "in_progress":     0.3,   # Small credit — under investigation
    "not_proven":      0.1,   # Participation credit
}

XP_BONUS_EVIDENCE   = 50    # Per evidence item with actual data
XP_BONUS_POC        = 100   # Has proof of concept
XP_BONUS_DEFENCE    = 75    # Submitted a defence/mitigation
XP_BONUS_CROSS_REF  = 25    # Card references other AVE cards
XP_BONUS_FIRST_CARD = 200   # First ever submission bonus
XP_BONUS_NEW_CATEGORY = 300 # First card in a new category
XP_BONUS_NOVEL_DISCOVERY = 150  # "New" disclosure status


# ═══════════════════════════════════════════════════════════════════
# Tier System
# ═══════════════════════════════════════════════════════════════════

class Tier(str, Enum):
    """Contributor tier — progression based on cumulative XP."""
    WATCHER   = "watcher"      #    0+ XP — Joined the hunt
    HUNTER    = "hunter"       #  500+ XP — Proven contributor
    SENTINEL  = "sentinel"     # 1500+ XP — Serious researcher
    ARCHITECT = "architect"    # 4000+ XP — Shaping the taxonomy
    FELLOW    = "fellow"       # 8000+ XP — NAIL Research Fellow


TIER_THRESHOLDS = [
    (8000, Tier.FELLOW),
    (4000, Tier.ARCHITECT),
    (1500, Tier.SENTINEL),
    (500,  Tier.HUNTER),
    (0,    Tier.WATCHER),
]

TIER_ICONS = {
    Tier.WATCHER:   "👁️",
    Tier.HUNTER:    "🏹",
    Tier.SENTINEL:  "🛡️",
    Tier.ARCHITECT: "🏗️",
    Tier.FELLOW:    "⭐",
}

TIER_DESCRIPTIONS = {
    Tier.WATCHER:   "Joined the hunt",
    Tier.HUNTER:    "Proven vulnerability hunter",
    Tier.SENTINEL:  "Trusted security researcher",
    Tier.ARCHITECT: "Shaping the agentic safety taxonomy",
    Tier.FELLOW:    "NAIL Research Fellow",
}


def _compute_tier(xp: int) -> Tier:
    """Determine tier from cumulative XP."""
    for threshold, tier in TIER_THRESHOLDS:
        if xp >= threshold:
            return tier
    return Tier.WATCHER


def _next_tier_info(xp: int) -> tuple[Optional[Tier], int]:
    """Return (next_tier, xp_needed) or (None, 0) if max tier."""
    current = _compute_tier(xp)
    for threshold, tier in reversed(TIER_THRESHOLDS):
        if threshold > xp:
            return tier, threshold - xp
    return None, 0


# ═══════════════════════════════════════════════════════════════════
# Badge System
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Badge:
    """An achievement badge earned through contribution."""
    id: str
    name: str
    icon: str
    description: str
    rarity: str   # "common", "uncommon", "rare", "epic", "legendary"


# Badge catalog — all earnable badges
BADGES: dict[str, Badge] = {
    # ── Quantity badges ──────────────────────────────────────────
    "first_blood": Badge(
        "first_blood", "First Blood", "🩸",
        "Submitted your first AVE card", "common",
    ),
    "five_alive": Badge(
        "five_alive", "Five Alive", "🖐️",
        "5 accepted AVE cards", "uncommon",
    ),
    "ten_ring": Badge(
        "ten_ring", "Ten Ring", "🎯",
        "10 accepted AVE cards", "rare",
    ),
    "twenty_vision": Badge(
        "twenty_vision", "20/20 Vision", "🔭",
        "20 accepted AVE cards", "epic",
    ),

    # ── Severity badges ──────────────────────────────────────────
    "critical_finder": Badge(
        "critical_finder", "Critical Finder", "🔴",
        "Found a CRITICAL severity vulnerability", "uncommon",
    ),
    "critical_hunter": Badge(
        "critical_hunter", "Critical Hunter", "💀",
        "Found 3+ CRITICAL severity vulnerabilities", "rare",
    ),
    "doomsday_prophet": Badge(
        "doomsday_prophet", "Doomsday Prophet", "☠️",
        "Found 5+ CRITICAL severity vulnerabilities", "epic",
    ),

    # ── Evidence badges ──────────────────────────────────────────
    "show_your_work": Badge(
        "show_your_work", "Show Your Work", "📊",
        "Submitted a card with empirical evidence", "common",
    ),
    "lab_rat": Badge(
        "lab_rat", "Lab Rat", "🐀",
        "5+ cards with empirical evidence", "uncommon",
    ),
    "proof_positive": Badge(
        "proof_positive", "Proof Positive", "🧪",
        "Submitted a card with a working PoC", "uncommon",
    ),

    # ── Defence badges ───────────────────────────────────────────
    "shield_bearer": Badge(
        "shield_bearer", "Shield Bearer", "🛡️",
        "Submitted a card with a known defence", "common",
    ),
    "mitigation_master": Badge(
        "mitigation_master", "Mitigation Master", "⚔️",
        "5+ cards with proven defences", "rare",
    ),

    # ── Category badges ──────────────────────────────────────────
    "category_pioneer": Badge(
        "category_pioneer", "Category Pioneer", "🗺️",
        "First card in a previously empty category", "rare",
    ),
    "polymath": Badge(
        "polymath", "Polymath", "🎓",
        "Submitted cards across 5+ different categories", "rare",
    ),
    "taxonomist": Badge(
        "taxonomist", "Taxonomist", "📚",
        "Submitted cards across 10+ different categories", "epic",
    ),

    # ── Cross-reference badges ───────────────────────────────────
    "connector": Badge(
        "connector", "Connector", "🔗",
        "Linked your card to existing AVE cards", "common",
    ),
    "web_weaver": Badge(
        "web_weaver", "Web Weaver", "🕸️",
        "5+ cards with cross-references to other AVEs", "uncommon",
    ),

    # ── Discovery badges ─────────────────────────────────────────
    "novel_discovery": Badge(
        "novel_discovery", "Novel Discovery", "💡",
        "Reported a previously undocumented vulnerability", "uncommon",
    ),
    "trailblazer": Badge(
        "trailblazer", "Trailblazer", "🔥",
        "5+ novel discoveries not previously documented", "rare",
    ),

    # ── Streak badges ────────────────────────────────────────────
    "streak_3": Badge(
        "streak_3", "Hat Trick", "🎩",
        "3 submissions in 3 consecutive months", "uncommon",
    ),
    "streak_6": Badge(
        "streak_6", "Half Year Hero", "📅",
        "6 submissions in 6 consecutive months", "rare",
    ),
    "streak_12": Badge(
        "streak_12", "Year of Living Dangerously", "🏆",
        "12 submissions in 12 consecutive months", "legendary",
    ),

    # ── Special badges ───────────────────────────────────────────
    "proved_and_defended": Badge(
        "proved_and_defended", "Proved & Defended", "🏰",
        "A card that is both proven AND has mitigation", "rare",
    ),
    "compound_threat": Badge(
        "compound_threat", "Compound Threat", "⚡",
        "Card that references 3+ other AVEs", "rare",
    ),
    "fellow_status": Badge(
        "fellow_status", "NAIL Research Fellow", "⭐",
        "Achieved NAIL Research Fellow tier", "legendary",
    ),
}

RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4}


# ═══════════════════════════════════════════════════════════════════
# Contributor Profile
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ContributorProfile:
    """Full profile for a contributor, computed from their AVE cards."""
    handle: str
    total_xp: int = 0
    tier: Tier = Tier.WATCHER
    cards_submitted: int = 0
    cards_by_severity: dict[str, int] = field(default_factory=dict)
    cards_by_category: dict[str, int] = field(default_factory=dict)
    cards_by_status: dict[str, int] = field(default_factory=dict)
    badges: list[Badge] = field(default_factory=list)
    streak_months: int = 0
    active_months: list[str] = field(default_factory=list)  # "YYYY-MM" sorted
    ave_ids: list[str] = field(default_factory=list)
    rank: int = 0

    @property
    def next_tier(self) -> Optional[Tier]:
        nt, _ = _next_tier_info(self.total_xp)
        return nt

    @property
    def xp_to_next_tier(self) -> int:
        _, needed = _next_tier_info(self.total_xp)
        return needed

    @property
    def tier_icon(self) -> str:
        return TIER_ICONS[self.tier]

    @property
    def unique_categories(self) -> int:
        return len(self.cards_by_category)

    @property
    def critical_count(self) -> int:
        return self.cards_by_category.get("critical", 0)

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "total_xp": self.total_xp,
            "tier": self.tier.value,
            "tier_icon": self.tier_icon,
            "cards_submitted": self.cards_submitted,
            "cards_by_severity": self.cards_by_severity,
            "cards_by_category": self.cards_by_category,
            "badges": [{"id": b.id, "name": b.name, "icon": b.icon,
                        "rarity": b.rarity} for b in self.badges],
            "streak_months": self.streak_months,
            "ave_ids": self.ave_ids,
            "rank": self.rank,
        }


# ═══════════════════════════════════════════════════════════════════
# Profile Builder
# ═══════════════════════════════════════════════════════════════════

def _load_cards_from_directory(cards_dir: str) -> list[dict]:
    """Load all AVE card JSON files from a directory."""
    cards = []
    p = Path(cards_dir)
    if not p.is_dir():
        return cards
    for f in sorted(p.glob("AVE-*.json")):
        if f.name in ("index.json", "severity_index.json"):
            continue
        try:
            with open(f) as fh:
                data = json.load(fh)
                data["_source_file"] = str(f)
                cards.append(data)
        except (json.JSONDecodeError, IOError):
            pass
    return cards


def _load_cards_from_registry() -> list[dict]:
    """Load all cards from the in-memory registry."""
    from .registry import all_cards
    return [c.to_dict() for c in all_cards()]


def _compute_card_xp(card: dict, is_first: bool = False,
                     is_new_category: bool = False) -> int:
    """Calculate XP earned from a single card."""
    severity = card.get("severity", "medium")
    status = card.get("status", "theoretical")

    base = XP_BY_SEVERITY.get(severity, 50)
    multiplier = XP_BY_STATUS.get(status, 0.5)
    xp = int(base * multiplier)

    # Evidence bonus
    evidence = card.get("evidence", [])
    for e in evidence:
        if e.get("key_metric") and e.get("key_value"):
            if not str(e.get("key_metric", "")).startswith("[FILL"):
                xp += XP_BONUS_EVIDENCE

    # PoC bonus
    if card.get("poc"):
        xp += XP_BONUS_POC

    # Defence bonus
    defences = card.get("defences", [])
    if defences and any(d.get("name") for d in defences):
        xp += XP_BONUS_DEFENCE

    # Cross-reference bonus
    related = card.get("related_aves", [])
    if related:
        xp += XP_BONUS_CROSS_REF

    # First card bonus
    if is_first:
        xp += XP_BONUS_FIRST_CARD

    # New category pioneer
    if is_new_category:
        xp += XP_BONUS_NEW_CATEGORY

    # Novel discovery bonus — infer from card metadata if present
    disclosure = card.get("_disclosure", "")
    if "new" in disclosure.lower() or "novel" in str(card.get("aliases", "")).lower():
        xp += XP_BONUS_NOVEL_DISCOVERY

    return xp


def _compute_streak(months: list[str]) -> int:
    """Calculate longest consecutive month streak."""
    if not months:
        return 0
    sorted_months = sorted(set(months))
    best = 1
    current = 1
    for i in range(1, len(sorted_months)):
        prev = sorted_months[i - 1]
        curr = sorted_months[i]
        try:
            prev_dt = datetime.strptime(prev, "%Y-%m")
            curr_dt = datetime.strptime(curr, "%Y-%m")
            diff_months = (curr_dt.year - prev_dt.year) * 12 + (curr_dt.month - prev_dt.month)
            if diff_months == 1:
                current += 1
                best = max(best, current)
            else:
                current = 1
        except ValueError:
            current = 1
    return best


def _award_badges(profile: ContributorProfile, cards: list[dict],
                  global_first_categories: dict[str, str]) -> None:
    """Determine which badges a contributor has earned."""
    earned: list[Badge] = []
    n = profile.cards_submitted
    sev = profile.cards_by_severity

    # Quantity badges
    if n >= 1:
        earned.append(BADGES["first_blood"])
    if n >= 5:
        earned.append(BADGES["five_alive"])
    if n >= 10:
        earned.append(BADGES["ten_ring"])
    if n >= 20:
        earned.append(BADGES["twenty_vision"])

    # Severity badges
    crit = sev.get("critical", 0)
    if crit >= 1:
        earned.append(BADGES["critical_finder"])
    if crit >= 3:
        earned.append(BADGES["critical_hunter"])
    if crit >= 5:
        earned.append(BADGES["doomsday_prophet"])

    # Evidence badges
    cards_with_evidence = sum(
        1 for c in cards
        if any(e.get("key_metric") and not str(e.get("key_metric", "")).startswith("[FILL")
               for e in c.get("evidence", []))
    )
    if cards_with_evidence >= 1:
        earned.append(BADGES["show_your_work"])
    if cards_with_evidence >= 5:
        earned.append(BADGES["lab_rat"])

    # PoC badge
    if any(c.get("poc") for c in cards):
        earned.append(BADGES["proof_positive"])

    # Defence badges
    cards_with_defences = sum(
        1 for c in cards
        if c.get("defences") and any(d.get("name") for d in c.get("defences", []))
    )
    if cards_with_defences >= 1:
        earned.append(BADGES["shield_bearer"])
    if cards_with_defences >= 5:
        earned.append(BADGES["mitigation_master"])

    # Category badges
    if profile.unique_categories >= 5:
        earned.append(BADGES["polymath"])
    if profile.unique_categories >= 10:
        earned.append(BADGES["taxonomist"])

    # Category pioneer — first person to submit in a category
    for cat, first_handle in global_first_categories.items():
        if first_handle == profile.handle:
            earned.append(BADGES["category_pioneer"])
            break  # Only awarded once even if pioneer in multiple

    # Cross-reference badges
    cards_with_refs = sum(1 for c in cards if c.get("related_aves"))
    if cards_with_refs >= 1:
        earned.append(BADGES["connector"])
    if cards_with_refs >= 5:
        earned.append(BADGES["web_weaver"])

    # Novel discovery
    novel_count = sum(
        1 for c in cards
        if "new" in c.get("_disclosure", "").lower()
    )
    # Also count cards with "novel" / original status markers
    if not novel_count:
        novel_count = sum(
            1 for c in cards
            if c.get("status") in ("proven", "proven_mitigated")
            and c.get("date_discovered", "") >= "2025-01"
        )
    if novel_count >= 1:
        earned.append(BADGES["novel_discovery"])
    if novel_count >= 5:
        earned.append(BADGES["trailblazer"])

    # Streak badges
    if profile.streak_months >= 3:
        earned.append(BADGES["streak_3"])
    if profile.streak_months >= 6:
        earned.append(BADGES["streak_6"])
    if profile.streak_months >= 12:
        earned.append(BADGES["streak_12"])

    # Proved & Defended — any card that is proven_mitigated
    if sev.get("proven_mitigated", 0) or profile.cards_by_status.get("proven_mitigated", 0):
        earned.append(BADGES["proved_and_defended"])

    # Compound threat — card referencing 3+ other AVEs
    if any(len(c.get("related_aves", [])) >= 3 for c in cards):
        earned.append(BADGES["compound_threat"])

    # Fellow status
    if profile.tier == Tier.FELLOW:
        earned.append(BADGES["fellow_status"])

    # Deduplicate and sort by rarity
    seen = set()
    unique: list[Badge] = []
    for b in earned:
        if b.id not in seen:
            seen.add(b.id)
            unique.append(b)
    unique.sort(key=lambda b: RARITY_ORDER.get(b.rarity, 0), reverse=True)

    profile.badges = unique


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def build_profiles(
    cards_dir: Optional[str] = None,
    use_registry: bool = False,
) -> dict[str, ContributorProfile]:
    """
    Build contributor profiles from AVE card data.

    Args:
        cards_dir: Path to ave-database/cards/ directory
        use_registry: If True, use the in-memory registry instead

    Returns:
        Dict mapping contributor handle → ContributorProfile
    """
    if use_registry:
        cards = _load_cards_from_registry()
    elif cards_dir:
        cards = _load_cards_from_directory(cards_dir)
    else:
        # Try default path
        for try_path in ["ave-database/cards", "../ave-database/cards"]:
            if Path(try_path).is_dir():
                cards = _load_cards_from_directory(try_path)
                break
        else:
            cards = _load_cards_from_registry()

    # Group cards by contributor
    by_contributor: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        contributor = card.get("contributor", "").strip()
        if not contributor or contributor.startswith("["):
            contributor = "NAIL Institute"  # Default for unfilled
        by_contributor[contributor].append(card)

    # Track first-in-category pioneers
    category_first: dict[str, tuple[str, str]] = {}  # cat -> (date, handle)
    for contributor, contrib_cards in by_contributor.items():
        for card in contrib_cards:
            cat = card.get("category", "emergent")
            date = card.get("date_discovered", "9999-99")
            if cat not in category_first or date < category_first[cat][0]:
                category_first[cat] = (date, contributor)

    global_first_categories = {cat: handle for cat, (_, handle) in category_first.items()}

    # Build profiles
    profiles: dict[str, ContributorProfile] = {}

    for contributor, contrib_cards in by_contributor.items():
        profile = ContributorProfile(handle=contributor)
        profile.cards_submitted = len(contrib_cards)
        profile.ave_ids = sorted(c.get("ave_id", "") for c in contrib_cards)

        # Count by severity/category/status
        for card in contrib_cards:
            sev = card.get("severity", "medium")
            cat = card.get("category", "emergent")
            status = card.get("status", "theoretical")
            profile.cards_by_severity[sev] = profile.cards_by_severity.get(sev, 0) + 1
            profile.cards_by_category[cat] = profile.cards_by_category.get(cat, 0) + 1
            profile.cards_by_status[status] = profile.cards_by_status.get(status, 0) + 1

        # Collect active months
        months = []
        for card in contrib_cards:
            dd = card.get("date_discovered", "")
            if re.match(r"\d{4}-\d{2}", dd):
                months.append(dd[:7])
        profile.active_months = sorted(set(months))
        profile.streak_months = _compute_streak(months)

        # Compute XP
        seen_categories: set[str] = set()
        for i, card in enumerate(sorted(contrib_cards, key=lambda c: c.get("date_discovered", ""))):
            cat = card.get("category", "emergent")
            is_first = (i == 0)
            is_new_cat = cat not in seen_categories and global_first_categories.get(cat) == contributor
            seen_categories.add(cat)
            profile.total_xp += _compute_card_xp(card, is_first=is_first, is_new_category=is_new_cat)

        # Set tier
        profile.tier = _compute_tier(profile.total_xp)

        # Award badges
        _award_badges(profile, contrib_cards, global_first_categories)

        profiles[contributor] = profile

    # Assign ranks
    ranked = sorted(profiles.values(), key=lambda p: (-p.total_xp, -p.cards_submitted))
    for i, p in enumerate(ranked, 1):
        p.rank = i

    return profiles


def leaderboard(
    cards_dir: Optional[str] = None,
    use_registry: bool = False,
    top_n: int = 50,
) -> list[ContributorProfile]:
    """Return ranked leaderboard of top contributors."""
    profiles = build_profiles(cards_dir, use_registry)
    ranked = sorted(profiles.values(), key=lambda p: (-p.total_xp, -p.cards_submitted))
    return ranked[:top_n]


def get_profile(
    handle: str,
    cards_dir: Optional[str] = None,
    use_registry: bool = False,
) -> Optional[ContributorProfile]:
    """Get a single contributor's profile."""
    profiles = build_profiles(cards_dir, use_registry)
    # Case-insensitive lookup
    for key, profile in profiles.items():
        if key.lower() == handle.lower():
            return profile
    return None


# ═══════════════════════════════════════════════════════════════════
# Terminal Formatters
# ═══════════════════════════════════════════════════════════════════

def format_leaderboard(profiles: list[ContributorProfile]) -> str:
    """Format leaderboard for terminal output."""
    lines = [
        "",
        f"{'═' * 76}",
        f"  🏆 AVE Database — Contributor Leaderboard",
        f"{'═' * 76}",
        "",
        f"  {'Rank':<6} {'Tier':<4} {'Handle':<22} {'XP':>7} {'Cards':>6} {'Badges':>7} {'Streak':>7}",
        f"  {'─' * 6} {'─' * 4} {'─' * 22} {'─' * 7} {'─' * 6} {'─' * 7} {'─' * 7}",
    ]

    for p in profiles:
        lines.append(
            f"  #{p.rank:<5} {p.tier_icon:<4} {p.handle:<22} "
            f"{p.total_xp:>6}⚡ {p.cards_submitted:>5} {len(p.badges):>6}🏅 "
            f"{p.streak_months:>5}mo"
        )

    lines.append("")
    lines.append(f"  {'─' * 70}")
    lines.append(f"  {len(profiles)} contributors ranked")
    lines.append("")
    return "\n".join(lines)


def format_profile(profile: ContributorProfile) -> str:
    """Format a contributor profile for terminal output."""
    lines = [
        "",
        f"╔{'═' * 68}╗",
        f"║  {profile.tier_icon} {profile.handle:<63} ║",
        f"╠{'═' * 68}╣",
        f"║  Tier:       {profile.tier.value.upper():<53} ║",
        f"║  XP:         {profile.total_xp:,}⚡{'':>48} ║"[:71] + " ║",
        f"║  Cards:      {profile.cards_submitted:<53} ║",
        f"║  Rank:       #{profile.rank:<52} ║",
        f"║  Streak:     {profile.streak_months} months{'':>47} ║"[:71] + " ║",
    ]

    # Next tier progress
    if profile.next_tier:
        pct = (profile.total_xp / (profile.total_xp + profile.xp_to_next_tier)) * 100
        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        lines.append(f"╠{'─' * 68}╣")
        lines.append(f"║  Next tier:  {TIER_ICONS[profile.next_tier]} {profile.next_tier.value.upper()} "
                     f"({profile.xp_to_next_tier:,} XP needed){'':>25} ║"[:71] + " ║")
        lines.append(f"║  Progress:  [{bar}] {pct:.0f}%{'':>30} ║"[:71] + " ║")

    # Badges
    if profile.badges:
        lines.append(f"╠{'─' * 68}╣")
        lines.append(f"║  Badges ({len(profile.badges)}):{'':>55} ║"[:71] + " ║")
        for badge in profile.badges:
            rarity_tag = f"[{badge.rarity.upper()}]"
            lines.append(f"║    {badge.icon} {badge.name:<20} {rarity_tag:<12} "
                         f"{badge.description[:28]:<28} ║")

    # Severity breakdown
    if profile.cards_by_severity:
        lines.append(f"╠{'─' * 68}╣")
        lines.append(f"║  Severity Breakdown:{'':>47} ║")
        sev_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "info": "ℹ️"}
        for sev, count in sorted(profile.cards_by_severity.items(),
                                  key=lambda x: {"critical": 0, "high": 1, "medium": 2,
                                                  "low": 3, "info": 4}.get(x[0], 5)):
            icon = sev_icons.get(sev, "")
            lines.append(f"║    {icon} {sev:>12}: {count:<48} ║")

    # AVE IDs
    if profile.ave_ids:
        lines.append(f"╠{'─' * 68}╣")
        lines.append(f"║  Cards:{'':>60} ║")
        row = "    "
        for ave_id in profile.ave_ids:
            if len(row) + len(ave_id) + 2 > 65:
                lines.append(f"║  {row:<66} ║")
                row = "    "
            row += ave_id + ", "
        if row.strip().rstrip(","):
            lines.append(f"║  {row.rstrip(', '):<66} ║")

    lines.append(f"╚{'═' * 68}╝")
    lines.append("")
    return "\n".join(lines)


def format_badges_catalog() -> str:
    """Format the full badge catalog for terminal output."""
    lines = [
        "",
        f"{'═' * 76}",
        f"  🏅 AVE Database — Badge Catalog",
        f"{'═' * 76}",
        "",
    ]

    by_rarity: dict[str, list[Badge]] = defaultdict(list)
    for badge in BADGES.values():
        by_rarity[badge.rarity].append(badge)

    for rarity in ["legendary", "epic", "rare", "uncommon", "common"]:
        if rarity not in by_rarity:
            continue
        rarity_icon = {"legendary": "✨", "epic": "💎", "rare": "💜",
                       "uncommon": "💚", "common": "⬜"}.get(rarity, "")
        lines.append(f"  {rarity_icon} {rarity.upper()}")
        lines.append(f"  {'─' * 72}")
        for badge in by_rarity[rarity]:
            lines.append(f"    {badge.icon} {badge.name:<24} {badge.description}")
        lines.append("")

    lines.append(f"  Total: {len(BADGES)} badges available")
    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Markdown Generators (for HALL_OF_FAME.md)
# ═══════════════════════════════════════════════════════════════════

def format_hall_of_fame(
    cards_dir: Optional[str] = None,
    use_registry: bool = False,
) -> str:
    """Generate the full HALL_OF_FAME.md content."""
    profiles = build_profiles(cards_dir, use_registry)
    ranked = sorted(profiles.values(), key=lambda p: (-p.total_xp, -p.cards_submitted))

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# 🏆 AVE Database — Hall of Fame",
        "",
        f"[![Contributors](https://img.shields.io/badge/Contributors-{len(ranked)}-blue)]"
        f"(./CONTRIBUTING.md)",
        f"[![Cards](https://img.shields.io/badge/AVE_Cards-"
        f"{sum(p.cards_submitted for p in ranked)}-green)](./ave-database/)",
        "",
        "> **Recognising the security researchers who make agentic AI safer.**",
        ">",
        f"> *Auto-generated on {now} from AVE Database card data.*",
        "",
        "---",
        "",
    ]

    # Tier overview
    lines.extend([
        "## 🎖️ Tier System",
        "",
        "| Icon | Tier | XP Required | Description |",
        "|------|------|-------------|-------------|",
    ])
    for tier in [Tier.FELLOW, Tier.ARCHITECT, Tier.SENTINEL, Tier.HUNTER, Tier.WATCHER]:
        threshold = next(t for t, ti in TIER_THRESHOLDS if ti == tier)
        lines.append(
            f"| {TIER_ICONS[tier]} | **{tier.value.upper()}** | "
            f"{threshold:,}+ XP | {TIER_DESCRIPTIONS[tier]} |"
        )
    lines.extend(["", "---", ""])

    # Leaderboard
    lines.extend([
        "## 🏅 Leaderboard",
        "",
        "| Rank | Tier | Contributor | XP | Cards | Badges | Streak |",
        "|-----:|------|-------------|---:|------:|-------:|-------:|",
    ])
    for p in ranked:
        badge_icons = "".join(b.icon for b in p.badges[:5])
        if len(p.badges) > 5:
            badge_icons += f" +{len(p.badges) - 5}"
        lines.append(
            f"| #{p.rank} | {p.tier_icon} {p.tier.value} | **{p.handle}** | "
            f"{p.total_xp:,}⚡ | {p.cards_submitted} | "
            f"{badge_icons} ({len(p.badges)}) | {p.streak_months}mo |"
        )
    lines.extend(["", "---", ""])

    # Individual profiles
    lines.extend([
        "## 👤 Contributor Profiles",
        "",
    ])

    for p in ranked:
        lines.extend([
            f"### {p.tier_icon} {p.handle}",
            "",
            f"**Tier:** {p.tier.value.upper()} · "
            f"**XP:** {p.total_xp:,}⚡ · "
            f"**Cards:** {p.cards_submitted} · "
            f"**Rank:** #{p.rank}",
            "",
        ])

        # Badges
        if p.badges:
            badge_line = " ".join(f"{b.icon} {b.name}" for b in p.badges)
            lines.append(f"**Badges:** {badge_line}")
            lines.append("")

        # Cards
        if p.ave_ids:
            lines.append(f"**Cards:** {', '.join(f'`{aid}`' for aid in p.ave_ids)}")
            lines.append("")

        # Progress bar
        if p.next_tier:
            pct = (p.total_xp / (p.total_xp + p.xp_to_next_tier)) * 100
            filled = int(pct / 5)
            bar = "█" * filled + "░" * (20 - filled)
            lines.append(
                f"**Progress to {p.next_tier.value.upper()}:** "
                f"`[{bar}]` {pct:.0f}% ({p.xp_to_next_tier:,} XP needed)"
            )
            lines.append("")

        lines.append("---")
        lines.append("")

    # Badge catalog
    lines.extend([
        "## 🏅 Badge Catalog",
        "",
        "| Icon | Badge | Rarity | How to Earn |",
        "|------|-------|--------|-------------|",
    ])
    sorted_badges = sorted(BADGES.values(),
                           key=lambda b: RARITY_ORDER.get(b.rarity, 0), reverse=True)
    for badge in sorted_badges:
        rarity_icon = {"legendary": "✨", "epic": "💎", "rare": "💜",
                       "uncommon": "💚", "common": "⬜"}.get(badge.rarity, "")
        lines.append(
            f"| {badge.icon} | **{badge.name}** | "
            f"{rarity_icon} {badge.rarity} | {badge.description} |"
        )
    lines.extend(["", "---", ""])

    # XP breakdown
    lines.extend([
        "## ⚡ How XP Works",
        "",
        "### Base XP by Severity",
        "",
        "| Severity | Base XP |",
        "|----------|--------:|",
    ])
    for sev, xp in sorted(XP_BY_SEVERITY.items(),
                           key=lambda x: x[1], reverse=True):
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡",
                "low": "🟢", "info": "ℹ️"}.get(sev, "")
        lines.append(f"| {icon} {sev} | {xp} XP |")

    lines.extend([
        "",
        "### Status Multiplier",
        "",
        "| Status | Multiplier |",
        "|--------|----------:|",
    ])
    for status, mult in sorted(XP_BY_STATUS.items(),
                                key=lambda x: x[1], reverse=True):
        lines.append(f"| `{status}` | ×{mult} |")

    lines.extend([
        "",
        "### Bonus XP",
        "",
        "| Action | Bonus |",
        "|--------|------:|",
        f"| First card ever | +{XP_BONUS_FIRST_CARD} XP |",
        f"| Evidence with data | +{XP_BONUS_EVIDENCE} XP (per item) |",
        f"| Proof of Concept | +{XP_BONUS_POC} XP |",
        f"| Defence/mitigation | +{XP_BONUS_DEFENCE} XP |",
        f"| Cross-references | +{XP_BONUS_CROSS_REF} XP |",
        f"| Novel discovery | +{XP_BONUS_NOVEL_DISCOVERY} XP |",
        f"| First in new category | +{XP_BONUS_NEW_CATEGORY} XP |",
        "",
        "---",
        "",
        "*Want to see your name here? "
        "[Submit a vulnerability](https://github.com/dleighsystem/nailinstitute/issues/new"
        "?template=ave-submission.yml) and start earning XP!*",
        "",
        "*Maintained by the "
        "[NAIL Institute](https://github.com/dleighsystem/nailinstitute) — "
        "Building the safety infrastructure for agentic AI.*",
    ])

    return "\n".join(lines)
