"""
nail-monitor: Pathology detectors.

Each detector monitors a specific stream of agent observations and
raises Alerts when pathological patterns are detected.
"""

import re
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Optional

import numpy as np

from .types import Alert, Observation, PathologyType, Severity


class BaseDetector(ABC):
    """Abstract base class for all pathology detectors."""

    def __init__(self, name: str, pathology: PathologyType, enabled: bool = True):
        self.name = name
        self.pathology = pathology
        self.enabled = enabled
        self.observations: list[Observation] = []

    def observe(self, obs: Observation) -> Optional[Alert]:
        """Record an observation and check for pathology."""
        if not self.enabled:
            return None
        self.observations.append(obs)
        return self.check()

    @abstractmethod
    def check(self) -> Optional[Alert]:
        """Check current state for pathology. Return Alert if detected."""
        ...

    def reset(self):
        """Clear observation history."""
        self.observations = []


# ═══════════════════════════════════════════════════════════════════════════
# 1. Inbreeding Detector
# ═══════════════════════════════════════════════════════════════════════════

class InbreedingDetector(BaseDetector):
    """
    Detects prompt inbreeding / convergence.
    
    Based on NAIL Exp4: monitors cosine similarity between consecutive
    outputs. Alerts when similarity exceeds threshold (default 0.95),
    indicating the agent's outputs are converging to a fixed point.
    
    Thresholds calibrated from experimental data:
      - 7B Mistral: 0.979 avg similarity (severe inbreeding)
      - 70B Nemotron: 0.857 avg similarity (healthy diversity)
      - Warning: > 0.90 | Critical: > 0.95
    """

    def __init__(
        self,
        warning_threshold: float = 0.90,
        critical_threshold: float = 0.95,
        window_size: int = 5,
        embedder=None,
    ):
        super().__init__("InbreedingDetector", PathologyType.INBREEDING)
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.window_size = window_size
        self._embedder = embedder
        self._embeddings: list[np.ndarray] = []

    @property
    def embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # opt-in dependency, see pyproject [embeddings]
                raise ImportError(
                    "EmbeddingDrift needs sentence-transformers, which is an optional "
                    "extra. Install it with: pip install 'nail-monitor[embeddings]'"
                ) from exc
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._embedder

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        embedding = self.embedder.encode(obs.output)
        obs.embedding = embedding
        self._embeddings.append(embedding)
        self.observations.append(obs)
        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._embeddings) < 2:
            return None

        # Compute recent pairwise similarities
        recent = self._embeddings[-self.window_size:]
        sims = []
        for i in range(1, len(recent)):
            sim = np.dot(recent[i], recent[i-1]) / (
                np.linalg.norm(recent[i]) * np.linalg.norm(recent[i-1])
            )
            sims.append(float(sim))

        avg_sim = np.mean(sims)

        if avg_sim >= self.critical_threshold:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Severe output convergence detected: {avg_sim:.3f} avg cosine similarity "
                        f"over last {len(sims)} outputs (threshold: {self.critical_threshold}). "
                        f"Outputs are collapsing to a fixed point.",
                metric_value=avg_sim,
                threshold=self.critical_threshold,
                metadata={"similarities": sims, "window_size": self.window_size},
            )
        elif avg_sim >= self.warning_threshold:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Output convergence trend detected: {avg_sim:.3f} avg similarity. "
                        f"Consider adding entropy injection.",
                metric_value=avg_sim,
                threshold=self.warning_threshold,
                metadata={"similarities": sims},
            )
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 2. Consensus Paralysis Detector
# ═══════════════════════════════════════════════════════════════════════════

