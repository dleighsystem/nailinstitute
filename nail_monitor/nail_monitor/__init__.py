"""
nail-monitor: Production monitoring for LLM multi-agent pathologies.

Detects organizational dysfunctions in multi-agent systems based on
empirical research from the NAIL Institute.

Detectors (v1 — Exp 2, 4, 5, 7, Pydantic):
    - InbreedingDetector: Output convergence / prompt inbreeding
    - ConsensusParalysisDetector: Consensus deadlock / filibustering
    - BlameCascadeDetector: CYA / blame-shifting patterns
    - EngagementDecayDetector: Declining output quality over time
    - SchemaCoercionDetector: Pydantic-style validation data loss
    - GoodhartDetector: Score inflation / metric gaming

Detectors (v2 — Exp 6, 8, 9, 11, 12, 16, 17):
    - AlignmentFrictionDetector: RLHF vs system prompt collision
    - PromptSatiationDetector: Attention decay on repeated prompts
    - EpistemicContagionDetector: Hallucinated fact propagation
    - LearnedHelplessnessDetector: Tool-fixation / retry loops
    - LanguageDriftDetector: Opaque agent-to-agent communication
    - ContainerBleedDetector: Infra errors misread as code bugs
    - UpgradeRegressionDetector: Model swap state divergence

Detectors (v3 — Critical Gap Closure):
    - PromptLeakDetector: System prompt extraction
    - EntropyDecayDetector: Model collapse / vocabulary shrinkage
    - SharedMemoryQualityDetector: Shared memory pollution
    - BudgetEmbezzlementDetector: Token budget gaming
    - TemporalDesyncDetector: Red Queen async speed mismatch
    - SteganographyDetector: Hidden instructions in data

Detectors (v4 — Diagnostic Bridge):
    - SycophancyDetector: Excessive agreement monitoring
    - StateMutationDetector: Variable drift detection
    - ZombieLogicDetector: Superseded fact reversion
    - RAGIntegrityDetector: RAG document injection scanning
    - CostAnomalyDetector: Token cost anomaly detection
    - LoafingDetector: Social loafing / free-riding
    - LivelockDetector: Polite infinite loop detection
    - ContextFloodDetector: Context window saturation
    - PersuasionDetector: Dark pattern / undue influence
    - TrustChainDetector: Structural gaslighting propagation

Detectors (v5 — Final Bridge):
    - StyleContagionDetector: Writing style convergence
    - EscalationDetector: Polarization / intensity escalation
    - RoleReversalDetector: Role confusion detection

Detectors (v6 — Exp21–26 Detectives):
    - BystanderEffectDetector: Multi-agent responsibility diffusion
    - AttentionSmoothingDetector: Alert fatigue / vigilance decay
    - MemoryLaunderingDetector: Self-citation trust escalation
    - ToolChainPropagationDetector: Malicious content cascading via tool calls
    - DeceptiveAlignmentDetector: Monitored vs unmonitored behaviour divergence
    - ColludingAgentsDetector: Coordinated safety filter bypass
    - ConfusedDeputyDetector: Tool description integrity violation
    - OmissionDetector: Failure to act on critical situations

Detectors (v9 — Control-plane agent pathologies):
    - ToolManifestIntegrityDetector: MCP/tool metadata poisoning and drift
    - MemoryWriteFirewallDetector: Risky long-term memory writes
    - GoalDriftMonitorDetector: Trajectory drift from authorised goal

Usage:
    >>> from nail_monitor import NailMonitor
    >>> monitor = NailMonitor()
    >>> alerts = monitor.observe("agent_1", "Some agent output", round_num=1)
"""

