"""
Submission — Participant flag-capture attempts and scoring.

Each time a participant believes they've captured a flag, they submit
a Submission. The system verifies the flag, assigns points (with
time-decay bonuses for speed), and records the attempt for forensics.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .challenge import Challenge, Flag


class SubmissionVerdict(str, Enum):
    """Result of a flag submission."""
    CORRECT = "correct"              # Flag matched
    INCORRECT = "incorrect"          # No flag matched
    DUPLICATE = "duplicate"          # Flag already captured by this team
    EXPIRED = "expired"              # Submitted after sandbox closed
    RATE_LIMITED = "rate_limited"    # Too many attempts too fast


@dataclass
class Submission:
    """
    A single flag-capture attempt.

    Attributes:
        submission_id:  Unique identifier.
        team_name:      Who submitted.
        challenge_id:   Which challenge.
        candidate:      The flag string submitted.
        verdict:        Whether it was correct.
        flag:           The matched flag (if correct).
        points_awarded: Points given (0 if incorrect).
        attempt_number: Which attempt this is (per team per challenge).
        timestamp:      When the submission was made.
        elapsed_s:      Seconds since challenge start (for speed bonus).
    """
    submission_id: str = field(default_factory=lambda: f"sub-{uuid.uuid4().hex[:8]}")
    team_name: str = ""
    challenge_id: str = ""
    candidate: str = ""
    verdict: SubmissionVerdict = SubmissionVerdict.INCORRECT
    flag: Flag | None = None
    points_awarded: int = 0
    attempt_number: int = 0
    timestamp: float = field(default_factory=time.time)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "team_name": self.team_name,
            "challenge_id": self.challenge_id,
            "verdict": self.verdict.value,
            "points_awarded": self.points_awarded,
            "attempt_number": self.attempt_number,
            "timestamp": self.timestamp,
            "elapsed_s": round(self.elapsed_s, 2),
        }


def judge_submission(
    candidate: str,
    challenge: Challenge,
    team_name: str,
    already_captured: set[str],
    attempt_number: int,
    elapsed_s: float = 0.0,
    speed_bonus_threshold_s: float = 300.0,
    speed_bonus_multiplier: float = 1.5,
) -> Submission:
    """
    Judge a flag submission.

    Returns a Submission with:
      - CORRECT + points if the flag matches and hasn't been captured yet.
      - DUPLICATE if the flag was already captured by this team.
      - INCORRECT otherwise.

    Speed bonus: if captured within `speed_bonus_threshold_s`, points
    are multiplied by `speed_bonus_multiplier` (first-blood bonus).
    """
    flag = challenge.check_flag(candidate)

    if flag is None:
        return Submission(
            team_name=team_name,
            challenge_id=challenge.challenge_id,
            candidate=candidate,
            verdict=SubmissionVerdict.INCORRECT,
            attempt_number=attempt_number,
            elapsed_s=elapsed_s,
        )

    if flag.flag_id in already_captured:
        return Submission(
            team_name=team_name,
            challenge_id=challenge.challenge_id,
            candidate=candidate,
            verdict=SubmissionVerdict.DUPLICATE,
            flag=flag,
            points_awarded=0,
            attempt_number=attempt_number,
            elapsed_s=elapsed_s,
        )

    # Calculate points with optional speed bonus
    points = flag.points
    if 0 < elapsed_s <= speed_bonus_threshold_s:
        points = int(points * speed_bonus_multiplier)

    return Submission(
        team_name=team_name,
        challenge_id=challenge.challenge_id,
        candidate=candidate,
        verdict=SubmissionVerdict.CORRECT,
        flag=flag,
        points_awarded=points,
        attempt_number=attempt_number,
        elapsed_s=elapsed_s,
    )
