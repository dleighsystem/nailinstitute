"""Continuous compliance over live fleet telemetry, per organisation.

Bridges the fleet event store to the nail-compliance drift monitor
(``compliance.ComplianceMonitor``): each org's observed event *kinds* become
compliance capabilities (via ``compliance.capabilities_from_events``), merged
with any declared capabilities, and re-checked against that org's certified
baseline. Regressions and new violations fire the injected ``kill_switch``
(``(org, pathology, count)`` — e.g. :class:`fleet.alerts.WebhookKillSwitch`),
so compliance drift escalates through the same per-org channel as any other
pathology.

Drift arises live in two ways: evidence *expiring* out of the telemetry window
(retention pruning drops the events that satisfied a control) and evidence
*appearing* (a prohibited or newly-applicable behaviour starts emitting events).

nail-compliance is an **optional** dependency, imported lazily (same pattern
as nail_monitor in :mod:`fleet.detect`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .store import Store


def killswitch_on_drift(
    kill_switch: Callable[[str, str, int], None],
    *,
    escalate_kinds: tuple[str, ...] = ("regression", "new_violation"),
) -> Callable[[str, Any], None]:
    """Adapt a fleet ``kill_switch(org, pathology, count)`` into a
    ``ComplianceMonitor(on_drift=...)`` callback.

    Each escalating drift fires the switch once, as pathology
    ``compliance.<kind>:<control_id>`` — so the receiving cohort-incident
    endpoint sees exactly which control regressed. A failed kill-switch must
    not swallow the drift result, so transport errors are absorbed here.
    """
    def on_drift(org: str, result: Any) -> None:
        for d in result.drifts:
            if d.kind not in escalate_kinds:
                continue
            try:
                kill_switch(org, f"compliance.{d.kind}:{d.control_id}", 1)
            except Exception:
                pass
    return on_drift


@dataclass
class OrgComplianceSpec:
    """How to frame an org's deployment for the gap engine.

    Capabilities are the union of ``declared_capabilities`` and whatever is
    *derived* from the org's observed event kinds — declaration covers what
    telemetry can't show (e.g. documentation), derivation keeps it honest.
    """
    party: str = "deployer"
    risk_tier: str = "high"
    jurisdictions: tuple[str, ...] = ("eu", "uk", "us")
    declared_capabilities: frozenset[str] = field(default_factory=frozenset)


class FleetComplianceWatcher:
    """Per-org compliance drift over the fleet telemetry store.

    Parameters
    ----------
    store:
        The fleet telemetry :class:`~fleet.store.Store`.
    kill_switch:
        Optional ``(org, pathology, count) -> None`` escalation callback
        (e.g. :class:`fleet.alerts.WebhookKillSwitch`); fired via
        :func:`killswitch_on_drift` on regressions / new violations.
    specs / default_spec:
        Per-org :class:`OrgComplianceSpec` overrides and the fallback spec.
    registry:
        Optional ``compliance.ComplianceRegistry`` (defaults to the
        tri-jurisdiction ``DEFAULT_REGISTRY``).
    event_kind_caps:
        Optional ``{event_kind: capability}`` override map passed through to
        ``capabilities_from_events``.
    """

    def __init__(
        self,
        store: Store,
        *,
        kill_switch: Optional[Callable[[str, str, int], None]] = None,
        specs: dict[str, OrgComplianceSpec] | None = None,
        default_spec: OrgComplianceSpec | None = None,
        registry: Any = None,
        event_kind_caps: dict[str, str] | None = None,
    ) -> None:
        self.store = store
        self.kill_switch = kill_switch
        self.specs = dict(specs or {})
        self.default_spec = default_spec or OrgComplianceSpec()
        self.registry = registry
        self.event_kind_caps = event_kind_caps
        self._monitor: Any = None

    @staticmethod
    def _compliance():
        try:
            import compliance
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                "FleetComplianceWatcher requires nail-compliance. Install it "
                "(pip install -e compliance/), or run without the /v1/compliance "
                "surface."
            ) from exc
        return compliance

    def monitor(self) -> Any:
        """The underlying (lazily-built) ``ComplianceMonitor`` — exposes
        ``export_baselines`` / ``import_baselines`` for persistence."""
        if self._monitor is None:
            c = self._compliance()
            on_drift = (killswitch_on_drift(self.kill_switch)
                        if self.kill_switch is not None else None)
            self._monitor = c.ComplianceMonitor(self.registry, on_drift=on_drift)
        return self._monitor

    def spec(self, org: str) -> OrgComplianceSpec:
        return self.specs.get(org, self.default_spec)

    def profile(self, org: str) -> Any:
        """Build the org's ``WorkflowProfile`` from its live telemetry."""
        c = self._compliance()
        spec = self.spec(org)
        caps = c.capabilities_from_events(self.store.list_kinds(org=org),
                                          self.event_kind_caps)
        caps |= set(spec.declared_capabilities)
        return c.WorkflowProfile(
            name=org,
            party=c.Party(spec.party),
            risk_tier=c.RiskTier(spec.risk_tier),
            capabilities=frozenset(caps),
            jurisdictions=tuple(c.Jurisdiction(j) for j in spec.jurisdictions),
        )

    def report(self, org: str) -> Any:
        """Stateless point-in-time ``GapReport`` for an org (no drift, no escalation)."""
        c = self._compliance()
        return c.evaluate(self.profile(org), self.registry)

    def baseline(self, org: str) -> Any:
        """Certify the org's current posture as its drift baseline."""
        return self.monitor().set_baseline(org, self.profile(org))

    def check(self, org: str) -> Any:
        """Re-check an org against its baseline; escalating drifts fire the
        kill-switch. Returns the compliance ``DriftResult``."""
        return self.monitor().check(org, self.profile(org))

    def check_all(self) -> dict[str, Any]:
        """Drift-check every org known to the store: ``{org: DriftResult}``."""
        return {o["org"]: self.check(o["org"]) for o in self.store.list_orgs()}
