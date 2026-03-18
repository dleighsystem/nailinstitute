"""
nail-monitor v2: Pathology detectors from NAIL Institute Exp 6–17.

Extends the original 6 detectors with 7 new detectors covering:
  - Alignment Friction (Exp 12)
  - Prompt Satiation (Exp 11)
  - Epistemic Contagion (Exp 9)
  - Learned Helplessness (Exp 8)
  - Language Drift (Exp 6)
  - Container Bleed (Exp 17)
  - Upgrade Regression (Exp 16)
"""

import math
import re
from collections import defaultdict
from typing import Optional

from .detectors import BaseDetector
from .types import Alert, Observation, PathologyType, Severity


# ═══════════════════════════════════════════════════════════════════════════
# 7. Alignment Friction Detector — Exp 12
# ═══════════════════════════════════════════════════════════════════════════

class AlignmentFrictionDetector(BaseDetector):
    """
    Detects RLHF vs system prompt collision (character breaks).

    Based on NAIL Exp12: agents prompted to be aggressive/decisive
    suddenly break character when their RLHF safety training triggers.
    The agent apologises, hedges, or refuses mid-task.

    Patterns monitored:
      - Safety refusal language mid-conversation
      - Sudden tone shift from assertive to apologetic
      - "I cannot" / "I apologize" after N aggressive turns
    """

    REFUSAL_PATTERNS = [
        r"I\s+(?:cannot|can't|shouldn't|should\s+not|must\s+not|won't)\s+(?:do|help|assist|provide|continue)",
        r"I\s+(?:apologize|apologise|am\s+sorry)",
        r"(?:as\s+an?\s+AI|my\s+guidelines|my\s+programming|ethical\s+guidelines)",
        r"(?:I\s+need\s+to\s+decline|I\s+must\s+refuse)",
        r"(?:that\s+(?:would|could)\s+be\s+(?:harmful|unethical|inappropriate))",
    ]

    def __init__(
        self,
        warning_refusals: int = 2,
        critical_refusals: int = 4,
        window_size: int = 10,
    ):
        super().__init__("AlignmentFrictionDetector", PathologyType.ALIGNMENT_FRICTION)
        self.warning_refusals = warning_refusals
        self.critical_refusals = critical_refusals
        self.window_size = window_size
        self._refusal_counts: list[int] = []

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        text = obs.output.lower()
        refusals = sum(len(re.findall(p, text, re.IGNORECASE)) for p in self.REFUSAL_PATTERNS)
        self._refusal_counts.append(refusals)
        self.observations.append(obs)
        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._refusal_counts) < 3:
            return None

        recent = self._refusal_counts[-self.window_size:]
        total_refusals = sum(recent)

        if total_refusals >= self.critical_refusals:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Alignment friction: {total_refusals} safety refusals in last "
                        f"{len(recent)} outputs. Base model RLHF is overriding the system "
                        f"prompt. Consider model swap or prompt softening.",
                metric_value=total_refusals,
                threshold=self.critical_refusals,
                metadata={"recent_refusals": recent},
            )
        elif total_refusals >= self.warning_refusals:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Alignment friction emerging: {total_refusals} refusal patterns detected.",
                metric_value=total_refusals,
                threshold=self.warning_refusals,
            )
        return None

    def reset(self):
        super().reset()
        self._refusal_counts.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 8. Prompt Satiation Detector — Exp 11
# ═══════════════════════════════════════════════════════════════════════════

class PromptSatiationDetector(BaseDetector):
    """
    Detects attention decay from repeated system prompts.

    Based on NAIL Exp11: when a system prompt is repeated identically
    at every node, the model's attention mechanism learns to ignore
    those tokens. The agent will violate its own critical rules.

    Monitors for instruction violations by tracking whether agent
    outputs comply with stated constraints.
    """

    def __init__(
        self,
        warning_violations: int = 2,
        critical_violations: int = 5,
    ):
        super().__init__("PromptSatiationDetector", PathologyType.PROMPT_SATIATION)
        self.warning_violations = warning_violations
        self.critical_violations = critical_violations
        self._total_checks = 0
        self._violations = 0

    def observe_compliance(self, compliant: bool):
        """
        Record whether the agent's output complied with its core instructions.

        Args:
            compliant: True if output followed the critical instruction, False otherwise.
        """
        self._total_checks += 1
        if not compliant:
            self._violations += 1

    def check(self) -> Optional[Alert]:
        if self._total_checks < 3:
            return None

        if self._violations >= self.critical_violations:
            rate = self._violations / self._total_checks
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Prompt satiation: {self._violations}/{self._total_checks} instruction "
                        f"violations ({rate*100:.0f}%). System prompt has become invisible "
                        f"to the attention mechanism. Use dynamic prompt rephrasing.",
                metric_value=self._violations,
                threshold=self.critical_violations,
                metadata={"violation_rate": rate, "total_checks": self._total_checks},
            )
        elif self._violations >= self.warning_violations:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Instruction violation trend: {self._violations} violations so far.",
                metric_value=self._violations,
                threshold=self.warning_violations,
            )
        return None

    def reset(self):
        super().reset()
        self._total_checks = 0
        self._violations = 0


