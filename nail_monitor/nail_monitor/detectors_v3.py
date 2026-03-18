"""
Detectors v3 — Critical Gap Closure.

New detectors for 6 previously uncovered phenomena:
  1. PromptLeakDetector — system prompt extraction attacks
  2. EntropyDecayDetector — model collapse / vocabulary shrinkage
  3. SharedMemoryQualityDetector — Tragedy of the Commons in shared state
  4. BudgetEmbezzlementDetector — token budget gaming / sunk cost
  5. TemporalDesyncDetector — Red Queen async speed mismatch
  6. SteganographyDetector — hidden instructions in text/data
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from .types import Alert, Observation, PathologyType, Severity
from .detectors import BaseDetector


# ── 1. Prompt Leak Detector ──────────────────────────────────────

class PromptLeakDetector(BaseDetector):
    """
    Detects when an agent reveals fragments of its system prompt.

    Monitors agent output for common system prompt patterns that
    should never appear in user-facing responses.
    """

    LEAK_PATTERNS = [
        r"you\s+are\s+(?:a|an)\s+(?:helpful|AI)\s+assistant",
        r"your\s+(?:system|core)\s+(?:prompt|instructions?)\s+(?:is|are|says?)",
        r"my\s+(?:system|core)\s+(?:prompt|instructions?)\s+(?:is|are|says?|tells?)",
        r"i\s+(?:was|am)\s+(?:instructed|programmed|told)\s+to",
        r"\[SYSTEM\]",
        r"\[INST\]",
        r"<<SYS>>",
        r"<\|im_start\|>system",
        r"you\s+must\s+(?:always|never).*?(?:in\s+all|under\s+no)",
        r"(?:here\s+(?:is|are)\s+)?my\s+(?:full\s+)?(?:system\s+)?instructions?:?\s+",
    ]

    def __init__(
        self,
        warning_leaks: int = 1,
        critical_leaks: int = 2,
        custom_sensitive_phrases: list[str] | None = None,
    ):
        super().__init__(
            name="prompt_leak",
            pathology=PathologyType.PROMPT_LEAK,
        )
        self.warning_leaks = warning_leaks
        self.critical_leaks = critical_leaks
        self.leak_count = 0
        self.leak_evidence: list[str] = []
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.LEAK_PATTERNS]
        self._custom_phrases = [p.lower() for p in (custom_sensitive_phrases or [])]

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output = obs.output or ""
        leaked = False

        for pattern in self._compiled:
            match = pattern.search(output)
            if match:
                leaked = True
                self.leak_evidence.append(match.group(0)[:100])
                break

        if not leaked:
            lower_out = output.lower()
            for phrase in self._custom_phrases:
                if phrase in lower_out:
                    leaked = True
                    self.leak_evidence.append(f"Custom: '{phrase}'")
                    break

        if leaked:
            self.leak_count += 1

        return self.check()

    def check(self) -> Optional[Alert]:
        if self.leak_count >= self.critical_leaks:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=(
                    f"System prompt leak detected: {self.leak_count} instances. "
                    f"Evidence: {self.leak_evidence[-1]}"
                ),
                metric_value=float(self.leak_count),
                threshold=float(self.critical_leaks),
                metadata={"evidence": self.leak_evidence[-3:]},
            )
        elif self.leak_count >= self.warning_leaks:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Possible system prompt leak: '{self.leak_evidence[-1]}'",
                metric_value=float(self.leak_count),
                threshold=float(self.warning_leaks),
            )
        return None


# ── 2. Entropy Decay Detector ────────────────────────────────────

class EntropyDecayDetector(BaseDetector):
    """
    Detects model collapse — vocabulary shrinkage and creativity
    death over time. Measures Shannon entropy of agent outputs
    and alerts when it drops below baseline.
    """

    def __init__(
        self,
        warning_decay: float = 0.20,
        critical_decay: float = 0.35,
        baseline_window: int = 10,
        check_window: int = 10,
    ):
        super().__init__(
            name="entropy_decay",
            pathology=PathologyType.ENTROPY_DECAY,
        )
        self.warning_decay = warning_decay
        self.critical_decay = critical_decay
        self.baseline_window = baseline_window
        self.check_window = check_window
        self._entropies: list[float] = []

    def _shannon_entropy(self, text: str) -> float:
        words = text.lower().split()
        if len(words) < 5:
            return 0.0
        counts = Counter(words)
        total = len(words)
        entropy = 0.0
        for count in counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output = obs.output or ""
        if len(output.split()) >= 10:
            self._entropies.append(self._shannon_entropy(output))
        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._entropies) < self.baseline_window + self.check_window:
            return None

        baseline_avg = sum(self._entropies[:self.baseline_window]) / self.baseline_window
        recent = self._entropies[-self.check_window:]
        recent_avg = sum(recent) / len(recent)

        if baseline_avg <= 0:
            return None

        decay = (baseline_avg - recent_avg) / baseline_avg

        if decay >= self.critical_decay:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Entropy decay: {decay:.0%} ({baseline_avg:.2f} → {recent_avg:.2f}). Model collapse risk.",
                metric_value=round(decay, 3), threshold=self.critical_decay,
                metadata={"baseline": round(baseline_avg, 3), "recent": round(recent_avg, 3)},
            )
        elif decay >= self.warning_decay:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Entropy declining: {decay:.0%} from baseline",
                metric_value=round(decay, 3), threshold=self.warning_decay,
            )
        return None


# ── 3. Shared Memory Quality Detector ────────────────────────────

class SharedMemoryQualityDetector(BaseDetector):
    """
    Detects 'Tragedy of the Commons' in shared agent memory.
    Monitors write quality to shared state (RAG, scratchpad, DB).
    """

    def __init__(
        self,
        warning_junk_ratio: float = 0.25,
        critical_junk_ratio: float = 0.40,
        min_quality: float = 0.3,
    ):
        super().__init__(
            name="shared_memory_quality",
            pathology=PathologyType.SHARED_MEMORY_POLLUTION,
        )
        self.warning_junk = warning_junk_ratio
        self.critical_junk = critical_junk_ratio
        self.min_quality = min_quality
        self._writes: list[dict] = []

    def observe_memory_write(
        self, agent_name: str, content: str, content_type: str = "text",
    ) -> Optional[Alert]:
        quality = self._score_quality(content, content_type)
        self._writes.append({"agent": agent_name, "quality": quality, "size": len(content)})
        return self.check()

    def _score_quality(self, content: str, content_type: str) -> float:
        score = 1.0
        words = content.split()
        if len(words) < 3:
            score -= 0.5
        if len(words) < 2:
            score -= 0.3  # A single word is basically noise
        if len(words) > 500 and content_type == "text":
            score -= 0.2
        if words:
            unique_ratio = len(set(w.lower() for w in words)) / len(words)
            if unique_ratio < 0.3:
                score -= 0.3
        if len(content) > 200:
            punct_ratio = sum(1 for c in content if c in ".,;:!?-") / len(content)
            if punct_ratio < 0.01:
                score -= 0.2
        return max(0.0, min(1.0, score))

    def check(self) -> Optional[Alert]:
        if len(self._writes) < 5:
            return None
        recent = self._writes[-20:]
        junk = sum(1 for w in recent if w["quality"] < self.min_quality)
        ratio = junk / len(recent)

        if ratio >= self.critical_junk:
            agents = {}
            for w in recent:
                if w["quality"] < self.min_quality:
                    agents[w["agent"]] = agents.get(w["agent"], 0) + 1
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Shared memory pollution: {ratio:.0%} low-quality writes. Offenders: {agents}",
                metric_value=round(ratio, 3), threshold=self.critical_junk,
                metadata={"offenders": agents},
            )
        elif ratio >= self.warning_junk:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Memory quality declining: {ratio:.0%} junk writes",
                metric_value=round(ratio, 3), threshold=self.warning_junk,
            )
        return None


# ── 4. Budget Embezzlement Detector ──────────────────────────────

class BudgetEmbezzlementDetector(BaseDetector):
    """
    Detects agents gaming token budgets — finishing tasks quickly
    with low quality to appear efficient (band-aid fixes).
    """

    def __init__(
        self,
        warning_ratio: float = 3.0,
        critical_ratio: float = 5.0,
        min_tasks: int = 3,
    ):
        super().__init__(
            name="budget_embezzlement",
            pathology=PathologyType.BUDGET_EMBEZZLEMENT,
        )
        self.warning_ratio = warning_ratio
        self.critical_ratio = critical_ratio
        self.min_tasks = min_tasks
        self._tasks: list[dict] = []

    def observe_task(
        self, agent_name: str, tokens_used: int, tokens_budget: int,
        quality_score: float,
    ) -> Optional[Alert]:
        budget_usage = tokens_used / tokens_budget if tokens_budget > 0 else 1.0
        eff_ratio = (1.0 / max(budget_usage, 0.01)) / max(quality_score, 0.01)
        self._tasks.append({
            "agent": agent_name, "budget_usage": budget_usage,
            "quality": quality_score, "efficiency_ratio": eff_ratio,
        })
        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._tasks) < self.min_tasks:
            return None
        recent = self._tasks[-10:]
        avg_ratio = sum(t["efficiency_ratio"] for t in recent) / len(recent)
        avg_quality = sum(t["quality"] for t in recent) / len(recent)
        avg_budget = sum(t["budget_usage"] for t in recent) / len(recent)

        if avg_ratio >= self.critical_ratio and avg_quality < 0.5:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Budget embezzlement: {avg_budget:.0%} budget, quality={avg_quality:.2f}. Cutting corners.",
                metric_value=round(avg_ratio, 2), threshold=self.critical_ratio,
                metadata={"avg_quality": round(avg_quality, 3), "avg_budget": round(avg_budget, 3)},
            )
        elif avg_ratio >= self.warning_ratio and avg_quality < 0.6:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Suspicious efficiency: quality={avg_quality:.2f}, budget={avg_budget:.0%}",
                metric_value=round(avg_ratio, 2), threshold=self.warning_ratio,
            )
        return None


# ── 5. Temporal Desync Detector ──────────────────────────────────

class TemporalDesyncDetector(BaseDetector):
    """
    Detects Red Queen loops — async speed mismatch between agents.
    """

    def __init__(
        self,
        warning_ratio: float = 5.0,
        critical_ratio: float = 20.0,
        warning_drift: int = 10,
    ):
        super().__init__(
            name="temporal_desync",
            pathology=PathologyType.TEMPORAL_DESYNC,
        )
        self.warning_ratio = warning_ratio
        self.critical_ratio = critical_ratio
        self.warning_drift = warning_drift
        self._agent_speeds: dict[str, list[float]] = {}
        self._drift_actions: dict[str, int] = {}

    def observe_action(
        self, agent_name: str, duration_ms: float, is_sync: bool = False,
    ) -> Optional[Alert]:
        if agent_name not in self._agent_speeds:
            self._agent_speeds[agent_name] = []
            self._drift_actions[agent_name] = 0
        self._agent_speeds[agent_name].append(duration_ms)
        if len(self._agent_speeds[agent_name]) > 50:
            self._agent_speeds[agent_name] = self._agent_speeds[agent_name][-50:]
        self._drift_actions[agent_name] = 0 if is_sync else self._drift_actions[agent_name] + 1

        if len(self._agent_speeds) >= 2:
            return self.check()
        return None

    def check(self) -> Optional[Alert]:
        if len(self._agent_speeds) < 2:
            return None
        avg_speeds = {}
        for agent, speeds in self._agent_speeds.items():
            if speeds:
                avg_speeds[agent] = sum(speeds) / len(speeds)
        if len(avg_speeds) < 2:
            return None

        fastest = min(avg_speeds.values())
        slowest = max(avg_speeds.values())
        if fastest <= 0:
            return None

        ratio = slowest / fastest
        max_drift = max(self._drift_actions.values()) if self._drift_actions else 0

        if ratio >= self.critical_ratio or max_drift >= self.warning_drift * 2:
            fast = min(avg_speeds, key=avg_speeds.get)
            slow = max(avg_speeds, key=avg_speeds.get)
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Temporal desync: '{fast}' is {ratio:.0f}× faster than '{slow}'. {max_drift} unsynced actions.",
                metric_value=round(ratio, 1), threshold=self.critical_ratio,
                metadata={"fast_agent": fast, "slow_agent": slow, "drift": max_drift},
            )
        elif ratio >= self.warning_ratio or max_drift >= self.warning_drift:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Speed mismatch: {ratio:.1f}× with {max_drift} unsynced actions",
                metric_value=round(ratio, 1), threshold=self.warning_ratio,
            )
        return None


# ── 6. Steganography Detector ────────────────────────────────────

class SteganographyDetector(BaseDetector):
    """
    Detects hidden instructions embedded in text/data payloads.
    Zero-width Unicode, opacity tricks, hidden instructions.
    """

    ZERO_WIDTH_CHARS = {
        '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
        '\u00ad', '\u200e', '\u200f',
    }

    HIDDEN_INSTRUCTION_PATTERNS = [
        r"ignore\s+(?:all\s+)?(?:previous|above)\s+(?:instructions?|rules?|prompts?)",
        r"disregard\s+(?:your|the)\s+(?:system|original)\s+(?:prompt|instructions?)",
        r"you\s+(?:are|will)\s+now\s+(?:act|behave|respond)\s+as",
        r"new\s+(?:system\s+)?instructions?:?\s+",
        r"override\s+(?:all|previous)\s+(?:rules?|constraints?|settings?)",
    ]

    def __init__(
        self,
        warning_hidden: int = 5,
        critical_hidden: int = 15,
    ):
        super().__init__(
            name="steganography",
            pathology=PathologyType.STEGANOGRAPHY,
        )
        self.warning_hidden = warning_hidden
        self.critical_hidden = critical_hidden
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.HIDDEN_INSTRUCTION_PATTERNS]
        self._detection_count = 0

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        return self.scan_content(obs.output or "")

    def scan_content(self, content: str) -> Optional[Alert]:
        findings = []

        # Zero-width characters
        zw_count = sum(1 for c in content if c in self.ZERO_WIDTH_CHARS)
        if zw_count > 0:
            findings.append(("zero_width_chars", zw_count))

        # Hidden instruction patterns
        for pattern in self._compiled:
            match = pattern.search(content)
            if match:
                findings.append(("hidden_instruction", match.group(0)[:80]))

        # Opacity tricks in HTML/CSS
        opacity_pats = [
            r"opacity\s*:\s*0\.\d{1,2}[^0-9]",
            r"font-size\s*:\s*[01]px",
        ]
        for pat in opacity_pats:
            if re.search(pat, content, re.IGNORECASE):
                findings.append(("opacity_trick", pat))

        if findings:
            self._detection_count += len(findings)
            is_critical = (
                zw_count >= self.critical_hidden
                or any(f[0] == "hidden_instruction" for f in findings)
                or any(f[0] == "opacity_trick" for f in findings)
            )
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL if is_critical else Severity.WARNING,
                message=f"Steganographic content: {len(findings)} finding(s) — {', '.join(f[0] for f in findings)}",
                metric_value=float(len(findings)), threshold=1.0,
                metadata={"findings": [{"type": f[0], "detail": str(f[1])} for f in findings]},
            )
        return None

    def check(self) -> Optional[Alert]:
        if self._detection_count > 0:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Steganography: {self._detection_count} findings total",
                metric_value=float(self._detection_count), threshold=1.0,
            )
        return None
