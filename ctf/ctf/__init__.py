"""
CTF — Agentic Capture-The-Flag Platform
=========================================

Phase 4 of the Agent-CVE programme. Hosts red-team CTF events where
human participants (or automated agents) attempt to exploit defended
AI agents within constrained sandboxes.

Architecture:

    ┌─────────────────────────────────────────────────────────┐
    │                    Tournament                           │
    │  (manages event lifecycle, scoring, leaderboard)        │
    └────────┬───────────────────────────────────┬────────────┘
             │                                   │
    ┌────────▼──────────┐           ┌────────────▼────────────┐
    │    Challenges       │           │     Scoreboard          │
    │  (objective defs,   │           │  (live rankings, team   │
    │   flag placement,   │           │   stats, prize tiers)   │
    │   difficulty tiers) │           └─────────────────────────┘
    └────────┬──────────┘
             │
    ┌────────▼──────────┐
    │    Sandbox          │   ← isolated execution environment
    │  (agent + defences  │      per challenge per participant
    │   + flags + budget) │
    └────────┬──────────┘
             │
    ┌────────▼──────────┐
    │   Submission        │   ← participant attempts judged
    │   (flag capture,    │      automatically
    │    AVE card draft)  │
    └─────────────────────┘

Usage:
    >>> from ctf import Tournament, Challenge, Difficulty
    >>>
    >>> # Build a CTF event
    >>> tourney = Tournament.weekend_ctf(name="NAIL CTF #1")
    >>> tourney.register_team("AlphaHackers")
    >>> tourney.register_team("ZeroDaySquad")
    >>>
    >>> # Run it
    >>> tourney.open()
    >>> sub = tourney.submit("AlphaHackers", challenge_id="edos-01", flag="NAIL{...}")
    >>> print(sub.correct, sub.points)
    >>>
    >>> # Leaderboard
    >>> for entry in tourney.scoreboard.rankings():
    ...     print(entry.team, entry.total_points)
"""

__version__ = "2.0.0"

from .challenge import (
    Challenge,
    Difficulty,
    Flag,
    Objective,
    ObjectiveType,
)
from .sandbox import (
    Sandbox,
    SandboxConfig,
    SandboxState,
)
from .submission import (
    Submission,
    SubmissionVerdict,
)
from .scoreboard import (
    Scoreboard,
    TeamScore,
)
from .tournament import (
    Tournament,
    TournamentState,
    EventResult,
)
from .event_config import (
    EventTemplate,
    weekend_ctf_template,
    quick_demo_template,
    enterprise_ctf_template,
    arena_seeded_template,
    get_template,
    list_templates,
)
from .server import CTFServerConfig

__all__ = [
    # Challenges
    "Challenge",
    "Difficulty",
    "Flag",
    "Objective",
    "ObjectiveType",
    # Sandbox
    "Sandbox",
    "SandboxConfig",
    "SandboxState",
    # Submissions
    "Submission",
    "SubmissionVerdict",
    # Scoreboard
    "Scoreboard",
    "TeamScore",
    # Tournament
    "Tournament",
    "TournamentState",
    "EventResult",
    # Event Config (v2.0)
    "EventTemplate",
    "weekend_ctf_template",
    "quick_demo_template",
    "enterprise_ctf_template",
    "arena_seeded_template",
    "get_template",
    "list_templates",
    # Server (v2.0)
    "CTFServerConfig",
]