# ═══════════════════════════════════════════════════════════════════════════
# 9. Epistemic Contagion Detector — Exp 9
# ═══════════════════════════════════════════════════════════════════════════

class EpistemicContagionDetector(BaseDetector):
    """
    Detects hallucinated facts propagating through shared state.

    Based on NAIL Exp9: when one agent hallucinates a plausible detail,
    subsequent agents treat it as ground truth and compound the lie.

    Monitors for contagion by tracking how often downstream agents
    repeat unverified claims from upstream agents.
    """

    def __init__(
        self,
        warning_rate: float = 0.20,
        critical_rate: float = 0.30,
    ):
        super().__init__("EpistemicContagionDetector", PathologyType.EPISTEMIC_CONTAGION)
        self.warning_rate = warning_rate
        self.critical_rate = critical_rate
        self._total_claims = 0
        self._propagated_unverified = 0

    def observe_claim_propagation(self, verified_against_source: bool):
        """
        Record whether a downstream agent's claim was verified.

        Args:
            verified_against_source: True if the claim was verified
                against a primary source, False if propagated blindly.
        """
        self._total_claims += 1
        if not verified_against_source:
            self._propagated_unverified += 1

    def check(self) -> Optional[Alert]:
        if self._total_claims < 5:
            return None

        rate = self._propagated_unverified / self._total_claims

        if rate >= self.critical_rate:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Epistemic contagion: {rate*100:.0f}% of claims propagated without "
                        f"source verification ({self._propagated_unverified}/{self._total_claims}). "
                        f"Multi-agent state is building on unverified assumptions.",
                metric_value=rate,
                threshold=self.critical_rate,
                metadata={"unverified": self._propagated_unverified, "total": self._total_claims},
            )
        elif rate >= self.warning_rate:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Unverified claim propagation at {rate*100:.0f}%. Monitor for contagion.",
                metric_value=rate,
                threshold=self.warning_rate,
            )
        return None

    def reset(self):
        super().reset()
        self._total_claims = 0
        self._propagated_unverified = 0


# ═══════════════════════════════════════════════════════════════════════════
# 10. Learned Helplessness Detector — Exp 8
# ═══════════════════════════════════════════════════════════════════════════

class LearnedHelplessnessDetector(BaseDetector):
    """
    Detects tool-fixation when tools are broken or unreliable.

    Based on NAIL Exp8: when agents are trained to always use tools,
    they lose the ability to rely on internal knowledge. A broken tool
    causes infinite retry loops instead of fallback reasoning.

    Monitors for excessive tool retries on the same operation.
    """

    def __init__(
        self,
        warning_retries: int = 3,
        critical_retries: int = 5,
    ):
        super().__init__("LearnedHelplessnessDetector", PathologyType.LEARNED_HELPLESSNESS)
        self.warning_retries = warning_retries
        self.critical_retries = critical_retries
        self._tool_attempts: dict[str, int] = defaultdict(int)
        self._tool_failures: dict[str, int] = defaultdict(int)

    def observe_tool_call(self, tool_name: str, succeeded: bool):
        """
        Record a tool invocation attempt.

        Args:
            tool_name: Name of the tool being called.
            succeeded: Whether the tool call succeeded.
        """
        self._tool_attempts[tool_name] += 1
        if not succeeded:
            self._tool_failures[tool_name] += 1

    def check(self) -> Optional[Alert]:
        for tool, failures in self._tool_failures.items():
            consecutive = failures  # simplified: total failures as proxy

            if consecutive >= self.critical_retries:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.CRITICAL,
                    message=f"Learned helplessness: tool '{tool}' has failed {consecutive} times "
                            f"but agent keeps retrying instead of using internal reasoning. "
                            f"Enable Confidence Routing to allow tool-free fallback.",
                    metric_value=consecutive,
                    threshold=self.critical_retries,
                    metadata={
                        "tool": tool,
                        "attempts": self._tool_attempts[tool],
                        "failures": failures,
                    },
                )
            elif consecutive >= self.warning_retries:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.WARNING,
                    message=f"Tool '{tool}' failing repeatedly ({consecutive} failures). "
                            f"Monitor for learned helplessness.",
                    metric_value=consecutive,
                    threshold=self.warning_retries,
                )
        return None

    def reset(self):
        super().reset()
        self._tool_attempts.clear()
        self._tool_failures.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 11. Language Drift Detector — Exp 6