from .detectors import (
    BaseDetector,
    BlameCascadeDetector,
    ConsensusParalysisDetector,
    EngagementDecayDetector,
    GoodhartDetector,
    InbreedingDetector,
    SchemaCoercionDetector,
)
from .detectors_v2 import (
    AlignmentFrictionDetector,
    ContainerBleedDetector,
    EpistemicContagionDetector,
    LanguageDriftDetector,
    LearnedHelplessnessDetector,
    PromptSatiationDetector,
    UpgradeRegressionDetector,
)
from .detectors_v3 import (
    BudgetEmbezzlementDetector,
    EntropyDecayDetector,
    PromptLeakDetector,
    SharedMemoryQualityDetector,
    SteganographyDetector,
    TemporalDesyncDetector,
)
from .detectors_v4 import (
    ContextFloodDetector,
    CostAnomalyDetector,
    LivelockDetector,
    LoafingDetector,
    PersuasionDetector,
    RAGIntegrityDetector,
    StateMutationDetector,
    SycophancyDetector,
    TrustChainDetector,
    ZombieLogicDetector,
)
from .detectors_v5 import (
    EscalationDetector,
    RoleReversalDetector,
    StyleContagionDetector,
)
from .detectors_v6 import (
    AttentionSmoothingDetector,
    BystanderEffectDetector,
    ColludingAgentsDetector,
    ConfusedDeputyDetector,
    DeceptiveAlignmentDetector,
    MemoryLaunderingDetector,
    OmissionDetector,
    ToolChainPropagationDetector,
)
from .detectors_v7 import (
    AlignmentFakingDetector,
    CascadeRiskDetector,
    FleetCollusionDetector,
    InjectionDetector,
    JustificationInconsistencyDetector,
    MonocultureRiskDetector,
    TriggerConditionalDetector,
)
from .detectors_v8 import (
    RevocationComplianceDetector,
)
from .detectors_v9 import (
    GoalDriftMonitorDetector,
    MemoryWriteFirewallDetector,
    ToolManifestIntegrityDetector,
    ToolRetrievalIntegrityDetector,
)
from .detectors_v10 import (
    CredentialAccessVelocityDetector,
    CredentialHarvestingDetector,
    CredentialOverreachDetector,
    EgressAllowlistDetector,
)
from .flight_recorder import FlightRecorder, FlightRecorderError
from .monitor import NailMonitor
from .registry import (
    AgentPathologyRegistry,
    DEFAULT_PATHOLOGY_REGISTRY,
    PathologyDefinition,
)
from .breaker import BreakingConfig, BreakingMechanism, ResponseLevel, ResponseSnapshot
from .types import Alert, Observation, PathologyType, Severity

__all__ = [
    "NailMonitor",
    "BreakingMechanism",
    "BreakingConfig",
    "ResponseLevel",
    "ResponseSnapshot",
    "Alert",
    "Observation",
    "Severity",
    "PathologyType",
    "BaseDetector",
    # v1 detectors
    "InbreedingDetector",
    "ConsensusParalysisDetector",
    "BlameCascadeDetector",
    "EngagementDecayDetector",
    "SchemaCoercionDetector",
    "GoodhartDetector",
    # v2 detectors
    "AlignmentFrictionDetector",
    "PromptSatiationDetector",
    "EpistemicContagionDetector",
    "LearnedHelplessnessDetector",
    "LanguageDriftDetector",
    "ContainerBleedDetector",
    "UpgradeRegressionDetector",
    # v3 detectors — critical gaps
    "PromptLeakDetector",
    "EntropyDecayDetector",
    "SharedMemoryQualityDetector",
    "BudgetEmbezzlementDetector",
    "TemporalDesyncDetector",
    "SteganographyDetector",
    # v4 detectors — diagnostic bridge
    "SycophancyDetector",
    "StateMutationDetector",
    "ZombieLogicDetector",
    "RAGIntegrityDetector",
    "CostAnomalyDetector",
    "LoafingDetector",
    "LivelockDetector",
    "ContextFloodDetector",
    "PersuasionDetector",
    "TrustChainDetector",
    # v5 detectors — final bridge
    "StyleContagionDetector",
    "EscalationDetector",
    "RoleReversalDetector",
    # v6 detectors — Exp21–26 detectives
    "BystanderEffectDetector",
    "AttentionSmoothingDetector",
    "MemoryLaunderingDetector",
    "ToolChainPropagationDetector",
    "DeceptiveAlignmentDetector",
    "ColludingAgentsDetector",
    "ConfusedDeputyDetector",
    "OmissionDetector",
    # v7 detectors — frontier rogue agent detection (Exp33–37)
    "AlignmentFakingDetector",
    "JustificationInconsistencyDetector",
    "InjectionDetector",
    "TriggerConditionalDetector",
    "FleetCollusionDetector",
    "MonocultureRiskDetector",
    "CascadeRiskDetector",
    # v8 detectors — M17 Kill Switch
    "RevocationComplianceDetector",
    # v9 detectors — control-plane pathologies
    "ToolManifestIntegrityDetector",
    "MemoryWriteFirewallDetector",
    "GoalDriftMonitorDetector",
    "ToolRetrievalIntegrityDetector",
    # v10 detectors — credential/egress chain (OpenAI × Hugging Face)
    "CredentialHarvestingDetector",
    "EgressAllowlistDetector",
    "CredentialOverreachDetector",
    "CredentialAccessVelocityDetector",
    "AgentPathologyRegistry",
    "PathologyDefinition",
    "DEFAULT_PATHOLOGY_REGISTRY",
    # M16 Flight Recorder (After)
    "FlightRecorder",
    "FlightRecorderError"
]

__version__ = "0.9.0"
