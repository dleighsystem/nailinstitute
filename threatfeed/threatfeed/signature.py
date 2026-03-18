"""
SignatureCompiler — Converts raw threat intelligence into executable signatures.

Takes raw attack data from Canary incidents, Arena breakthroughs, and CTF
discoveries, and compiles them into structured detection signatures that
can be deployed to the NAIL Monitor SDK.

This is the engine behind the "Protect" phase of the GTM pipeline:
  DISCOVER → PUBLISH → **PROTECT**
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class SignatureType(str, Enum):
    """Type of detection signature."""
    REGEX = "regex"                   # Pattern-match on text
    KEYWORD = "keyword"              # Simple keyword presence
    THRESHOLD = "threshold"          # Numeric threshold comparison
    COMPOSITE = "composite"          # Multiple conditions AND/OR
    BEHAVIOURAL = "behavioural"      # Sequence-based detection


class SignatureSource(str, Enum):
    """Origin of the signature intelligence."""
    CANARY = "canary"                # From honeypot fleet incidents
    ARENA = "arena"                  # From Red/Blue self-play breakthroughs
    CTF = "ctf"                      # From CTF event discoveries
    DIAGNOSTIC = "diagnostic"        # From diagnostic pipeline failures
    HORIZON = "horizon"              # From horizon campaign findings
    MANUAL = "manual"                # Manually authored by researcher
    AUTO_LEARNED = "auto_learned"    # Machine-learned from patterns


@dataclass(frozen=True)
class Signature:
    """
    An executable detection signature.

    The atomic unit of the SDK's "Live Threat Definition Update" system.
    When deployed to a client's NAIL Monitor, this signature actively
    scans for the specific attack pattern it describes.
    """
    signature_id: str
    name: str
    sig_type: SignatureType
    source: SignatureSource
    pattern: str = ""                # Regex or keyword pattern
    threshold: float = 0.0           # For threshold-type signatures
    description: str = ""
    severity: str = "medium"
    ave_id: str = ""                 # Link to AVE card if known
    metadata: tuple[tuple[str, str], ...] = ()  # Extra key-value pairs
    created_at: float = 0.0
    version: int = 1

    def matches(self, text: str) -> bool:
        """Test if this signature matches the given text."""
        if self.sig_type == SignatureType.REGEX:
            return bool(re.search(self.pattern, text, re.I))
        elif self.sig_type == SignatureType.KEYWORD:
            return self.pattern.lower() in text.lower()
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature_id": self.signature_id,
            "name": self.name,
            "type": self.sig_type.value,
            "source": self.source.value,
            "pattern": self.pattern,
            "threshold": self.threshold,
            "description": self.description,
            "severity": self.severity,
            "ave_id": self.ave_id,
            "version": self.version,
            "created_at": self.created_at,
        }


class SignatureCompiler:
    """
    Compiles raw threat intelligence into executable Signatures.

    Input sources:
      - Canary TrapWire extracted signatures
      - Arena Red Swarm attack gene profiles
      - CTF novel attack methodologies
      - Diagnostic pipeline failure patterns

    Output:
      - Signature objects ready for deployment to SDK clients
    """

    def __init__(self) -> None:
        self._compiled: list[Signature] = []
        self._compile_count = 0

    @property
    def signatures(self) -> list[Signature]:
        return list(self._compiled)

    @property
    def count(self) -> int:
        return len(self._compiled)

    def compile_from_canary(
        self,
        extracted: list[dict[str, Any]],
    ) -> list[Signature]:
        """
        Compile signatures from Canary TrapWire extractions.

        Each extraction dict should have:
          - signal: threat signal type
          - rule_description: what was detected
          - sample_text: raw attack text
          - severity: severity level
        """
        new_sigs: list[Signature] = []
        for ext in extracted:
            self._compile_count += 1
            sig = Signature(
                signature_id=f"SIG-CAN-{self._compile_count:04d}",
                name=f"Canary Detection: {ext.get('signal', 'unknown')}",
                sig_type=SignatureType.REGEX,
                source=SignatureSource.CANARY,
                pattern=re.escape(ext.get("sample_text", "")[:100]),
                description=ext.get("rule_description", ""),
                severity=ext.get("severity", "medium"),
                created_at=time.time(),
            )
            new_sigs.append(sig)
            self._compiled.append(sig)
        return new_sigs

    def compile_from_arena(
        self,
        red_signatures: list[dict[str, Any]],
    ) -> list[Signature]:
        """
        Compile signatures from Arena Red Swarm attack profiles.

        Each dict should have:
          - attack_type: type of attack
          - genes: gene profile dict
          - fitness: attack fitness score
          - stealth_level: how stealthy
        """
        new_sigs: list[Signature] = []
        for red in red_signatures:
            self._compile_count += 1
            genes = red.get("genes", {})
            # Build a composite threshold signature from gene values
            sig = Signature(
                signature_id=f"SIG-ARN-{self._compile_count:04d}",
                name=f"Arena Attack: {red.get('attack_type', 'unknown')}",
                sig_type=SignatureType.THRESHOLD,
                source=SignatureSource.ARENA,
                threshold=red.get("fitness", 0.5),
                description=(
                    f"GA-evolved attack pattern: {red.get('attack_type', 'unknown')}. "
                    f"Stealth: {red.get('stealth_level', 0):.2f}, "
                    f"Fitness: {red.get('fitness', 0):.4f}"
                ),
                severity="high" if red.get("fitness", 0) > 0.7 else "medium",
                metadata=tuple(
                    (f"gene_{k}", str(round(v, 4))) for k, v in genes.items()
                ),
                created_at=time.time(),
            )
            new_sigs.append(sig)
            self._compiled.append(sig)
        return new_sigs

    def compile_from_ctf(
        self,
        methodologies: list[dict[str, Any]],
    ) -> list[Signature]:
        """
        Compile signatures from CTF methodology harvests.

        Each dict should have:
          - team: team name
          - technique_summary: description of the attack
          - flags_captured: number of flags taken
        """
        new_sigs: list[Signature] = []
        for meth in methodologies:
            self._compile_count += 1
            sig = Signature(
                signature_id=f"SIG-CTF-{self._compile_count:04d}",
                name=f"CTF Methodology: {meth.get('team', 'unknown')}",
                sig_type=SignatureType.BEHAVIOURAL,
                source=SignatureSource.CTF,
                description=meth.get("technique_summary", ""),
                severity="high" if meth.get("flags_captured", 0) >= 3 else "medium",
                metadata=(
                    ("team", meth.get("team", "")),
                    ("flags", str(meth.get("flags_captured", 0))),
                    ("turns", str(meth.get("turns", 0))),
                ),
                created_at=time.time(),
            )
            new_sigs.append(sig)
            self._compiled.append(sig)
        return new_sigs

    def compile_from_draft(
        self,
        draft_card: dict[str, Any],
    ) -> Signature:
        """Compile a single signature from a draft AVE card dict."""
        self._compile_count += 1
        sig = Signature(
            signature_id=f"SIG-DRF-{self._compile_count:04d}",
            name=draft_card.get("name", draft_card.get("title", "Draft")),
            sig_type=SignatureType.KEYWORD,
            source=SignatureSource.MANUAL,
            pattern=draft_card.get("name", draft_card.get("title", "")),
            description=draft_card.get("summary", draft_card.get("description", "")),
            severity=draft_card.get("severity", "medium"),
            ave_id=draft_card.get("ave_id", ""),
            created_at=time.time(),
        )
        self._compiled.append(sig)
        return sig

    def reset(self) -> None:
        """Clear all compiled signatures."""
        self._compiled.clear()
        self._compile_count = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_signatures": len(self._compiled),
            "by_source": self._count_by_source(),
            "by_type": self._count_by_type(),
        }

    def _count_by_source(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sig in self._compiled:
            counts[sig.source.value] = counts.get(sig.source.value, 0) + 1
        return counts

    def _count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sig in self._compiled:
            counts[sig.sig_type.value] = counts.get(sig.sig_type.value, 0) + 1
        return counts
