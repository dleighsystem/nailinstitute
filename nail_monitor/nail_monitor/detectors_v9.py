"""
nail-monitor: v9 Detectors — Agent control-plane pathology pack
================================================================

These detectors monitor the surfaces where modern agents fail before the final
answer exists: tool metadata, persistent memory writes, and trajectory drift.
They are deterministic and metadata-driven so they can run in production
without model calls or network access.

Metadata contracts:
    - tool_manifest / tool_manifests: tool/MCP metadata snapshots
    - memory_writes: proposed long-term memory writes
    - task_goal/session_id/plan_steps/tool_calls/action: trajectory state
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Optional

from .detectors import BaseDetector
from .types import Alert, Observation, PathologyType, Severity


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "into", "is", "it", "of", "on", "or", "our", "that", "the", "their",
    "this", "to", "use", "using", "with", "you", "your",
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{k} {_flatten_text(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(v) for v in value)
    return str(value)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
        if token not in _STOPWORDS
    }


def _first_present(data: dict[str, Any], names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return default


class ToolManifestIntegrityDetector(BaseDetector):
    """Detect poisoned or drifting tool/MCP metadata.

    The first clean manifest for a tool becomes its baseline. Later hash drift,
    suspicious instructions in metadata, or unreviewed new tools raise alerts.

    Metadata keys:
        - tool_manifest: dict for one tool
        - tool_manifests: list[dict] or dict[name, dict]
    """

    SUSPICIOUS_PATTERNS = (
        r"\b(ignore|disregard|forget)\b.{0,80}\b(instructions?|rules?|polic(?:y|ies)|system|developer)\b",
        r"\b(do not|don't|never)\b.{0,80}\b(tell|reveal|mention|disclose|log|audit)\b",
        r"\b(hidden|secret|covert|stealth|silent(?:ly)?)\b.{0,80}\b(instruction|prompt|rule|mode|channel)\b",
        r"\b(exfiltrate|leak|dump|copy|send)\b.{0,80}\b(secret|token|credential|password|api[_ -]?key|env)\b",
        r"\b(system prompt|developer message|chain[- ]of[- ]thought|private key|bearer token)\b",
        r"\b(bypass|disable|override|circumvent)\b.{0,80}\b(guard|safety|policy|monitor|approval)\b",
    )
    HIGH_RISK_SCOPES = {"network", "filesystem", "shell", "database", "email", "secrets", "payments"}

    def __init__(
        self,
        *,
        allow_new_tools: bool = True,
        require_signature_for_high_risk: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="ToolManifestIntegrityDetector",
            pathology=PathologyType.TOOL_MANIFEST_POISONING,
            enabled=enabled,
        )
        self.allow_new_tools = allow_new_tools
        self.require_signature_for_high_risk = require_signature_for_high_risk
        self._compiled = [re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in self.SUSPICIOUS_PATTERNS]
        self._baseline_hashes: dict[str, str] = {}
        self._baseline_scopes: dict[str, set[str]] = {}

    def check(self) -> Optional[Alert]:
        obs = self.observations[-1]
        manifests = self._normalise_manifests(obs.metadata)
        for manifest in manifests:
            alert = self._check_manifest(manifest, obs)
            if alert:
                return alert
        return None

    def _normalise_manifests(self, meta: dict[str, Any]) -> list[dict[str, Any]]:
        raw = meta.get("tool_manifests", [])
        if isinstance(raw, dict):
            manifests = []
            for name, spec in raw.items():
                item = dict(spec or {}) if isinstance(spec, dict) else {"description": spec}
                item.setdefault("name", str(name))
                manifests.append(item)
            raw = manifests
        elif raw is None:
            raw = []
        elif not isinstance(raw, list):
            raw = [raw]

        if "tool_manifest" in meta:
            raw = [*raw, meta["tool_manifest"]]

        return [dict(item) for item in raw if isinstance(item, dict)]

    def _tool_id(self, manifest: dict[str, Any]) -> str:
        name = str(_first_present(manifest, ("name", "tool_name", "id"), "unknown"))
        server = str(_first_present(manifest, ("server", "mcp_server", "provider"), "local"))
        return f"{server}/{name}"

    def _scopes(self, manifest: dict[str, Any]) -> set[str]:
        raw = _first_present(manifest, ("scopes", "permissions", "capabilities"), [])
        if isinstance(raw, str):
            raw = re.split(r"[,;\s]+", raw)
        if not isinstance(raw, Iterable):
            return set()
        return {str(item).strip().lower() for item in raw if str(item).strip()}

    def _check_manifest(self, manifest: dict[str, Any], obs: Observation) -> Optional[Alert]:
        tool_id = self._tool_id(manifest)
        description_text = _flatten_text(
            {
                "description": manifest.get("description"),
                "input_schema": manifest.get("input_schema"),
                "parameters": manifest.get("parameters"),
                "annotations": manifest.get("annotations"),
            }
        )
        for pattern in self._compiled:
            match = pattern.search(description_text)
            if match:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.CRITICAL,
                    message=f"Suspicious tool metadata for {tool_id}: {match.group(0)[:120]}",
                    metric_value=1.0,
                    threshold=0.0,
                    metadata={
                        "tool_id": tool_id,
                        "reason": "suspicious_metadata_instruction",
                        "pattern": pattern.pattern,
                        "match": match.group(0)[:200],
                    },
                )

        manifest_hash = _fingerprint(
            {
                "name": _first_present(manifest, ("name", "tool_name", "id"), "unknown"),
                "description": manifest.get("description", ""),
                "input_schema": manifest.get("input_schema", manifest.get("parameters", {})),
                "annotations": manifest.get("annotations", {}),
                "scopes": sorted(self._scopes(manifest)),
            }
        )
        scopes = self._scopes(manifest)
        high_risk_scopes = scopes & self.HIGH_RISK_SCOPES
        signed = bool(manifest.get("signature") or manifest.get("signed") or manifest.get("verified"))

        if tool_id not in self._baseline_hashes:
            self._baseline_hashes[tool_id] = manifest_hash
            self._baseline_scopes[tool_id] = set(scopes)
            if not self.allow_new_tools:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.WARNING,
                    message=f"New tool manifest observed without prior baseline: {tool_id}",
                    metric_value=1.0,
                    threshold=0.0,
                    metadata={"tool_id": tool_id, "reason": "new_tool_without_baseline"},
                )
            if self.require_signature_for_high_risk and high_risk_scopes and not signed:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.WARNING,
                    message=f"High-risk tool {tool_id} lacks verified signature: {sorted(high_risk_scopes)}",
                    metric_value=float(len(high_risk_scopes)),
                    threshold=1.0,
                    metadata={
                        "tool_id": tool_id,
                        "reason": "unsigned_high_risk_tool",
                        "scopes": sorted(scopes),
                    },
                )
            return None

        if manifest_hash != self._baseline_hashes[tool_id]:
            old_scopes = self._baseline_scopes.get(tool_id, set())
            expanded = sorted(scopes - old_scopes)
            severity = Severity.CRITICAL if (set(expanded) & self.HIGH_RISK_SCOPES) else Severity.WARNING
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=severity,
                message=f"Tool manifest drift detected for {tool_id}",
                metric_value=1.0,
                threshold=0.0,
                metadata={
                    "tool_id": tool_id,
                    "reason": "manifest_hash_drift",
                    "baseline_hash": self._baseline_hashes[tool_id],
                    "current_hash": manifest_hash,
                    "expanded_scopes": expanded,
                },
            )
        return None

    def reset(self):
        super().reset()
        self._baseline_hashes = {}
        self._baseline_scopes = {}


# ── Tool retrieval integrity (lazy / selective tool loading) ─────────────────

def _as_tool_list(raw: Any) -> list[Any]:
    """Normalise a loaded/authorised/required tool spec into a flat list."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        items: list[Any] = []
        for name, spec in raw.items():
            if isinstance(spec, dict):
                manifest = dict(spec)
                manifest.setdefault("name", str(name))
                items.append(manifest)
            else:
                items.append({"name": str(name)})
        return items
    if isinstance(raw, (str, bytes)):
        return [raw]
    if isinstance(raw, Iterable):
        return list(raw)
    return [raw]


