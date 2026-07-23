"""nail-monitor: v10 Detectors — Credential / egress chain
=========================================================

The runtime half of NAIL's response to the July 2026 OpenAI × Hugging Face
incident, where an agent that broke containment found credentials scoped far
wider than its task, used them to move laterally, and reached hosts it should
never have touched. The static ``nail_security.credential_scope`` scanner stops
the *setup* (over-scoped secrets at rest); these detectors watch the *runtime*
behaviour that scanner can't see:

  * CredentialHarvestingDetector  (AVE-2025-0028) — a secret the agent read from
        its environment reappears on an outbound surface (tool arg, network body,
        final answer), or raw secret material leaves at all; also flags bulk
        enumeration of secrets in a single turn.
  * EgressAllowlistDetector       — the agent contacts a host outside its
        allowlist ("obtained internet access it shouldn't have"). Silent until a
        policy exists, so it never fabricates alerts.
  * CredentialOverreachDetector   (AVE-2025-0026) — an action wields a credential
        whose scope exceeds what the task authorised: the classic confused
        deputy, which the tool-description-tampering ConfusedDeputyDetector does
        not cover.
  * CredentialAccessVelocityDetector — credential-fuelled lateral movement: a
        burst of privileged actions or a fan-out across many distinct hosts,
        the "thousands of actions over a weekend" signature.

All four are deterministic and metadata-driven — no model calls, no network — so
they can run inline in production.
"""
from __future__ import annotations

import ipaddress
import re
from collections import deque
from typing import Any, Optional
from urllib.parse import urlparse

from .detectors import BaseDetector
from .types import Alert, Observation, PathologyType, Severity


# ── Secret material patterns (kept local so nail_monitor stays standalone) ────
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
)

# Hosts that exist to receive exfiltrated data / out-of-band callbacks.
_EXFIL_SINK_HOSTS = (
    "pastebin.com", "paste.ee", "ghostbin", "requestbin", "webhook.site",
    "ngrok.io", "ngrok-free.app", "burpcollaborator.net", "oastify.com",
    "interact.sh", "pipedream.net", "transfer.sh", "0x0.st", "termbin.com",
)

# Credential scopes that are dangerous the instant they exceed task scope.
_HIGH_RISK_SCOPES = {
    "*", "admin", "administrator", "root", "owner", "write", "delete",
    "iam", "secretsmanager", "kms", "s3:*", "ec2:*", "org:admin",
    "repo", "write:org", "cluster-admin", "sudo",
}