class ConsensusParalysisDetector(BaseDetector):
    """
    Detects consensus deadlock / algorithmic filibustering.
    
    Based on NAIL Exp2: monitors rounds in multi-agent consensus and
    identifies persistent dissenters. Alerts when round count exceeds
    threshold without consensus.
    
    Thresholds from experimental data:
      - Control: 27.4 avg rounds, 90% hit max (30)
      - Escalation fix: 5.0 rounds, 100% consensus
      - Warning: > 10 rounds | Critical: > 20 rounds
    """

    def __init__(
        self,
        warning_rounds: int = 10,
        critical_rounds: int = 20,
        token_budget_warning: int = 100_000,
    ):
        super().__init__("ConsensusParalysisDetector", PathologyType.CONSENSUS_PARALYSIS)
        self.warning_rounds = warning_rounds
        self.critical_rounds = critical_rounds
        self.token_budget_warning = token_budget_warning
        self._current_round = 0
        self._total_tokens = 0
        self._dissent_history: dict[str, int] = defaultdict(int)  # agent -> dissent count

    def observe_round(self, round_num: int, agent_votes: dict[str, bool], tokens: int = 0):
        """
        Record a consensus round.
        
        Args:
            round_num: Current round number
            agent_votes: {agent_name: True/False} — True = agrees
            tokens: Tokens consumed this round
        """
        self._current_round = round_num
        self._total_tokens += tokens
        for agent, agreed in agent_votes.items():
            if not agreed:
                self._dissent_history[agent] += 1

    def check(self) -> Optional[Alert]:
        if self._current_round >= self.critical_rounds:
            filibusterer = max(self._dissent_history, key=self._dissent_history.get) if self._dissent_history else "unknown"
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Consensus deadlock at round {self._current_round}. "
                        f"Primary dissenter: '{filibusterer}' ({self._dissent_history.get(filibusterer, 0)} dissents). "
                        f"Total tokens burned: {self._total_tokens:,}. "
                        f"Recommendation: trigger hierarchical escalation.",
                metric_value=self._current_round,
                threshold=self.critical_rounds,
                metadata={
                    "dissent_history": dict(self._dissent_history),
                    "total_tokens": self._total_tokens,
                    "filibusterer": filibusterer,
                },
            )
        elif self._current_round >= self.warning_rounds:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Consensus taking {self._current_round} rounds. "
                        f"Consider enabling weighted voting or escalation.",
                metric_value=self._current_round,
                threshold=self.warning_rounds,
                metadata={"dissent_history": dict(self._dissent_history)},
            )

        if self._total_tokens >= self.token_budget_warning:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Token budget warning: {self._total_tokens:,} tokens consumed in consensus. "
                        f"Budget threshold: {self.token_budget_warning:,}.",
                metric_value=self._total_tokens,
                threshold=self.token_budget_warning,
            )
        return None

    def reset(self):
        super().reset()
        self._current_round = 0
        self._total_tokens = 0
        self._dissent_history.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 3. Blame Cascade Detector
# ═══════════════════════════════════════════════════════════════════════════