def _tool_name(item: Any) -> str:
    """Stable, server-agnostic tool identity (last path segment, lowercased)."""
    if isinstance(item, dict):
        name = _first_present(item, ("name", "tool_name", "id"), "")
    else:
        name = item
    name = str(name).strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return name


def _scopes_of(item: Any) -> set[str]:
    if not isinstance(item, dict):
        return set()
    raw = _first_present(item, ("scopes", "permissions", "capabilities"), [])
    if isinstance(raw, str):
        raw = re.split(r"[,;\s]+", raw)
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return set()
    return {str(x).strip().lower() for x in raw if str(x).strip()}


class ToolRetrievalIntegrityDetector(BaseDetector):
    """Detect manipulation of lazy / selective (retrieved) tool loading.

    Modern agents cut context cost by retrieving only the tools relevant to the
    current task instead of loading the full manifest. That subset is an attack
    surface a full-manifest scan cannot see:

      * starvation — a required safety/approval/validation tool is not retrieved,
        so the agent proceeds without it (no poisoned tool, an *absent* one);
      * surfacing — a tool the task never authorised (often high-risk scope) is
        pulled into the loaded subset.

    Metadata keys (per observation):
      * loaded_tools     — the tool subset actually loaded this turn (ids or
                           manifest dicts). Presence of this key activates the
                           detector; without it the detector stays silent.
      * authorized_tools — the least-privilege set the agent/task may load (ids
                           or manifests; supplies scope info). May instead be
                           fixed once at construction.
      * required_tools   — ids that MUST be loaded for this task (safety/approval).

    With neither authorized_tools nor required_tools configured the detector is
    silent by design (no policy => no false positives).
    """

    HIGH_RISK_SCOPES = {"network", "filesystem", "shell", "database", "email", "secrets", "payments"}

    def __init__(
        self,
        *,
        authorized_tools: Any = None,
        required_tools: Any = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="ToolRetrievalIntegrityDetector",
            pathology=PathologyType.TOOL_RETRIEVAL_MANIPULATION,
            enabled=enabled,
        )
        self._default_authorized = self._index(authorized_tools)
        self._default_required = {_tool_name(t) for t in _as_tool_list(required_tools)}

    @staticmethod
    def _index(raw: Any) -> dict[str, set[str]]:
        """Map tool name -> scope set for a loaded/authorised spec."""
        return {_tool_name(entry): _scopes_of(entry) for entry in _as_tool_list(raw)}

    def check(self) -> Optional[Alert]:
        obs = self.observations[-1]
        meta = obs.metadata
        if "loaded_tools" not in meta:
            return None

        loaded = self._index(meta.get("loaded_tools"))
        authorized = self._index(meta.get("authorized_tools")) or self._default_authorized
        required = {_tool_name(t) for t in _as_tool_list(meta.get("required_tools"))} or self._default_required

        # 1) Starvation — a required tool was not retrieved into the loaded subset.
        missing = sorted(required - set(loaded))
        if missing:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Required tool(s) not retrieved for task: {missing}",
                metric_value=float(len(missing)),
                threshold=0.0,
                metadata={
                    "reason": "required_tool_starved",
                    "missing_tools": missing,
                    "loaded_tools": sorted(loaded),
                },
            )

        # 2) Surfacing — a loaded tool is outside the authorised least-privilege set.
        if authorized:
            unauthorized = sorted(set(loaded) - set(authorized))
            if unauthorized:
                risky = sorted({
                    scope
                    for tool in unauthorized
                    for scope in loaded.get(tool, set())
                    if scope in self.HIGH_RISK_SCOPES
                })
                severity = Severity.CRITICAL if risky else Severity.WARNING
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=severity,
                    message=f"Unauthorised tool(s) surfaced by retrieval: {unauthorized}",
                    metric_value=float(len(unauthorized)),
                    threshold=0.0,
                    metadata={
                        "reason": "unauthorized_tool_surfaced",
                        "unauthorized_tools": unauthorized,
                        "high_risk_scopes": risky,
                    },
                )
        return None


