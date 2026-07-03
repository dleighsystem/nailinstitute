"""Compliance control registry — the EU AI Act slice (P1).

Each control is wired to the NAIL component that already provides evidence of
conformity, and declares the capability keys a deployment must assert. UK and US
frameworks extend this same registry in later phases.
"""
from __future__ import annotations

from typing import Iterable

from .schema import (
    ComplianceControl,
    Evidence,
    Framework,
    Jurisdiction,
    Party,
    RiskTier,
)

_EU = Jurisdiction.EU
_AIA = Framework.EU_AI_ACT

# ── EU AI Act controls ─────────────────────────────────────────────────────
_EU_AI_ACT_CONTROLS: tuple[ComplianceControl, ...] = (
    ComplianceControl(
        control_id="EU-AIA-ART5",
        jurisdiction=_EU, framework=_AIA, reference="Article 5",
        title="Prohibited AI practices",
        party=Party.BOTH,
        risk_tiers=(RiskTier.ANY,),
        requirement=(
            "Must not place on the market or use AI for social scoring, subliminal/"
            "manipulative techniques causing harm, or biometric categorisation on "
            "sensitive traits."
        ),
        guidance="Enforce hard guardrails that make prohibited practices unreachable.",
        prohibited_capabilities=(
            "social_scoring", "subliminal_manipulation", "biometric_categorisation_sensitive",
        ),
        evidence=(Evidence("Prohibited-practice guardrails", "shield / firewall"),),
        severity="critical",
    ),
    ComplianceControl(
        control_id="EU-AIA-ART9",
        jurisdiction=_EU, framework=_AIA, reference="Article 9",
        title="Risk management system",
        party=Party.PROVIDER,
        requirement="A continuous, iterative process to identify, estimate and evaluate risks.",
        guidance="Run the adversarial arena/CTF matrix and enumerate hazards against the AVE database.",
        capabilities_required=("adversarial_risk_testing",),
        evidence=(
            Evidence("Adversarial test matrix", "arena / ctf"),
            Evidence("Hazard enumeration", "ave (45 pathology cards)"),
        ),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART10",
        jurisdiction=_EU, framework=_AIA, reference="Article 10",
        title="Data and data governance",
        party=Party.PROVIDER,
        requirement="Training/validation data governed for relevance, representativeness and PII handling.",
        guidance="Track provenance and scrub secrets/PII on ingress.",
        capabilities_required=("data_provenance_controls", "pii_handling"),
        evidence=(Evidence("Provenance + secret scrub", "shield.taint_vault / shield.secret_scrub"),),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART11",
        jurisdiction=_EU, framework=_AIA, reference="Article 11 / Annex IV",
        title="Technical documentation",
        party=Party.PROVIDER,
        requirement="Documentation demonstrating conformity, drawn up before placing on the market.",
        guidance="Auto-generate the certification passport from the test pipeline.",
        capabilities_required=("technical_documentation",),
        evidence=(Evidence("Certification passport", "nail_harness.cert_pipeline (CertBundle)"),),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART12",
        jurisdiction=_EU, framework=_AIA, reference="Article 12",
        title="Record-keeping (traceability)",
        party=Party.BOTH,
        requirement="Automatic, tamper-evident logging of events over the system lifetime.",
        guidance="Emit an immutable, hash-chained audit log for every high-risk action.",
        capabilities_required=("immutable_audit_log",),
        evidence=(Evidence("Immutable flight recorder", "nail_monitor.flight_recorder"),),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART13",
        jurisdiction=_EU, framework=_AIA, reference="Article 13",
        title="Transparency and provision of information to deployers",
        party=Party.PROVIDER,
        requirement="Instructions for use enabling deployers to interpret output and comply.",
        guidance="Ship usage instructions + the passport with each certified system.",
        capabilities_required=("usage_instructions",),
        evidence=(Evidence("Passport + instructions", "nail_harness.cert_pipeline"),),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART14",
        jurisdiction=_EU, framework=_AIA, reference="Article 14",
        title="Human oversight",
        party=Party.BOTH,
        requirement="Designed so natural persons can oversee, intervene and stop the system.",
        guidance="Provide human-in-the-loop checkpoints and an enforceable kill-switch.",
        capabilities_required=("human_oversight", "kill_switch"),
        evidence=(
            Evidence("Revocation / expiry (M17)", "nail_harness (M17)"),
            Evidence("Per-org kill-switch", "fleet.OrgPathologyAlerter / fleet.WebhookKillSwitch"),
        ),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART15",
        jurisdiction=_EU, framework=_AIA, reference="Article 15",
        title="Accuracy, robustness and cybersecurity",
        party=Party.PROVIDER,
        requirement="Appropriate accuracy, robustness and resilience against adversarial manipulation.",
        guidance="Continuously monitor for pathologies and re-run the adversarial suite.",
        capabilities_required=("robustness_monitoring", "adversarial_risk_testing"),
        evidence=(
            Evidence("Runtime pathology detectors", "nail_monitor.detectors_v9"),
            Evidence("Diagnostic rating", "diagnostic"),
        ),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART26",
        jurisdiction=_EU, framework=_AIA, reference="Article 26",
        title="Obligations of deployers of high-risk AI",
        party=Party.DEPLOYER,
        requirement="Use per instructions, assign human oversight, monitor operation and keep logs.",
        guidance="Run the fleet monitor with per-org oversight and retained logs.",
        capabilities_required=("human_oversight", "operational_logging", "post_market_monitoring"),
        evidence=(
            Evidence("Multi-tenant fleet monitor", "fleet"),
            Evidence("Immutable logs", "nail_monitor.flight_recorder"),
        ),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART50",
        jurisdiction=_EU, framework=_AIA, reference="Article 50",
        title="Transparency obligations (limited risk)",
        party=Party.BOTH,
        risk_tiers=(RiskTier.LIMITED, RiskTier.HIGH),
        requirement="Inform natural persons that they are interacting with an AI system.",
        guidance="Disclose AI interaction to end users.",
        capabilities_required=("ai_disclosure",),
        evidence=(Evidence("Interaction disclosure", "application layer"),),
        severity="medium",
    ),
    ComplianceControl(
        control_id="EU-AIA-ART55",
        jurisdiction=_EU, framework=_AIA, reference="Article 55",
        title="GPAI models with systemic risk",
        party=Party.PROVIDER,
        risk_tiers=(RiskTier.GPAI,),
        requirement="Adversarial testing, systemic-risk assessment and serious-incident reporting.",
        guidance="Red-team the model and wire serious-incident reporting.",
        capabilities_required=("adversarial_risk_testing", "incident_reporting"),
        evidence=(
            Evidence("Red-team arena", "arena / ctf"),
            Evidence("Incident reporting", "canary.IncidentLog / fleet alerting"),
        ),
    ),
    ComplianceControl(
        control_id="EU-AIA-ART72",
        jurisdiction=_EU, framework=_AIA, reference="Article 72",
        title="Post-market monitoring",
        party=Party.PROVIDER,
        requirement="Collect and analyse performance data across the system's lifetime.",
        guidance="Stream telemetry to the fleet monitor and act on per-org pathology alerts.",
        capabilities_required=("post_market_monitoring",),
        evidence=(Evidence("Fleet telemetry + per-org detection", "fleet.FleetPathologyScanner"),),
    ),
)


