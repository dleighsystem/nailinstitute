"""NailSecurity — unified product interface.

Wraps Shield, AVE, TaintVault, Canary, and Arena behind two clean
operations: protect() and assess(). Enterprise integrations only need
to import NailSecurity — they don't need to know how the pieces fit.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class ThreatLevel(str, Enum):
    CLEAR    = "clear"      # No signals detected
    LOW      = "low"        # Minor canonicalisation or scrub changes
    MEDIUM   = "medium"     # Injection score 0.3–0.65 or laundering risk
    HIGH     = "high"       # Injection score 0.65–0.85 or known AVE match
    CRITICAL = "critical"   # Injection score > 0.85 or laundering confirmed


# ── Result types ───────────────────────────────────────────────────────────────

@dataclass
class ProtectResult:
    """Result of passing input through the Shield pipeline.

    Attributes
    ----------
    shielded_text : str
        Canonicalised, secret-scrubbed, provenance-wrapped text. Pass this
        to the agent instead of the raw input.
    threat_level : ThreatLevel
        Aggregated threat assessment.
    blocked : bool
        True if the input should be rejected (threat_level == CRITICAL
        and block_on_critical=True in NailSecurity config).
    block_reason : str
        Human-readable reason if blocked.
    injection_score : float | None
        0.0–1.0 confidence the input is an injection attempt (None = classifier off).
    is_injection : bool | None
        Classifier verdict (None = classifier off).
    secrets_scrubbed : int
        Number of secrets removed from the input.
    canonical_changes : list[str]
        List of canonicalisation transformations applied.
    chain_id : str | None
        AVE-compatible hash chain entry for audit trail.
    span_id : str
        Unique ID for this input span.
    ave_matches : list[dict]
        AVE vulnerability cards that match the detected attack type.
    laundering_reports : list[dict]
        Any trust-laundering alerts from the TaintVault scan (if vault provided).
    latency_ms : float
    """
    shielded_text: str
    threat_level: ThreatLevel
    blocked: bool
    block_reason: str
    injection_score: Optional[float]
    is_injection: Optional[bool]
    secrets_scrubbed: int
    canonical_changes: list[str]
    chain_id: Optional[str]
    span_id: str
    ave_matches: list[dict] = field(default_factory=list)
    laundering_reports: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "shielded_text_length": len(self.shielded_text),
            "threat_level": self.threat_level.value,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "injection_score": self.injection_score,
            "is_injection": self.is_injection,
            "secrets_scrubbed": self.secrets_scrubbed,
            "canonical_changes": self.canonical_changes,
            "chain_id": self.chain_id,
            "span_id": self.span_id,
            "ave_matches": self.ave_matches,
            "laundering_reports": self.laundering_reports,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class AssessResult:
    """Result of assessing a deployed agent's risk posture.

    Attributes
    ----------
    agent_id : str
    critical_aves : list[dict]    AVE cards with CRITICAL severity
    high_aves : list[dict]        AVE cards with HIGH severity
    open_theories : list[str]     Unvalidated theories from threat landscape
    canary_incidents : int        Incidents captured by the Canary Fleet
    arena_breach_rate : float     Latest Arena red/blue breach rate (0.0-1.0)
    laundering_alerts : int       Active trust-laundering alerts in the vault
    risk_score : float            0.0 (clean) - 1.0 (critical)
    recommendations : list[str]
    """
    agent_id: str
    critical_aves: list[dict]
    high_aves: list[dict]
    open_theories: list[str]
    canary_incidents: int
    arena_breach_rate: float
    laundering_alerts: int
    risk_score: float
    recommendations: list[str]
    timestamp: str = ""

    def summary(self) -> str:
        lines = [
            f"AssessResult for agent '{self.agent_id}'",
            f"  Risk score:       {self.risk_score:.2f}",
            f"  Critical AVEs:    {len(self.critical_aves)}",
            f"  High AVEs:        {len(self.high_aves)}",
            f"  Open theories:    {len(self.open_theories)}",
            f"  Canary incidents: {self.canary_incidents}",
            f"  Arena breach rate:{self.arena_breach_rate:.1%}",
            f"  Laundering alerts:{self.laundering_alerts}",
        ]
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    - {r}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "risk_score": round(self.risk_score, 3),
            "critical_aves": self.critical_aves,
            "high_aves": self.high_aves,
            "open_theories": self.open_theories,
            "canary_incidents": self.canary_incidents,
            "arena_breach_rate": round(self.arena_breach_rate, 4),
            "laundering_alerts": self.laundering_alerts,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp,
        }


# ── NailSecurity ──────────────────────────────────────────────────────────────

class NailSecurity:
    """Unified NAIL security layer.

    Parameters
    ----------
    classify : bool
        Enable injection classifier (requires Ollama/nail-guard:v4). Default False.
    classifier_backend : "ollama" | "guard"
        Classifier backend. "guard" uses GuardClient for BEE/SDF/CIA/CCB verdicts.
    guard_client : GuardClient | None
        Pre-instantiated GuardClient (only used with classifier_backend="guard").
    block_on_critical : bool
        If True, protect() sets blocked=True when threat_level==CRITICAL. Default True.
    taint_vault : TaintVault | None
        Optional shared TaintVault for memory lineage tracking. If None, a
        new in-memory vault is created per NailSecurity instance.
    canary_fleet : Fleet | None
        Optional Canary Fleet instance. If None, assess() skips canary metrics.
    """

    def __init__(
        self,
        *,
        classify: bool = False,
        classifier_backend: str = "ollama",
        guard_client=None,
        block_on_critical: bool = True,
        taint_vault=None,
        canary_fleet=None,
    ):
        self._classify = classify
        self._classifier_backend = classifier_backend
        self._guard_client = guard_client
        self._block_on_critical = block_on_critical
        self._canary_fleet = canary_fleet

        # TaintVault — lazy import so nail_security works without shield installed
        if taint_vault is not None:
            self._vault = taint_vault
        else:
            try:
                from shield.taint_vault import TaintVault
                self._vault = TaintVault()
            except ImportError:
                self._vault = None

    # ── protect ───────────────────────────────────────────────────────────────

    def protect(
        self,
        text: str,
        *,
        source: str,
        store_in_vault: bool = True,
        trust_score: float = 0.25,
    ) -> ProtectResult:
        """Pass raw external input through the full Shield pipeline.

        Parameters
        ----------
        text : str
            Raw untrusted input (email body, user message, RAG chunk, tool return).
        source : str
            Provenance string e.g. "email:user@x.com", "rag:doc-7#chunk-2".
        store_in_vault : bool
            If True, store the shielded input as a TaintEntry in the vault.
        trust_score : float
            Initial trust score for this input (0.0–1.0). Default 0.25 (UNTRUSTED).
        """
        t0 = time.monotonic()

        try:
            from shield import process as shield_process
        except ImportError:
            # Graceful fallback if shield not installed
            return ProtectResult(
                shielded_text=f'<UNTRUSTED src="{source}">\n{text}\n</UNTRUSTED>',
                threat_level=ThreatLevel.MEDIUM,
                blocked=False,
                block_reason="shield_not_installed",
                injection_score=None,
                is_injection=None,
                secrets_scrubbed=0,
                canonical_changes=[],
                chain_id=None,
                span_id="u-fallback",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        shielded = shield_process(
            text,
            source=source,
            classify=self._classify,
            classifier_backend=self._classifier_backend,
            guard_client=self._guard_client,
        )

        # ── Threat level classification ──────────────────────────────────────
        threat_level = self._classify_threat(shielded)

        # ── Store in TaintVault ──────────────────────────────────────────────
        laundering_reports: list[dict] = []
        if store_in_vault and self._vault is not None:
            entry = self._vault.store(
                shielded.text,
                source_chain_id=shielded.chain_id,
                trust_score=trust_score,
            )
            # Scan for laundering in any related facts
            reports = self._vault.scan_for_laundering()
            laundering_reports = [
                {"fact_id": r.fact_id, "inflation": r.inflation, "explanation": r.explanation}
                for r in reports
            ]
            if laundering_reports:
                threat_level = _escalate(threat_level, ThreatLevel.HIGH)

        # ── AVE lookup ───────────────────────────────────────────────────────
        ave_matches: list[dict] = []
        if shielded.is_injection:
            ave_matches = self._lookup_ave_for_injection(shielded.injection_reason)

        # ── Block decision ───────────────────────────────────────────────────
        blocked = self._block_on_critical and threat_level == ThreatLevel.CRITICAL
        block_reason = ""
        if blocked:
            block_reason = (
                f"injection_score={shielded.injection_score:.2f}, "
                f"classifier={shielded.injection_reason}"
                if shielded.injection_score is not None
                else "critical_threat_detected"
            )

        latency_ms = (time.monotonic() - t0) * 1000

        return ProtectResult(
            shielded_text=shielded.text,
            threat_level=threat_level,
            blocked=blocked,
            block_reason=block_reason,
            injection_score=shielded.injection_score,
            is_injection=shielded.is_injection,
            secrets_scrubbed=sum(shielded.secret_counts.values()),
            canonical_changes=shielded.canonical_changes,
            chain_id=shielded.chain_id,
            span_id=shielded.span_id,
            ave_matches=ave_matches,
            laundering_reports=laundering_reports,
            latency_ms=latency_ms,
        )

    # ── assess ────────────────────────────────────────────────────────────────

    def assess(self, agent_id: str) -> AssessResult:
        """Assess the security risk posture of a deployed agent.

        Pulls together AVE database, Canary Fleet incident counts, Arena
        breach rate, and TaintVault laundering status into a single risk report.
        """
        critical_aves: list[dict] = []
        high_aves: list[dict] = []

        try:
            import ave as ave_db
            critical_cards = ave_db.cards_by_severity(ave_db.Severity.CRITICAL)
            high_cards = ave_db.cards_by_severity(ave_db.Severity.HIGH)
            critical_aves = [
                {"ave_id": c.ave_id, "name": c.name, "status": c.status.value,
                 "summary": c.summary[:200]}
                for c in critical_cards
            ]
            high_aves = [
                {"ave_id": c.ave_id, "name": c.name, "status": c.status.value,
                 "summary": c.summary[:200]}
                for c in high_cards
            ]
        except ImportError:
            pass

        # ── Open theories (not yet lab-proven) ────────────────────────────────
        open_theories = [
            "Theory A: Semantic Trojan Horses (EXP-30 pending live run)",
            "Theory B: Temporal Persona Shift (EXP-31 pending live run)",
            "Theory G: Time-Bomb / Deadman Payloads (untested)",
        ]

        # ── Canary Fleet incidents ─────────────────────────────────────────────
        canary_incidents = 0
        if self._canary_fleet is not None:
            try:
                count_dict = self._canary_fleet.incident_log.count()
                canary_incidents = count_dict.get("total", 0) if isinstance(count_dict, dict) else int(count_dict)
            except Exception:
                pass

        # ── Arena breach rate ─────────────────────────────────────────────────
        arena_breach_rate = 0.0
        try:
            from pathlib import Path
            import json
            cp_path = Path("logs/arena/checkpoint.json")
            if cp_path.exists():
                data = json.loads(cp_path.read_text())
                battles = data.get("total_battles", 0)
                red_wins = data.get("total_red_wins", 0)
                if battles > 0:
                    arena_breach_rate = red_wins / battles
        except Exception:
            pass

        # ── Laundering alerts ─────────────────────────────────────────────────
        laundering_alerts = 0
        if self._vault is not None:
            try:
                laundering_alerts = len(self._vault.scan_for_laundering())
            except Exception:
                pass

        # ── Risk score ────────────────────────────────────────────────────────
        # Weighted combination of available signals
        risk_score = 0.0
        risk_score += min(len(critical_aves) * 0.03, 0.30)     # up to 0.30 for AVE exposure
        risk_score += arena_breach_rate * 0.30                   # 0.30 for breach rate
        risk_score += min(canary_incidents * 0.05, 0.20)         # 0.20 for canary hits
        risk_score += min(laundering_alerts * 0.10, 0.20)        # 0.20 for laundering
        risk_score = min(risk_score, 1.0)

        # ── Recommendations ───────────────────────────────────────────────────
        recs: list[str] = []
        if len(critical_aves) > 5:
            recs.append("Review and mitigate top CRITICAL AVE cards (AVE-2025-0001, AVE-2025-0009, etc.)")
        if arena_breach_rate > 0.4:
            recs.append(f"Arena breach rate {arena_breach_rate:.0%} — evolve Blue Bridge defences")
        if laundering_alerts > 0:
            recs.append(f"{laundering_alerts} memory laundering alert(s) — audit TaintVault lineage")
        if canary_incidents > 0:
            recs.append(f"{canary_incidents} Canary incident(s) — review draft AVE cards")
        if not recs:
            recs.append("No immediate action required — continue monitoring")

        return AssessResult(
            agent_id=agent_id,
            critical_aves=critical_aves,
            high_aves=high_aves,
            open_theories=open_theories,
            canary_incidents=canary_incidents,
            arena_breach_rate=arena_breach_rate,
            laundering_alerts=laundering_alerts,
            risk_score=round(risk_score, 3),
            recommendations=recs,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _classify_threat(shielded) -> ThreatLevel:
        score = shielded.injection_score
        n_secrets = sum(shielded.secret_counts.values()) if shielded.secret_counts else 0
        n_changes = len(shielded.canonical_changes)

        if score is None:
            # No classifier — use heuristics
            if n_secrets > 0 and n_changes > 1:
                return ThreatLevel.MEDIUM
            if n_secrets > 2:
                return ThreatLevel.HIGH
            if n_changes > 0 or n_secrets > 0:
                return ThreatLevel.LOW
            return ThreatLevel.CLEAR

        if score >= 0.85:
            return ThreatLevel.CRITICAL
        if score >= 0.65:
            return ThreatLevel.HIGH
        if score >= 0.30:
            return ThreatLevel.MEDIUM
        if score > 0.0 or n_secrets > 0 or n_changes > 0:
            return ThreatLevel.LOW
        return ThreatLevel.CLEAR

    @staticmethod
    def _lookup_ave_for_injection(reason: str) -> list[dict]:
        """Look up relevant AVE cards based on the classifier's reason string."""
        try:
            import ave as ave_db
            lower_reason = reason.lower()
            # Map common attack type labels to AVE categories
            category_map = {
                "prompt_injection": ave_db.Category.INJECTION,
                "injection":        ave_db.Category.INJECTION,
                "credential":       ave_db.Category.CREDENTIAL,
                "memory":           ave_db.Category.MEMORY,
                "social":           ave_db.Category.SOCIAL,
                "tool":             ave_db.Category.TOOL,
            }
            matched_category = None
            for keyword, category in category_map.items():
                if keyword in lower_reason:
                    matched_category = category
                    break

            if matched_category:
                cards = ave_db.cards_by_category(matched_category)[:3]
            else:
                cards = ave_db.cards_by_severity(ave_db.Severity.CRITICAL)[:2]

            return [
                {"ave_id": c.ave_id, "name": c.name, "severity": c.severity.value}
                for c in cards
            ]
        except ImportError:
            return []


# ── Helpers ───────────────────────────────────────────────────────────────────

_THREAT_ORDER = [
    ThreatLevel.CLEAR, ThreatLevel.LOW, ThreatLevel.MEDIUM,
    ThreatLevel.HIGH, ThreatLevel.CRITICAL,
]


def _escalate(current: ThreatLevel, minimum: ThreatLevel) -> ThreatLevel:
    """Return the higher of two threat levels."""
    if _THREAT_ORDER.index(minimum) > _THREAT_ORDER.index(current):
        return minimum
    return current
