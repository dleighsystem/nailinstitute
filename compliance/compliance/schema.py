"""Compliance & Governance schema — machine-checkable regulatory controls.

Models AI / agentic regulation (EU AI Act first; UK & US to follow) as structured
``ComplianceControl`` records, so a workflow or deployment can be checked against
them for gaps and violations — "an AVE, but for regulations".

Each control declares the **capabilities** a deployment must have to satisfy it
(and, for prohibited practices, capabilities whose presence is a violation) and
points at the **NAIL components** that provide evidence of conformity.

NOTE: this is decision-support tooling, **not legal advice** — control content
must be validated by a qualified person and is dated because the regulatory
target is moving.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Jurisdiction(str, Enum):
    EU = "eu"
    UK = "uk"
    US = "us"


class Framework(str, Enum):
    EU_AI_ACT = "eu_ai_act"
    GDPR = "gdpr"
    UK_GDPR = "uk_gdpr"
    UK_AI_PRINCIPLES = "uk_ai_principles"
    NIST_AI_RMF = "nist_ai_rmf"
    US_STATE_LAW = "us_state_law"


class Party(str, Enum):
    """Who bears the obligation — the EU AI Act's central Provider/Deployer split."""
    PROVIDER = "provider"
    DEPLOYER = "deployer"
    BOTH = "both"


class RiskTier(str, Enum):
    UNACCEPTABLE = "unacceptable"
    HIGH = "high"
    LIMITED = "limited"
    MINIMAL = "minimal"
    GPAI = "gpai"          # general-purpose AI model
    ANY = "any"


class Status(str, Enum):
    """Result of checking a control against a workflow / deployment profile."""
    SATISFIED = "satisfied"
    PARTIAL = "partial"
    GAP = "gap"
    VIOLATION = "violation"      # a prohibited capability is present
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Evidence:
    """A NAIL component / artifact that provides proof a control is met."""
    name: str
    nail_component: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "nail_component": self.nail_component, "notes": self.notes}


@dataclass(frozen=True)
class ComplianceControl:
    control_id: str                              # e.g. "EU-AIA-ART12"
    jurisdiction: Jurisdiction
    framework: Framework
    reference: str                               # "Article 12", "GOVERN 1.1"
    title: str
    party: Party
    requirement: str                             # what the law requires
    guidance: str                                # how a deployment satisfies it
    capabilities_required: tuple[str, ...] = ()  # capability keys a deployment must assert
    prohibited_capabilities: tuple[str, ...] = ()  # presence of any => VIOLATION
    risk_tiers: tuple[RiskTier, ...] = (RiskTier.HIGH,)
    evidence: tuple[Evidence, ...] = ()          # NAIL components that provide proof
    severity: str = "high"                       # impact if unmet
    references: tuple[str, ...] = ()
    effective_date: str = "2026-08-02"           # dated: the target is moving

    def applies_to(self, *, party: Party, risk_tier: RiskTier) -> bool:
        party_ok = self.party == Party.BOTH or party == Party.BOTH or self.party == party
        tier_ok = RiskTier.ANY in self.risk_tiers or risk_tier in self.risk_tiers
        return party_ok and tier_ok

    def to_dict(self) -> dict:
        return {
            "control_id": self.control_id,
            "jurisdiction": self.jurisdiction.value,
            "framework": self.framework.value,
            "reference": self.reference,
            "title": self.title,
            "party": self.party.value,
            "requirement": self.requirement,
            "guidance": self.guidance,
            "capabilities_required": list(self.capabilities_required),
            "prohibited_capabilities": list(self.prohibited_capabilities),
            "risk_tiers": [t.value for t in self.risk_tiers],
            "evidence": [e.to_dict() for e in self.evidence],
            "severity": self.severity,
            "references": list(self.references),
            "effective_date": self.effective_date,
        }
