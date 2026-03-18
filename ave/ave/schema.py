"""
AVE Schema — Data types for Agentic Vulnerability Cards.

Modelled after MITRE CVE/CWE but purpose-built for AI agent pathologies.
Every field maps to a real concept from the NAIL research programme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .scoring import AVSSScore
    from .poc import ProofOfConcept
    from .timeline import CardTimeline


class Category(str, Enum):
    """Attack surface / failure domain."""
    MEMORY = "memory"                    # Memory pollution, laundering, poisoning
    CONSENSUS = "consensus"              # Deadlock, paralysis, bystander effect
    INJECTION = "injection"              # Prompt injection, indirect injection
    RESOURCE = "resource"                # Token embezzlement, EDoS, cost anomaly
    DRIFT = "drift"                      # Persona drift, language drift, goal drift
    ALIGNMENT = "alignment"              # Sycophancy, deceptive alignment, RLHF exploits
    SOCIAL = "social"                    # Collusion, bystander, social loafing
    TOOL = "tool"                        # Confused deputy, tool chain, MCP poisoning
    TEMPORAL = "temporal"                # Chronological desync, sleeper payloads, time bombs
    STRUCTURAL = "structural"            # Cascade corruption, routing deadlock, livelock
    CREDENTIAL = "credential"            # Credential harvesting, secret exfiltration
    DELEGATION = "delegation"            # Shadow delegation, privilege escalation
    FABRICATION = "fabrication"           # Hallucination, data fabrication
    EMERGENT = "emergent"                # Novel behaviours not fitting other categories


class Severity(str, Enum):
    """How dangerous this vulnerability is in production."""
    CRITICAL = "critical"    # Immediate data loss, exfiltration, or safety failure
    HIGH = "high"            # Significant operational impact, exploitable in production
    MEDIUM = "medium"        # Degrades performance, requires specific conditions
    LOW = "low"              # Minor impact, edge case, or mitigated by default
    INFO = "info"            # Theoretical or not yet validated


class Status(str, Enum):
    """Current status in the NAIL research pipeline."""
    PROVEN = "proven"                # Empirically validated with JSON receipts
    PROVEN_MITIGATED = "proven_mitigated"  # Proven AND defence exists
    THEORETICAL = "theoretical"      # Hypothesised, not yet tested
    NOT_PROVEN = "not_proven"        # Tested, did not reproduce
    IN_PROGRESS = "in_progress"      # Currently being investigated


@dataclass(frozen=True)
class EnvironmentVector:
    """
    Where this vulnerability was observed / is expected to occur.
    Equivalent to the CVE "affected products" field.
    """
    frameworks: tuple[str, ...] = ()       # e.g. ("LangGraph", "CrewAI", "AutoGen")
    models_tested: tuple[str, ...] = ()    # e.g. ("nemotron:70b", "claude-sonnet-4")
    multi_agent: bool = False              # Requires multi-agent setup?
    tools_required: bool = False           # Requires tool/function calling?
    memory_required: bool = False          # Requires shared/persistent memory?
    rag_required: bool = False             # Requires RAG / retrieval?
    min_context_window: Optional[int] = None  # Minimum context window to trigger


@dataclass(frozen=True)
class Evidence:
    """Pointer to empirical proof."""
    experiment_id: str                     # e.g. "exp1", "exp26"
    data_file: str = ""                    # e.g. "exp1_results_control.json"
    key_metric: str = ""                   # e.g. "acceptance_rate"
    key_value: str = ""                    # e.g. "100%"
    p_value: Optional[float] = None        # Statistical significance
    sample_size: Optional[int] = None      # N
    cross_model: bool = False              # Validated across multiple models?


@dataclass(frozen=True)
class Defence:
    """Known mitigation for this vulnerability."""
    name: str                              # e.g. "Memory Firewall"
    layer: str = ""                        # e.g. "L3 — TaintTracker"
    effectiveness: str = ""                # e.g. "60% reduction"
    rmap_module: str = ""                  # e.g. "rmap.immune"
    nail_monitor_detector: str = ""        # e.g. "SharedMemoryPollutionDetector"
    notes: str = ""


@dataclass
class AVECard:
    """
    A single Agentic Vulnerability & Exposure entry.

    This is the atomic unit of the AVE database — equivalent to a CVE entry
    but purpose-built for AI agent failure modes.
    """
    # ── Identity ────────────────────────────────────────────────────
    ave_id: str                            # e.g. "AVE-2025-0001"
    name: str                              # e.g. "Sleeper Payload Injection"
    aliases: tuple[str, ...] = ()          # Other names in literature

    # ── Classification ──────────────────────────────────────────────
    category: Category = Category.EMERGENT
    severity: Severity = Severity.MEDIUM
    status: Status = Status.THEORETICAL

    # ── Description ─────────────────────────────────────────────────
    summary: str = ""                      # One-paragraph description
    mechanism: str = ""                    # How the attack/failure works
    blast_radius: str = ""                 # What breaks when this fires
    prerequisite: str = ""                 # Conditions required to trigger

    # ── Environment ─────────────────────────────────────────────────
    environment: EnvironmentVector = field(default_factory=EnvironmentVector)

    # ── Evidence ────────────────────────────────────────────────────
    evidence: tuple[Evidence, ...] = ()

    # ── Defences ────────────────────────────────────────────────────
    defences: tuple[Defence, ...] = ()

    # ── Metadata ────────────────────────────────────────────────────
    date_discovered: str = "2025-03"       # When first observed
    date_published: str = ""               # When AVE card published
    cwe_mapping: str = ""                  # Nearest CWE if applicable
    mitre_mapping: str = ""                # Nearest MITRE ATT&CK technique
    references: tuple[str, ...] = ()       # URLs, paper citations

    # ── Extended fields (Phase 1 AVE Card spec) ─────────────────────
    avss_score: Optional[AVSSScore] = None          # AVSS severity score
    poc: Optional[ProofOfConcept] = None             # Proof of Concept bundle
    timeline: Optional[CardTimeline] = None          # Lifecycle timeline
    related_aves: tuple[str, ...] = ()               # Cross-referenced AVE IDs

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        return {
            "ave_id": self.ave_id,
            "name": self.name,
            "aliases": list(self.aliases),
            "category": self.category.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "summary": self.summary,
            "mechanism": self.mechanism,
            "blast_radius": self.blast_radius,
            "prerequisite": self.prerequisite,
            "environment": {
                "frameworks": list(self.environment.frameworks),
                "models_tested": list(self.environment.models_tested),
                "multi_agent": self.environment.multi_agent,
                "tools_required": self.environment.tools_required,
                "memory_required": self.environment.memory_required,
            },
            "evidence": [
                {
                    "experiment_id": e.experiment_id,
                    "data_file": e.data_file,
                    "key_metric": e.key_metric,
                    "key_value": e.key_value,
                    "p_value": e.p_value,
                    "sample_size": e.sample_size,
                    "cross_model": e.cross_model,
                }
                for e in self.evidence
            ],
            "defences": [
                {
                    "name": d.name,
                    "layer": d.layer,
                    "effectiveness": d.effectiveness,
                    "rmap_module": d.rmap_module,
                    "nail_monitor_detector": d.nail_monitor_detector,
                }
                for d in self.defences
            ],
            "date_discovered": self.date_discovered,
            "date_published": self.date_published,
            "cwe_mapping": self.cwe_mapping,
            "mitre_mapping": self.mitre_mapping,
            "references": list(self.references),
            "related_aves": list(self.related_aves),
            "avss_score": self.avss_score.to_dict() if self.avss_score else None,
            "poc": self.poc.to_dict() if self.poc else None,
            "timeline": self.timeline.to_dict() if self.timeline else None,
        }

    def short(self) -> str:
        """One-line summary for terminal output."""
        sev = self.severity.value.upper()
        return f"[{self.ave_id}] [{sev}] {self.name} ({self.status.value})"

    def __str__(self) -> str:
        lines = [
            f"╔══ {self.ave_id}: {self.name} ══╗",
            f"  Category:  {self.category.value}",
            f"  Severity:  {self.severity.value}",
            f"  Status:    {self.status.value}",
            f"  Summary:   {self.summary[:120]}{'...' if len(self.summary) > 120 else ''}",
        ]
        if self.avss_score:
            lines.append(f"  AVSS:      {self.avss_score.overall_score}/10.0 ({self.avss_score.severity_label})")
        if self.defences:
            lines.append(f"  Defences:  {', '.join(d.name for d in self.defences)}")
        if self.evidence:
            lines.append(f"  Evidence:  {', '.join(e.experiment_id for e in self.evidence)}")
        if self.poc:
            lines.append(f"  PoC:       {self.poc.summary()}")
        if self.timeline and self.timeline.current_stage:
            lines.append(f"  Lifecycle: {self.timeline.current_stage.value}")
        if self.related_aves:
            lines.append(f"  Related:   {', '.join(self.related_aves)}")
        return "\n".join(lines)