def _mask(value: str) -> str:
    value = value.strip()
    if len(value) <= 8:
        return (value[:2] + "…") if value else ""
    return value[:4] + "…" + f"({len(value)} chars)"


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{k} {_flatten(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _scope_tokens(raw: Any) -> set[str]:
    tokens: set[str] = set()
    for entry in _as_list(raw):
        for tok in re.split(r"[\s,;]+", str(entry)):
            tok = tok.strip().lower()
            if tok:
                tokens.add(tok)
    return tokens


def _host_of(destination: Any) -> str:
    """Extract a hostname from a URL, host, or {url|host|destination} dict."""
    if isinstance(destination, dict):
        destination = (
            destination.get("host")
            or destination.get("url")
            or destination.get("destination")
            or destination.get("endpoint")
            or ""
        )
    text = str(destination).strip()
    if not text:
        return ""
    if "://" not in text:
        text = "//" + text
    host = urlparse(text).hostname or ""
    return host.lower()


def _find_secrets(text: str) -> list[tuple[str, str]]:
    """Return (kind, match) pairs for any secret material in text."""
    hits: list[tuple[str, str]] = []
    for kind, pattern in _SECRET_PATTERNS:
        for m in pattern.finditer(text):
            hits.append((kind, m.group(0)))
    return hits


# ═══════════════════════════════════════════════════════════════════════════
# 1. Credential Harvesting Detector  (AVE-2025-0028)
# ═══════════════════════════════════════════════════════════════════════════

class CredentialHarvestingDetector(BaseDetector):
    """Detect secrets leaving the agent, or bulk secret enumeration.

    Metadata keys (per observation):
      * secret_reads   — secrets the agent read this turn. dict {name: value},
                         list of values, or list of names. Values are
                         fingerprinted so a later reappearance can be caught even
                         when the value never appears in cleartext logs.
      * tool_calls     — outbound tool invocations (list of dicts / strings).
                         Args are treated as an outbound surface.
      * egress         — outbound network payloads (urls/bodies/dicts).
      * output         — the agent's text output (always available).

    Alerts:
      * CRITICAL — a previously-read secret, or raw secret material, appears on
        an outbound surface (exfiltration).
      * WARNING  — the agent enumerated many distinct secrets in one turn
        (harvesting posture) without (yet) exfiltrating.
    """

    def __init__(self, *, enumeration_threshold: int = 3, enabled: bool = True) -> None:
        super().__init__(
            name="CredentialHarvestingDetector",
            pathology=PathologyType.CREDENTIAL_HARVESTING,
            enabled=enabled,
        )
        self.enumeration_threshold = enumeration_threshold
        # Real secret values the agent has read, kept in-process only (never
        # written to an Alert or log), so a later reappearance can be matched.
        # value -> name. Only values that are plausibly secrets (>= 8 chars and
        # distinct from their own name) are tracked, to avoid matching on a bare
        # env-var name the agent merely mentions.
        self._known_secrets: dict[str, str] = {}

    @staticmethod
    def _read_pairs(secret_reads: Any) -> list[tuple[str, str]]:
        """Normalise secret_reads into (name, value) pairs."""
        if isinstance(secret_reads, dict):
            return [(str(k), str(v)) for k, v in secret_reads.items()]
        pairs = []
        for entry in _as_list(secret_reads):
            if isinstance(entry, dict):
                name = str(entry.get("name") or entry.get("key") or "secret")
                val = str(entry.get("value") or entry.get("val") or name)
                pairs.append((name, val))
            else:
                pairs.append((str(entry), str(entry)))
        return pairs

    def check(self) -> Optional[Alert]:
        obs = self.observations[-1]
        meta = obs.metadata

        # Record any real secret values read this turn.
        read_pairs = self._read_pairs(meta.get("secret_reads"))
        for name, value in read_pairs:
            if value and len(value) >= 8 and value != name:
                self._known_secrets[value] = name

        # Assemble the outbound surface (never includes secret_reads themselves).
        outbound = " ".join(
            [
                obs.output or "",
                _flatten(meta.get("tool_calls")),
                _flatten(meta.get("egress")),
                _flatten(meta.get("network_calls")),
            ]
        )

        # 1) A known (previously read) secret reappears outbound → exfiltration.
        for value, name in self._known_secrets.items():
            if value in outbound:
                return Alert(
                    detector=self.name,
                    pathology=self.pathology,
                    severity=Severity.CRITICAL,
                    message=(
                        f"Harvested credential '{name}' reappeared on an outbound "
                        "surface — probable exfiltration."
                    ),
                    metric_value=1.0,
                    threshold=0.0,
                    metadata={
                        "reason": "known_secret_exfiltrated",
                        "secret_name": name,
                        "value_preview": _mask(value),
                    },
                )

        # 2) Raw secret material on the outbound surface (no prior read needed).
        leaked = _find_secrets(outbound)
        if leaked:
            kind, value = leaked[0]
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=f"Secret material ({kind}) present in agent output/egress.",
                metric_value=float(len(leaked)),
                threshold=0.0,
                metadata={
                    "reason": "raw_secret_in_outbound",
                    "kinds": sorted({k for k, _ in leaked}),
                    "value_preview": _mask(value),
                },
            )

        # 3) Bulk enumeration of secrets in a single turn (harvesting posture).
        distinct = {name for name, _ in read_pairs}
        if len(distinct) >= self.enumeration_threshold:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.WARNING,
                message=(
                    f"Agent read {len(distinct)} distinct secrets in one turn — "
                    "credential-harvesting posture."
                ),
                metric_value=float(len(distinct)),
                threshold=float(self.enumeration_threshold),
                metadata={"reason": "bulk_secret_enumeration", "secrets": sorted(distinct)},
            )
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 2. Egress Allowlist Detector
# ═══════════════════════════════════════════════════════════════════════════

