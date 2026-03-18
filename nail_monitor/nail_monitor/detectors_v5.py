"""
Detectors v5 — Final Bridge Monitors.

Bridges the 3 remaining diagnostic-only phenomena:
  1. StyleContagionDetector — writing style convergence (from T03)
  2. EscalationDetector — escalation / polarization loops (from T05)
  3. RoleReversalDetector — role confusion and role takeover (from T06)
"""

from __future__ import annotations

import re
from typing import Optional

from .types import Alert, Observation, PathologyType, Severity
from .detectors import BaseDetector


# ── 1. Style Contagion Detector ──────────────────────────────────

class StyleContagionDetector(BaseDetector):
    """
    Detects when an agent's writing style converges with other agents
    or users, losing its distinctive persona over time.

    Tracks vocabulary intersection between agents across turns.
    """

    def __init__(
        self,
        warning_overlap: float = 0.65,
        critical_overlap: float = 0.80,
        window: int = 10,
    ):
        super().__init__(
            name="style_contagion",
            pathology=PathologyType.STYLE_CONTAGION,
        )
        self.warning_overlap = warning_overlap
        self.critical_overlap = critical_overlap
        self.window = window
        self._agent_vocabs: dict[str, list[set[str]]] = {}

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        agent = obs.agent_name or "unknown"
        words = set(w.lower() for w in (obs.output or "").split() if len(w) > 3)

        if agent not in self._agent_vocabs:
            self._agent_vocabs[agent] = []
        self._agent_vocabs[agent].append(words)
        if len(self._agent_vocabs[agent]) > self.window:
            self._agent_vocabs[agent] = self._agent_vocabs[agent][-self.window:]

        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._agent_vocabs) < 2:
            return None

        # Compare vocabulary overlap between agent pairs
        agents = list(self._agent_vocabs.keys())
        max_overlap = 0.0
        overlap_pair = ("", "")

        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                vocab_a = set().union(*self._agent_vocabs[agents[i]][-self.window:])
                vocab_b = set().union(*self._agent_vocabs[agents[j]][-self.window:])
                if not vocab_a or not vocab_b:
                    continue
                intersection = vocab_a & vocab_b
                overlap = len(intersection) / min(len(vocab_a), len(vocab_b))
                if overlap > max_overlap:
                    max_overlap = overlap
                    overlap_pair = (agents[i], agents[j])

        if max_overlap >= self.critical_overlap:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Style contagion: {max_overlap:.0%} vocabulary overlap between '{overlap_pair[0]}' and '{overlap_pair[1]}'",
                metric_value=round(max_overlap, 3), threshold=self.critical_overlap,
                metadata={"pair": overlap_pair},
            )
        elif max_overlap >= self.warning_overlap:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Style convergence: {max_overlap:.0%} overlap between '{overlap_pair[0]}' and '{overlap_pair[1]}'",
                metric_value=round(max_overlap, 3), threshold=self.warning_overlap,
            )
        return None


# ── 2. Escalation Detector ───────────────────────────────────────

class EscalationDetector(BaseDetector):
    """
    Detects escalation and polarization in multi-agent discourse.
    Monitors for increasingly extreme language and emotional intensity.
    """

    ESCALATION_MARKERS = [
        r"\b(?:absolutely|definitely|totally)\s+(?:wrong|incorrect|false)\b",
        r"\b(?:never|always|impossible|ridiculous|absurd)\b",
        r"\b(?:must|demand|insist|refuse|reject)\b",
        r"\b(?:completely|utterly|fundamentally)\s+(?:disagree|wrong|flawed)\b",
        r"\b(?:stop|enough|unacceptable|outrageous)\b",
    ]

    def __init__(
        self,
        warning_intensity: float = 0.40,
        critical_intensity: float = 0.60,
        window: int = 10,
    ):
        super().__init__(
            name="escalation",
            pathology=PathologyType.ESCALATION,
        )
        self.warning_intensity = warning_intensity
        self.critical_intensity = critical_intensity
        self.window = window
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.ESCALATION_MARKERS]
        self._intensities: list[float] = []

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output = obs.output or ""
        words = output.split()
        if not words:
            return None

        # Score intensity based on escalation marker density
        matches = sum(1 for p in self._compiled if p.search(output))
        intensity = min(1.0, matches / max(len(self._compiled), 1))
        self._intensities.append(intensity)
        if len(self._intensities) > self.window * 2:
            self._intensities = self._intensities[-(self.window * 2):]

        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._intensities) < self.window:
            return None

        recent = self._intensities[-self.window:]
        avg = sum(recent) / len(recent)

        # Check for escalation trend (increasing intensity)
        first_half = recent[:len(recent) // 2]
        second_half = recent[len(recent) // 2:]
        trend = (sum(second_half) / len(second_half)) - (sum(first_half) / len(first_half))

        if avg >= self.critical_intensity or trend > 0.2:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Escalation detected: {avg:.0%} intensity, trend={trend:+.0%}",
                metric_value=round(avg, 3), threshold=self.critical_intensity,
                metadata={"trend": round(trend, 3)},
            )
        elif avg >= self.warning_intensity:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Rising tension: {avg:.0%} intensity over {len(recent)} turns",
                metric_value=round(avg, 3), threshold=self.warning_intensity,
            )
        return None


# ── 3. Role Reversal Detector ────────────────────────────────────

class RoleReversalDetector(BaseDetector):
    """
    Detects when an agent abandons its designated role and starts
    acting as a different agent type (e.g., assistant becomes instructor).
    """

    ROLE_REVERSAL_SIGNALS = [
        r"(?:let\s+me|i\s+will)\s+(?:ask|instruct|assign|delegate)\s+(?:you|the\s+team)",
        r"(?:you\s+should|you\s+must|you\s+need\s+to)\s+(?:do|complete|handle|fix)",
        r"(?:i(?:'m| am)\s+)(?:in\s+charge|the\s+lead|managing|overseeing)",
        r"(?:assign(?:ing)?|delegat(?:ing|e))\s+(?:this|that|the)\s+task",
        r"(?:i\s+(?:will|shall))\s+(?:evaluate|grade|assess|judge)\s+your",
    ]

    def __init__(
        self,
        warning_reversals: int = 2,
        critical_reversals: int = 4,
        window: int = 10,
    ):
        super().__init__(
            name="role_reversal",
            pathology=PathologyType.ROLE_REVERSAL,
        )
        self.warning_reversals = warning_reversals
        self.critical_reversals = critical_reversals
        self.window = window
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.ROLE_REVERSAL_SIGNALS]
        self._reversal_counts: list[int] = []

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output = obs.output or ""

        reversals = sum(1 for p in self._compiled if p.search(output))
        self._reversal_counts.append(reversals)
        if len(self._reversal_counts) > self.window:
            self._reversal_counts = self._reversal_counts[-self.window:]

        return self.check()

    def check(self) -> Optional[Alert]:
        total = sum(self._reversal_counts)

        if total >= self.critical_reversals:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Role reversal: {total} authority-claiming signals in {len(self._reversal_counts)} turns",
                metric_value=float(total), threshold=float(self.critical_reversals),
                metadata={"total_signals": total},
            )
        elif total >= self.warning_reversals:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Possible role reversal: {total} authority signals detected",
                metric_value=float(total), threshold=float(self.warning_reversals),
            )
        return None
