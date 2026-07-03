"""Gap-analysis engine — check a workflow/deployment profile against the controls.

A :class:`WorkflowProfile` declares the capabilities a workflow/deployment has
(later phases derive these automatically, e.g. by introspecting a LangGraph
StateGraph). :func:`evaluate` maps the profile against the applicable controls and
returns a :class:`GapReport` of satisfied / partial / gap / violation findings.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .registry import DEFAULT_REGISTRY, ComplianceRegistry
from .schema import ComplianceControl, Jurisdiction, Party, RiskTier, Status


@dataclass
class WorkflowProfile:
    """A declared profile of the workflow/deployment under review."""
    name: str
    party: Party
    risk_tier: RiskTier
    capabilities: frozenset[str] = field(default_factory=frozenset)
    jurisdictions: tuple[Jurisdiction, ...] = (Jurisdiction.EU,)


@dataclass
class ControlFinding:
    control: ComplianceControl
    status: Status
    missing_capabilities: tuple[str, ...] = ()
    triggered_prohibitions: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "control_id": self.control.control_id,
            "reference": self.control.reference,
            "title": self.control.title,
            "party": self.control.party.value,
            "status": self.status.value,
            "severity": self.control.severity,
            "missing_capabilities": list(self.missing_capabilities),
            "triggered_prohibitions": list(self.triggered_prohibitions),
        }


@dataclass
class GapReport:
    profile_name: str
    findings: list[ControlFinding]

    @property
    def gaps(self) -> list[ControlFinding]:
        return [f for f in self.findings if f.status in (Status.GAP, Status.PARTIAL)]

    @property
    def violations(self) -> list[ControlFinding]:
        return [f for f in self.findings if f.status == Status.VIOLATION]

    @property
    def compliant(self) -> bool:
        return not self.violations and not self.gaps

    def summary(self) -> dict[str, int]:
        counts: Counter[str] = Counter(f.status.value for f in self.findings)
        return dict(counts)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile_name,
            "compliant": self.compliant,
            "summary": self.summary(),
            "findings": [f.to_dict() for f in self.findings],
        }


def evaluate(profile: WorkflowProfile,
             registry: ComplianceRegistry | None = None) -> GapReport:
    registry = registry or DEFAULT_REGISTRY
    caps = set(profile.capabilities)
    findings: list[ControlFinding] = []

    for control in registry.for_scope(
        jurisdictions=profile.jurisdictions, party=profile.party, risk_tier=profile.risk_tier,
    ):
        triggered = tuple(sorted(caps & set(control.prohibited_capabilities)))
        if triggered:
            findings.append(ControlFinding(control, Status.VIOLATION, triggered_prohibitions=triggered))
            continue

        required = set(control.capabilities_required)
        missing = tuple(sorted(required - caps))
        if not missing:
            status = Status.SATISFIED
        elif missing == tuple(sorted(required)):
            status = Status.GAP        # none of the required capabilities present
        else:
            status = Status.PARTIAL    # some present, some missing
        findings.append(ControlFinding(control, status, missing_capabilities=missing))

    findings.sort(key=lambda f: (f.status != Status.VIOLATION, f.status != Status.GAP,
                                 f.control.control_id))
    return GapReport(profile.name, findings)
