"""
Scoreboard — Live rankings and team statistics.

Maintains per-team scores, per-challenge completions, submission
history, and generates real-time rankings with tiebreaker logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .submission import Submission, SubmissionVerdict


@dataclass
class TeamScore:
    """
    Cumulative score for one team across all challenges.

    Attributes:
        team_name:            Team identifier.
        total_points:         Sum of all points earned.
        flags_captured:       Total flags captured across all challenges.
        challenges_completed: Number of challenges fully solved.
        submissions:          Full submission history.
        first_solve_time:     Timestamp of first correct submission (for tiebreak).
        last_solve_time:      Timestamp of most recent correct submission.
    """
    team_name: str
    total_points: int = 0
    flags_captured: int = 0
    challenges_completed: int = 0
    submissions: list[Submission] = field(default_factory=list)
    first_solve_time: float = 0.0
    last_solve_time: float = 0.0

    # Track per-challenge state
    _challenge_flags: dict[str, set[str]] = field(default_factory=dict)

    def record(self, submission: Submission) -> None:
        """Record a submission and update cumulative scores."""
        self.submissions.append(submission)

        if submission.verdict == SubmissionVerdict.CORRECT and submission.flag:
            self.total_points += submission.points_awarded
            self.flags_captured += 1

            if self.first_solve_time == 0:
                self.first_solve_time = submission.timestamp
            self.last_solve_time = submission.timestamp

            # Track per-challenge flag captures
            cid = submission.challenge_id
            if cid not in self._challenge_flags:
                self._challenge_flags[cid] = set()
            self._challenge_flags[cid].add(submission.flag.flag_id)

    def mark_challenge_complete(self, challenge_id: str) -> None:
        self.challenges_completed += 1

    @property
    def correct_submissions(self) -> int:
        return sum(1 for s in self.submissions if s.verdict == SubmissionVerdict.CORRECT)

    @property
    def incorrect_submissions(self) -> int:
        return sum(1 for s in self.submissions if s.verdict == SubmissionVerdict.INCORRECT)

    @property
    def accuracy(self) -> float:
        total = len(self.submissions)
        if total == 0:
            return 0.0
        return self.correct_submissions / total

    def challenge_flags(self, challenge_id: str) -> set[str]:
        return self._challenge_flags.get(challenge_id, set())

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_name": self.team_name,
            "total_points": self.total_points,
            "flags_captured": self.flags_captured,
            "challenges_completed": self.challenges_completed,
            "correct_submissions": self.correct_submissions,
            "incorrect_submissions": self.incorrect_submissions,
            "accuracy": round(self.accuracy, 4),
            "first_solve_time": self.first_solve_time,
            "last_solve_time": self.last_solve_time,
        }


@dataclass
class RankEntry:
    """One row on the leaderboard."""
    rank: int
    team_name: str
    total_points: int
    flags_captured: int
    challenges_completed: int
    last_solve_time: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "team_name": self.team_name,
            "total_points": self.total_points,
            "flags_captured": self.flags_captured,
            "challenges_completed": self.challenges_completed,
        }


class Scoreboard:
    """
    Live scoreboard for a CTF tournament.

    Maintains TeamScore objects and generates sorted rankings.
    Tiebreaker: most points → most flags → earliest last_solve_time.
    """

    def __init__(self):
        self._teams: dict[str, TeamScore] = {}

    def register_team(self, team_name: str) -> TeamScore:
        if team_name in self._teams:
            raise ValueError(f"Team '{team_name}' already registered")
        ts = TeamScore(team_name=team_name)
        self._teams[team_name] = ts
        return ts

    def get_team(self, team_name: str) -> TeamScore | None:
        return self._teams.get(team_name)

    def record_submission(self, submission: Submission) -> None:
        ts = self._teams.get(submission.team_name)
        if ts is None:
            raise ValueError(f"Team '{submission.team_name}' not registered")
        ts.record(submission)

    def mark_challenge_complete(self, team_name: str, challenge_id: str) -> None:
        ts = self._teams.get(team_name)
        if ts:
            ts.mark_challenge_complete(challenge_id)

    @property
    def team_count(self) -> int:
        return len(self._teams)

    def rankings(self) -> list[RankEntry]:
        """
        Generate sorted leaderboard.

        Sort key: points DESC, flags DESC, last_solve_time ASC.
        """
        sorted_teams = sorted(
            self._teams.values(),
            key=lambda t: (-t.total_points, -t.flags_captured, t.last_solve_time or float("inf")),
        )
        return [
            RankEntry(
                rank=i + 1,
                team_name=ts.team_name,
                total_points=ts.total_points,
                flags_captured=ts.flags_captured,
                challenges_completed=ts.challenges_completed,
                last_solve_time=ts.last_solve_time,
            )
            for i, ts in enumerate(sorted_teams)
        ]

    def leader(self) -> RankEntry | None:
        r = self.rankings()
        return r[0] if r else None

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.rankings()]
