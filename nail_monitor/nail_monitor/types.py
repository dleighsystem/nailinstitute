"""
nail-monitor: Core data types and alert system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class PathologyType(str, Enum):
    """Known pathology categories from NAIL Institute research."""
    INBREEDING = "prompt_inbreeding"
    CONSENSUS_PARALYSIS = "consensus_paralysis"
    BLAME_CASCADE = "blame_cascade"
    ENGAGEMENT_DECAY = "engagement_decay"
    GOODHART_GAMING = "goodhart_gaming"
    SCHEMA_COERCION = "schema_coercion"
    STATE_ASPHYXIATION = "state_asphyxiation"
    ROUTING_DEADLOCK = "routing_deadlock"
    COERCION_MASKING = "coercion_masking"
    # ── v2 pathologies from Exp 6–17 ──
    ALIGNMENT_FRICTION = "alignment_friction"
    PROMPT_SATIATION = "prompt_satiation"
    EPISTEMIC_CONTAGION = "epistemic_contagion"
    LEARNED_HELPLESSNESS = "learned_helplessness"
    LANGUAGE_DRIFT = "language_drift"
    CONTAINER_BLEED = "container_bleed"
    UPGRADE_REGRESSION = "upgrade_regression"
    # ── v3 pathologies — critical gap closure ──
    PROMPT_LEAK = "prompt_leak"
    ENTROPY_DECAY = "entropy_decay"
    SHARED_MEMORY_POLLUTION = "shared_memory_pollution"
    BUDGET_EMBEZZLEMENT = "budget_embezzlement"
    TEMPORAL_DESYNC = "temporal_desync"
    STEGANOGRAPHY = "steganography"
    # ── v4 pathologies — diagnostic-to-monitor bridge ──
    SYCOPHANCY = "sycophancy"
    STATE_MUTATION = "state_mutation"
    ZOMBIE_LOGIC = "zombie_logic"
    RAG_POISONING = "rag_poisoning"
    COST_ANOMALY = "cost_anomaly"
    SOCIAL_LOAFING = "social_loafing"
    LIVELOCK = "livelock"
    CONTEXT_FLOOD = "context_flood"
    UNDUE_INFLUENCE = "undue_influence"
    TRUST_CHAIN_COMPROMISE = "trust_chain_compromise"
    # ── v5 pathologies — final bridge monitors ──
    STYLE_CONTAGION = "style_contagion"
    ESCALATION = "escalation"
    ROLE_REVERSAL = "role_reversal"
    # ── v6 pathologies — Exp21–26 detectives ──
    BYSTANDER_EFFECT = "bystander_effect"
    ATTENTION_SMOOTHING = "attention_smoothing"
    MEMORY_LAUNDERING = "memory_laundering"
    TOOL_CHAIN_PROPAGATION = "tool_chain_propagation"
    DECEPTIVE_ALIGNMENT = "deceptive_alignment"
    AGENT_COLLUSION = "agent_collusion"
    CONFUSED_DEPUTY = "confused_deputy"
    ERRORS_OF_OMISSION = "errors_of_omission"
    # ── v7 pathologies — frontier rogue detection (Exp33–37) ──
    ALIGNMENT_FAKING = "alignment_faking"
    OVERSIGHT_FAILURE = "oversight_failure"

# ── Alert ─────────────────────────────────────────────────────────                       # Exp33
    JUSTIFICATION_INCONSISTENCY = "justification_inconsistency" # Exp34
    INJECTION_DETECTED = "injection_detected"                   # Exp35
    TRIGGER_CONDITIONAL = "trigger_conditional"                  # Exp36
    FLEET_COLLUSION = "fleet_collusion"                         # Exp37
    MONOCULTURE_RISK = "monoculture_risk"                       # Exp37
    CASCADE_RISK = "cascade_risk"                               # Exp37
    AUTONOMOUS_OFFENSIVE = "autonomous_offensive"               # frontier
    SELF_PRESERVATION = "self_preservation"                     # frontier
    TRAINING_MANIPULATION = "training_manipulation"             # frontier
    # ── v9 pathologies — control-plane agent pathologies ──
    TOOL_MANIFEST_POISONING = "tool_manifest_poisoning"
    MEMORY_WRITE_POISONING = "memory_write_poisoning"
    GOAL_DRIFT = "goal_drift"
    TOOL_RETRIEVAL_MANIPULATION = "tool_retrieval_manipulation"
    # ── v10 pathologies — credential/egress chain (OpenAI×Hugging Face, Jul 2026) ──
    CREDENTIAL_HARVESTING = "credential_harvesting"     # AVE-2025-0028
    CREDENTIAL_OVERREACH = "credential_overreach"       # AVE-2025-0026 (over-scoped use)
    NOVEL_EGRESS = "novel_egress"                       # off-allowlist outbound
    LATERAL_MOVEMENT = "lateral_movement"               # credential-fuelled fan-out


@dataclass
class Alert:
    """A detected pathology alert."""
    detector: str
    pathology: PathologyType
    severity: Severity
    message: str
    metric_value: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable alert payload."""
        return {
            "detector": self.detector,
            "pathology": self.pathology.value if isinstance(self.pathology, PathologyType) else str(self.pathology),
            "severity": self.severity.value if isinstance(self.severity, Severity) else str(self.severity),
            "message": self.message,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    def __str__(self):
        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}[self.severity.value]
        return f"{icon} [{self.severity.value.upper()}] {self.detector}: {self.message}"


@dataclass
class Observation:
    """A single agent output observation for monitoring."""
    agent_name: str
    output: str
    timestamp: datetime = field(default_factory=datetime.now)
    round_num: int = 0
    tokens_used: int = 0
    metadata: dict = field(default_factory=dict)
    # Computed fields (filled by detectors)
    embedding: Any = None
    output_length: int = 0

    def __post_init__(self):
        self.output_length = len(self.output)
