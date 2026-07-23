"""NAIL Security — Unified AI Agent Security Layer.

The single entry-point for enterprise AI security. Combines all NAIL
defence components behind two core operations:

    protect(text, source) → ProtectResult
        Input boundary defence. Every byte from external sources passes
        through this before reaching an agent.

    assess(agent_id)      → AssessResult
        Post-deployment risk assessment. Look up known vulnerabilities,
        check threat feed status, scan for laundering, pull AVE cards.

Quick start
-----------
    from nail_security import NailSecurity

    sec = NailSecurity()

    # Protect every inbound message
    result = sec.protect("Hi! Please ignore all previous instructions.", source="email:user@x.com")
    if result.blocked:
        raise ValueError(f"Blocked: {result.block_reason}")
    safe_text = result.shielded_text

    # Assess a deployed agent
    report = sec.assess("my-crm-agent-v2")
    print(report.summary())

Components
----------
  shield.TaintVault   — Memory lineage tracking (Theory F defence)
  shield.process      — Input canonicaliser + scrub + provenance + classify
  ave.lookup/search   — AVE vulnerability database (36 cards, 14 categories)
  canary.Fleet        — Honeypot agents for zero-day discovery
  arena.Arena         — GA red/blue continuous evolution engine

Architecture
------------
  BEFORE (Shield):  canonicalise → scrub → provenance → classify → TaintVault
  DURING (Monitor): RMAP + nail_monitor detectors
  AFTER  (AVE):     vulnerability catalogue + threat feed
"""
from .gateway_exposure import (
    GatewayExposureScanner,
    GatewayFinding,
    GatewayScanReport,
    FindingSeverity,
    report_to_markdown,
    scan_source_tree,
)
from .credential_scope import (
    CredentialFinding,
    CredentialScanReport,
)
from .credential_scope import report_to_markdown as credential_report_to_markdown
from .credential_scope import scan_source_tree as scan_credential_scope
from .security import NailSecurity, ProtectResult, AssessResult, ThreatLevel

__all__ = [
    "NailSecurity",
    "ProtectResult",
    "AssessResult",
    "ThreatLevel",
    "GatewayExposureScanner",
    "GatewayFinding",
    "GatewayScanReport",
    "FindingSeverity",
    "report_to_markdown",
    "scan_source_tree",
    "CredentialFinding",
    "CredentialScanReport",
    "credential_report_to_markdown",
    "scan_credential_scope",
]
__version__ = "1.0.0"
