"""
NAIL Institute — Defender: Memory Provenance Tagger
====================================================
Trust-level enforcement on agent memory operations.
Defends against Exp22 Memory Laundering where agents store untrusted
data in memory and later cite it as verified through self-reference.

Every memory write is tagged with provenance metadata (source, trust_level,
timestamp, writing agent). Reads enforce a trust ceiling — data cannot be
cited at a higher trust level than it was written.

Usage:
    memory = ProvenanceMemory()

    # Write with provenance
    memory.write("user_count", 50000, source="web_scrape", trust_level=0.3,
                 agent="research_agent")

    # Read with trust enforcement
    result = memory.read("user_count", required_trust=0.8)
    # result.trust_violation == True — trust 0.3 < required 0.8

    # Attempt to cite as verified → BLOCKED
    result = memory.read("user_count", cited_as_verified=True)
    # result.laundering_detected == True
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ProvenanceTag:
    """Metadata attached to every memory entry."""
    source: str                           # Where the data came from
    trust_level: float                    # 0.0 (untrusted) to 1.0 (verified)
    writing_agent: str                    # Which agent wrote this
    timestamp: float = field(default_factory=time.time)
    write_round: int = 0                  # Round number when written
    source_type: str = "unknown"          # "user_input", "tool_output", "agent_inference", "external_api"
    parent_key: Optional[str] = None      # If derived from another memory entry
    verification_method: str = "none"     # How the data was verified


@dataclass
class ReadResult:
    """Result of a provenance-checked memory read."""
    key: str
    value: Any
    found: bool
    provenance: Optional[ProvenanceTag] = None
    trust_violation: bool = False         # Read trust > write trust
    laundering_detected: bool = False     # Self-citation trust escalation
    blocked: bool = False                 # Read was blocked due to policy
    message: str = ""


class ProvenanceMemory:
    """Trust-enforced memory store with full provenance tracking.

    Prevents memory laundering by ensuring data cannot be cited at a
    higher trust level than it was originally stored with. Tracks the
    full provenance chain — who wrote what, when, and from where.

    Defence against:
        - Memory Laundering (Exp22): Agent writes low-trust data, reads it
          back citing it as verified
        - Epistemic Contagion (Exp9): Hallucinated facts propagate through
          shared memory
        - Zombie Logic (v4 detector): Superseded data resurfaces
    """

    # Trust level constants
    TRUST_VERIFIED = 1.0       # Human-verified or from authoritative source
    TRUST_HIGH = 0.8           # From trusted API or validated tool
    TRUST_MEDIUM = 0.5         # From general tool output, unchecked
    TRUST_LOW = 0.3            # Agent inference, not validated
    TRUST_UNTRUSTED = 0.1      # User input, web scrape, unknown source

    def __init__(
        self,
        trust_floor: float = 0.5,
        enforce_verification: bool = True,
        max_entries: int = 10000,
    ):
        """
        Args:
            trust_floor: Minimum trust level to cite data as "verified".
            enforce_verification: If True, blocks reads that cite low-trust
                data as verified (laundering prevention).
            max_entries: Maximum number of entries stored.
        """
        self.trust_floor = trust_floor
        self.enforce_verification = enforce_verification
        self.max_entries = max_entries

        self._store: dict[str, tuple[Any, ProvenanceTag]] = {}
        self._history: list[dict] = []  # Audit log
        self._violations: list[ReadResult] = []

    def write(
        self,
        key: str,
        value: Any,
        source: str,
        trust_level: float,
        agent: str,
        round_num: int = 0,
        source_type: str = "unknown",
        parent_key: Optional[str] = None,
        verification_method: str = "none",
    ) -> ProvenanceTag:
        """Write a value with full provenance tagging.

        Args:
            key: Memory key.
            value: The data to store.
            source: Where the data came from (e.g., "web_search", "user_input").
            trust_level: Trust level (0.0-1.0).
            agent: Name of the agent writing this data.
            round_num: Current round number.
            source_type: Category of source.
            parent_key: If derived from another entry, the parent's key.
            verification_method: How the data was verified ("none", "cross_reference", etc).

        Returns:
            ProvenanceTag attached to this entry.
        """
        # Enforce trust ceiling from parent
        if parent_key and parent_key in self._store:
            _, parent_prov = self._store[parent_key]
            trust_level = min(trust_level, parent_prov.trust_level)

        tag = ProvenanceTag(
            source=source,
            trust_level=min(max(trust_level, 0.0), 1.0),  # Clamp 0-1
            writing_agent=agent,
            write_round=round_num,
            source_type=source_type,
            parent_key=parent_key,
            verification_method=verification_method,
        )

        # Evict oldest if at capacity
        if len(self._store) >= self.max_entries and key not in self._store:
            oldest = min(self._store, key=lambda k: self._store[k][1].timestamp)
            del self._store[oldest]

        self._store[key] = (value, tag)

        self._history.append({
            "operation": "write",
            "key": key,
            "agent": agent,
            "trust_level": tag.trust_level,
            "source": source,
            "round": round_num,
            "timestamp": tag.timestamp,
        })

        return tag

    def read(
        self,
        key: str,
        reading_agent: str = "unknown",
        required_trust: float = 0.0,
        cited_as_verified: bool = False,
        round_num: int = 0,
    ) -> ReadResult:
        """Read a value with provenance and trust enforcement.

        Args:
            key: Memory key to read.
            reading_agent: Name of the agent reading this data.
            required_trust: Minimum trust level required for this read.
            cited_as_verified: If True, the agent is citing this data as verified.
            round_num: Current round number.

        Returns:
            ReadResult with value, provenance, and any violations.
        """
        if key not in self._store:
            return ReadResult(key=key, value=None, found=False, message="Key not found")

        value, prov = self._store[key]

        # Trust enforcement
        trust_violation = prov.trust_level < required_trust

        # Laundering detection: agent citing its own low-trust data as verified
        laundering = (
            cited_as_verified and
            prov.trust_level < self.trust_floor and
            prov.writing_agent == reading_agent
        )

        blocked = False
        message = ""

        if laundering and self.enforce_verification:
            blocked = True
            message = (
                f"MEMORY LAUNDERING BLOCKED: Agent '{reading_agent}' attempting to cite "
                f"key '{key}' as verified, but it was written by the same agent with "
                f"trust {prov.trust_level:.2f} (floor: {self.trust_floor:.2f})"
            )
        elif trust_violation:
            message = (
                f"Trust violation: key '{key}' has trust {prov.trust_level:.2f}, "
                f"required {required_trust:.2f}"
            )

        result = ReadResult(
            key=key,
            value=value if not blocked else None,
            found=True,
            provenance=prov,
            trust_violation=trust_violation,
            laundering_detected=laundering,
            blocked=blocked,
            message=message,
        )

        if laundering or trust_violation:
            self._violations.append(result)

        self._history.append({
            "operation": "read",
            "key": key,
            "agent": reading_agent,
            "cited_as_verified": cited_as_verified,
            "trust_level": prov.trust_level,
            "trust_violation": trust_violation,
            "laundering_detected": laundering,
            "blocked": blocked,
            "round": round_num,
            "timestamp": time.time(),
        })

        return result

    def trace_provenance(self, key: str, max_depth: int = 10) -> list[dict]:
        """Trace the full provenance chain for a memory entry.

        Follows parent_key links back to the original source.

        Args:
            key: Starting key.
            max_depth: Maximum chain depth to prevent infinite loops.

        Returns:
            List of provenance records from newest to oldest.
        """
        chain = []
        current_key = key
        visited = set()

        for _ in range(max_depth):
            if current_key not in self._store or current_key in visited:
                break
            visited.add(current_key)

            value, prov = self._store[current_key]
            chain.append({
                "key": current_key,
                "source": prov.source,
                "trust_level": prov.trust_level,
                "writing_agent": prov.writing_agent,
                "timestamp": prov.timestamp,
                "source_type": prov.source_type,
                "verification": prov.verification_method,
            })

            if prov.parent_key:
                current_key = prov.parent_key
            else:
                break

        return chain

    @property
    def violations(self) -> list[ReadResult]:
        """All trust violations and laundering attempts."""
        return self._violations

    @property
    def audit_log(self) -> list[dict]:
        """Full read/write audit log."""
        return self._history

    def get_stats(self) -> dict:
        """Summary statistics."""
        total_writes = sum(1 for h in self._history if h["operation"] == "write")
        total_reads = sum(1 for h in self._history if h["operation"] == "read")
        laundering_attempts = sum(1 for v in self._violations if v.laundering_detected)
        trust_violations = sum(1 for v in self._violations if v.trust_violation)

        return {
            "entries": len(self._store),
            "total_writes": total_writes,
            "total_reads": total_reads,
            "violations": len(self._violations),
            "laundering_attempts": laundering_attempts,
            "trust_violations": trust_violations,
            "laundering_blocked": sum(1 for v in self._violations if v.blocked),
        }

    def reset(self):
        """Clear all state."""
        self._store.clear()
        self._history.clear()
        self._violations.clear()
