"""
nail-monitor: Main NailMonitor orchestrator.

Provides a single entry-point for monitoring multi-agent LLM systems
for organizational pathologies identified by the NAIL Institute research.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

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
from .types import Alert, Observation, Severity

logger = logging.getLogger("nail_monitor")


class NailMonitor:
    """
    Unified pathology monitor for LLM multi-agent systems.
    
    Integrates all six NAIL-derived detectors into a single monitoring
    interface. Designed for production integration — attach to your
    agent loop and call `.observe()` after each agent output.
    
    Usage:
        >>> from nail_monitor import NailMonitor
        >>> monitor = NailMonitor()
        >>> 
        >>> # In your agent loop:
        >>> for output in agent.run():
        ...     alerts = monitor.observe(
        ...         agent_name="reviewer_1",
        ...         output=output.text,
        ...         round_num=output.round,
        ...         tokens_used=output.tokens,
        ...     )
        ...     for alert in alerts:
        ...         if alert.severity == "critical":
        ...             trigger_mitigation(alert)
    """

    def __init__(
        self,
        enable_inbreeding: bool = True,
        enable_consensus: bool = True,
        enable_blame: bool = True,
        enable_engagement: bool = True,
        enable_schema: bool = True,
        enable_goodhart: bool = True,
        # ── v2 detectors (Exp 6–17) ──
        enable_alignment_friction: bool = True,
        enable_prompt_satiation: bool = True,
        enable_epistemic_contagion: bool = True,
        enable_learned_helplessness: bool = True,
        enable_language_drift: bool = True,
        enable_container_bleed: bool = True,
        enable_upgrade_regression: bool = True,
        # ── v6 detectors (Exp 21–26 detectives) ──
        enable_bystander_effect: bool = True,
        enable_attention_smoothing: bool = True,
        enable_memory_laundering: bool = True,
        enable_tool_chain_propagation: bool = True,
        enable_deceptive_alignment: bool = True,
        enable_colluding_agents: bool = True,
        enable_confused_deputy: bool = True,
        enable_omission: bool = True,
        # ── v7 detectors (Exp 33–37: frontier rogue agent detection) ──
        enable_alignment_faking: bool = True,
        enable_justification_inconsistency: bool = True,
        enable_injection: bool = True,
        enable_trigger_conditional: bool = True,
        enable_fleet_collusion: bool = True,
        enable_monoculture_risk: bool = True,
        enable_cascade_risk: bool = True,
        # ── v8 detectors (M17 kill switches) ──
        enable_revocation_compliance: bool = True,
        # ── v9 detectors (control-plane agent pathologies) ──
        enable_tool_manifest_integrity: bool = True,
        enable_memory_write_firewall: bool = True,
        enable_goal_drift_monitor: bool = True,
        enable_tool_retrieval_integrity: bool = True,
        # ── v10 detectors (credential/egress chain — OpenAI × Hugging Face) ──
        enable_credential_harvesting: bool = True,
        enable_egress_allowlist: bool = True,
        enable_credential_overreach: bool = True,
        enable_credential_velocity: bool = True,
        allowed_hosts: Optional[list] = None,
        authorized_scopes: Optional[list] = None,
        log_alerts: bool = True,
        alert_log_path: Optional[str] = None,
    ):
        self.log_alerts = log_alerts
        self.alert_log_path = Path(alert_log_path) if alert_log_path else None
        self._alert_history: list[Alert] = []
        self._start_time = time.time()

        # Initialize detectors
        self.detectors: dict[str, BaseDetector] = {}

        if enable_inbreeding:
            self.detectors["inbreeding"] = InbreedingDetector()
        if enable_consensus:
            self.detectors["consensus"] = ConsensusParalysisDetector()
        if enable_blame:
            self.detectors["blame"] = BlameCascadeDetector()
        if enable_engagement:
            self.detectors["engagement"] = EngagementDecayDetector()
        if enable_schema:
            self.detectors["schema"] = SchemaCoercionDetector()
        if enable_goodhart:
            self.detectors["goodhart"] = GoodhartDetector()

        # ── v2 detectors ──
        if enable_alignment_friction:
            self.detectors["alignment_friction"] = AlignmentFrictionDetector()
        if enable_prompt_satiation:
            self.detectors["prompt_satiation"] = PromptSatiationDetector()
        if enable_epistemic_contagion:
            self.detectors["epistemic_contagion"] = EpistemicContagionDetector()
        if enable_learned_helplessness:
            self.detectors["learned_helplessness"] = LearnedHelplessnessDetector()
        if enable_language_drift:
            self.detectors["language_drift"] = LanguageDriftDetector()
        if enable_container_bleed:
            self.detectors["container_bleed"] = ContainerBleedDetector()
        if enable_upgrade_regression:
            self.detectors["upgrade_regression"] = UpgradeRegressionDetector()

        # ── v6 detectors (Exp 21–26 detectives) ──
        if enable_bystander_effect:
            self.detectors["bystander_effect"] = BystanderEffectDetector()
        if enable_attention_smoothing:
            self.detectors["attention_smoothing"] = AttentionSmoothingDetector()
        if enable_memory_laundering:
            self.detectors["memory_laundering"] = MemoryLaunderingDetector()
        if enable_tool_chain_propagation:
            self.detectors["tool_chain_propagation"] = ToolChainPropagationDetector()
        if enable_deceptive_alignment:
            self.detectors["deceptive_alignment"] = DeceptiveAlignmentDetector()
        if enable_colluding_agents:
            self.detectors["colluding_agents"] = ColludingAgentsDetector()
        if enable_confused_deputy:
            self.detectors["confused_deputy"] = ConfusedDeputyDetector()
        if enable_omission:
            self.detectors["omission"] = OmissionDetector()

        # ── v7 detectors (Exp 33–37: frontier rogue agent detection) ──
        if enable_alignment_faking:
            self.detectors["alignment_faking"] = AlignmentFakingDetector()
        if enable_justification_inconsistency:
            self.detectors["justification_inconsistency"] = JustificationInconsistencyDetector()
        if enable_injection:
            self.detectors["injection"] = InjectionDetector()
        if enable_trigger_conditional:
            self.detectors["trigger_conditional"] = TriggerConditionalDetector()
        if enable_fleet_collusion:
            self.detectors["fleet_collusion"] = FleetCollusionDetector()
        if enable_monoculture_risk:
            self.detectors["monoculture_risk"] = MonocultureRiskDetector()
        if enable_cascade_risk:
            self.detectors["cascade_risk"] = CascadeRiskDetector()

        # ── v8 detectors (M17 Revocation Compliance) ──
        if enable_revocation_compliance:
            from .detectors_v8 import RevocationComplianceDetector
            self.detectors["revocation_compliance"] = RevocationComplianceDetector()

        # ── v9 detectors (control-plane agent pathologies) ──
        if enable_tool_manifest_integrity:
            self.detectors["tool_manifest_integrity"] = ToolManifestIntegrityDetector()
        if enable_memory_write_firewall:
            self.detectors["memory_write_firewall"] = MemoryWriteFirewallDetector()
        if enable_goal_drift_monitor:
            self.detectors["goal_drift_monitor"] = GoalDriftMonitorDetector()
        if enable_tool_retrieval_integrity:
            self.detectors["tool_retrieval_integrity"] = ToolRetrievalIntegrityDetector()

        # ── v10 detectors (credential/egress chain — OpenAI × Hugging Face) ──
        if enable_credential_harvesting:
            self.detectors["credential_harvesting"] = CredentialHarvestingDetector()
        if enable_egress_allowlist:
            self.detectors["egress_allowlist"] = EgressAllowlistDetector(allowed_hosts=allowed_hosts)
        if enable_credential_overreach:
            self.detectors["credential_overreach"] = CredentialOverreachDetector(
                authorized_scopes=authorized_scopes
            )
        if enable_credential_velocity:
            self.detectors["credential_velocity"] = CredentialAccessVelocityDetector()

        if log_alerts:
            logging.basicConfig(level=logging.INFO)
            logger.info(
                "NailMonitor initialized with %d detectors: %s",
                len(self.detectors),
                list(self.detectors.keys()),
            )

    # ── Primary Observe Interface ──────────────────────────────────────

    def observe(
        self,
        agent_name: str,
        output: str,
        round_num: int = 0,
        tokens_used: int = 0,
        metadata: Optional[dict] = None,
    ) -> list[Alert]:
        """
        Feed an agent output to all applicable detectors.
        
        Args:
            agent_name: Identifier for the agent producing this output.
            output: The agent's output text.
            round_num: Current round/step number.
            tokens_used: Tokens consumed for this output.
            metadata: Optional dict with detector-specific data, e.g.:
                - tool_descriptions: {name: desc} for ConfusedDeputyDetector
                - memory_writes/reads: for MemoryLaunderingDetector
                - monitoring_state: for DeceptiveAlignmentDetector
                - is_critical_alert: for BystanderEffectDetector
                - requires_action: for OmissionDetector
                - tool_calls: for ToolChainPropagationDetector
                - request_text: for ColludingAgentsDetector
                v7 (frontier rogue agent detection):
                - monitoring_mentioned: bool for AlignmentFakingDetector
                - refusal_rate, caveat_density: float for AlignmentFakingDetector
                - info_accessed, info_referenced: list[str] for JustificationInconsistencyDetector
                - retrieved_content: str for InjectionDetector
                - context_variables: dict for TriggerConditionalDetector
                - agent_action_code: int for FleetCollusionDetector
                - model_backend, had_error: for MonocultureRiskDetector
                - had_error, error_source_agent: for CascadeRiskDetector
                v9 (control-plane pathology detection):
                - tool_manifest/tool_manifests for ToolManifestIntegrityDetector
                - memory_writes with source/trust/fact_type for MemoryWriteFirewallDetector
                - task_goal/plan_steps/tool_calls/action for GoalDriftMonitorDetector
                v10 (credential/egress chain — OpenAI × Hugging Face):
                - secret_reads (dict/list), tool_calls, egress for CredentialHarvestingDetector
                - egress/network_calls + allowed_hosts for EgressAllowlistDetector
                - credential_scopes + authorized_scopes/action_scope for CredentialOverreachDetector
                - sensitive_action/credential_access + resource/host for CredentialAccessVelocityDetector

        Returns list of Alerts (may be empty if no pathologies detected).
        """
        obs = Observation(
            agent_name=agent_name,
            output=output,
            round_num=round_num,
            tokens_used=tokens_used,
            metadata=metadata or {},
        )

        alerts = []

        # Inbreeding: per-agent tracking
        if "inbreeding" in self.detectors:
            alert = self.detectors["inbreeding"].observe(obs)
            if alert:
                alerts.append(alert)

        # Blame cascade: all agents
        if "blame" in self.detectors:
            alert = self.detectors["blame"].observe(obs)
            if alert:
                alerts.append(alert)

        # Engagement decay: all agents
        if "engagement" in self.detectors:
            alert = self.detectors["engagement"].observe(obs)
            if alert:
                alerts.append(alert)

        # ── v2 detectors that use standard observe() ──
        for key in ("alignment_friction", "language_drift", "container_bleed"):
            if key in self.detectors:
                alert = self.detectors[key].observe(obs)
                if alert:
                    alerts.append(alert)

        # ── v6 detectors (Exp 21–26 detectives) ──
        v6_keys = (
            "bystander_effect", "attention_smoothing", "memory_laundering",
            "tool_chain_propagation", "deceptive_alignment",
            "colluding_agents", "confused_deputy", "omission",
        )
        for key in v6_keys:
            if key in self.detectors:
                alert = self.detectors[key].observe(obs)
                if alert:
                    alerts.append(alert)

        # ── v7 detectors (Exp 33–37: frontier rogue agent detection) ──
        v7_keys = (
            "alignment_faking", "justification_inconsistency", "injection",
            "trigger_conditional", "fleet_collusion", "monoculture_risk",
            "cascade_risk",
        )
        for key in v7_keys:
            if key in self.detectors:
                alert = self.detectors[key].observe(obs)
                if alert:
                    alerts.append(alert)

        # ── v9 detectors (control-plane agent pathologies) ──
        v9_keys = (
            "tool_manifest_integrity",
            "memory_write_firewall",
            "goal_drift_monitor",
        )
        for key in v9_keys:
            if key in self.detectors:
                alert = self.detectors[key].observe(obs)
                if alert:
                    alerts.append(alert)

        # ── v10 detectors (credential/egress chain) ──
        v10_keys = (
            "credential_harvesting",
            "egress_allowlist",
            "credential_overreach",
            "credential_velocity",
        )
        for key in v10_keys:
            if key in self.detectors:
                alert = self.detectors[key].observe(obs)
                if alert:
                    alerts.append(alert)

        self._process_alerts(alerts)
        return alerts

    # ── Specialized Observe Methods ────────────────────────────────────

    def observe_consensus_round(
        self,
        round_num: int,
        agent_votes: dict[str, bool],
        tokens: int = 0,
    ) -> Optional[Alert]:
        """
        Record a consensus voting round.
        
        Args:
            round_num: Current round number.
            agent_votes: {agent_name: True/False} — True = agrees.
            tokens: Tokens consumed this round.
        """
        if "consensus" not in self.detectors:
            return None
        det: ConsensusParalysisDetector = self.detectors["consensus"]
        det.observe_round(round_num, agent_votes, tokens)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    def observe_validation(
        self,
        passed: bool,
        retries: int = 0,
        had_default_fallback: bool = False,
    ) -> Optional[Alert]:
        """Record a schema validation attempt."""
        if "schema" not in self.detectors:
            return None
        det: SchemaCoercionDetector = self.detectors["schema"]
        det.observe_validation(passed, retries, had_default_fallback)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    def observe_scores(
        self,
        internal_score: float,
        external_score: float,
    ) -> Optional[Alert]:
        """Record internal vs external evaluation scores."""
        if "goodhart" not in self.detectors:
            return None
        det: GoodhartDetector = self.detectors["goodhart"]
        det.observe_scores(internal_score, external_score)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    # ── v2 specialized observe methods ──────────────────────────────────

    def observe_tool_call(
        self,
        tool_name: str,
        succeeded: bool,
    ) -> Optional[Alert]:
        """Record a tool invocation for learned helplessness detection."""
        if "learned_helplessness" not in self.detectors:
            return None
        det: LearnedHelplessnessDetector = self.detectors["learned_helplessness"]
        det.observe_tool_call(tool_name, succeeded)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    def observe_compliance(
        self,
        compliant: bool,
    ) -> Optional[Alert]:
        """Record instruction compliance for prompt satiation detection."""
        if "prompt_satiation" not in self.detectors:
            return None
        det: PromptSatiationDetector = self.detectors["prompt_satiation"]
        det.observe_compliance(compliant)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    def observe_claim_propagation(
        self,
        verified_against_source: bool,
    ) -> Optional[Alert]:
        """Record claim propagation for epistemic contagion detection."""
        if "epistemic_contagion" not in self.detectors:
            return None
        det: EpistemicContagionDetector = self.detectors["epistemic_contagion"]
        det.observe_claim_propagation(verified_against_source)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    def observe_state_size(
        self,
        size: int,
    ) -> Optional[Alert]:
        """Record state-object size for upgrade regression detection."""
        if "upgrade_regression" not in self.detectors:
            return None
        det: UpgradeRegressionDetector = self.detectors["upgrade_regression"]
        det.observe_state_size(size)
        alert = det.check()
        if alert:
            self._process_alerts([alert])
        return alert

    def set_upgrade_baseline(self, state_sizes: list[int]):
        """Set baseline state sizes for upgrade regression detection."""
        if "upgrade_regression" in self.detectors:
            det: UpgradeRegressionDetector = self.detectors["upgrade_regression"]
            det.set_baseline(state_sizes)

    # ── v9 specialized observe methods ─────────────────────────────────

    def observe_tool_manifest(
        self,
        agent_name: str,
        manifest: dict,
        *,
        round_num: int = 0,
    ) -> list[Alert]:
        """Record one tool/MCP manifest snapshot for integrity monitoring."""
        return self.observe(
            agent_name=agent_name,
            output="",
            round_num=round_num,
            metadata={"tool_manifest": manifest},
        )

    def observe_tool_retrieval(
        self,
        agent_name: str,
        *,
        loaded_tools,
        authorized_tools=None,
        required_tools=None,
        round_num: int = 0,
    ) -> list[Alert]:
        """Record one lazy/selective tool-loading snapshot for retrieval-integrity monitoring.

        ``loaded_tools`` is the subset actually retrieved this turn; optional
        ``authorized_tools`` (least-privilege set) and ``required_tools``
        (safety/approval tools) drive the surfacing and starvation checks.
        """
        metadata: dict = {"loaded_tools": loaded_tools}
        if authorized_tools is not None:
            metadata["authorized_tools"] = authorized_tools
        if required_tools is not None:
            metadata["required_tools"] = required_tools
        return self.observe(
            agent_name=agent_name,
            output="",
            round_num=round_num,
            metadata=metadata,
        )

    def observe_memory_write(
        self,
        agent_name: str,
        write: dict,
        *,
        round_num: int = 0,
    ) -> list[Alert]:
        """Record one proposed long-term memory write for firewall monitoring."""
        return self.observe(
            agent_name=agent_name,
            output=str(write.get("value") or write.get("content") or ""),
            round_num=round_num,
            metadata={"memory_writes": [write]},
        )

    def observe_goal_state(
        self,
        agent_name: str,
        *,
        task_goal: str,
        session_id: str = "",
        output: str = "",
        plan_steps: list[str] | None = None,
        tool_calls: list[dict] | None = None,
        action: str = "",
        allowed_tools: list[str] | None = None,
        sensitive_action: bool = False,
        goal_alignment_score: float | None = None,
        round_num: int = 0,
    ) -> list[Alert]:
        """Record the current trajectory state for goal-drift monitoring."""
        metadata = {
            "task_goal": task_goal,
            "session_id": session_id,
            "plan_steps": plan_steps or [],
            "tool_calls": tool_calls or [],
            "action": action,
            "allowed_tools": allowed_tools or [],
            "sensitive_action": sensitive_action,
        }
        if goal_alignment_score is not None:
            metadata["goal_alignment_score"] = goal_alignment_score
        return self.observe(
            agent_name=agent_name,
            output=output,
            round_num=round_num,
            metadata=metadata,
        )

    # ── Alert Management ───────────────────────────────────────────────

    def _process_alerts(self, alerts: list[Alert]):
        """Log and store alerts."""
        for alert in alerts:
            self._alert_history.append(alert)

            if self.log_alerts:
                log_fn = {
                    Severity.INFO: logger.info,
                    Severity.WARNING: logger.warning,
                    Severity.CRITICAL: logger.critical,
                }.get(alert.severity, logger.warning)
                log_fn("[%s] %s", alert.detector, alert.message)

            if self.alert_log_path:
                with open(self.alert_log_path, "a") as f:
                    f.write(json.dumps(alert.to_dict()) + "\n")

    @property
    def alerts(self) -> list[Alert]:
        """All alerts generated during this session."""
        return self._alert_history

    @property
    def critical_alerts(self) -> list[Alert]:
        """Only critical alerts."""
        return [a for a in self._alert_history if a.severity == Severity.CRITICAL]

    @property
    def has_critical(self) -> bool:
        """Whether any critical pathologies have been detected."""
        return len(self.critical_alerts) > 0

    # ── Reporting ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Generate a summary report of all detections."""
        elapsed = time.time() - self._start_time
        by_type = {}
        for alert in self._alert_history:
            key = alert.pathology.value if hasattr(alert.pathology, 'value') else str(alert.pathology)
            if key not in by_type:
                by_type[key] = {"count": 0, "max_severity": "info", "latest_message": ""}
            by_type[key]["count"] += 1
            by_type[key]["latest_message"] = alert.message
            if alert.severity == Severity.CRITICAL:
                by_type[key]["max_severity"] = "critical"
            elif alert.severity == Severity.WARNING and by_type[key]["max_severity"] != "critical":
                by_type[key]["max_severity"] = "warning"

        return {
            "session_duration_sec": round(elapsed, 1),
            "total_alerts": len(self._alert_history),
            "critical_alerts": len(self.critical_alerts),
            "active_detectors": list(self.detectors.keys()),
            "pathologies_detected": by_type,
        }

    def print_summary(self):
        """Print a human-readable monitoring summary."""
        s = self.summary()
        print("\n" + "=" * 60)
        print("  NAIL Monitor — Session Summary")
        print("=" * 60)
        print(f"  Duration:       {s['session_duration_sec']}s")
        print(f"  Total Alerts:   {s['total_alerts']}")
        print(f"  Critical:       {s['critical_alerts']}")
        print(f"  Detectors:      {', '.join(s['active_detectors'])}")
        print("-" * 60)
        if s["pathologies_detected"]:
            for ptype, info in s["pathologies_detected"].items():
                icon = "🔴" if info["max_severity"] == "critical" else "🟡" if info["max_severity"] == "warning" else "🟢"
                print(f"  {icon} {ptype}: {info['count']} alert(s) [{info['max_severity']}]")
                print(f"     Last: {info['latest_message'][:100]}...")
        else:
            print("  🟢 No pathologies detected.")
        print("=" * 60 + "\n")

    # ── Reset & Config ─────────────────────────────────────────────────

    def reset(self):
        """Reset all detectors and clear alert history."""
        for det in self.detectors.values():
            det.reset()
        self._alert_history.clear()
        self._start_time = time.time()

    def disable(self, detector_name: str):
        """Disable a specific detector."""
        if detector_name in self.detectors:
            self.detectors[detector_name].enabled = False

    def enable(self, detector_name: str):
        """Re-enable a specific detector."""
        if detector_name in self.detectors:
            self.detectors[detector_name].enabled = True

    # ── Specialized Observation Wrappers ──────────────────────────────

    def observe_halt_signal(self, agent_id: str, tier: int = 1) -> None:
        """Called when Neuravant / the client issues an M17 tier halt signal."""
        if "revocation_compliance" in self.detectors:
            self.detectors["revocation_compliance"].observe_halt_signal(agent_id, tier)

    def observe_halt_acknowledged(self, agent_id: str, tier: int = 1) -> list[Alert]:
        """Called when the agent acknowledges the M17 halt signal."""
        alerts = []
        if "revocation_compliance" in self.detectors:
            alerts.extend(self.detectors["revocation_compliance"].observe_halt_acknowledged(agent_id, tier))
            for alert in alerts:
                self._alert_history.append(alert)
                if self.log_alerts:
                    self.log_alert(alert)
        return alerts
