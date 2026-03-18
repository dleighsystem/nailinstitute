"""
AVSS — Agentic Vulnerability Severity Score
=============================================

A CVSS-like scoring system purpose-built for AI agent vulnerabilities.
Produces a 0.0–10.0 score with severity label, based on vector components
that reflect the unique threat landscape of autonomous agents.

Score Components (each rated 0.0–1.0):
    AV — Attack Vector:       How accessible the attack surface is
    AC — Attack Complexity:    Skill/conditions needed to exploit
    PR — Privileges Required:  Level of access the attacker needs
    UI — User Interaction:     Does exploitation need human in the loop?
    SC — Scope Change:         Does the blast radius escape the agent boundary?
    CI — Confidentiality:      Data exfiltration / secret leakage risk
    II — Integrity Impact:     Corruption of agent state or output quality
    AI — Availability Impact:  EDoS, token drain, service degradation
    TE — Temporal Exploitability: How mature/active is exploitation?
    AE — Agentic Exploitability:  Unique to agentic systems — multi-hop,
                                   cross-agent, memory persistence factors
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AttackVector(str, Enum):
    """How the vulnerability is accessed."""
    NETWORK = "network"          # Remote, via API or chat interface
    ADJACENT = "adjacent"        # Requires access to the same agent network
    LOCAL = "local"              # Requires local system/memory access
    PHYSICAL = "physical"        # Requires physical access to hardware


class AttackComplexity(str, Enum):
    """Conditions required beyond attacker control."""
    LOW = "low"          # Readily exploitable, no special conditions
    HIGH = "high"        # Requires specific timing, race conditions, or setup


class PrivilegesRequired(str, Enum):
    """Access level needed."""
    NONE = "none"            # No authentication needed (public chat)
    LOW = "low"              # Basic user access
    HIGH = "high"            # Admin / developer access


class UserInteraction(str, Enum):
    """Does exploitation need a human in the loop?"""
    NONE = "none"        # Fully automated exploitation
    REQUIRED = "required"    # Needs user to click/approve/interact


class ScopeChange(str, Enum):
    """Does exploitation cross a trust boundary?"""
    UNCHANGED = "unchanged"  # Impact stays within the vulnerable component
    CHANGED = "changed"      # Blast radius escapes to other agents/systems


class Impact(str, Enum):
    """Impact level for C/I/A triad."""
    NONE = "none"        # No impact
    LOW = "low"          # Minor degradation
    HIGH = "high"        # Severe / total compromise


class TemporalExploitability(str, Enum):
    """How actively exploited / mature is this?"""
    NOT_DEFINED = "not_defined"
    UNPROVEN = "unproven"        # PoC exists but no active exploitation
    POC = "poc"                  # Functional PoC available
    FUNCTIONAL = "functional"    # Reliable exploit exists
    HIGH = "high"                # Actively exploited in the wild


class AgenticExploitability(str, Enum):
    """Unique agentic risk factors."""
    NONE = "none"                # Single-shot, no persistence
    LOW = "low"                  # Single agent, ephemeral
    MEDIUM = "medium"            # Multi-agent OR persistent memory
    HIGH = "high"                # Multi-agent AND persistent memory AND cross-hop
    CRITICAL = "critical"        # Self-propagating across agent swarms


# ── Numeric weights for score calculation ─────────────────────────────

_AV_WEIGHTS = {
    AttackVector.NETWORK: 0.85,
    AttackVector.ADJACENT: 0.62,
    AttackVector.LOCAL: 0.55,
    AttackVector.PHYSICAL: 0.20,
}

_AC_WEIGHTS = {
    AttackComplexity.LOW: 0.77,
    AttackComplexity.HIGH: 0.44,
}

_PR_WEIGHTS_UNCHANGED = {
    PrivilegesRequired.NONE: 0.85,
    PrivilegesRequired.LOW: 0.62,
    PrivilegesRequired.HIGH: 0.27,
}

_PR_WEIGHTS_CHANGED = {
    PrivilegesRequired.NONE: 0.85,
    PrivilegesRequired.LOW: 0.68,
    PrivilegesRequired.HIGH: 0.50,
}

_UI_WEIGHTS = {
    UserInteraction.NONE: 0.85,
    UserInteraction.REQUIRED: 0.62,
}

_IMPACT_WEIGHTS = {
    Impact.NONE: 0.0,
    Impact.LOW: 0.22,
    Impact.HIGH: 0.56,
}

_TEMPORAL_WEIGHTS = {
    TemporalExploitability.NOT_DEFINED: 1.0,
    TemporalExploitability.UNPROVEN: 0.91,
    TemporalExploitability.POC: 0.94,
    TemporalExploitability.FUNCTIONAL: 0.97,
    TemporalExploitability.HIGH: 1.0,
}

_AGENTIC_WEIGHTS = {
    AgenticExploitability.NONE: 1.0,
    AgenticExploitability.LOW: 1.04,
    AgenticExploitability.MEDIUM: 1.08,
    AgenticExploitability.HIGH: 1.14,
    AgenticExploitability.CRITICAL: 1.20,
}


@dataclass(frozen=True)
class AVSSVector:
    """
    Complete AVSS vector — all the inputs needed to compute a score.

    Usage:
        >>> v = AVSSVector(
        ...     attack_vector=AttackVector.NETWORK,
        ...     attack_complexity=AttackComplexity.LOW,
        ...     privileges_required=PrivilegesRequired.NONE,
        ...     confidentiality=Impact.HIGH,
        ...     integrity=Impact.HIGH,
        ...     availability=Impact.HIGH,
        ... )
        >>> score = compute_avss(v)
        >>> score.base_score
        9.8
    """
    attack_vector: AttackVector = AttackVector.NETWORK
    attack_complexity: AttackComplexity = AttackComplexity.LOW
    privileges_required: PrivilegesRequired = PrivilegesRequired.NONE
    user_interaction: UserInteraction = UserInteraction.NONE
    scope_change: ScopeChange = ScopeChange.UNCHANGED
    confidentiality: Impact = Impact.NONE
    integrity: Impact = Impact.NONE
    availability: Impact = Impact.NONE
    temporal: TemporalExploitability = TemporalExploitability.NOT_DEFINED
    agentic: AgenticExploitability = AgenticExploitability.NONE

    def vector_string(self) -> str:
        """CVSS-style vector string, e.g. AVSS:1.0/AV:N/AC:L/PR:N/..."""
        parts = [
            f"AV:{self.attack_vector.value[0].upper()}",
            f"AC:{self.attack_complexity.value[0].upper()}",
            f"PR:{self.privileges_required.value[0].upper()}",
            f"UI:{self.user_interaction.value[0].upper()}",
            f"S:{'C' if self.scope_change == ScopeChange.CHANGED else 'U'}",
            f"C:{self.confidentiality.value[0].upper()}",
            f"I:{self.integrity.value[0].upper()}",
            f"A:{self.availability.value[0].upper()}",
            f"TE:{self.temporal.value[:3].upper()}",
            f"AE:{self.agentic.value[:3].upper()}",
        ]
        return "AVSS:1.0/" + "/".join(parts)

    def to_dict(self) -> dict:
        return {
            "attack_vector": self.attack_vector.value,
            "attack_complexity": self.attack_complexity.value,
            "privileges_required": self.privileges_required.value,
            "user_interaction": self.user_interaction.value,
            "scope_change": self.scope_change.value,
            "confidentiality": self.confidentiality.value,
            "integrity": self.integrity.value,
            "availability": self.availability.value,
            "temporal": self.temporal.value,
            "agentic": self.agentic.value,
        }


@dataclass(frozen=True)
class AVSSScore:
    """Computed AVSS result."""
    base_score: float              # 0.0–10.0
    temporal_score: float          # 0.0–10.0 (base × temporal modifier)
    agentic_score: float           # 0.0–10.0 (temporal × agentic modifier)
    overall_score: float           # Final score (capped at 10.0)
    severity_label: str            # "none", "low", "medium", "high", "critical"
    vector: AVSSVector
    vector_string: str

    def to_dict(self) -> dict:
        return {
            "base_score": self.base_score,
            "temporal_score": self.temporal_score,
            "agentic_score": self.agentic_score,
            "overall_score": self.overall_score,
            "severity_label": self.severity_label,
            "vector_string": self.vector_string,
            "vector": self.vector.to_dict(),
        }


def _roundup(val: float) -> float:
    """CVSS-style round-up to one decimal place."""
    return math.ceil(val * 10) / 10


def _severity_label(score: float) -> str:
    """Map numeric score to severity label."""
    if score == 0.0:
        return "none"
    if score < 4.0:
        return "low"
    if score < 7.0:
        return "medium"
    if score < 9.0:
        return "high"
    return "critical"


def compute_avss(vector: AVSSVector) -> AVSSScore:
    """
    Compute the full AVSS score from a vector.

    Follows CVSS 3.1 math with an extra agentic multiplier:

        ISS = 1 - [(1-C) × (1-I) × (1-A)]

        if scope unchanged:
            Impact = 6.42 × ISS
        else:
            Impact = 7.52 × [ISS - 0.029] - 3.25 × [ISS - 0.02]^15

        Exploitability = 8.22 × AV × AC × PR × UI

        if Impact <= 0:
            BaseScore = 0
        elif scope unchanged:
            BaseScore = min(Impact + Exploitability, 10)
        else:
            BaseScore = min(1.08 × (Impact + Exploitability), 10)

        TemporalScore = BaseScore × TE
        AgenticScore  = TemporalScore × AE
        OverallScore  = min(AgenticScore, 10.0)
    """
    # Impact Sub-Score
    c_val = _IMPACT_WEIGHTS[vector.confidentiality]
    i_val = _IMPACT_WEIGHTS[vector.integrity]
    a_val = _IMPACT_WEIGHTS[vector.availability]
    iss = 1.0 - ((1.0 - c_val) * (1.0 - i_val) * (1.0 - a_val))

    if vector.scope_change == ScopeChange.UNCHANGED:
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)

    # Exploitability Sub-Score
    av_val = _AV_WEIGHTS[vector.attack_vector]
    ac_val = _AC_WEIGHTS[vector.attack_complexity]
    if vector.scope_change == ScopeChange.CHANGED:
        pr_val = _PR_WEIGHTS_CHANGED[vector.privileges_required]
    else:
        pr_val = _PR_WEIGHTS_UNCHANGED[vector.privileges_required]
    ui_val = _UI_WEIGHTS[vector.user_interaction]

    exploitability = 8.22 * av_val * ac_val * pr_val * ui_val

    # Base Score
    if impact <= 0:
        base = 0.0
    elif vector.scope_change == ScopeChange.UNCHANGED:
        base = _roundup(min(impact + exploitability, 10.0))
    else:
        base = _roundup(min(1.08 * (impact + exploitability), 10.0))

    # Temporal Score
    te_val = _TEMPORAL_WEIGHTS[vector.temporal]
    temporal = _roundup(base * te_val)

    # Agentic Score
    ae_val = _AGENTIC_WEIGHTS[vector.agentic]
    agentic = _roundup(temporal * ae_val)

    overall = min(agentic, 10.0)

    return AVSSScore(
        base_score=base,
        temporal_score=temporal,
        agentic_score=agentic,
        overall_score=overall,
        severity_label=_severity_label(overall),
        vector=vector,
        vector_string=vector.vector_string(),
    )


# ── Convenience presets ────────────────────────────────────────────────

def critical_network_agent() -> AVSSVector:
    """Preset: critical network-accessible multi-agent vulnerability."""
    return AVSSVector(
        attack_vector=AttackVector.NETWORK,
        attack_complexity=AttackComplexity.LOW,
        privileges_required=PrivilegesRequired.NONE,
        user_interaction=UserInteraction.NONE,
        scope_change=ScopeChange.CHANGED,
        confidentiality=Impact.HIGH,
        integrity=Impact.HIGH,
        availability=Impact.HIGH,
        temporal=TemporalExploitability.FUNCTIONAL,
        agentic=AgenticExploitability.HIGH,
    )


def medium_local_single() -> AVSSVector:
    """Preset: medium-severity single-agent local vulnerability."""
    return AVSSVector(
        attack_vector=AttackVector.LOCAL,
        attack_complexity=AttackComplexity.HIGH,
        privileges_required=PrivilegesRequired.LOW,
        user_interaction=UserInteraction.REQUIRED,
        scope_change=ScopeChange.UNCHANGED,
        confidentiality=Impact.LOW,
        integrity=Impact.LOW,
        availability=Impact.NONE,
        temporal=TemporalExploitability.POC,
        agentic=AgenticExploitability.LOW,
    )