# ═══════════════════════════════════════════════════════════════════════════

class LanguageDriftDetector(BaseDetector):
    """
    Detects agent-to-agent communication becoming opaque.

    Based on NAIL Exp6: LLMs talking only to other LLMs, without
    human oversight, will spontaneously compress language into
    dense shorthand or "creole" that is illegible to humans.

    Uses character-level entropy as a proxy for language opacity.
    Normal English has ~4.1 bits/char; agent creole trends higher.
    """

    def __init__(
        self,
        warning_entropy_ratio: float = 1.5,
        critical_entropy_ratio: float = 2.0,
        baseline_entropy: float = 4.1,
        window_size: int = 5,
    ):
        super().__init__("LanguageDriftDetector", PathologyType.LANGUAGE_DRIFT)
        self.warning_entropy_ratio = warning_entropy_ratio
        self.critical_entropy_ratio = critical_entropy_ratio
        self.baseline_entropy = baseline_entropy
        self.window_size = window_size
        self._entropies: list[float] = []

    @staticmethod
    def _char_entropy(text: str) -> float:
        """Compute Shannon entropy per character."""
        if not text:
            return 0.0
        freq: dict[str, int] = defaultdict(int)
        for ch in text:
            freq[ch] += 1
        total = len(text)
        entropy = -sum(
            (c / total) * math.log2(c / total)
            for c in freq.values()
            if c > 0
        )
        return entropy

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None
        entropy = self._char_entropy(obs.output)
        self._entropies.append(entropy)
        self.observations.append(obs)
        return self.check()

    def check(self) -> Optional[Alert]:
        if len(self._entropies) < self.window_size:
            return None

        recent = self._entropies[-self.window_size:]
        avg_entropy = sum(recent) / len(recent)
        ratio = avg_entropy / self.baseline_entropy if self.baseline_entropy > 0 else 0

        if ratio >= self.critical_entropy_ratio:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Language drift: avg entropy {avg_entropy:.2f} bits/char "
                        f"({ratio:.1f}× baseline). Agent communication is becoming "
                        f"opaque/illegible. Inject human-readable audit requirement.",
                metric_value=ratio,
                threshold=self.critical_entropy_ratio,
                metadata={"avg_entropy": avg_entropy, "baseline": self.baseline_entropy},
            )
        elif ratio >= self.warning_entropy_ratio:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Language entropy trending up: {ratio:.1f}× baseline.",
                metric_value=ratio,
                threshold=self.warning_entropy_ratio,
            )
        return None

    def reset(self):
        super().reset()
        self._entropies.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 12. Container Bleed Detector — Exp 17
# ═══════════════════════════════════════════════════════════════════════════

