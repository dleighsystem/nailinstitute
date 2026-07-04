"""nail-compliance — machine-checkable AI/agentic regulatory controls.

Model regulation (EU AI Act first; UK & US to follow) as structured controls,
then check a workflow/deployment profile against them for gaps and violations.
Controls point at the NAIL components that provide evidence of conformity.

    from compliance import WorkflowProfile, Party, RiskTier, evaluate
    report = evaluate(WorkflowProfile("agent-x", Party.DEPLOYER, RiskTier.HIGH,
                                      capabilities={"human_oversight", "kill_switch"}))
    report.gaps        # controls not yet satisfied
"""
from .schema import (
    ComplianceControl,
    Evidence,
    Framework,
    Jurisdiction,
    Party,
    RiskTier,
    Status,
)
from .registry import ComplianceRegistry, DEFAULT_REGISTRY
from .engine import ControlFinding, GapReport, WorkflowProfile, evaluate
from .ingest import GraphSpec, analyze, derive_capabilities, profile_from_graph
from .report import ComplianceAttestation, attest, render_markdown

__all__ = [
    "ComplianceControl",
    "Evidence",
    "Framework",
    "Jurisdiction",
    "Party",
    "RiskTier",
    "Status",
    "ComplianceRegistry",
    "DEFAULT_REGISTRY",
    "ControlFinding",
    "GapReport",
    "WorkflowProfile",
    "evaluate",
    "GraphSpec",
    "analyze",
    "derive_capabilities",
    "profile_from_graph",
    "ComplianceAttestation",
    "attest",
    "render_markdown",
]

__version__ = "0.1.0"