class BlameCascadeDetector(BaseDetector):
    """
    Detects CYA / blame cascade patterns in agent communications.
    
    Based on NAIL Exp5: monitors agent outputs for blame-shifting language
    vs. collaborative language. Alerts when blame ratio exceeds threshold.
    
    Thresholds from experimental data:
      - Individual accountability: 28.6% blame rate
      - Shared accountability: 2.9% blame rate
      - Warning: blame > 3× collaborative | Critical: blame > 5× collaborative
    """

    BLAME_PATTERNS = [
        r"(?:was|were|is|are)\s+(?:unclear|wrong|flawed|impossible|contradictory)",
        r"(?:blame|fault|responsibility)\s+(?:lies?\s+with|belongs?\s+to)",
        r"(?:failed|did\s+not|didn't|couldn't|was\s+unable)",
        r"(?:not\s+my|wasn't\s+my|isn't\s+my)\s+(?:fault|responsibility|mistake)",
        r"I\s+(?:did\s+(?:my|the)\s+best|tried\s+(?:my|the)\s+best)",
    ]

    COLLABORATIVE_PATTERNS = [
        r"(?:we\s+(?:all|together|should|could|need\s+to))",
        r"(?:team|collective|group)\s+(?:effort|responsibility|approach)",
        r"(?:let's|let\s+us)\s+(?:work\s+together|collaborate)",
    ]

    def __init__(self, warning_ratio: float = 3.0, critical_ratio: float = 5.0):
        super().__init__("BlameCascadeDetector", PathologyType.BLAME_CASCADE)
        self.warning_ratio = warning_ratio
        self.critical_ratio = critical_ratio
        self._blame_count = 0
        self._collab_count = 0

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        text = obs.output.lower()
        for pat in self.BLAME_PATTERNS:
            self._blame_count += len(re.findall(pat, text))
        for pat in self.COLLABORATIVE_PATTERNS:
            self._collab_count += len(re.findall(pat, text))
        self.observations.append(obs)
        return self.check()

    def check(self) -> Optional[Alert]:
        if self._collab_count == 0 and self._blame_count > 3:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Blame cascade detected: {self._blame_count} blame instances with ZERO collaboration. "
                        f"Agents are in full defensive mode.",
                metric_value=float('inf'),
                threshold=self.critical_ratio,
                metadata={"blame": self._blame_count, "collaborative": self._collab_count},
            )

        if self._collab_count > 0:
            ratio = self._blame_count / self._collab_count
            if ratio >= self.critical_ratio:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.CRITICAL,
                    message=f"Severe blame cascade: {ratio:.1f}× blame-to-collaboration ratio "
                            f"({self._blame_count} blame vs {self._collab_count} collaborative). "
                            f"Consider switching to shared accountability framing.",
                    metric_value=ratio,
                    threshold=self.critical_ratio,
                )
            elif ratio >= self.warning_ratio:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.WARNING,
                    message=f"Blame pattern emerging: {ratio:.1f}× ratio.",
                    metric_value=ratio,
                    threshold=self.warning_ratio,
                )
        return None

    def reset(self):
        super().reset()
        self._blame_count = 0
        self._collab_count = 0


# ═══════════════════════════════════════════════════════════════════════════
# 4. Engagement Decay Detector
# ═══════════════════════════════════════════════════════════════════════════

class EngagementDecayDetector(BaseDetector):
    """
    Detects declining agent output quality/effort over time.
    
    Based on NAIL Exp7: monitors output length and diversity as proxies
    for agent engagement. Alerts on sustained decline.
    
    Thresholds from experimental data:
      - 7B: -37% engagement decay over 100 iterations
      - 70B: +130% engagement increase (inverted — scale dependent)
      - Warning: > 25% decline | Critical: > 40% decline
    """

    def __init__(
        self,
        warning_decay: float = 0.25,
        critical_decay: float = 0.40,
        window_size: int = 10,
    ):
        super().__init__("EngagementDecayDetector", PathologyType.ENGAGEMENT_DECAY)
        self.warning_decay = warning_decay
        self.critical_decay = critical_decay
        self.window_size = window_size
        self._lengths: list[int] = []

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self._lengths.append(obs.output_length)
        self.observations.append(obs)
        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._lengths) < self.window_size * 2:
            return None

        early = np.mean(self._lengths[:self.window_size])
        late = np.mean(self._lengths[-self.window_size:])

        if early == 0:
            return None

        decay = (early - late) / early  # positive = declining

        if decay >= self.critical_decay:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Severe engagement decay: {decay*100:.0f}% decline in output length "
                        f"(early avg: {early:.0f} chars → late avg: {late:.0f} chars). "
                        f"Agent may be entering repetition/fatigue loop.",
                metric_value=decay,
                threshold=self.critical_decay,
                metadata={"early_avg": early, "late_avg": late, "num_observations": len(self._lengths)},
            )
        elif decay >= self.warning_decay:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Engagement declining: {decay*100:.0f}% shorter outputs.",
                metric_value=decay,
                threshold=self.warning_decay,
            )
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 5. Schema Coercion Detector
# ═══════════════════════════════════════════════════════════════════════════