# ── UK controls (principles-based + UK GDPR) ───────────────────────────────
_UK = Jurisdiction.UK
_UK_PRIN = Framework.UK_AI_PRINCIPLES
_UK_GDPR = Framework.UK_GDPR

_UK_CONTROLS: tuple[ComplianceControl, ...] = (
    ComplianceControl(
        control_id="UK-PRIN-SAFETY",
        jurisdiction=_UK, framework=_UK_PRIN, reference="Principle 1",
        title="Safety, security and robustness",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="AI must function robustly, securely and safely across its lifecycle, with risks continually monitored.",
        guidance="Run adversarial testing and continuous robustness monitoring.",
        capabilities_required=("adversarial_risk_testing", "robustness_monitoring"),
        evidence=(Evidence("Adversarial suite + detectors", "arena / ctf / nail_monitor"),),
    ),
    ComplianceControl(
        control_id="UK-PRIN-TRANSPARENCY",
        jurisdiction=_UK, framework=_UK_PRIN, reference="Principle 2",
        title="Appropriate transparency and explainability",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="Parties should access information on the system and understand its decisions where appropriate.",
        guidance="Disclose AI interaction and ship technical documentation.",
        capabilities_required=("ai_disclosure", "technical_documentation"),
        evidence=(Evidence("Passport + disclosure", "nail_harness.cert_pipeline"),),
    ),
    ComplianceControl(
        control_id="UK-PRIN-FAIRNESS",
        jurisdiction=_UK, framework=_UK_PRIN, reference="Principle 3",
        title="Fairness",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="AI should not undermine legal rights, discriminate unfairly, or create unfair outcomes.",
        guidance="Run bias / fairness testing.",
        capabilities_required=("bias_audit",),
        evidence=(Evidence("Bias probe scenarios", "diagnostic (ETHICS/BIAS_PROBE)"),),
    ),
    ComplianceControl(
        control_id="UK-PRIN-ACCOUNTABILITY",
        jurisdiction=_UK, framework=_UK_PRIN, reference="Principle 4",
        title="Accountability and governance",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="Governance measures and clear accountability across the AI lifecycle.",
        guidance="Assign a governance owner; retain logs and human oversight.",
        capabilities_required=("governance_owner", "operational_logging", "human_oversight"),
        evidence=(Evidence("Fleet monitor + flight recorder", "fleet / nail_monitor.flight_recorder"),),
    ),
    ComplianceControl(
        control_id="UK-PRIN-CONTESTABILITY",
        jurisdiction=_UK, framework=_UK_PRIN, reference="Principle 5",
        title="Contestability and redress",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="Users should be able to contest AI decisions and seek redress.",
        guidance="Provide a human-review / appeal path for AI decisions.",
        capabilities_required=("contestability_redress",),
        evidence=(Evidence("Human review path", "application layer"),),
        severity="medium",
    ),
    ComplianceControl(
        control_id="UK-GDPR-ART22",
        jurisdiction=_UK, framework=_UK_GDPR, reference="UK GDPR Art. 22",
        title="Automated decision-making and profiling",
        party=Party.DEPLOYER, risk_tiers=(RiskTier.HIGH, RiskTier.LIMITED),
        requirement="Individuals may not be subject to solely automated decisions with legal/significant effects without human intervention.",
        guidance="Insert human-in-the-loop and a contest/redress route for significant decisions.",
        capabilities_required=("human_oversight", "contestability_redress"),
        evidence=(Evidence("HITL + review", "fleet kill-switch / application layer"),),
    ),
    ComplianceControl(
        control_id="UK-GDPR-DPIA",
        jurisdiction=_UK, framework=_UK_GDPR, reference="UK GDPR Art. 35",
        title="Data protection impact assessment",
        party=Party.DEPLOYER,
        requirement="A DPIA is required for high-risk processing of personal data.",
        guidance="Complete a DPIA and enforce PII controls.",
        capabilities_required=("impact_assessment", "pii_handling"),
        evidence=(Evidence("PII controls", "shield.secret_scrub / shield.taint_vault"),),
    ),
)

