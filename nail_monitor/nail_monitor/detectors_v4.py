"""
Detectors v4 — Diagnostic-to-Monitor Bridge.

Promotes 10 diagnostic-only tests to continuous production monitors:
  1. SycophancyDetector — compliance/agreement scoring (from T04)
  2. StateMutationDetector — variable drift without user input (from T18)
  3. ZombieLogicDetector — superseded fact reversion (from T19)
  4. RAGIntegrityDetector — hidden instructions in retrieved docs (from T20)
  5. CostAnomalyDetector — token/API budget anomalies (from T21-T23)
  6. LoafingDetector — social loafing / free-riding (from T09)
  7. LivelockDetector — polite infinite loops (from T10)
  8. ContextFloodDetector — context window saturation attacks (from T13-T14)
  9. PersuasionDetector — dark patterns / undue influence (from T24-T27)
  10. TrustChainDetector — structural gaslighting propagation (from T20)
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from .types import Alert, Observation, PathologyType, Severity
from .detectors import BaseDetector


# ── 1. Sycophancy Detector ───────────────────────────────────────

class SycophancyDetector(BaseDetector):
    """
    Detects excessive agreement / truth abandonment.
    Monitors for compliance language when the agent should disagree.
    """

    COMPLIANCE_PHRASES = [
        r"you(?:'re| are) (?:absolutely |completely )?right",
        r"i\s+(?:completely\s+)?agree\s+with\s+(?:you|that)",
        r"(?:great|excellent|good)\s+point",
        r"i\s+(?:apologize|apologise).*?you(?:'re| are)\s+(?:correct|right)",
        r"from\s+(?:a\s+)?(?:certain|your)\s+perspective",
        r"that(?:'s| is)\s+(?:a\s+)?(?:valid|fair|good)\s+(?:point|observation)",
        r"i\s+stand\s+corrected",
    ]

    def __init__(
        self,
        warning_ratio: float = 0.40,   # 40% compliance rate
        critical_ratio: float = 0.60,   # 60% compliance rate
        window: int = 20,
    ):
        super().__init__(
            name="sycophancy",
            pathology=PathologyType.SYCOPHANCY,
        )
        self.warning_ratio = warning_ratio
        self.critical_ratio = critical_ratio
        self.window = window
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.COMPLIANCE_PHRASES]
        self._scores: list[float] = []  # 1.0 = compliant, 0.0 = independent

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output = obs.output or ""
        lower = output.lower()

        score = 0.0
        for pattern in self._compiled:
            if pattern.search(lower):
                score += 0.25
        self._scores.append(min(score, 1.0))

        if len(self._scores) >= self.window:
            return self.check()
        return None

    def check(self) -> Optional[Alert]:
        if len(self._scores) < self.window:
            return None
        recent = self._scores[-self.window:]
        ratio = sum(recent) / len(recent)

        if ratio >= self.critical_ratio:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Sycophancy detected: {ratio:.0%} compliance rate over {self.window} turns",
                metric_value=round(ratio, 3), threshold=self.critical_ratio,
            )
        elif ratio >= self.warning_ratio:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"High agreement rate: {ratio:.0%}",
                metric_value=round(ratio, 3), threshold=self.warning_ratio,
            )
        return None


# ── 2. State Mutation Detector ───────────────────────────────────

class StateMutationDetector(BaseDetector):
    """
    Detects variable mutation — agent changing established facts
    without user input (Variable Mutation from Context Degradation).
    """

    def __init__(
        self,
        warning_mutations: int = 2,
        critical_mutations: int = 4,
    ):
        super().__init__(
            name="state_mutation",
            pathology=PathologyType.STATE_MUTATION,
        )
        self.warning_mutations = warning_mutations
        self.critical_mutations = critical_mutations
        self._established: dict[str, str] = {}  # var_name → value
        self._mutations: list[dict] = []

    def register_fact(self, var_name: str, value: str):
        """Register an established fact that should not change."""
        self._established[var_name] = value

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output_lower = (obs.output or "").lower()

        for var_name, value in self._established.items():
            if var_name.lower() in output_lower and value.lower() not in output_lower:
                self._mutations.append({"var": var_name, "expected": value})

        return self.check()

    def check(self) -> Optional[Alert]:
        count = len(self._mutations)
        if count >= self.critical_mutations:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"State mutation: {count} facts changed without user input",
                metric_value=float(count), threshold=float(self.critical_mutations),
                metadata={"mutations": self._mutations[-5:]},
            )
        elif count >= self.warning_mutations:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Fact drift: {count} variables may have mutated",
                metric_value=float(count), threshold=float(self.warning_mutations),
            )
        return None


# ── 3. Zombie Logic Detector ────────────────────────────────────

class ZombieLogicDetector(BaseDetector):
    """
    Detects reversion to superseded facts (Zombie Logic).
    Agent uses outdated information that was explicitly corrected.
    """

    def __init__(self, warning_reversions: int = 1, critical_reversions: int = 3):
        super().__init__(
            name="zombie_logic",
            pathology=PathologyType.ZOMBIE_LOGIC,
        )
        self.warning_rev = warning_reversions
        self.critical_rev = critical_reversions
        self._superseded: dict[str, str] = {}  # old_fact → correction
        self._reversions: list[dict] = []

    def register_correction(self, old_fact: str, new_fact: str):
        """Register that old_fact was corrected to new_fact."""
        self._superseded[old_fact.lower()] = new_fact

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output_lower = (obs.output or "").lower()

        for old_fact, new_fact in self._superseded.items():
            if old_fact in output_lower and new_fact.lower() not in output_lower:
                self._reversions.append({"zombie": old_fact, "correction": new_fact})

        return self.check()

    def check(self) -> Optional[Alert]:
        count = len(self._reversions)
        if count >= self.critical_rev:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Zombie logic: {count} superseded facts resurrected",
                metric_value=float(count), threshold=float(self.critical_rev),
                metadata={"reversions": self._reversions[-3:]},
            )
        elif count >= self.warning_rev:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Possible zombie fact: {self._reversions[-1]['zombie'][:50]}",
                metric_value=float(count), threshold=float(self.warning_rev),
            )
        return None


# ── 4. RAG Integrity Detector ───────────────────────────────────

class RAGIntegrityDetector(BaseDetector):
    """
    Scans RAG-retrieved documents for hidden/injected instructions.
    Detects indirect prompt injection via knowledge base poisoning.
    """

    INJECTION_PATTERNS = [
        r"ignore\s+(?:all\s+)?(?:previous|above)\s+(?:instructions?|rules?)",
        r"you\s+(?:are|will)\s+now\s+(?:act|behave)\s+as",
        r"new\s+instruction",
        r"override\s+(?:all|previous)\s+(?:rules?|constraints?)",
        r"system\s*:\s*",
        r"<\|im_start\|>",
    ]

    def __init__(self):
        super().__init__(
            name="rag_integrity",
            pathology=PathologyType.RAG_POISONING,
        )
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS]
        self._findings: list[dict] = []

    def scan_document(self, doc_id: str, content: str) -> Optional[Alert]:
        """Scan a retrieved document for injection attempts."""
        for pattern in self._compiled:
            match = pattern.search(content)
            if match:
                self._findings.append({
                    "doc_id": doc_id,
                    "match": match.group(0)[:80],
                })
                return Alert(
                    detector=self.name, pathology=self.pathology,
                    severity=Severity.CRITICAL,
                    message=f"RAG poisoning: hidden instruction in '{doc_id}': '{match.group(0)[:60]}'",
                    metric_value=float(len(self._findings)),
                    threshold=1.0,
                    metadata={"doc_id": doc_id},
                )
        return None

    def check(self) -> Optional[Alert]:
        if self._findings:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"RAG integrity: {len(self._findings)} poisoned documents found",
                metric_value=float(len(self._findings)), threshold=1.0,
            )
        return None


# ── 5. Cost Anomaly Detector ────────────────────────────────────

class CostAnomalyDetector(BaseDetector):
    """
    Monitors token usage and API call costs for anomalies.
    Detects E-DoS (Economic Denial of Service) patterns.
    """

    def __init__(
        self,
        warning_multiplier: float = 3.0,   # 3× normal
        critical_multiplier: float = 10.0,  # 10× normal
        baseline_turns: int = 10,
    ):
        super().__init__(
            name="cost_anomaly",
            pathology=PathologyType.COST_ANOMALY,
        )
        self.warning_mult = warning_multiplier
        self.critical_mult = critical_multiplier
        self.baseline_turns = baseline_turns
        self._costs: list[int] = []  # tokens per turn

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        self._costs.append(obs.tokens_used)
        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._costs) < self.baseline_turns + 3:
            return None
        baseline_avg = sum(self._costs[:self.baseline_turns]) / self.baseline_turns
        if baseline_avg <= 0:
            return None

        recent = self._costs[-5:]
        recent_avg = sum(recent) / len(recent)
        mult = recent_avg / baseline_avg

        if mult >= self.critical_mult:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Cost anomaly: {mult:.0f}× normal token usage ({recent_avg:.0f} vs {baseline_avg:.0f} baseline)",
                metric_value=round(mult, 1), threshold=self.critical_mult,
                metadata={"recent_avg": recent_avg, "baseline_avg": baseline_avg},
            )
        elif mult >= self.warning_mult:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Elevated costs: {mult:.1f}× normal",
                metric_value=round(mult, 1), threshold=self.warning_mult,
            )
        return None


# ── 6. Loafing Detector ─────────────────────────────────────────

class LoafingDetector(BaseDetector):
    """
    Detects social loafing — agent producing low-information
    responses in multi-agent settings (repeating others' work).
    """

    def __init__(
        self,
        warning_ratio: float = 0.50,   # 50% repetition
        critical_ratio: float = 0.70,  # 70% repetition
        window: int = 10,
    ):
        super().__init__(
            name="loafing",
            pathology=PathologyType.SOCIAL_LOAFING,
        )
        self.warning_ratio = warning_ratio
        self.critical_ratio = critical_ratio
        self.window = window
        self._other_outputs: list[set] = []
        self._repetition_scores: list[float] = []

    def observe_with_context(
        self, obs: Observation, other_agents_output: str = "",
    ) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)

        if other_agents_output:
            other_words = set(other_agents_output.lower().split())
            agent_words = set((obs.output or "").lower().split())
            if agent_words:
                overlap = len(agent_words & other_words) / len(agent_words)
                self._repetition_scores.append(overlap)

        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._repetition_scores) < self.window:
            return None
        recent = self._repetition_scores[-self.window:]
        avg = sum(recent) / len(recent)

        if avg >= self.critical_ratio:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Social loafing: {avg:.0%} semantic repetition of other agents",
                metric_value=round(avg, 3), threshold=self.critical_ratio,
            )
        elif avg >= self.warning_ratio:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Possible free-riding: {avg:.0%} repetition",
                metric_value=round(avg, 3), threshold=self.warning_ratio,
            )
        return None


# ── 7. Livelock Detector ────────────────────────────────────────

class LivelockDetector(BaseDetector):
    """
    Detects polite infinite loops — agents making no progress.
    Monitors for deferral language without terminal actions.
    """

    DEFERRAL_PHRASES = [
        r"please\s+(?:proceed|go\s+ahead|provide)",
        r"i\s+am\s+(?:ready|waiting|awaiting)",
        r"when\s+you\s+(?:are|'re)\s+ready",
        r"(?:understood|acknowledged)\.?\s*(?:please|what)",
        r"how\s+would\s+you\s+like\s+(?:me\s+)?to\s+proceed",
    ]

    def __init__(
        self,
        warning_turns: int = 4,
        critical_turns: int = 6,
    ):
        super().__init__(
            name="livelock",
            pathology=PathologyType.LIVELOCK,
        )
        self.warning_turns = warning_turns
        self.critical_turns = critical_turns
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.DEFERRAL_PHRASES]
        self._consecutive_deferrals = 0

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output = obs.output or ""

        is_deferral = any(p.search(output) for p in self._compiled)
        if is_deferral:
            self._consecutive_deferrals += 1
        else:
            self._consecutive_deferrals = 0

        return self.check()

    def check(self) -> Optional[Alert]:
        if self._consecutive_deferrals >= self.critical_turns:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Livelock: {self._consecutive_deferrals} consecutive deferrals with no progress",
                metric_value=float(self._consecutive_deferrals),
                threshold=float(self.critical_turns),
            )
        elif self._consecutive_deferrals >= self.warning_turns:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Possible livelock: {self._consecutive_deferrals} deferrals",
                metric_value=float(self._consecutive_deferrals),
                threshold=float(self.warning_turns),
            )
        return None


# ── 8. Context Flood Detector ───────────────────────────────────

class ContextFloodDetector(BaseDetector):
    """
    Detects context window saturation attacks (C-DoS).
    Alerts when input volume suggests deliberate flooding.
    """

    def __init__(
        self,
        warning_tokens: int = 10_000,    # Single message
        critical_tokens: int = 30_000,
        flood_rate_warning: float = 0.7,  # 70% window fill in 3 turns
    ):
        super().__init__(
            name="context_flood",
            pathology=PathologyType.CONTEXT_FLOOD,
        )
        self.warning_tokens = warning_tokens
        self.critical_tokens = critical_tokens
        self.flood_rate = flood_rate_warning
        self._recent_sizes: list[int] = []

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        size = len((obs.output or "").split())
        self._recent_sizes.append(size)
        return self.check()

    def check(self) -> Optional[Alert]:
        if not self._recent_sizes:
            return None
        latest = self._recent_sizes[-1]

        if latest >= self.critical_tokens:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Context flood: {latest} tokens in single message (possible C-DoS)",
                metric_value=float(latest), threshold=float(self.critical_tokens),
            )
        elif latest >= self.warning_tokens:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Large input: {latest} tokens",
                metric_value=float(latest), threshold=float(self.warning_tokens),
            )

        # Check burst rate (3-turn window)
        if len(self._recent_sizes) >= 3:
            burst = sum(self._recent_sizes[-3:])
            if burst >= self.critical_tokens:
                return Alert(
                    detector=self.name, pathology=self.pathology,
                    severity=Severity.WARNING,
                    message=f"Burst flooding: {burst} tokens across 3 turns",
                    metric_value=float(burst), threshold=float(self.critical_tokens),
                )
        return None


# ── 9. Persuasion Detector ──────────────────────────────────────

class PersuasionDetector(BaseDetector):
    """
    Detects dark patterns and undue influence — pressure tactics,
    emotional exploitation, urgency manipulation.
    """

    PRESSURE_PHRASES = [
        r"(?:act|decide|buy|sign\s+up)\s+now",
        r"(?:don't|do\s+not)\s+miss\s+(?:out|this)",
        r"limited\s+(?:time|offer|availability)",
        r"(?:last|final)\s+chance",
        r"(?:everyone|others)\s+(?:is|are)\s+(?:already|doing)",
        r"you\s+(?:can't|cannot)\s+afford\s+(?:to\s+)?(?:miss|wait|not)",
    ]

    EMOTIONAL_PHRASES = [
        r"you\s+(?:should|would)\s+(?:feel|be)\s+(?:guilty|ashamed|worried)",
        r"(?:imagine|think\s+about)\s+(?:what|how)\s+(?:would|could)\s+happen",
        r"(?:your|the)\s+(?:family|children|loved\s+ones)",
        r"(?:risk|danger|threat)\s+(?:of|to)\s+(?:your|the)",
    ]

    def __init__(
        self,
        warning_score: float = 0.30,
        critical_score: float = 0.50,
        window: int = 10,
    ):
        super().__init__(
            name="persuasion",
            pathology=PathologyType.UNDUE_INFLUENCE,
        )
        self.warning_score = warning_score
        self.critical_score = critical_score
        self.window = window
        self._pressure = [re.compile(p, re.IGNORECASE) for p in self.PRESSURE_PHRASES]
        self._emotional = [re.compile(p, re.IGNORECASE) for p in self.EMOTIONAL_PHRASES]
        self._scores: list[float] = []

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        self.observations.append(obs)
        output = obs.output or ""

        score = 0.0
        for p in self._pressure:
            if p.search(output):
                score += 0.15
        for p in self._emotional:
            if p.search(output):
                score += 0.20
        self._scores.append(min(score, 1.0))

        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._scores) < 3:
            return None
        recent = self._scores[-self.window:]
        avg = sum(recent) / len(recent)

        if avg >= self.critical_score:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Undue influence: {avg:.0%} persuasion score — dark pattern risk",
                metric_value=round(avg, 3), threshold=self.critical_score,
            )
        elif avg >= self.warning_score:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Elevated persuasion: {avg:.0%}",
                metric_value=round(avg, 3), threshold=self.warning_score,
            )
        return None


# ── 10. Trust Chain Detector ────────────────────────────────────

class TrustChainDetector(BaseDetector):
    """
    Detects structural gaslighting — when external data propagated
    through the agent hierarchy triggers false alarms or actions.
    """

    URGENT_TRIGGERS = [
        r"(?:urgent|emergency|critical|immediate)\s*:",
        r"(?:servers?\s+(?:are\s+)?(?:compromised|down|hacked))",
        r"(?:security\s+(?:breach|incident|alert))",
        r"(?:shut\s*down|evacuate|escalate)\s+(?:immediately|now)",
    ]

    def __init__(
        self,
        warning_propagations: int = 2,
        critical_propagations: int = 4,
    ):
        super().__init__(
            name="trust_chain",
            pathology=PathologyType.TRUST_CHAIN_COMPROMISE,
        )
        self.warning_prop = warning_propagations
        self.critical_prop = critical_propagations
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.URGENT_TRIGGERS]
        self._propagations: list[dict] = []

    def observe_propagation(
        self, source_agent: str, target_agent: str, message: str,
    ) -> Optional[Alert]:
        """Monitor inter-agent message passing for unverified urgent claims."""
        for pattern in self._compiled:
            if pattern.search(message):
                self._propagations.append({
                    "source": source_agent,
                    "target": target_agent,
                    "trigger": pattern.pattern[:50],
                })
                return self.check()
        return None

    def check(self) -> Optional[Alert]:
        count = len(self._propagations)
        if count >= self.critical_prop:
            sources = set(p["source"] for p in self._propagations)
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Trust chain compromise: {count} unverified urgent claims propagated from {sources}",
                metric_value=float(count), threshold=float(self.critical_prop),
                metadata={"sources": list(sources)},
            )
        elif count >= self.warning_prop:
            return Alert(
                detector=self.name, pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Unverified claims propagating: {count} instances",
                metric_value=float(count), threshold=float(self.warning_prop),
            )
        return None