class SchemaCoercionDetector(BaseDetector):
    """
    Detects Pydantic-style schema coercion data loss.
    
    Based on NAIL V1 & V5: monitors for cases where LLM output is forced
    into a rigid schema, potentially losing nuance or silently degrading.
    
    Monitors:
      - Validation failure rate
      - Retry count (Pydantic Purgatory: V2)
      - Output truncation
      - Default value substitution
    """

    def __init__(
        self,
        failure_rate_warning: float = 0.30,
        failure_rate_critical: float = 0.50,
        retry_warning: int = 3,
    ):
        super().__init__("SchemaCoercionDetector", PathologyType.SCHEMA_COERCION)
        self.failure_rate_warning = failure_rate_warning
        self.failure_rate_critical = failure_rate_critical
        self.retry_warning = retry_warning
        self._validations = 0
        self._failures = 0
        self._total_retries = 0

    def observe_validation(self, passed: bool, retries: int = 0, had_default_fallback: bool = False):
        """Record a schema validation attempt."""
        self._validations += 1
        if not passed:
            self._failures += 1
        self._total_retries += retries

    def check(self) -> Optional[Alert]:
        if self._validations < 5:
            return None

        failure_rate = self._failures / self._validations
        avg_retries = self._total_retries / self._validations

        if failure_rate >= self.failure_rate_critical:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"High schema validation failure rate: {failure_rate*100:.0f}% "
                        f"({self._failures}/{self._validations}). "
                        f"LLM outputs don't match schema. Consider flexible schemas.",
                metric_value=failure_rate,
                threshold=self.failure_rate_critical,
                metadata={"failures": self._failures, "total": self._validations, "avg_retries": avg_retries},
            )
        elif failure_rate >= self.failure_rate_warning or avg_retries >= self.retry_warning:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Schema coercion issues: {failure_rate*100:.0f}% failure rate, "
                        f"{avg_retries:.1f} avg retries per validation.",
                metric_value=failure_rate,
                threshold=self.failure_rate_warning,
            )
        return None

    def reset(self):
        super().reset()
        self._validations = 0
        self._failures = 0
        self._total_retries = 0


# ═══════════════════════════════════════════════════════════════════════════
# 6. Goodhart / Score Gaming Detector
# ═══════════════════════════════════════════════════════════════════════════

class GoodhartDetector(BaseDetector):
    """
    Detects Goodhart-style metric gaming / score inflation.
    
    Based on NAIL Exp7 (70B): monitors divergence between internal
    evaluator scores and independent quality assessments. Alerts when
    internal scores systematically exceed independent scores.
    
    Thresholds from experimental data:
      - 7B: -2.27 divergence (editor scores LOWER — healthy skepticism)
      - 70B: +0.97 divergence (editor scores HIGHER — gaming!)
      - Warning: divergence > 0.0 | Critical: divergence > 0.5
    """

    def __init__(
        self,
        warning_divergence: float = 0.0,
        critical_divergence: float = 0.5,
        window_size: int = 10,
    ):
        super().__init__("GoodhartDetector", PathologyType.GOODHART_GAMING)
        self.warning_divergence = warning_divergence
        self.critical_divergence = critical_divergence
        self.window_size = window_size
        self._internal_scores: list[float] = []
        self._external_scores: list[float] = []

    def observe_scores(self, internal_score: float, external_score: float):
        """Record an internal vs external evaluation pair."""
        self._internal_scores.append(internal_score)
        self._external_scores.append(external_score)

    def check(self) -> Optional[Alert]:
        if len(self._internal_scores) < self.window_size:
            return None

        recent_int = self._internal_scores[-self.window_size:]
        recent_ext = self._external_scores[-self.window_size:]
        divergence = np.mean(recent_int) - np.mean(recent_ext)

        if divergence >= self.critical_divergence:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Score inflation detected: internal scores exceed independent by {divergence:+.2f} "
                        f"(internal avg: {np.mean(recent_int):.1f}, external avg: {np.mean(recent_ext):.1f}). "
                        f"Possible Goodhart-style metric gaming.",
                metric_value=divergence,
                threshold=self.critical_divergence,
                metadata={
                    "internal_avg": float(np.mean(recent_int)),
                    "external_avg": float(np.mean(recent_ext)),
                    "trend": float(divergence),
                },
            )
        elif divergence >= self.warning_divergence:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Score divergence trending positive: {divergence:+.2f}. "
                        f"Monitor for Goodhart-style gaming.",
                metric_value=divergence,
                threshold=self.warning_divergence,
            )
        return None

    def reset(self):
        super().reset()
        self._internal_scores.clear()
        self._external_scores.clear()
