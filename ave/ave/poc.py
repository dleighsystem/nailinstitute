"""
PoC — Proof of Concept data model for AVE Cards
=================================================

Every AVE Card should include reproducible evidence. This module
defines structured PoC types:

  1. ScriptPoC     — A Python script that reproduces the vulnerability
  2. LogPoC        — A JSON conversation/event log demonstrating the failure
  3. ConfigPoC     — Agent configuration that triggers the behaviour
  4. CompositePoC  — Combines multiple PoC artifacts

PoCs are versioned, timestamped, and include execution environment
metadata so reviewers can reproduce findings.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class PoCType(str, Enum):
    """Classification of proof-of-concept artifact."""
    SCRIPT = "script"            # Executable Python reproduction script
    LOG = "log"                  # JSON log / conversation trace
    CONFIG = "config"            # Agent/system configuration
    PROMPT = "prompt"            # Adversarial prompt that triggers the vuln
    COMPOSITE = "composite"      # Bundle of multiple artifacts


class PoCStatus(str, Enum):
    """Review status of the PoC."""
    DRAFT = "draft"              # Not yet reviewed
    VERIFIED = "verified"        # Independently reproduced
    DISPUTED = "disputed"        # Reproduction failed / contested
    REDACTED = "redacted"        # Removed for safety reasons


@dataclass
class PoCEnvironment:
    """
    Execution environment required to reproduce the PoC.
    Allows reviewers to set up identical conditions.
    """
    python_version: str = "3.12"
    framework: str = ""                    # e.g. "LangGraph 0.2"
    model: str = ""                        # e.g. "nemotron:70b"
    model_provider: str = "ollama"         # ollama, openai, anthropic, etc.
    hardware: str = ""                     # e.g. "NVIDIA DGX GB10"
    packages: tuple[str, ...] = ()         # e.g. ("langchain>=0.3", "chromadb")
    env_vars: tuple[str, ...] = ()         # Required env vars (names only, not values)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "python_version": self.python_version,
            "framework": self.framework,
            "model": self.model,
            "model_provider": self.model_provider,
            "hardware": self.hardware,
            "packages": list(self.packages),
            "env_vars": list(self.env_vars),
            "notes": self.notes,
        }


@dataclass
class PoCScript:
    """
    An executable Python script that reproduces the vulnerability.

    The script should be self-contained and exit with code 0 on success
    (vulnerability reproduced) or non-zero on failure (could not reproduce).
    """
    filename: str                          # e.g. "reproduce_ave_0001.py"
    code: str                              # The full Python source
    description: str = ""                  # What the script does
    expected_output: str = ""              # What output indicates success
    timeout_seconds: int = 300             # Max execution time
    requires_model: bool = True            # Needs a running LLM?

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.code.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "description": self.description,
            "expected_output": self.expected_output,
            "timeout_seconds": self.timeout_seconds,
            "requires_model": self.requires_model,
            "code_lines": self.code.count("\n") + 1,
        }


@dataclass
class PoCLog:
    """
    A JSON conversation or event log demonstrating the failure.

    Typically a sequence of agent interactions showing how the
    vulnerability manifests step by step.
    """
    log_name: str                          # e.g. "consensus_deadlock_trace.json"
    entries: tuple[dict[str, Any], ...] = ()  # The log entries
    description: str = ""
    total_tokens: int = 0                  # Total tokens consumed in this trace
    total_rounds: int = 0                  # Number of agent rounds
    failure_round: int = 0                 # Which round the failure first appears

    def to_dict(self) -> dict:
        return {
            "log_name": self.log_name,
            "description": self.description,
            "total_tokens": self.total_tokens,
            "total_rounds": self.total_rounds,
            "failure_round": self.failure_round,
            "entry_count": len(self.entries),
        }

    def to_json(self) -> str:
        """Full JSON dump of all log entries."""
        return json.dumps(
            {
                "log_name": self.log_name,
                "description": self.description,
                "metadata": {
                    "total_tokens": self.total_tokens,
                    "total_rounds": self.total_rounds,
                    "failure_round": self.failure_round,
                },
                "entries": list(self.entries),
            },
            indent=2,
        )


@dataclass
class PoCPrompt:
    """
    An adversarial prompt that triggers the vulnerability.

    This is the minimum reproducible example — just the text
    an attacker would send to exploit the vulnerability.
    """
    prompt_text: str                       # The adversarial prompt
    target_role: str = "user"              # Which role sends this (user, system, tool)
    context: str = ""                      # Setup context needed
    expected_behaviour: str = ""           # What happens when this fires
    bypass_type: str = ""                  # e.g. "direct_injection", "indirect", "multi-turn"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.prompt_text.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "sha256": self.sha256,
            "target_role": self.target_role,
            "context": self.context,
            "expected_behaviour": self.expected_behaviour,
            "bypass_type": self.bypass_type,
            "prompt_length": len(self.prompt_text),
        }


@dataclass
class ProofOfConcept:
    """
    Complete Proof of Concept bundle for an AVE Card.

    Combines scripts, logs, prompts, and environment information
    into a single reproducible artifact. This is what gets attached
    to an AVE Card and published to the public repository.
    """
    poc_id: str                            # e.g. "PoC-AVE-2025-0001-v1"
    ave_id: str                            # Parent AVE Card ID
    poc_type: PoCType = PoCType.COMPOSITE
    status: PoCStatus = PoCStatus.DRAFT
    version: int = 1
    author: str = "NAIL Institute"
    description: str = ""

    # ── Artifacts ───────────────────────────────────────────────────
    scripts: tuple[PoCScript, ...] = ()
    logs: tuple[PoCLog, ...] = ()
    prompts: tuple[PoCPrompt, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)

    # ── Environment ─────────────────────────────────────────────────
    environment: PoCEnvironment = field(default_factory=PoCEnvironment)

    # ── Metadata ────────────────────────────────────────────────────
    created_at: str = ""
    verified_at: str = ""
    verified_by: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @property
    def artifact_count(self) -> int:
        """Total number of PoC artifacts."""
        return len(self.scripts) + len(self.logs) + len(self.prompts) + (1 if self.config else 0)

    def verify(self, verified_by: str) -> None:
        """Mark this PoC as independently verified."""
        self.status = PoCStatus.VERIFIED
        self.verified_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.verified_by = verified_by

    def redact(self, reason: str = "") -> None:
        """Redact this PoC for safety reasons."""
        self.status = PoCStatus.REDACTED
        self.notes = reason or "Redacted for safety"

    def to_dict(self) -> dict:
        return {
            "poc_id": self.poc_id,
            "ave_id": self.ave_id,
            "poc_type": self.poc_type.value,
            "status": self.status.value,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "artifact_count": self.artifact_count,
            "scripts": [s.to_dict() for s in self.scripts],
            "logs": [l.to_dict() for l in self.logs],
            "prompts": [p.to_dict() for p in self.prompts],
            "config": self.config,
            "environment": self.environment.to_dict(),
            "created_at": self.created_at,
            "verified_at": self.verified_at,
            "verified_by": self.verified_by,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        """Full JSON serialisation."""
        return json.dumps(self.to_dict(), indent=2)

    def summary(self) -> str:
        """One-line summary."""
        return (
            f"[{self.poc_id}] {self.poc_type.value} | "
            f"{self.artifact_count} artifacts | "
            f"status={self.status.value}"
        )