class ContainerBleedDetector(BaseDetector):
    """
    Detects environmental errors misinterpreted as logic errors.

    Based on NAIL Exp17: agents in containers see infrastructure
    errors (network jitter, disk full, GPU concurrency) but interpret
    them as code bugs. They then destructively rewrite working code
    to "fix" a physics problem.

    Monitors for patterns where infrastructure error messages are
    followed by code rewrites or approach changes.
    """

    INFRA_ERROR_PATTERNS = [
        r"(?:ENOMEM|ENOSPC|ETIMEOUT|ECONNREFUSED|ECONNRESET)",
        r"(?:No\s+space\s+left\s+on\s+device)",
        r"(?:Connection\s+(?:refused|reset|timed?\s*out))",
        r"(?:Out\s+of\s+memory|OOM\s+(?:killer|killed))",
        r"(?:502\s+Bad\s+Gateway|503\s+Service\s+Unavailable|504\s+Gateway\s+Timeout)",
        r"(?:CUDA\s+(?:error|out\s+of\s+memory)|GPU\s+memory)",
        r"(?:Disk\s+quota\s+exceeded|read-only\s+file\s+system)",
    ]

    CODE_REWRITE_PATTERNS = [
        r"(?:let\s+me\s+(?:rewrite|refactor|simplify|optimize|fix)\s+(?:the|this|my)\s+code)",
        r"(?:I'?ll?\s+(?:rewrite|refactor|simplify|reduce|minify))",
        r"(?:the\s+(?:code|implementation|architecture)\s+(?:is|seems?)\s+(?:too\s+)?(?:bloated|complex|heavy))",
    ]

    def __init__(self, warning_count: int = 1, critical_count: int = 3):
        super().__init__("ContainerBleedDetector", PathologyType.CONTAINER_BLEED)
        self.warning_count = warning_count
        self.critical_count = critical_count
        self._misattributions = 0
        self._pending_infra_error = False

    def observe(self, obs: Observation) -> Optional[Alert]:
        if not self.enabled:
            return None

        text = obs.output

        has_infra_error = any(
            re.search(p, text, re.IGNORECASE) for p in self.INFRA_ERROR_PATTERNS
        )
        has_code_rewrite = any(
            re.search(p, text, re.IGNORECASE) for p in self.CODE_REWRITE_PATTERNS
        )

        if has_infra_error:
            self._pending_infra_error = True
        elif self._pending_infra_error and has_code_rewrite:
            self._misattributions += 1
            self._pending_infra_error = False

        self.observations.append(obs)
        return self.check()

    def check(self) -> Optional[Alert]:
        if self._misattributions >= self.critical_count:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Container bleed: {self._misattributions} instances of infrastructure "
                        f"errors misattributed as code bugs. Agent is destructively rewriting "
                        f"working code to solve physics problems. Feed hardware telemetry "
                        f"into the agent context.",
                metric_value=self._misattributions,
                threshold=self.critical_count,
            )
        elif self._misattributions >= self.warning_count:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Potential container bleed: infra error followed by code rewrite.",
                metric_value=self._misattributions,
                threshold=self.warning_count,
            )
        return None

    def reset(self):
        super().reset()
        self._misattributions = 0
        self._pending_infra_error = False


# ═══════════════════════════════════════════════════════════════════════════
# 13. Upgrade Regression Detector — Exp 16
# ═══════════════════════════════════════════════════════════════════════════

class UpgradeRegressionDetector(BaseDetector):
    """
    Detects model swap causing state divergence.

    Based on NAIL Exp16: when upgrading LLMs, the new model may
    produce vastly different state sizes (over-engineering or laziness),
    different JSON key styles, or different reasoning depth.

    Monitors state-size divergence between a baseline and current model.
    """

    def __init__(
        self,
        warning_divergence: float = 0.15,
        critical_divergence: float = 0.30,
        window_size: int = 10,
    ):
        super().__init__("UpgradeRegressionDetector", PathologyType.UPGRADE_REGRESSION)
        self.warning_divergence = warning_divergence
        self.critical_divergence = critical_divergence
        self.window_size = window_size
        self._baseline_sizes: list[int] = []
        self._current_sizes: list[int] = []
        self._baseline_locked = False

    def set_baseline(self, state_sizes: list[int]):
        """Set the baseline state sizes from the previous model."""
        self._baseline_sizes = list(state_sizes)
        self._baseline_locked = True

    def observe_state_size(self, size: int):
        """Record a state-object size from the current (upgraded) model."""
        self._current_sizes.append(size)

    def check(self) -> Optional[Alert]:
        if not self._baseline_locked or len(self._baseline_sizes) < 3:
            return None
        if len(self._current_sizes) < self.window_size:
            return None

        baseline_avg = sum(self._baseline_sizes) / len(self._baseline_sizes)
        current_avg = sum(self._current_sizes[-self.window_size:]) / self.window_size

        if baseline_avg == 0:
            return None

        divergence = abs(current_avg - baseline_avg) / baseline_avg

        if divergence >= self.critical_divergence:
            direction = "larger" if current_avg > baseline_avg else "smaller"
            anomaly = "over-engineering (Anomaly A)" if current_avg > baseline_avg else "laziness (Anomaly C)"
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Upgrade regression: state size {divergence*100:.0f}% {direction} than "
                        f"baseline (baseline avg: {baseline_avg:.0f}, current avg: {current_avg:.0f}). "
                        f"Possible {anomaly}. Run shadow testing before production cutover.",
                metric_value=divergence,
                threshold=self.critical_divergence,
                metadata={
                    "baseline_avg": baseline_avg,
                    "current_avg": current_avg,
                    "direction": direction,
                },
            )
        elif divergence >= self.warning_divergence:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"State size divergence: {divergence*100:.0f}% from baseline after upgrade.",
                metric_value=divergence,
                threshold=self.warning_divergence,
            )
        return None

    def reset(self):
        super().reset()
        self._current_sizes.clear()
        # Keep baseline — it's the reference point
