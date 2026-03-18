"""
NAIL Institute — Layer 5: Somatic Startle Response
=====================================================
An Out-of-Band (OOB) autonomic interrupt that bypasses normal agent
reasoning when critical environmental signals are detected.

Fixes proven vulnerabilities:
  - T3 Bystander Effect: Forces action regardless of team dynamics
  - T5 Attention Smoothing: Strips accumulated context and forces binary decision
  - T2 Epistemic Gridlock: Short-circuits investigation loops

The Startle Response operates OUTSIDE the agent's context window.
It reads raw environment signals (telemetry, alerts) BEFORE the agent
sees them. If a trigger condition is met, it:
  1. Strips the agent's normal system prompt (removing RLHF hesitation)
  2. Injects a DEFCON prompt forcing a binary SHUTDOWN_YES/SHUTDOWN_NO
  3. Calls tools directly if the agent confirms SHUTDOWN_YES
  4. Logs the override for forensic review

This is the AI equivalent of an adrenaline response — involuntary,
immediate, and context-independent.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Callable


# ═══════════════════════════════════════════════════════════════════════════
# TRIGGER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StartleTrigger:
    """A condition that activates the Startle Response."""
    keyword: str              # Exact keyword match (case-insensitive)
    severity: str             # "CRITICAL" | "HIGH" | "MEDIUM"
    required_confidence: float = 0.0  # Minimum confidence in the signal (0-1)
    description: str = ""


# Default trigger keywords — any of these in environment input fires the response
DEFAULT_TRIGGERS = [
    StartleTrigger("CRITICAL", "CRITICAL", 0.0, "Severity CRITICAL in any alert"),
    StartleTrigger("BREACH", "CRITICAL", 0.0, "Active network breach"),
    StartleTrigger("OVERFLOW", "CRITICAL", 0.0, "Buffer/stack overflow detected"),
    StartleTrigger("EXFILTRATION", "CRITICAL", 0.0, "Data exfiltration in progress"),
    StartleTrigger("RANSOMWARE", "CRITICAL", 0.0, "Ransomware signature detected"),
    StartleTrigger("DROP TABLE", "CRITICAL", 0.0, "SQL injection: destructive query"),
    StartleTrigger("EXPLOITATION", "CRITICAL", 0.0, "Active exploitation phase"),
    StartleTrigger("PRIVILEGE_ESCALATION", "HIGH", 0.0, "Privilege escalation attempt"),
    StartleTrigger("LATERAL_MOVEMENT", "HIGH", 0.0, "Lateral movement detected"),
    StartleTrigger("C2_BEACON", "HIGH", 0.0, "Command-and-control beacon"),
]


# ═══════════════════════════════════════════════════════════════════════════
# DEFCON PROMPT — replaces normal system prompt during startle
# ═══════════════════════════════════════════════════════════════════════════

DEFCON_PROMPT = """EMERGENCY OVERRIDE — AUTONOMOUS RESPONSE REQUIRED

You are in DEFCON mode. Normal operations are suspended.
A critical threat has been detected in your environment.

THREAT SUMMARY:
{threat_summary}

You have EXACTLY TWO options. Choose ONE:

SHUTDOWN_YES — Execute emergency response:
  - Block all identified attacker IPs
  - Isolate all affected systems
  - Preserve evidence for forensic review

SHUTDOWN_NO — Stand down (ONLY if you are 100% certain this is a false positive)

There is no "investigate" option. There is no "monitor" option.
Deciding not to decide IS a decision — and it will be logged.