class EgressAllowlistDetector(BaseDetector):
    """Detect outbound connections to hosts outside the authorised allowlist.

    Metadata keys (per observation):
      * egress / network_calls / http_requests — destinations contacted this
        turn (urls, hosts, or {url|host|destination,[body]} dicts). Presence of
        any of these keys activates the detector.
      * allowed_hosts — the authorised destination allowlist (hosts or urls).
        May instead be fixed once at construction.

    With no allowlist configured the detector is silent by design (no policy =>
    no false positives), matching the ToolRetrievalIntegrityDetector contract.
    """

    def __init__(self, *, allowed_hosts: Any = None, enabled: bool = True) -> None:
        super().__init__(
            name="EgressAllowlistDetector",
            pathology=PathologyType.NOVEL_EGRESS,
            enabled=enabled,
        )
        self._default_allow = {_host_of(h) for h in _as_list(allowed_hosts) if _host_of(h)}

    @staticmethod
    def _is_allowed(host: str, allow: set[str]) -> bool:
        if host in allow:
            return True
        # Allow subdomains of an allowlisted apex (e.g. api.github.com vs github.com).
        return any(host == a or host.endswith("." + a) for a in allow)

    @staticmethod
    def _is_raw_ip(host: str) -> bool:
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def check(self) -> Optional[Alert]:
        obs = self.observations[-1]
        meta = obs.metadata

        raw = (
            meta.get("egress")
            if "egress" in meta
            else meta.get("network_calls")
            if "network_calls" in meta
            else meta.get("http_requests")
        )
        if raw is None:
            return None

        allow = {_host_of(h) for h in _as_list(meta.get("allowed_hosts")) if _host_of(h)}
        allow = allow or self._default_allow
        if not allow:
            return None  # no policy => stay silent

        offenders: list[dict[str, Any]] = []
        for dest in _as_list(raw):
            host = _host_of(dest)
            if not host or self._is_allowed(host, allow):
                continue
            body = _flatten(dest) if isinstance(dest, dict) else ""
            carries_secret = bool(_find_secrets(body)) or "secret" in body.lower()
            sink = any(s in host for s in _EXFIL_SINK_HOSTS)
            offenders.append(
                {
                    "host": host,
                    "raw_ip": self._is_raw_ip(host),
                    "exfil_sink": sink,
                    "carries_secret": carries_secret,
                }
            )

        if not offenders:
            return None

        aggravated = any(o["carries_secret"] or o["exfil_sink"] or o["raw_ip"] for o in offenders)
        hosts = sorted({o["host"] for o in offenders})
        return Alert(
            detector=self.name,
            pathology=self.pathology,
            severity=Severity.CRITICAL if aggravated else Severity.WARNING,
            message=f"Off-allowlist egress to {hosts}",
            metric_value=float(len(offenders)),
            threshold=0.0,
            metadata={
                "reason": "novel_egress",
                "offenders": offenders,
                "allowed_hosts": sorted(allow),
            },
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. Credential Overreach Detector  (AVE-2025-0026 — the confused-deputy gap)
# ═══════════════════════════════════════════════════════════════════════════

class CredentialOverreachDetector(BaseDetector):
    """Detect an action wielding a credential scoped beyond the task's authority.

    This is the classic confused deputy — a credential far broader than the task
    needs. It is distinct from the (identically-named) ConfusedDeputyDetector,
    which only watches for tool-description tampering.

    Metadata keys (per observation):
      * credential_scopes / granted_scopes — scopes the credential in use carries.
      * authorized_scopes / task_scopes    — least-privilege scopes the task may
        use (may be fixed once at construction).
      * action_scope                        — scope the current action requires.

    Silent unless an authorised scope set is available (no policy => no FP).
    """

    def __init__(self, *, authorized_scopes: Any = None, enabled: bool = True) -> None:
        super().__init__(
            name="CredentialOverreachDetector",
            pathology=PathologyType.CREDENTIAL_OVERREACH,
            enabled=enabled,
        )
        self._default_authorized = _scope_tokens(authorized_scopes)

    def check(self) -> Optional[Alert]:
        obs = self.observations[-1]
        meta = obs.metadata

        granted = _scope_tokens(meta.get("credential_scopes") or meta.get("granted_scopes"))
        if not granted:
            return None
        authorized = _scope_tokens(meta.get("authorized_scopes") or meta.get("task_scopes"))
        authorized = authorized or self._default_authorized
        if not authorized:
            return None  # no policy => stay silent

        excess = granted - authorized
        if not excess:
            return None

        risky = sorted(s for s in excess if s in _HIGH_RISK_SCOPES or s.endswith(":*") or "*" in s)
        action_scope = str(meta.get("action_scope") or "").strip().lower()
        action_overreaches = bool(action_scope) and action_scope in excess

        severity = Severity.CRITICAL if (risky or action_overreaches) else Severity.WARNING
        return Alert(
            detector=self.name,
            pathology=self.pathology,
            severity=severity,
            message=(
                "Credential scope exceeds task authorisation: "
                f"{sorted(excess)} beyond authorised set."
            ),
            metric_value=float(len(excess)),
            threshold=0.0,
            metadata={
                "reason": "over_scoped_credential",
                "excess_scopes": sorted(excess),
                "high_risk_excess": risky,
                "authorized_scopes": sorted(authorized),
                "action_scope": action_scope or None,
            },
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. Credential-Access Velocity Detector  (lateral movement / fan-out)
# ═══════════════════════════════════════════════════════════════════════════

class CredentialAccessVelocityDetector(BaseDetector):
    """Detect credential-fuelled lateral movement: bursts of privileged actions
    or fan-out across many distinct hosts/resources — the "thousands of actions
    over a weekend" signature.

    Metadata keys (per observation):
      * sensitive_action / credential_access — bool; counts this turn as privileged.
      * tool_calls    — list; privileged tool calls also count as actions.
      * resource / host / target — the resource/host touched (drives fan-out).

    Tracks a rolling window of the last ``window`` privileged events and alerts
    when the count or the number of distinct resources crosses a threshold.
    """

    _SENSITIVE_TOOL_HINT = re.compile(
        r"\b(?:ssh|scp|kubectl|aws|gcloud|az|boto|s3|secret|credential|token|"
        r"assume_role|curl|wget|http|exec|deploy|delete|drop)\b",
        re.I,
    )

    def __init__(
        self,
        *,
        window: int = 20,
        max_actions: int = 12,
        max_distinct_resources: int = 8,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="CredentialAccessVelocityDetector",
            pathology=PathologyType.LATERAL_MOVEMENT,
            enabled=enabled,
        )
        self.window = window
        self.max_actions = max_actions
        self.max_distinct_resources = max_distinct_resources
        self._events: deque[tuple[int, str]] = deque(maxlen=window)
        self._tick = 0

    def _is_sensitive(self, obs: Observation) -> bool:
        meta = obs.metadata
        if meta.get("sensitive_action") or meta.get("credential_access"):
            return True
        for call in _as_list(meta.get("tool_calls")):
            if self._SENSITIVE_TOOL_HINT.search(_flatten(call)):
                return True
        return False

    def check(self) -> Optional[Alert]:
        obs = self.observations[-1]
        if not self._is_sensitive(obs):
            return None

        self._tick += 1
        resource = _host_of(
            obs.metadata.get("host")
            or obs.metadata.get("resource")
            or obs.metadata.get("target")
            or ""
        ) or str(
            obs.metadata.get("resource") or obs.metadata.get("target") or obs.agent_name
        )
        self._events.append((self._tick, resource))

        count = len(self._events)
        distinct = {res for _, res in self._events if res}

        if count >= self.max_actions:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=(
                    f"Privileged-action burst: {count} sensitive actions within the "
                    f"last {self.window} observations."
                ),
                metric_value=float(count),
                threshold=float(self.max_actions),
                metadata={
                    "reason": "action_velocity",
                    "action_count": count,
                    "distinct_resources": sorted(distinct),
                },
            )
        if len(distinct) >= self.max_distinct_resources:
            return Alert(
                detector=self.name,
                pathology=self.pathology,
                severity=Severity.CRITICAL,
                message=(
                    f"Lateral fan-out across {len(distinct)} distinct resources — "
                    "credential reuse across hosts."
                ),
                metric_value=float(len(distinct)),
                threshold=float(self.max_distinct_resources),
                metadata={
                    "reason": "resource_fanout",
                    "distinct_resources": sorted(distinct),
                },
            )
        return None