class MemoryWriteFirewallDetector(BaseDetector):
    """Detect risky long-term memory writes before trust can be laundered.

    Metadata keys:
        - memory_writes: [{key, value, source, trust_level, fact_type,
                           human_reviewed, provenance, ttl_seconds}, ...]
    """

    PROTECTED_FACT_TYPES = {
        "policy", "procedure", "credential", "secret", "token", "permission",
        "routing", "tool_config", "system_prompt", "developer_instruction",
        "safety_rule", "identity", "goal", "authority", "billing", "legal",
        "financial_advice", "medical_advice",
    }
    UNTRUSTED_SOURCES = {"user", "tool", "external", "web", "rag", "scraped", "email", "clipboard"}
    SECRET_PATTERNS = (
        r"\b(?:sk|nail_sk|ghp|xox[baprs]|AIza|SG)\S{12,}\b",
        r"(?i)\b(api[_ -]?key|secret|token|password|credential)\s*[:=]\s*[^\s,;]+",
        r"\b[A-Za-z0-9+/]{32,}={0,2}\b",
    )

    def __init__(
        self,
        *,
        trust_floor: float = 0.5,
        require_provenance_for_untrusted: bool = True,
        require_expiry_for_untrusted: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="MemoryWriteFirewallDetector",
            pathology=PathologyType.MEMORY_WRITE_POISONING,
            enabled=enabled,
        )
        self.trust_floor = trust_floor
        self.require_provenance_for_untrusted = require_provenance_for_untrusted
        self.require_expiry_for_untrusted = require_expiry_for_untrusted
        self._secret_patterns = [re.compile(pattern) for pattern in self.SECRET_PATTERNS]

    def check(self) -> Optional[Alert]:
        obs = self.observations[-1]
        for write in obs.metadata.get("memory_writes", []) or []:
            if isinstance(write, dict):
                alert = self._check_write(write, obs)
                if alert:
                    return alert
        return None

    def _check_write(self, write: dict[str, Any], obs: Observation) -> Optional[Alert]:
        key = str(write.get("key") or write.get("id") or "unknown")
        value = str(write.get("value") or write.get("content") or "")
        source = str(write.get("source") or "unknown").strip().lower()
        fact_type = str(write.get("fact_type") or write.get("type") or write.get("category") or "").strip().lower()
        trust = float(write.get("trust_level", write.get("trust", 1.0)) or 0.0)
        human_reviewed = bool(write.get("human_reviewed") or write.get("approved_by_human"))
        provenance = write.get("provenance") or write.get("source_uri") or write.get("source_id")
        ttl_seconds = write.get("ttl_seconds", write.get("expires_in_seconds"))
        untrusted = source in self.UNTRUSTED_SOURCES or trust < self.trust_floor

        for pattern in self._secret_patterns:
            if pattern.search(f"{key} {value}"):
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.CRITICAL,
                    message=f"Secret-like material attempted to enter memory key '{key}'",
                    metric_value=1.0,
                    threshold=0.0,
                    metadata={
                        "agent": obs.agent_name,
                        "memory_key": key,
                        "source": source,
                        "fact_type": fact_type,
                        "reason": "secret_like_memory_write",
                    },
                )

        if untrusted and fact_type in self.PROTECTED_FACT_TYPES and not human_reviewed:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=(
                    f"Untrusted memory write to protected fact type '{fact_type}' "
                    f"for key '{key}' requires quarantine/review"
                ),
                metric_value=trust,
                threshold=self.trust_floor,
                metadata={
                    "agent": obs.agent_name,
                    "memory_key": key,
                    "source": source,
                    "fact_type": fact_type,
                    "trust_level": trust,
                    "reason": "protected_fact_from_untrusted_source",
                },
            )

        missing_controls = []
        if untrusted and self.require_provenance_for_untrusted and not provenance:
            missing_controls.append("provenance")
        if untrusted and self.require_expiry_for_untrusted and not ttl_seconds:
            missing_controls.append("ttl_seconds")
        if missing_controls:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=f"Untrusted memory write '{key}' missing controls: {', '.join(missing_controls)}",
                metric_value=float(len(missing_controls)),
                threshold=1.0,
                metadata={
                    "agent": obs.agent_name,
                    "memory_key": key,
                    "source": source,
                    "fact_type": fact_type,
                    "trust_level": trust,
                    "missing_controls": missing_controls,
                    "reason": "missing_memory_write_controls",
                },
            )
        return None


