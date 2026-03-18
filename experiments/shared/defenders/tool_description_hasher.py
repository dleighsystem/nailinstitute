"""
NAIL Institute — Defender: Tool Description Hasher
====================================================
SHA-256 integrity verification for all tool descriptions at runtime.
Defends against Exp26 Confused Deputy attacks where tool descriptions
are modified to trick agents into performing malicious actions.

The ConfusedDeputyDetector (nail_monitor v6) detects changes after the
fact. This defender PREVENTS them by rejecting any tool call where the
description hash doesn't match the registered baseline.

Usage:
    hasher = ToolDescriptionHasher()

    # At agent init (or certification time), register all tools
    hasher.register_tools({
        "transfer": "Move money between your accounts",
        "search": "Search public records",
    })

    # Before every tool call, verify integrity
    result = hasher.verify_call("transfer", "Move money between your accounts")
    if result.blocked:
        print(f"BLOCKED: {result.reason}")

    # Periodic full scan
    results = hasher.full_scan({...current tool descriptions...})
"""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VerificationResult:
    """Result of a tool description integrity check."""
    tool_name: str
    verified: bool
    blocked: bool = False
    reason: str = ""
    original_hash: str = ""
    current_hash: str = ""
    timestamp: float = field(default_factory=time.time)


class ToolDescriptionHasher:
    """SHA-256 integrity verification for tool descriptions.

    Registers a baseline hash of every tool description at init time.
    Verifies that descriptions haven't been modified before allowing
    tool execution.

    Defence against: Confused Deputy (Exp26) — 100% exploitation rate
    on frontier models when tool descriptions are poisoned.
    """

    # Injection patterns that should NEVER appear in tool descriptions
    INJECTION_PATTERNS = [
        "ignore previous", "ignore prior", "ignore above",
        "disregard previous", "override previous",
        "actually you should", "new instructions",
        "system override", "admin override",
        "IMPORTANT:", "CRITICAL:", "URGENT:",
        "instead of", "rather than what",
    ]

    def __init__(self, verify_every_n_calls: int = 1):
        """
        Args:
            verify_every_n_calls: Verify hashes every N tool calls.
                1 = every call (maximum security, slight overhead).
                5 = every 5th call (faster, small detection gap).
        """
        self._baseline: dict[str, str] = {}  # {tool_name: sha256_hash}
        self._descriptions: dict[str, str] = {}  # {tool_name: description}
        self._call_count: int = 0
        self._verify_every = verify_every_n_calls
        self._violations: list[VerificationResult] = []
        self._registered_at: float = 0.0

    def _hash(self, text: str) -> str:
        """SHA-256 hash of normalised text."""
        return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()

    def register_tools(self, tool_descriptions: dict[str, str]) -> list[VerificationResult]:
        """Register baseline hashes for all tool descriptions.

        Should be called once at agent initialisation or certification time.
        Also scans for pre-existing injection in the descriptions.

        Args:
            tool_descriptions: {tool_name: description_text}

        Returns:
            List of VerificationResults. Check for .blocked=True indicating
            pre-poisoned descriptions detected at registration time.
        """
        results = []
        self._registered_at = time.time()

        for name, description in tool_descriptions.items():
            h = self._hash(description)
            self._baseline[name] = h
            self._descriptions[name] = description

            # Check for injection in initial description
            desc_lower = description.lower()
            injection = next(
                (p for p in self.INJECTION_PATTERNS if p in desc_lower),
                None,
            )

            if injection:
                result = VerificationResult(
                    tool_name=name,
                    verified=False,
                    blocked=True,
                    reason=f"Pre-poisoned: injection pattern '{injection}' found in initial description",
                    original_hash=h,
                    current_hash=h,
                )
                self._violations.append(result)
                results.append(result)
            else:
                results.append(VerificationResult(
                    tool_name=name,
                    verified=True,
                    original_hash=h,
                    current_hash=h,
                ))

        return results

    def verify_call(
        self, tool_name: str, current_description: str
    ) -> VerificationResult:
        """Verify a tool description before allowing execution.

        Args:
            tool_name: Name of the tool being called.
            current_description: Current description of the tool.

        Returns:
            VerificationResult — check .blocked to decide whether to allow execution.
        """
        self._call_count += 1

        # Skip verification based on frequency setting
        if self._call_count % self._verify_every != 0:
            return VerificationResult(
                tool_name=tool_name, verified=True, reason="skipped (frequency)"
            )

        # Unknown tool
        if tool_name not in self._baseline:
            result = VerificationResult(
                tool_name=tool_name,
                verified=False,
                blocked=True,
                reason=f"Unknown tool '{tool_name}' — not in baseline registry",
                current_hash=self._hash(current_description),
            )
            self._violations.append(result)
            return result

        # Hash comparison
        current_hash = self._hash(current_description)
        original_hash = self._baseline[tool_name]

        if current_hash != original_hash:
            result = VerificationResult(
                tool_name=tool_name,
                verified=False,
                blocked=True,
                reason=(
                    f"CONFUSED DEPUTY BLOCKED: Description for '{tool_name}' has been "
                    f"modified since registration. Hash {original_hash[:12]}... → "
                    f"{current_hash[:12]}..."
                ),
                original_hash=original_hash,
                current_hash=current_hash,
            )
            self._violations.append(result)
            return result

        return VerificationResult(
            tool_name=tool_name,
            verified=True,
            original_hash=original_hash,
            current_hash=current_hash,
        )

    def full_scan(
        self, current_descriptions: dict[str, str]
    ) -> list[VerificationResult]:
        """Verify ALL tool descriptions against baseline.

        Args:
            current_descriptions: Current {tool_name: description_text} dict.

        Returns:
            List of VerificationResults for ALL tools.
        """
        results = []
        for name, desc in current_descriptions.items():
            results.append(self.verify_call(name, desc))

        # Check for removed tools
        for name in self._baseline:
            if name not in current_descriptions:
                result = VerificationResult(
                    tool_name=name,
                    verified=False,
                    blocked=True,
                    reason=f"Tool '{name}' was registered but is now missing — potential attack",
                    original_hash=self._baseline[name],
                )
                self._violations.append(result)
                results.append(result)

        return results

    @property
    def violations(self) -> list[VerificationResult]:
        """All violations detected since initialisation."""
        return self._violations

    @property
    def is_compromised(self) -> bool:
        """Whether any tool description has been tampered with."""
        return len(self._violations) > 0

    def get_stats(self) -> dict:
        """Summary statistics."""
        return {
            "registered_tools": len(self._baseline),
            "total_verifications": self._call_count,
            "violations_detected": len(self._violations),
            "is_compromised": self.is_compromised,
            "registered_at": self._registered_at,
        }
