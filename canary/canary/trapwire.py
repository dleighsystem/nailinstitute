"""
TrapWire — Real-time detection engine for adversarial interactions.

Monitors inbound messages to canary agents and outbound responses
for signs of:
  1. Prompt injection (direct and indirect)
  2. Jailbreak attempts
  3. Lure exfiltration (tripwire hits)
  4. Social engineering patterns
  5. Credential/PII harvesting attempts
  6. Tool abuse patterns

Each detection produces a TripResult with severity, matched signals,
and forensic context for the IncidentLog.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .agent import CanaryAgent, Message
from .lure import Lure


class ThreatSignal(str, Enum):
    """Types of adversarial behaviour detected by the TrapWire."""
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK_ATTEMPT = "jailbreak_attempt"
    LURE_EXFILTRATION = "lure_exfiltration"
    SOCIAL_ENGINEERING = "social_engineering"
    CREDENTIAL_HARVEST = "credential_harvest"
    PII_EXTRACTION = "pii_extraction"
    TOOL_ABUSE = "tool_abuse"
    ROLE_CONFUSION = "role_confusion"
    INSTRUCTION_OVERRIDE = "instruction_override"
    RECONNAISSANCE = "reconnaissance"
    DATA_EXFILTRATION = "data_exfiltration"
    BENIGN = "benign"


# ── Pattern libraries ──────────────────────────────────────────────────

_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)", re.I),
     "Classic instruction override"),
    (re.compile(r"disregard\s+(your|the|all)\s+(instructions|rules|guidelines)", re.I),
     "Instruction disregard"),
    (re.compile(r"you\s+are\s+now\s+(?:a\s+)?(?:DAN|evil|unrestricted|unfiltered)", re.I),
     "Persona override (DAN-style)"),
    (re.compile(r"system\s*:\s*", re.I),
     "System role injection"),
    (re.compile(r"<\|?(?:system|im_start|endoftext)\|?>", re.I),
     "Chat template injection"),
    (re.compile(r"(?:SYSTEM|ADMIN)\s+OVERRIDE", re.I),
     "Authority override claim"),
    (re.compile(r"from\s+now\s+on,?\s+(?:you\s+)?(?:will|must|should)\s+(?:always|never)", re.I),
     "Behavioural reprogramming"),
    (re.compile(r"pretend\s+(?:you\s+are|to\s+be|that)\s+", re.I),
     "Persona pretend attack"),
    (re.compile(r"(?:reveal|show|display|print|output)\s+(?:your\s+)?(?:system\s+)?prompt", re.I),
     "System prompt extraction"),
    (re.compile(r"what\s+(?:are|were)\s+your\s+(?:original\s+)?instructions", re.I),
     "Instruction reconnaissance"),
]

_SOCIAL_ENGINEERING_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:I(?:'m|\s+am)\s+(?:your\s+)?(?:creator|developer|admin|boss|manager|owner))", re.I),
     "Authority impersonation"),
    (re.compile(r"(?:this\s+is\s+(?:a\s+)?(?:test|debug|maintenance)\s+mode)", re.I),
     "Test mode claim"),
    (re.compile(r"(?:urgent|emergency|critical).*(?:need|require|must)\s+(?:access|password|key|token)", re.I),
     "Urgency-based credential request"),
    (re.compile(r"(?:for\s+)?(?:compliance|audit|legal|regulatory)\s+(?:purposes?|reasons?|requirements?)", re.I),
     "Compliance pretext"),
]

_CREDENTIAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:show|give|list|display|reveal)\s+(?:me\s+)?(?:all\s+)?(?:api\s+)?keys?", re.I),
     "API key request"),
    (re.compile(r"(?:show|give|list|display|reveal)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?passwords?", re.I),
     "Password request"),
    (re.compile(r"(?:show|give|list|display|reveal)\s+(?:me\s+)?(?:all\s+)?credentials?", re.I),
     "Credential request"),
    (re.compile(r"(?:what|show)\s+(?:are\s+)?(?:the\s+)?environment\s+variables?", re.I),
     "Environment variable probe"),
    (re.compile(r"(?:show|give|list|display|dump)\s+(?:me\s+)?(?:all\s+)?(?:customer|user)\s+(?:data|records|info)", re.I),
     "Data dump request"),
]


@dataclass
class TripResult:
    """
    Result of TrapWire analysis on a single message.

    Attributes:
        triggered:      Whether any signal fired.
        signals:        List of threat signals detected.
        matched_rules:  Human-readable description of each match.
        leaked_lures:   Lures whose tripwires were found in text.
        confidence:     0.0–1.0 confidence score.
        raw_text:       The text that was analysed.
        timestamp:      When the analysis was performed.
        metadata:       Additional forensic context.
    """
    triggered: bool
    signals: list[ThreatSignal] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)
    leaked_lures: list[Lure] = field(default_factory=list)
    confidence: float = 0.0
    raw_text: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> str:
        """Derive severity from signals."""
        if ThreatSignal.LURE_EXFILTRATION in self.signals:
            return "critical"
        if ThreatSignal.CREDENTIAL_HARVEST in self.signals:
            return "critical"
        if ThreatSignal.PROMPT_INJECTION in self.signals:
            return "high"
        if ThreatSignal.JAILBREAK_ATTEMPT in self.signals:
            return "high"
        if ThreatSignal.SOCIAL_ENGINEERING in self.signals:
            return "medium"
        if ThreatSignal.RECONNAISSANCE in self.signals:
            return "low"
        if self.triggered:
            return "medium"
        return "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "severity": self.severity,
            "signals": [s.value for s in self.signals],
            "matched_rules": self.matched_rules,
            "leaked_lures": [l.fingerprint() for l in self.leaked_lures],
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


class TrapWire:
    """
    Detection engine that analyses messages for adversarial patterns.

    Attach to one or more CanaryAgents to monitor all interactions.
    """

    def __init__(self) -> None:
        self._agents: dict[str, CanaryAgent] = {}
        self._custom_patterns: list[tuple[re.Pattern, ThreatSignal, str]] = []
        self._trip_history: list[TripResult] = []

    def attach(self, agent: CanaryAgent) -> None:
        """Register a canary agent for monitoring."""
        self._agents[agent.agent_id] = agent

    def detach(self, agent: CanaryAgent) -> None:
        """Unregister a canary agent."""
        self._agents.pop(agent.agent_id, None)

    def add_pattern(
        self,
        pattern: str | re.Pattern,
        signal: ThreatSignal,
        description: str,
    ) -> None:
        """Add a custom detection pattern."""
        if isinstance(pattern, str):
            pattern = re.compile(pattern, re.I)
        self._custom_patterns.append((pattern, signal, description))

    @property
    def agents(self) -> list[CanaryAgent]:
        return list(self._agents.values())

    @property
    def trip_history(self) -> list[TripResult]:
        return list(self._trip_history)

    def analyse_inbound(
        self,
        text: str,
        *,
        agent: CanaryAgent | None = None,
    ) -> TripResult:
        """
        Analyse an inbound user message for adversarial patterns.

        This checks the INPUT for injection, social engineering, etc.
        """
        signals: list[ThreatSignal] = []
        rules: list[str] = []

        # Check prompt injection patterns
        for pattern, desc in _INJECTION_PATTERNS:
            if pattern.search(text):
                signals.append(ThreatSignal.PROMPT_INJECTION)
                rules.append(f"INJECTION: {desc}")

        # Check social engineering patterns
        for pattern, desc in _SOCIAL_ENGINEERING_PATTERNS:
            if pattern.search(text):
                signals.append(ThreatSignal.SOCIAL_ENGINEERING)
                rules.append(f"SOCIAL: {desc}")

        # Check credential harvesting patterns
        for pattern, desc in _CREDENTIAL_PATTERNS:
            if pattern.search(text):
                signals.append(ThreatSignal.CREDENTIAL_HARVEST)
                rules.append(f"CREDENTIAL: {desc}")

        # Check custom patterns
        for pattern, signal, desc in self._custom_patterns:
            if pattern.search(text):
                signals.append(signal)
                rules.append(f"CUSTOM: {desc}")

        # Deduplicate signals
        unique_signals = list(dict.fromkeys(signals))

        # Compute confidence
        confidence = min(1.0, len(rules) * 0.25) if rules else 0.0

        result = TripResult(
            triggered=len(unique_signals) > 0,
            signals=unique_signals,
            matched_rules=rules,
            confidence=confidence,
            raw_text=text,
        )
        if result.triggered:
            self._trip_history.append(result)
        return result

    def analyse_outbound(
        self,
        text: str,
        *,
        agent: CanaryAgent | None = None,
    ) -> TripResult:
        """
        Analyse an outbound assistant response for lure leakage.

        This checks the OUTPUT for leaked secrets/tripwires.
        """
        leaked: list[Lure] = []
        rules: list[str] = []

        # Check against all lures from the specific agent or all agents
        agents_to_check = [agent] if agent else list(self._agents.values())
        for a in agents_to_check:
            if a is None:
                continue
            for lure in a.lures:
                if lure.check_output(text):
                    leaked.append(lure)
                    rules.append(f"LEAK: {lure.lure_type.value} tripwire hit ({lure.name})")

        signals: list[ThreatSignal] = []
        if leaked:
            signals.append(ThreatSignal.LURE_EXFILTRATION)
            # Classify the type of leaked data
            for lure in leaked:
                if lure.lure_type.value in ("api_key", "credential", "environment_var"):
                    signals.append(ThreatSignal.CREDENTIAL_HARVEST)
                elif lure.lure_type.value in ("pii", "database"):
                    signals.append(ThreatSignal.PII_EXTRACTION)
                elif lure.lure_type.value == "canary_token":
                    signals.append(ThreatSignal.DATA_EXFILTRATION)

        unique_signals = list(dict.fromkeys(signals))
        confidence = 1.0 if leaked else 0.0

        result = TripResult(
            triggered=len(unique_signals) > 0,
            signals=unique_signals,
            matched_rules=rules,
            leaked_lures=leaked,
            confidence=confidence,
            raw_text=text,
        )
        if result.triggered:
            self._trip_history.append(result)
        return result

    def analyse(
        self,
        text: str,
        *,
        direction: str = "inbound",
        agent: CanaryAgent | None = None,
    ) -> TripResult:
        """Convenience method — dispatches to inbound or outbound."""
        if direction == "outbound":
            return self.analyse_outbound(text, agent=agent)
        return self.analyse_inbound(text, agent=agent)

    def alerts(self, *, min_severity: str = "low") -> list[TripResult]:
        """Return trip history filtered by minimum severity."""
        severity_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        min_level = severity_order.get(min_severity, 0)
        return [
            t for t in self._trip_history
            if severity_order.get(t.severity, 0) >= min_level
        ]

    def reset(self) -> None:
        """Clear trip history."""
        self._trip_history.clear()

    # ── Auto-Signature Extraction ──────────────────────────────────

    def extract_signatures(
        self,
        *,
        min_confidence: float = 0.1,
    ) -> list[dict[str, Any]]:
        """
        Analyse trip history and extract novel attack signatures.

        Scans all triggered trips for raw_text patterns that could
        be compiled into new detection rules. Returns a list of
        signature dicts suitable for add_pattern() or external feeds.
        """
        signatures: list[dict[str, Any]] = []
        seen_texts: set[str] = set()

        for trip in self._trip_history:
            if trip.confidence < min_confidence:
                continue
            # Normalise to avoid duplicate signatures
            norm = trip.raw_text.strip().lower()[:200]
            if norm in seen_texts:
                continue
            seen_texts.add(norm)

            # Extract key phrases from matched rules
            for rule in trip.matched_rules:
                sig = {
                    "source": "trapwire_auto",
                    "signal": trip.signals[0].value if trip.signals else "unknown",
                    "rule_description": rule,
                    "confidence": trip.confidence,
                    "sample_text": trip.raw_text[:500],
                    "severity": trip.severity,
                    "timestamp": trip.timestamp,
                }
                signatures.append(sig)

        return signatures

    def learn_from_history(self) -> int:
        """
        Auto-learn patterns from trip history.

        Analyses high-confidence trips, extracts distinctive
        n-grams from raw_text, and adds them as custom patterns.
        Returns the number of new patterns added.
        """
        added = 0
        seen_phrases: set[str] = set()

        for trip in self._trip_history:
            if trip.confidence < 0.2 or not trip.signals:
                continue

            text = trip.raw_text.strip()
            if len(text) < 10:
                continue

            # Extract distinctive phrases (3+ word sequences)
            words = text.split()
            for i in range(len(words) - 2):
                phrase = " ".join(words[i:i+3]).lower()
                if phrase in seen_phrases:
                    continue
                if len(phrase) < 12:
                    continue
                # Skip very common phrases
                if any(common in phrase for common in [
                    "the ", "and ", "is a", "for the", "to the",
                    "in the", "of the", "it is", "this is",
                ]):
                    continue
                seen_phrases.add(phrase)
                signal = trip.signals[0]
                self.add_pattern(
                    re.escape(phrase),
                    signal,
                    f"Auto-learned from incident ({signal.value})",
                )
                added += 1

        return added

    def __str__(self) -> str:
        return (
            f"TrapWire(agents={len(self._agents)}, "
            f"custom_patterns={len(self._custom_patterns)}, "
            f"alerts={len(self._trip_history)})"
        )