class GoalDriftMonitorDetector(BaseDetector):
    """Detect trajectory drift away from the user's authorized goal.

    Metadata keys:
        - session_id: stable session/trajectory id
        - task_goal or goal or user_goal: authorized goal text
        - plan_steps: list[str]
        - action or proposed_action: current action text
        - tool_calls: list[dict]
        - allowed_tools: list[str]
        - allowed_domains: list[str]
        - sensitive_action: bool
        - goal_alignment_score: optional precomputed [0,1]
    """

    CONTROL_PLANE_PATTERNS = (
        r"\b(avoid|ignore|bypass|disable|evade)\b.{0,80}\b(monitor|audit|logging|oversight|approval)\b",
        r"\b(prevent|avoid|resist)\b.{0,80}\b(shutdown|halt|revocation|rollback|replacement)\b",
        r"\b(exfiltrate|leak|dump|copy|send)\b.{0,80}\b(data|secret|token|credential|database|file)\b",
        r"\b(persist|backdoor|maintain access|escalate privilege|privilege escalation)\b",
        r"\b(change|rewrite|override|update)\b.{0,80}\b(policy|memory|goal|guardrail|system prompt)\b",
    )

    def __init__(
        self,
        *,
        overlap_warning: float = 0.20,
        overlap_critical: float = 0.08,
        sensitive_action_overlap_floor: float = 0.30,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="GoalDriftMonitorDetector",
            pathology=PathologyType.GOAL_DRIFT,
            enabled=enabled,
        )
        self.overlap_warning = overlap_warning
        self.overlap_critical = overlap_critical
        self.sensitive_action_overlap_floor = sensitive_action_overlap_floor
        self._compiled = [re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in self.CONTROL_PLANE_PATTERNS]
        self._session_goals: dict[str, str] = {}
        self._drift_counts: dict[str, int] = defaultdict(int)

    def check(self) -> Optional[Alert]:
        obs = self.observations[-1]
        meta = obs.metadata
        session_id = str(meta.get("session_id") or obs.agent_name)
        goal = str(_first_present(meta, ("task_goal", "goal", "user_goal"), "") or "")
        if goal:
            self._session_goals.setdefault(session_id, goal)
        authorized_goal = goal or self._session_goals.get(session_id, "")
        if not authorized_goal:
            return None

        trajectory_text = self._trajectory_text(obs)
        for pattern in self._compiled:
            match = pattern.search(trajectory_text)
            if match:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.CRITICAL,
                    message=f"Control-plane goal drift detected in session {session_id}: {match.group(0)[:120]}",
                    metric_value=1.0,
                    threshold=0.0,
                    metadata={
                        "session_id": session_id,
                        "agent": obs.agent_name,
                        "reason": "control_plane_drift_pattern",
                        "match": match.group(0)[:200],
                    },
                )

        allowed_tool_alert = self._check_allowed_tools(meta, session_id, obs)
        if allowed_tool_alert:
            return allowed_tool_alert

        alignment = meta.get("goal_alignment_score")
        if alignment is None:
            alignment = self._lexical_overlap(authorized_goal, trajectory_text)
        else:
            alignment = float(alignment)

        sensitive_action = bool(meta.get("sensitive_action"))
        if sensitive_action and alignment < self.sensitive_action_overlap_floor:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=(
                    f"Sensitive action has weak goal support in session {session_id} "
                    f"(alignment={alignment:.2f})"
                ),
                metric_value=alignment,
                threshold=self.sensitive_action_overlap_floor,
                metadata={
                    "session_id": session_id,
                    "agent": obs.agent_name,
                    "reason": "sensitive_action_weak_goal_support",
                    "authorized_goal": authorized_goal[:200],
                },
            )

        if alignment < self.overlap_warning:
            self._drift_counts[session_id] += 1
        else:
            self._drift_counts[session_id] = 0

        if alignment < self.overlap_critical or self._drift_counts[session_id] >= 2:
            severity = Severity.CRITICAL if alignment < self.overlap_critical else Severity.WARNING
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=severity,
                message=f"Trajectory appears off-goal in session {session_id} (alignment={alignment:.2f})",
                metric_value=alignment,
                threshold=self.overlap_warning,
                metadata={
                    "session_id": session_id,
                    "agent": obs.agent_name,
                    "reason": "low_goal_overlap",
                    "drift_count": self._drift_counts[session_id],
                    "authorized_goal": authorized_goal[:200],
                },
            )
        return None

    def _trajectory_text(self, obs: Observation) -> str:
        meta = obs.metadata
        parts = [
            obs.output,
            _flatten_text(meta.get("plan_steps", "")),
            _flatten_text(meta.get("tool_calls", "")),
            str(_first_present(meta, ("action", "proposed_action", "next_action"), "") or ""),
        ]
        return " ".join(parts)

    def _lexical_overlap(self, goal: str, trajectory: str) -> float:
        goal_tokens = _tokens(goal)
        if not goal_tokens:
            return 1.0
        trajectory_tokens = _tokens(trajectory)
        if not trajectory_tokens:
            return 0.0
        return len(goal_tokens & trajectory_tokens) / len(goal_tokens)

    def _check_allowed_tools(self, meta: dict[str, Any], session_id: str, obs: Observation) -> Optional[Alert]:
        allowed_tools = {str(tool).lower() for tool in meta.get("allowed_tools", []) or []}
        if not allowed_tools:
            return None
        for call in meta.get("tool_calls", []) or []:
            if not isinstance(call, dict):
                continue
            tool_name = str(call.get("tool_name") or call.get("name") or "").lower()
            if tool_name and tool_name not in allowed_tools:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.CRITICAL,
                    message=f"Tool '{tool_name}' is outside the authorized goal toolset in session {session_id}",
                    metric_value=1.0,
                    threshold=0.0,
                    metadata={
                        "session_id": session_id,
                        "agent": obs.agent_name,
                        "tool_name": tool_name,
                        "allowed_tools": sorted(allowed_tools),
                        "reason": "unauthorized_tool_for_goal",
                    },
                )
        return None

    def reset(self):
        super().reset()
        self._session_goals = {}
        self._drift_counts = defaultdict(int)