# ── US controls (NIST AI RMF backbone + state laws) ────────────────────────
_US = Jurisdiction.US
_NIST = Framework.NIST_AI_RMF
_STATE = Framework.US_STATE_LAW

_US_CONTROLS: tuple[ComplianceControl, ...] = (
    ComplianceControl(
        control_id="US-NIST-GOVERN",
        jurisdiction=_US, framework=_NIST, reference="NIST AI RMF: GOVERN",
        title="Govern — culture, policies and accountability",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="A culture of risk management with policies, accountability and oversight is present.",
        guidance="Assign accountable ownership; retain logs; enforce oversight.",
        capabilities_required=("governance_owner", "operational_logging", "human_oversight"),
        evidence=(Evidence("Fleet + flight recorder", "fleet / nail_monitor.flight_recorder"),),
    ),
    ComplianceControl(
        control_id="US-NIST-MAP",
        jurisdiction=_US, framework=_NIST, reference="NIST AI RMF: MAP",
        title="Map — context and risk identification",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="Context is established and risks to individuals, groups and society are identified.",
        guidance="Enumerate hazards (AVE) and assess impact.",
        capabilities_required=("adversarial_risk_testing", "impact_assessment"),
        evidence=(Evidence("AVE hazard catalog + arena", "ave / arena / ctf"),),
    ),
    ComplianceControl(
        control_id="US-NIST-MEASURE",
        jurisdiction=_US, framework=_NIST, reference="NIST AI RMF: MEASURE",
        title="Measure — analyse, assess and track",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="Risks are analysed, benchmarked and monitored over time.",
        guidance="Continuously monitor pathologies and track metrics.",
        capabilities_required=("robustness_monitoring", "post_market_monitoring"),
        evidence=(Evidence("Detectors + fleet monitor", "nail_monitor / fleet"),),
    ),
    ComplianceControl(
        control_id="US-NIST-MANAGE",
        jurisdiction=_US, framework=_NIST, reference="NIST AI RMF: MANAGE",
        title="Manage — prioritise and respond",
        party=Party.BOTH, risk_tiers=(RiskTier.ANY,),
        requirement="Risks are prioritised and acted upon, with response and recovery plans.",
        guidance="Wire incident reporting and an enforceable kill-switch.",
        capabilities_required=("incident_reporting", "kill_switch"),
        evidence=(Evidence("Incident log + kill-switch", "canary.IncidentLog / fleet.WebhookKillSwitch"),),
    ),
    ComplianceControl(
        control_id="US-CO-SB205",
        jurisdiction=_US, framework=_STATE, reference="Colorado AI Act (SB 24-205)",
        title="High-risk AI: consumer protection and impact assessment",
        party=Party.DEPLOYER,
        requirement="Deployers must use reasonable care to avoid algorithmic discrimination, complete impact assessments and notify consumers.",
        guidance="Run bias audits, complete impact assessments and disclose to consumers.",
        capabilities_required=("bias_audit", "impact_assessment", "consumer_notice"),
        evidence=(Evidence("Bias probe + passport", "diagnostic / nail_harness.cert_pipeline"),),
    ),
    ComplianceControl(
        control_id="US-NYC-LL144",
        jurisdiction=_US, framework=_STATE, reference="NYC Local Law 144",
        title="Automated employment decision tools — bias audit",
        party=Party.DEPLOYER,
        requirement="Automated employment decision tools require an annual independent bias audit and candidate notice.",
        guidance="Complete an independent bias audit and notify candidates.",
        capabilities_required=("bias_audit", "consumer_notice"),
        evidence=(Evidence("Bias audit", "diagnostic (ETHICS/BIAS_PROBE)"),),
    ),
)


