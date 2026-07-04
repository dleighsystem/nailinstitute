"""Continuous compliance-drift monitor.

Compliance is not point-in-time: a deployment certified compliant can **drift** as
its behaviour changes. This monitor holds a per-org **baseline** of control
statuses and, on re-check, flags:

  * ``regression``     — a control that was SATISFIED is now a gap/partial/violation
  * ``new_gap`` / ``new_violation`` — a newly-applicable control that isn't met
  * ``resolved``       — a previously-unmet control now satisfied

On drift it invokes an injected ``on_drift(org, DriftResult)`` callback — wire it
to the fleet's alerting / kill-switch (e.g. ``fleet.WebhookKillSwitch``) so
compliance becomes a live, per-organisation signal.

``capabilities_from_events`` maps fleet telemetry event *kinds* to compliance
capabilities, so the live fleet stream can drive re-checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from .engine import GapReport, WorkflowProfile, evaluate
from .registry import ComplianceRegistry
from .schema import Status

# Illustrative fleet-event-kind -> capability map (override with your own).
_EVENT_KIND_CAPS: dict[str, str] = {
    "shield.provenance": "data_provenance_controls",
    "shield.secret_scrub": "pii_handling",
    "oversight.intervention": "human_oversight",
    "killswitch.fired": "kill_switch",
    "fleet.killswitch": "kill_switch",
    "flight_recorder.entry": "immutable_audit_log",
    "monitor.scan": "post_market_monitoring",
    "diagnostic.bias_probe": "bias_audit",
    "arena.battle": "adversarial_risk_testing",
    "ctf.run": "adversarial_risk_testing",
    "detector.alert": "robustness_monitoring",
    "incident.captured": "incident_reporting",
    "disclosure.shown": "ai_disclosure",
}

_UNMET = (Status.GAP, Status.PARTIAL, Status.VIOLATION)


def capabilities_from_events(event_kinds: Iterable[str],
                             mapping: dict[str, str] | None = None) -> set[str]:
    """Derive compliance capabilities present, from observed fleet event kinds."""
    m = mapping or _EVENT_KIND_CAPS
    return {m[k] for k in event_kinds if k in m}


@dataclass
class ComplianceDrift:
    org: str
    kind: str            # regression | new_gap | new_violation | resolved
    control_id: str
    reference: str
    from_status: str
    to_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "org": self.org, "kind": self.kind, "control_id": self.control_id,
            "reference": self.reference, "from": self.from_status, "to": self.to_status,
        }


@dataclass
class DriftResult:
    org: str
    drifts: list[ComplianceDrift]
    report: GapReport

    @property
    def has_drift(self) -> bool:
        return bool(self.drifts)

    @property
    def regressions(self) -> list[ComplianceDrift]:
        return [d for d in self.drifts if d.kind in ("regression", "new_violation")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "org": self.org,
            "has_drift": self.has_drift,
            "drifts": [d.to_dict() for d in self.drifts],
            "report": self.report.to_dict(),
        }


class ComplianceMonitor:
    """Per-org compliance-drift monitor over a fixed certified baseline."""

    def __init__(self, registry: ComplianceRegistry | None = None, *,
                 on_drift: Optional[Callable[[str, "DriftResult"], None]] = None) -> None:
        self.registry = registry
        self.on_drift = on_drift
        self._baseline: dict[str, dict[str, str]] = {}   # org -> {control_id: status}

    def set_baseline(self, org: str, profile: WorkflowProfile) -> GapReport:
        """Record the certified baseline for an org (drift is measured against this)."""
        report = evaluate(profile, self.registry)
        self._baseline[org] = {f.control.control_id: f.status.value for f in report.findings}
        return report

    def check(self, org: str, profile: WorkflowProfile) -> DriftResult:
        """Re-evaluate a profile and report drift from the org's baseline."""
        report = evaluate(profile, self.registry)
        baseline = self._baseline.get(org, {})
        drifts: list[ComplianceDrift] = []

        for f in report.findings:
            cid = f.control.control_id
            now = f.status.value
            prev = baseline.get(cid)

            if prev is None:
                if f.status in (Status.GAP, Status.VIOLATION):
                    drifts.append(ComplianceDrift(org, f"new_{now}", cid, f.control.reference, "n/a", now))
            elif prev != now:
                if prev == Status.SATISFIED.value and f.status in _UNMET:
                    kind = "new_violation" if f.status == Status.VIOLATION else "regression"
                    drifts.append(ComplianceDrift(org, kind, cid, f.control.reference, prev, now))
                elif f.status == Status.SATISFIED:
                    drifts.append(ComplianceDrift(org, "resolved", cid, f.control.reference, prev, now))
                elif f.status == Status.VIOLATION:
                    drifts.append(ComplianceDrift(org, "new_violation", cid, f.control.reference, prev, now))

        result = DriftResult(org, drifts, report)
        if self.on_drift is not None and result.has_drift:
            self.on_drift(org, result)
        return result
