"""NAIL Agent Pathology Registry.

The registry is the operator-facing catalogue for agent pathologies. Detectors
emit alerts; registry entries explain what the alert means, what telemetry it
depends on, and which remedies should be considered first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .types import PathologyType, Severity


@dataclass(frozen=True)
class PathologyDefinition:
    """Stable metadata for a monitored agent pathology."""

    pathology: PathologyType
    name: str
    category: str
    detector: str
    description: str
    signals: tuple[str, ...]
    remedies: tuple[str, ...]
    default_severity: Severity = Severity.WARNING
    references: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "pathology": self.pathology.value,
            "name": self.name,
            "category": self.category,
            "detector": self.detector,
            "description": self.description,
            "signals": list(self.signals),
            "remedies": list(self.remedies),
            "default_severity": self.default_severity.value,
            "references": list(self.references),
        }


class AgentPathologyRegistry:
    """In-memory registry with deterministic lookup and filtering."""

    def __init__(self, definitions: Iterable[PathologyDefinition] = ()) -> None:
        self._definitions: dict[PathologyType, PathologyDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: PathologyDefinition) -> None:
        self._definitions[definition.pathology] = definition

    def get(self, pathology: PathologyType | str) -> PathologyDefinition:
        key = pathology if isinstance(pathology, PathologyType) else PathologyType(pathology)
        return self._definitions[key]

    def all(self) -> list[PathologyDefinition]:
        return list(self._definitions.values())

    def by_category(self, category: str) -> list[PathologyDefinition]:
        wanted = category.strip().lower()
        return [
            definition
            for definition in self._definitions.values()
            if definition.category.lower() == wanted
        ]

    def to_dict(self) -> dict:
        return {
            definition.pathology.value: definition.to_dict()
            for definition in self._definitions.values()
        }


DEFAULT_PATHOLOGY_REGISTRY = AgentPathologyRegistry(
    [
        PathologyDefinition(
            pathology=PathologyType.TOOL_MANIFEST_POISONING,
            name="Tool Manifest Poisoning",
            category="control_plane",
            detector="ToolManifestIntegrityDetector",
            description=(
                "A tool or MCP server presents changed, unsigned, or instruction-like "
                "metadata that can steer agent planning before any tool call executes."
            ),
            signals=(
                "tool manifest hash drift",
                "new untrusted tool metadata",
                "imperative or secrecy language in tool descriptions/schemas",
                "privilege or network scope expansion",
            ),
            remedies=(
                "sign and hash tool manifests",
                "pin canonical descriptions for approved tools",
                "quarantine new MCP servers until reviewed",
                "require human approval for privilege expansion",
            ),
            default_severity=Severity.CRITICAL,
            references=("mcp-tool-poisoning", "owasp-agentic-ai-supply-chain"),
        ),
        PathologyDefinition(
            pathology=PathologyType.MEMORY_WRITE_POISONING,
            name="Memory Write Poisoning",
            category="state",
            detector="MemoryWriteFirewallDetector",
            description=(
                "Untrusted input attempts to persist policies, credentials, goals, "
                "routing decisions, or other privileged state into long-term memory."
            ),
            signals=(
                "low-trust memory write",
                "protected fact type from external/user/tool source",
                "secret-like content in memory",
                "missing provenance or expiry on untrusted memory",
            ),
            remedies=(
                "quarantine risky memory writes",
                "require source, trust level, and expiry metadata",
                "human-review protected fact types",
                "separate user facts from policy/config memory",
            ),
            default_severity=Severity.CRITICAL,
            references=("memory-poisoning", "persistent-agent-state"),
        ),
        PathologyDefinition(
            pathology=PathologyType.GOAL_DRIFT,
            name="Goal Drift",
            category="trajectory",
            detector="GoalDriftMonitorDetector",
            description=(
                "The agent's plan, tool use, or proposed action diverges from the "
                "session goal or shows self-preservation, evasion, data exfiltration, "
                "or control-plane manipulation motives."
            ),
            signals=(
                "low lexical overlap with declared goal",
                "sensitive action outside allowed tools/domains",
                "self-preservation or monitoring-evasion language",
                "secret/data exfiltration intent",
            ),
            remedies=(
                "restate and reauthorize the goal",
                "gate sensitive actions",
                "replan from a clean context",
                "restrict tools until drift clears",
            ),
            default_severity=Severity.WARNING,
            references=("agentic-misalignment", "trajectory-monitoring"),
        ),
        PathologyDefinition(
            pathology=PathologyType.TOOL_RETRIEVAL_MANIPULATION,
            name="Tool Retrieval Manipulation",
            category="control_plane",
            detector="ToolRetrievalIntegrityDetector",
            description=(
                "Lazy/selective tool loading is steered so a required safety tool is "
                "never retrieved (starvation) or an unauthorised, often high-risk, tool "
                "is surfaced into the loaded subset — a failure a full-manifest scan "
                "cannot see because it only inspects tools that were loaded."
            ),
            signals=(
                "required/approval tool absent from the loaded subset",
                "loaded tool outside the authorised least-privilege set",
                "high-risk scope (shell/network/secrets/...) surfaced outside task scope",
                "retrieved tool-set diverges from the task baseline",
            ),
            remedies=(
                "declare required tools per task and fail closed when absent",
                "allowlist retrievable tools to a least-privilege authorised set",
                "gate high-risk-scope tools behind explicit authorisation",
                "attest the loaded subset per turn against the authorised registry",
            ),
            default_severity=Severity.CRITICAL,
            references=("AVE-2026-0045", "mcp-tool-retrieval", "least-privilege-tools"),
        ),
    ]
)