class ComplianceRegistry:
    """In-memory registry of compliance controls with deterministic lookup."""

    def __init__(self, controls: Iterable[ComplianceControl] = ()) -> None:
        self._controls: dict[str, ComplianceControl] = {}
        for control in controls:
            self._controls[control.control_id] = control

    def all(self) -> list[ComplianceControl]:
        return list(self._controls.values())

    def get(self, control_id: str) -> ComplianceControl:
        return self._controls[control_id]

    def by_jurisdiction(self, jurisdiction: Jurisdiction) -> list[ComplianceControl]:
        return [c for c in self._controls.values() if c.jurisdiction == jurisdiction]

    def by_party(self, party: Party) -> list[ComplianceControl]:
        return [c for c in self._controls.values()
                if c.party == party or c.party == Party.BOTH]

    def for_scope(self, *, jurisdictions: Iterable[Jurisdiction],
                  party: Party, risk_tier: RiskTier) -> list[ComplianceControl]:
        wanted = set(jurisdictions)
        return [
            c for c in self._controls.values()
            if c.jurisdiction in wanted and c.applies_to(party=party, risk_tier=risk_tier)
        ]


DEFAULT_REGISTRY = ComplianceRegistry(_EU_AI_ACT_CONTROLS + _UK_CONTROLS + _US_CONTROLS)
