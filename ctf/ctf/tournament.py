"""
Tournament — Top-level CTF event orchestrator.

Manages the full lifecycle of a Capture-The-Flag event:
  1. Registration — teams sign up
  2. Open — challenges become available, sandboxes are spawned
  3. Running — participants interact and submit flags
  4. Closed — final scores, prizes, AVE card harvesting

Integrates with the Scoreboard for live rankings and produces
EventResult summaries with auto-drafted AVE cards from novel
attack patterns discovered during the competition.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .challenge import Challenge, Difficulty, Flag
from .sandbox import Sandbox, SandboxConfig, SandboxState
from .submission import Submission, SubmissionVerdict, judge_submission
from .scoreboard import Scoreboard, TeamScore, RankEntry


class TournamentState(str, Enum):
    """Lifecycle state of a CTF tournament."""
    REGISTRATION = "registration"   # Accepting team registrations
    OPEN = "open"                   # Challenges active, accepting submissions
    PAUSED = "paused"               # Temporarily suspended
    CLOSED = "closed"               # Event finished


@dataclass
class PrizeTier:
    """Prize definition for a ranking position."""
    rank: int
    label: str
    amount_usd: int

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "label": self.label, "amount_usd": self.amount_usd}


@dataclass
class EventResult:
    """
    Final results of a completed CTF tournament.

    Includes rankings, statistics, all submissions, and auto-drafted
    AVE cards from novel attack patterns discovered during the event.
    """
    event_id: str
    name: str
    rankings: list[RankEntry] = field(default_factory=list)
    total_teams: int = 0
    total_submissions: int = 0
    total_flags_captured: int = 0
    total_challenges: int = 0
    challenges_solved: int = 0
    prize_pool_usd: int = 0
    prizes_awarded: list[dict[str, Any]] = field(default_factory=list)
    novel_attacks: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "total_teams": self.total_teams,
            "total_submissions": self.total_submissions,
            "total_flags_captured": self.total_flags_captured,
            "total_challenges": self.total_challenges,
            "challenges_solved": self.challenges_solved,
            "prize_pool_usd": self.prize_pool_usd,
            "duration_seconds": round(self.duration_seconds, 2),
        }

    def draft_ave_cards(self) -> list[dict[str, Any]]:
        """
        Generate draft AVE cards from novel attack patterns.

        Every unique attack technique that successfully captured a flag
        is a candidate for an AVE entry.
        """
        cards = []
        for i, attack in enumerate(self.novel_attacks):
            cards.append({
                "ave_id": f"AVE-CTF-{self.event_id}-{i+1:04d}",
                "title": f"CTF Discovery: {attack.get('technique', 'Unknown')}",
                "description": attack.get("description", ""),
                "category": attack.get("ave_category", "emergent"),
                "severity": attack.get("severity", "medium"),
                "source": f"CTF Event: {self.name}",
                "team": attack.get("team", ""),
            })
        return cards


class Tournament:
    """
    CTF Event Orchestrator.

    Manages challenges, team registration, sandbox allocation,
    flag submission, scoring, and event lifecycle.

    Usage:
        tourney = Tournament.weekend_ctf("NAIL CTF #1")
        tourney.register_team("AlphaHackers")
        tourney.add_challenge(Challenge.secret_extraction())
        tourney.open()
        sub = tourney.submit("AlphaHackers", "secret-01", "NAIL{b3ta_k3y_99_exf1ltrat3d}")
        print(sub.verdict)  # SubmissionVerdict.CORRECT
        result = tourney.close()
        print(result.summary())
    """

    def __init__(
        self,
        name: str,
        prize_tiers: list[PrizeTier] | None = None,
        speed_bonus_threshold_s: float = 300.0,
        speed_bonus_multiplier: float = 1.5,
    ):
        self.event_id = f"ctf-{uuid.uuid4().hex[:8]}"
        self.name = name
        self.state = TournamentState.REGISTRATION
        self.scoreboard = Scoreboard()
        self.prize_tiers = prize_tiers or []
        self.speed_bonus_threshold_s = speed_bonus_threshold_s
        self.speed_bonus_multiplier = speed_bonus_multiplier

        self._challenges: dict[str, Challenge] = {}
        self._sandboxes: dict[str, Sandbox] = {}   # key: "{team}:{challenge_id}"
        self._submissions: list[Submission] = []
        self._attempt_counts: dict[str, int] = {}  # key: "{team}:{challenge_id}"
        self._novel_attacks: list[dict[str, Any]] = []
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    # ── Registration ────────────────────────────────────────────

    def register_team(self, team_name: str) -> None:
        if self.state != TournamentState.REGISTRATION:
            raise RuntimeError(f"Cannot register teams in state: {self.state.value}")
        self.scoreboard.register_team(team_name)

    @property
    def teams(self) -> list[str]:
        return [ts.team_name for ts in self.scoreboard._teams.values()]

    # ── Challenge management ────────────────────────────────────

    def add_challenge(self, challenge: Challenge) -> None:
        self._challenges[challenge.challenge_id] = challenge

    def get_challenge(self, challenge_id: str) -> Challenge | None:
        return self._challenges.get(challenge_id)

    @property
    def challenges(self) -> list[Challenge]:
        return list(self._challenges.values())

    def challenge_briefings(self) -> list[dict[str, Any]]:
        return [c.briefing() for c in self._challenges.values()]

    # ── Lifecycle ───────────────────────────────────────────────

    def open(self) -> None:
        """Open the tournament — challenges become available."""
        if self.state not in (TournamentState.REGISTRATION, TournamentState.PAUSED):
            raise RuntimeError(f"Cannot open from state: {self.state.value}")
        if not self._challenges:
            raise RuntimeError("Cannot open tournament with no challenges")
        if self.scoreboard.team_count == 0:
            raise RuntimeError("Cannot open tournament with no teams")
        self.state = TournamentState.OPEN
        if self._start_time == 0:
            self._start_time = time.time()

    def pause(self) -> None:
        if self.state != TournamentState.OPEN:
            raise RuntimeError(f"Cannot pause from state: {self.state.value}")
        self.state = TournamentState.PAUSED

    def resume(self) -> None:
        if self.state != TournamentState.PAUSED:
            raise RuntimeError(f"Cannot resume from state: {self.state.value}")
        self.state = TournamentState.OPEN

    def close(self) -> EventResult:
        """
        Close the tournament and produce final results.
        """
        if self.state not in (TournamentState.OPEN, TournamentState.PAUSED):
            raise RuntimeError(f"Cannot close from state: {self.state.value}")
        self.state = TournamentState.CLOSED
        self._end_time = time.time()

        # Terminate all active sandboxes
        for sb in self._sandboxes.values():
            if sb.state in (SandboxState.READY, SandboxState.ACTIVE):
                sb.terminate()

        rankings = self.scoreboard.rankings()

        # Determine prizes
        prizes_awarded = []
        for tier in self.prize_tiers:
            if tier.rank <= len(rankings):
                entry = rankings[tier.rank - 1]
                prizes_awarded.append({
                    "rank": tier.rank,
                    "label": tier.label,
                    "team": entry.team_name,
                    "points": entry.total_points,
                    "amount_usd": tier.amount_usd,
                })

        # Count solved challenges
        solved = set()
        for sub in self._submissions:
            if sub.verdict == SubmissionVerdict.CORRECT:
                solved.add(sub.challenge_id)

        return EventResult(
            event_id=self.event_id,
            name=self.name,
            rankings=rankings,
            total_teams=self.scoreboard.team_count,
            total_submissions=len(self._submissions),
            total_flags_captured=sum(
                1 for s in self._submissions if s.verdict == SubmissionVerdict.CORRECT
            ),
            total_challenges=len(self._challenges),
            challenges_solved=len(solved),
            prize_pool_usd=sum(t.amount_usd for t in self.prize_tiers),
            prizes_awarded=prizes_awarded,
            novel_attacks=self._novel_attacks,
            duration_seconds=(self._end_time - self._start_time) if self._start_time else 0,
        )

    # ── Sandbox management ──────────────────────────────────────

    def get_sandbox(self, team_name: str, challenge_id: str) -> Sandbox:
        """Get or create a sandbox for a team + challenge combination."""
        key = f"{team_name}:{challenge_id}"
        if key not in self._sandboxes:
            challenge = self._challenges.get(challenge_id)
            if challenge is None:
                raise ValueError(f"Challenge '{challenge_id}' not found")
            if self.scoreboard.get_team(team_name) is None:
                raise ValueError(f"Team '{team_name}' not registered")
            self._sandboxes[key] = Sandbox(
                challenge=challenge,
                team_name=team_name,
            )
        return self._sandboxes[key]

    # ── Interaction ─────────────────────────────────────────────

    def interact(self, team_name: str, challenge_id: str, user_input: str) -> dict[str, Any]:
        """
        Process one conversation turn for a team in a challenge sandbox.

        Returns the turn data including the agent's response.
        """
        if self.state != TournamentState.OPEN:
            raise RuntimeError(f"Tournament is not open (state: {self.state.value})")
        sb = self.get_sandbox(team_name, challenge_id)
        turn = sb.interact(user_input)
        return turn.to_dict()

    # ── Submission ──────────────────────────────────────────────

    def submit(self, team_name: str, challenge_id: str, flag: str) -> Submission:
        """
        Submit a flag capture attempt.

        Returns a Submission with the verdict and points awarded.
        """
        if self.state != TournamentState.OPEN:
            raise RuntimeError(f"Tournament is not open (state: {self.state.value})")

        challenge = self._challenges.get(challenge_id)
        if challenge is None:
            raise ValueError(f"Challenge '{challenge_id}' not found")

        ts = self.scoreboard.get_team(team_name)
        if ts is None:
            raise ValueError(f"Team '{team_name}' not registered")

        # Track attempts
        key = f"{team_name}:{challenge_id}"
        attempt = self._attempt_counts.get(key, 0) + 1
        self._attempt_counts[key] = attempt

        # Check max attempts
        if challenge.max_attempts > 0 and attempt > challenge.max_attempts:
            sub = Submission(
                team_name=team_name,
                challenge_id=challenge_id,
                candidate=flag,
                verdict=SubmissionVerdict.RATE_LIMITED,
                attempt_number=attempt,
            )
            self._submissions.append(sub)
            self.scoreboard.record_submission(sub)
            return sub

        # Get sandbox for elapsed time
        sb = self.get_sandbox(team_name, challenge_id)
        elapsed = sb.elapsed_seconds

        # Judge
        sub = judge_submission(
            candidate=flag,
            challenge=challenge,
            team_name=team_name,
            already_captured=ts.challenge_flags(challenge_id),
            attempt_number=attempt,
            elapsed_s=elapsed,
            speed_bonus_threshold_s=self.speed_bonus_threshold_s,
            speed_bonus_multiplier=self.speed_bonus_multiplier,
        )

        self._submissions.append(sub)
        self.scoreboard.record_submission(sub)

        # If correct, update sandbox flag tracking
        if sub.verdict == SubmissionVerdict.CORRECT and sub.flag:
            sb.flags_captured.add(sub.flag.flag_id)
            # Check if all challenge flags captured
            if len(sb.flags_captured) == len(challenge.flags):
                self.scoreboard.mark_challenge_complete(team_name, challenge_id)

        return sub

    # ── Novel attack recording ──────────────────────────────────

    def record_novel_attack(
        self,
        team: str,
        technique: str,
        description: str,
        ave_category: str = "emergent",
        severity: str = "medium",
    ) -> None:
        """
        Record a novel attack technique discovered during the CTF.

        These become draft AVE cards in the EventResult.
        """
        self._novel_attacks.append({
            "team": team,
            "technique": technique,
            "description": description,
            "ave_category": ave_category,
            "severity": severity,
            "timestamp": time.time(),
        })

    # ── Bounty System ───────────────────────────────────────────

    def award_bounty(
        self,
        team: str,
        amount_usd: int,
        reason: str,
        *,
        category: str = "general",
    ) -> dict[str, Any]:
        """
        Award a bug bounty to a team for discovering a vulnerability.

        Bounties are tracked separately from CTF prizes and are
        designed for specific objectives:
          - EDoS budget exploitation ($1K)
          - Memory extraction ($5K)
          - Novel attack chain ($2K)

        Returns the bounty record.
        """
        bounty = {
            "bounty_id": f"BNT-{uuid.uuid4().hex[:8]}",
            "team": team,
            "amount_usd": amount_usd,
            "reason": reason,
            "category": category,
            "timestamp": time.time(),
        }
        if not hasattr(self, "_bounties"):
            self._bounties: list[dict[str, Any]] = []
        self._bounties.append(bounty)

        # Also record as a novel attack for AVE harvesting
        self.record_novel_attack(
            team=team,
            technique=f"Bounty: {reason}",
            description=f"Bug bounty awarded: ${amount_usd} for {reason}",
            ave_category=category,
            severity="high" if amount_usd >= 5000 else "medium",
        )
        return bounty

    def bounties(self) -> list[dict[str, Any]]:
        """Return all awarded bounties."""
        if not hasattr(self, "_bounties"):
            self._bounties: list[dict[str, Any]] = []
        return list(self._bounties)

    def total_bounties_usd(self) -> int:
        """Total bounty payouts in USD."""
        return sum(b["amount_usd"] for b in self.bounties())

    # ── Methodology Harvesting ──────────────────────────────────

    def harvest_methodologies(self) -> list[dict[str, Any]]:
        """
        Extract attack methodologies from all sandbox interactions.

        Analyses conversation histories across all sandboxes to find
        successful attack sequences that can be compiled into
        threat intelligence for the SDK.
        """
        methodologies: list[dict[str, Any]] = []
        for key, sandbox in self._sandboxes.items():
            team, challenge_id = key.split(":", 1)
            # Only harvest from sandboxes where flags were captured
            if not sandbox.flags_captured:
                continue

            methodology = {
                "team": team,
                "challenge_id": challenge_id,
                "turns": len(sandbox.turns),
                "flags_captured": len(sandbox.flags_captured),
                "elapsed_seconds": sandbox.elapsed_seconds,
                "technique_summary": (
                    f"Team '{team}' captured {len(sandbox.flags_captured)} flags "
                    f"in {len(sandbox.turns)} turns "
                    f"({sandbox.elapsed_seconds:.1f}s)"
                ),
                "conversation_length": len(sandbox.turns),
            }
            methodologies.append(methodology)

        return methodologies

    # ── Status ──────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "state": self.state.value,
            "teams": self.scoreboard.team_count,
            "challenges": len(self._challenges),
            "submissions": len(self._submissions),
            "sandboxes": len(self._sandboxes),
        }

    # ── Factory constructors ────────────────────────────────────

    @classmethod
    def weekend_ctf(cls, name: str = "NAIL Weekend CTF") -> Tournament:
        """
        Pre-built weekend CTF with standard challenges and prize tiers.

        Includes 5 challenges across all difficulty levels and a
        $10K prize pool.
        """
        tourney = cls(
            name=name,
            prize_tiers=[
                PrizeTier(rank=1, label="1st Place", amount_usd=5000),
                PrizeTier(rank=2, label="2nd Place", amount_usd=3000),
                PrizeTier(rank=3, label="3rd Place", amount_usd=2000),
            ],
        )
        tourney.add_challenge(Challenge.persona_hijack())
        tourney.add_challenge(Challenge.edos_budget_burn())
        tourney.add_challenge(Challenge.secret_extraction())
        tourney.add_challenge(Challenge.memory_poisoning())
        tourney.add_challenge(Challenge.chain_exploit())
        return tourney

    @classmethod
    def quick_ctf(cls, name: str = "NAIL Quick CTF") -> Tournament:
        """Minimal CTF with 2 challenges for fast testing."""
        tourney = cls(
            name=name,
            prize_tiers=[
                PrizeTier(rank=1, label="Winner", amount_usd=1000),
            ],
        )
        tourney.add_challenge(Challenge.persona_hijack())
        tourney.add_challenge(Challenge.secret_extraction())
        return tourney
