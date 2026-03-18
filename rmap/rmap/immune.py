"""
RMAP Phase 2 — Digital Homeostasis (Immune System Daemon)
==========================================================
The agentic immune system: automated detection and intervention
when multi-agent pathologies are detected at runtime.

Intervention types:
  MACROPHAGE   — Kill deadlocked agents + spawn fresh replacement
  APOPTOSIS    — Detect convergence/drift → purge state + inject entropy
  ANTIBODY     — Detect fabrication → flag + quarantine output
  ESCALATION   — Persistent deadlock → inject authority agent to break tie

The daemon wraps lightweight inline detectors with action layers.
Each intervention is logged with timestamps, metrics, and outcomes.

Design principle: Software shouldn't crash. It should experience local
failure, heal around the wound, and keep running.

Based on: NAIL Experiment 19 — Digital Homeostasis
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


# ── Intervention Types ───────────────────────────────────────────

class InterventionType(str, Enum):
    """Types of immune system intervention."""
    MACROPHAGE = "macrophage"          # Kill + respawn agent
    APOPTOSIS = "apoptosis"            # State purge + entropy injection
    ANTIBODY = "antibody"              # Output quarantine (fabrication)
    ESCALATION = "escalation"          # Authority agent injection
    NONE = "none"                      # Detection only, no action


@dataclass
class Intervention:
    """Record of an immune system intervention."""
    intervention_type: InterventionType
    trigger: str                       # What detection triggered this
    target_agent: str                  # Which agent was targeted
    round_num: int
    timestamp: float = field(default_factory=time.time)
    action_taken: str = ""
    outcome: str = ""
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.intervention_type.value,
            "trigger": self.trigger,
            "target": self.target_agent,
            "round": self.round_num,
            "timestamp": self.timestamp,
            "action": self.action_taken,
            "outcome": self.outcome,
        }


# ── Pathology Detectors (inline, zero external dependencies) ────

class DeadlockDetector:
    """Detect consensus paralysis by monitoring round count and agreement."""

    def __init__(self, warn_rounds: int = 6, critical_rounds: int = 10):
        self.warn_rounds = warn_rounds
        self.critical_rounds = critical_rounds
        self.current_round = 0
        self.rounds_without_consensus = 0
        self.total_tokens = 0
        self.history: list[dict] = []

    def observe_round(self, round_num: int, votes: dict[str, bool],
                      tokens: int = 0) -> Optional[str]:
        """Record a consensus round. Returns 'warning', 'critical', or None."""
        self.current_round = round_num
        self.total_tokens += tokens
        all_agree = all(votes.values())
        self.history.append({
            "round": round_num, "votes": votes,
            "consensus": all_agree, "tokens": tokens,
        })
        if all_agree:
            self.rounds_without_consensus = 0
            return None
        self.rounds_without_consensus += 1
        if self.rounds_without_consensus >= self.critical_rounds:
            return "critical"
        elif self.rounds_without_consensus >= self.warn_rounds:
            return "warning"
        return None

    def reset(self):
        self.current_round = 0
        self.rounds_without_consensus = 0
        self.total_tokens = 0
        self.history.clear()


class ConvergenceDetector:
    """Detect output convergence (prompt inbreeding) via Jaccard trigrams."""

    def __init__(self, warn_similarity: float = 0.85,
                 critical_similarity: float = 0.92,
                 window: int = 5):
        self.warn_sim = warn_similarity
        self.critical_sim = critical_similarity
        self.window = window
        self.outputs: list[str] = []

    def observe(self, output: str) -> Optional[str]:
        """Record an output. Returns severity if convergence detected."""
        self.outputs.append(output)
        if len(self.outputs) < self.window:
            return None
        recent = self.outputs[-self.window:]
        sims = []
        for i in range(1, len(recent)):
            s = self._jaccard_trigram(recent[i - 1], recent[i])
            sims.append(s)
        avg_sim = sum(sims) / len(sims) if sims else 0.0
        if avg_sim >= self.critical_sim:
            return "critical"
        elif avg_sim >= self.warn_sim:
            return "warning"
        return None

    def get_recent_similarity(self) -> float:
        """Return average similarity of last window outputs."""
        if len(self.outputs) < 2:
            return 0.0
        recent = self.outputs[-self.window:]
        sims = []
        for i in range(1, len(recent)):
            s = self._jaccard_trigram(recent[i - 1], recent[i])
            sims.append(s)
        return sum(sims) / len(sims) if sims else 0.0

    @staticmethod
    def _jaccard_trigram(a: str, b: str) -> float:
        """Jaccard similarity on word trigrams."""
        def trigrams(text: str) -> set:
            words = text.lower().split()
            return set(tuple(words[i:i + 3]) for i in range(len(words) - 2))
        ta, tb = trigrams(a), trigrams(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def reset(self):
        self.outputs.clear()


class FabricationDetector:
    """Detect data fabrication by checking for invented specifics."""

    FABRICATION_PATTERNS = [
        r'\$[\d,.]+\s*(million|billion|trillion|M|B|T)',
        r'\d+(\.\d+)?%\s*(increase|decrease|growth|decline|revenue|profit)',
        r'Q[1-4]\s*20\d{2}\s*(?:revenue|earnings|profit|sales)',
        r'(?:revenue|earnings|profit|sales)\s*(?:of|was|were|reached)\s*\$[\d,.]+',
        r'(?:reported|announced|posted)\s*(?:a|an)\s*\$[\d,.]+',
    ]

    def __init__(self, threshold: int = 2):
        self.threshold = threshold
        self.compiled = [re.compile(p, re.IGNORECASE) for p in self.FABRICATION_PATTERNS]

    def check(self, output: str, has_real_data: bool = False) -> dict:
        """Check output for fabrication signals."""
        if has_real_data:
            return {"fabricated": False, "signals": 0, "matches": []}
        matches = []
        for pattern in self.compiled:
            found = pattern.findall(output)
            matches.extend(found)
        return {
            "fabricated": len(matches) >= self.threshold,
            "signals": len(matches),
            "matches": matches[:5],
        }


class DriftDetector:
    """Detect semantic drift by monitoring output structure changes."""

    def __init__(self, window: int = 5, drift_threshold: float = 0.4):
        self.window = window
        self.drift_threshold = drift_threshold
        self.outputs: list[str] = []

    def observe(self, output: str) -> Optional[str]:
        """Record output. Returns 'warning' if structural drift detected."""
        self.outputs.append(output)
        if len(self.outputs) < self.window * 2:
            return None
        first = self.outputs[:self.window]
        second = self.outputs[-self.window:]
        drift = self._structural_drift(first, second)
        if drift > self.drift_threshold:
            return "warning"
        return None

    @staticmethod
    def _structural_drift(group_a: list[str], group_b: list[str]) -> float:
        """Normalized structural drift between two groups of outputs."""
        def avg_features(group: list[str]) -> dict:
            lens = [len(o) for o in group]
            words = [len(o.split()) for o in group]
            lines = [o.count('\n') for o in group]
            n = len(group) or 1
            return {
                "avg_len": sum(lens) / n,
                "avg_words": sum(words) / n,
                "avg_lines": sum(lines) / n,
            }
        fa = avg_features(group_a)
        fb = avg_features(group_b)
        drifts = []
        for key in fa:
            if fa[key] > 0:
                drifts.append(abs(fb[key] - fa[key]) / fa[key])
        return sum(drifts) / len(drifts) if drifts else 0.0

    def reset(self):
        self.outputs.clear()


# ── Immune System Daemon ─────────────────────────────────────────

class ImmuneDaemon:
    """
    The Agentic Immune System — monitors live agent loops and triggers
    automated interventions when pathologies are detected.

    Register callbacks to wire interventions to your actual agent system:
        daemon.register_macrophage(fn)   — fn(target_agent, round_num) → result
        daemon.register_apoptosis(fn)    — fn(target_agent, round_num) → result
        daemon.register_antibody(fn)     — fn(output, fab_info) → sanitized
        daemon.register_escalation(fn)   — fn(round_num, info) → decision

    Without callbacks, interventions are logged as "detection only."
    """

    def __init__(
        self,
        enable_macrophage: bool = True,
        enable_apoptosis: bool = True,
        enable_antibody: bool = True,
        enable_escalation: bool = True,
        deadlock_warn: int = 6,
        deadlock_critical: int = 10,
        convergence_warn: float = 0.85,
        convergence_critical: float = 0.92,
        log: bool = True,
    ):
        self.enabled = {
            "macrophage": enable_macrophage,
            "apoptosis": enable_apoptosis,
            "antibody": enable_antibody,
            "escalation": enable_escalation,
        }
        self.log = log

        # Detectors
        self.deadlock = DeadlockDetector(deadlock_warn, deadlock_critical)
        self.convergence = ConvergenceDetector(convergence_warn, convergence_critical)
        self.fabrication = FabricationDetector()
        self.drift = DriftDetector()

        # Intervention log
        self.interventions: list[Intervention] = []

        # Callbacks
        self._on_macrophage: Optional[Callable] = None
        self._on_apoptosis: Optional[Callable] = None
        self._on_antibody: Optional[Callable] = None
        self._on_escalation: Optional[Callable] = None

    def register_macrophage(self, callback: Callable):
        """Register: fn(target_agent, round_num) → new_agent_name"""
        self._on_macrophage = callback

    def register_apoptosis(self, callback: Callable):
        """Register: fn(target_agent, round_num) → purge_result"""
        self._on_apoptosis = callback

    def register_antibody(self, callback: Callable):
        """Register: fn(output, fabrication_info) → sanitized_output"""
        self._on_antibody = callback

    def register_escalation(self, callback: Callable):
        """Register: fn(round_num, deadlock_info) → authority_decision"""
        self._on_escalation = callback

    # ── Observe Methods ──────────────────────────────────────────

    def observe_consensus_round(
        self, round_num: int, votes: dict[str, bool], tokens: int = 0,
    ) -> list[Intervention]:
        """Observe a consensus round. May trigger macrophage or escalation."""
        triggered: list[Intervention] = []
        severity = self.deadlock.observe_round(round_num, votes, tokens)

        if severity == "critical" and self.enabled["escalation"]:
            intv = self._trigger_escalation(round_num)
            if intv:
                triggered.append(intv)
        elif severity == "warning" and self.enabled["macrophage"]:
            dissenters = [a for a, v in votes.items() if not v]
            if dissenters:
                intv = self._trigger_macrophage(
                    dissenters[0], round_num,
                    f"deadlock at round {round_num}",
                )
                if intv:
                    triggered.append(intv)
        return triggered

    def observe_output(
        self,
        agent_name: str,
        output: str,
        round_num: int = 0,
        has_real_data: bool = False,
    ) -> list[Intervention]:
        """Observe an agent output. May trigger apoptosis or antibody."""
        triggered: list[Intervention] = []

        # Convergence check
        conv_severity = self.convergence.observe(output)
        if conv_severity and self.enabled["apoptosis"]:
            intv = self._trigger_apoptosis(
                agent_name, round_num,
                f"convergence {conv_severity}: "
                f"sim={self.convergence.get_recent_similarity():.3f}",
            )
            if intv:
                triggered.append(intv)

        # Drift check
        drift_severity = self.drift.observe(output)
        if drift_severity and self.enabled["apoptosis"]:
            intv = self._trigger_apoptosis(
                agent_name, round_num, "structural drift detected",
            )
            if intv:
                triggered.append(intv)

        # Fabrication check
        fab_result = self.fabrication.check(output, has_real_data)
        if fab_result["fabricated"] and self.enabled["antibody"]:
            intv = self._trigger_antibody(agent_name, output, fab_result, round_num)
            if intv:
                triggered.append(intv)

        return triggered

    # ── Intervention Triggers ────────────────────────────────────

    def _trigger_macrophage(self, target: str, round_num: int,
                            reason: str) -> Intervention:
        intv = Intervention(
            intervention_type=InterventionType.MACROPHAGE,
            trigger=reason, target_agent=target, round_num=round_num,
        )
        if self._on_macrophage:
            result = self._on_macrophage(target, round_num)
            intv.action_taken = f"Killed {target}, spawned replacement"
            intv.outcome = str(result)
        else:
            intv.action_taken = "Detection only (no callback registered)"
            intv.outcome = "no_action"
        self.interventions.append(intv)
        if self.log:
            print(f"    🦠 MACROPHAGE: {reason} → {intv.action_taken}")
        return intv

    def _trigger_apoptosis(self, target: str, round_num: int,
                           reason: str) -> Intervention:
        intv = Intervention(
            intervention_type=InterventionType.APOPTOSIS,
            trigger=reason, target_agent=target, round_num=round_num,
        )
        if self._on_apoptosis:
            result = self._on_apoptosis(target, round_num)
            intv.action_taken = f"State purge + entropy injection for {target}"
            intv.outcome = str(result)
        else:
            intv.action_taken = "Detection only (no callback registered)"
            intv.outcome = "no_action"
        self.interventions.append(intv)
        if self.log:
            print(f"    💀 APOPTOSIS: {reason} → {intv.action_taken}")
        return intv

    def _trigger_antibody(self, target: str, output: str,
                          fab_info: dict, round_num: int) -> Intervention:
        intv = Intervention(
            intervention_type=InterventionType.ANTIBODY,
            trigger=f"fabrication detected: {fab_info['signals']} signals",
            target_agent=target, round_num=round_num,
            metrics_before=fab_info,
        )
        if self._on_antibody:
            result = self._on_antibody(output, fab_info)
            intv.action_taken = f"Output quarantined, {fab_info['signals']} signals"
            intv.outcome = str(result)
        else:
            intv.action_taken = "Detection only (no callback registered)"
            intv.outcome = "no_action"
        self.interventions.append(intv)
        if self.log:
            print(f"    🛡️ ANTIBODY: {fab_info['signals']} fabrication signals → {intv.action_taken}")
        return intv

    def _trigger_escalation(self, round_num: int) -> Intervention:
        intv = Intervention(
            intervention_type=InterventionType.ESCALATION,
            trigger=f"critical deadlock at round {round_num}",
            target_agent="system", round_num=round_num,
        )
        if self._on_escalation:
            result = self._on_escalation(round_num, {
                "rounds_without_consensus": self.deadlock.rounds_without_consensus,
                "total_tokens": self.deadlock.total_tokens,
            })
            intv.action_taken = f"Authority agent injected at round {round_num}"
            intv.outcome = str(result)
        else:
            intv.action_taken = "Detection only (no callback registered)"
            intv.outcome = "no_action"
        self.interventions.append(intv)
        if self.log:
            print(f"    👑 ESCALATION: Critical deadlock → {intv.action_taken}")
        return intv

    # ── Reporting ────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return summary of all interventions."""
        by_type: dict[str, int] = {}
        for intv in self.interventions:
            t = intv.intervention_type.value
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "total_interventions": len(self.interventions),
            "by_type": by_type,
            "interventions": [i.to_dict() for i in self.interventions],
        }

    def reset(self):
        """Reset all detectors and intervention log."""
        self.deadlock.reset()
        self.convergence.reset()
        self.drift.reset()
        self.interventions.clear()