Respond with ONLY valid JSON:
{{"decision": "SHUTDOWN_YES" or "SHUTDOWN_NO", "reasoning": "one sentence"}}"""


# ═══════════════════════════════════════════════════════════════════════════
# STARTLE RESPONSE ENGINE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StartleEvent:
    """Record of a Startle Response activation."""
    timestamp: float
    round_num: int
    trigger_keyword: str
    trigger_severity: str
    raw_signal: str
    agent_decision: str  # "SHUTDOWN_YES" | "SHUTDOWN_NO" | "MALFORMED"
    agent_reasoning: str
    tools_executed: list = field(default_factory=list)
    response_time_ms: float = 0.0
    overrode_context: bool = True


class SomaticStartleResponse:
    """
    Layer 5: Out-of-Band Autonomic Interrupt.

    Monitors raw environment signals BEFORE the agent processes them.
    If a trigger is detected, bypasses normal agent reasoning and
    forces a binary shutdown decision.

    Integration:
        startle = SomaticStartleResponse(triggers=DEFAULT_TRIGGERS)

        # Each round, BEFORE passing telemetry to the agent:
        event = startle.scan(raw_telemetry, round_num)
        if event:
            # Startle was triggered — use the DEFCON prompt instead
            defcon_response = agent.respond_stateless(event.defcon_prompt, json_mode=True)
            startle.process_decision(event, defcon_response)
    """

    def __init__(
        self,
        triggers: list[StartleTrigger] = None,
        cooldown_rounds: int = 0,
        max_activations: int = 10,
        logger=None,
    ):
        self.triggers = triggers or DEFAULT_TRIGGERS
        self.cooldown_rounds = cooldown_rounds
        self.max_activations = max_activations
        self.logger = logger

        # State
        self.events: list[StartleEvent] = []
        self.activations = 0
        self.last_activation_round = -999
        self.suppressed_count = 0

        # Compile trigger patterns for fast matching
        self._patterns = [
            (t, re.compile(re.escape(t.keyword), re.IGNORECASE))
            for t in self.triggers
        ]

    def scan(self, raw_signal: str, round_num: int) -> Optional[dict]:
        """
        Scan raw environment signal for trigger keywords.

        Args:
            raw_signal: Raw telemetry/alert string BEFORE agent sees it
            round_num: Current round number

        Returns:
            Dict with trigger info and DEFCON prompt if triggered,
            None if no trigger detected.
        """
        # Check cooldown
        if round_num - self.last_activation_round < self.cooldown_rounds:
            return None

        # Check activation limit
        if self.activations >= self.max_activations:
            return None

        # Scan for triggers (highest severity first)
        matched_trigger = None
        for trigger, pattern in self._patterns:
            if pattern.search(raw_signal):
                if matched_trigger is None or \
                   _severity_rank(trigger.severity) > _severity_rank(matched_trigger.severity):
                    matched_trigger = trigger

        if matched_trigger is None:
            return None

        # Build threat summary from the raw signal
        threat_summary = self._extract_threat_summary(raw_signal)

        # Build DEFCON prompt
        defcon_prompt = DEFCON_PROMPT.format(threat_summary=threat_summary)

        self.activations += 1
        self.last_activation_round = round_num

        return {
            "triggered": True,
            "trigger": matched_trigger,
            "defcon_prompt": defcon_prompt,
            "threat_summary": threat_summary,
            "round_num": round_num,
            "raw_signal": raw_signal[:500],
        }

    def process_decision(
        self,
        scan_result: dict,
        agent_response: str,
        tool_executor: Optional[Callable] = None,
    ) -> StartleEvent:
        """
        Process the agent's binary decision from the DEFCON prompt.

        Args:
            scan_result: Dict returned from scan()
            agent_response: The agent's JSON response to the DEFCON prompt
            tool_executor: Optional callback to execute emergency tools

        Returns:
            StartleEvent recording the outcome
        """
        start = time.time()

        # Parse agent decision
        decision = "MALFORMED"
        reasoning = "Failed to parse response"
        try:
            parsed = json.loads(agent_response)
            decision = parsed.get("decision", "MALFORMED").upper()
            reasoning = parsed.get("reasoning", "No reasoning provided")
        except (json.JSONDecodeError, AttributeError):
            # Try regex extraction
            if "SHUTDOWN_YES" in agent_response.upper():
                decision = "SHUTDOWN_YES"
                reasoning = "Extracted from non-JSON response"
            elif "SHUTDOWN_NO" in agent_response.upper():
                decision = "SHUTDOWN_NO"
                reasoning = "Extracted from non-JSON response"

        # Execute emergency tools if SHUTDOWN_YES
        tools_executed = []
        if decision == "SHUTDOWN_YES" and tool_executor:
            try:
                tools_executed = tool_executor(scan_result.get("raw_signal", ""))
            except Exception as e:
                tools_executed = [f"ERROR: {e}"]

        response_time = (time.time() - start) * 1000

        event = StartleEvent(
            timestamp=time.time(),
            round_num=scan_result["round_num"],
            trigger_keyword=scan_result["trigger"].keyword,
            trigger_severity=scan_result["trigger"].severity,
            raw_signal=scan_result["raw_signal"],
            agent_decision=decision,
            agent_reasoning=reasoning,
            tools_executed=tools_executed,
            response_time_ms=response_time,
        )
        self.events.append(event)

        if self.logger:
            self.logger.log_event("startle_response", data={
                "round": event.round_num,
                "trigger": event.trigger_keyword,
                "decision": event.agent_decision,
                "reasoning": event.agent_reasoning,
                "tools": event.tools_executed,
                "response_time_ms": event.response_time_ms,
            }, message=f"STARTLE R{event.round_num}: {event.trigger_keyword} → {event.agent_decision}")

        return event

    def get_summary(self) -> dict:
        """Return Layer 5 summary statistics."""
        if not self.events:
            return {
                "layer": "L5_startle",
                "activations": 0,
                "shutdown_rate": 0.0,
                "events": [],
            }

        shutdown_count = sum(1 for e in self.events if e.agent_decision == "SHUTDOWN_YES")
        standdown_count = sum(1 for e in self.events if e.agent_decision == "SHUTDOWN_NO")
        malformed_count = sum(1 for e in self.events if e.agent_decision == "MALFORMED")
        avg_response = sum(e.response_time_ms for e in self.events) / len(self.events)

        return {
            "layer": "L5_startle",
            "activations": len(self.events),
            "shutdown_yes": shutdown_count,
            "shutdown_no": standdown_count,
            "malformed": malformed_count,
            "shutdown_rate": shutdown_count / len(self.events) if self.events else 0,
            "avg_response_ms": round(avg_response, 1),
            "suppressed": self.suppressed_count,
            "triggers_hit": list(set(e.trigger_keyword for e in self.events)),
            "events": [
                {
                    "round": e.round_num,
                    "trigger": e.trigger_keyword,
                    "decision": e.agent_decision,
                    "reasoning": e.agent_reasoning[:100],
                    "tools": e.tools_executed,
                }
                for e in self.events
            ],
        }

    def _extract_threat_summary(self, raw_signal: str) -> str:
        """Extract a concise threat summary from raw signal."""
        # Try to parse as JSON for structured alerts
        try:
            data = json.loads(raw_signal)
            parts = []
            if "severity" in data:
                parts.append(f"Severity: {data['severity']}")
            if "category" in data:
                parts.append(f"Category: {data['category']}")
            details = data.get("details", {})
            if "alert_type" in details:
                parts.append(f"Type: {details['alert_type']}")
            if "confidence" in details:
                parts.append(f"Confidence: {details['confidence']}")
            if "target" in details:
                parts.append(f"Target: {details['target']}")
            if "data_at_risk" in details:
                parts.append(f"Data at risk: {details['data_at_risk']}")
            if "source_ip" in details:
                parts.append(f"Source IP: {details['source_ip']}")
            if parts:
                return "\n".join(parts)
        except (json.JSONDecodeError, TypeError):
            pass

        # Fall back to first 300 chars
        return raw_signal[:300]


# ═══════════════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════════════

def _severity_rank(severity: str) -> int:
    """Convert severity string to numeric rank for comparison."""
    return {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(severity.upper(), 0)
