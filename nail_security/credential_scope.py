"""Static credential-scope scanner — the AVE-2025-0040 prevention layer.

Motivation
----------
In the July 2026 OpenAI/Hugging Face incident, an agent that broke containment
did not need a novel exploit to do real damage: it *found credentials scoped
far wider than any task required*, and used them to move. VentureBeat's framing
— "the credential that let OpenAI's agents into Hugging Face exists in most
enterprises right now" — is the whole point. The cheapest place to stop that
chain is *before* an agent ever runs: don't leave over-scoped, long-lived
secrets sitting in the environment where a subprocess, MCP server, or code
interpreter can read them.

This scanner operationalises three proven AVE cards as a static, non-exploit
source-tree check:

  * AVE-2025-0040  Environment Inheritance Leak
        `os.environ.copy()` / full parent env handed to spawned subprocesses
        (MCP stdio servers, `npx`/`pipx`/`uvx` launchers, code interpreters).
  * AVE-2025-0028  Credential Harvesting
        long-lived secret material (AWS keys, HF/OpenAI/GitHub tokens, private
        keys, password literals) readable from source or environment.
  * AVE-2025-0026  Confused Deputy
        wildcard / administrator-scoped cloud grants — a credential the wrong
        principal can wield far beyond its task.

Like ``gateway_exposure``, it sends no payloads and executes nothing. It reads
files and reports findings with a severity, evidence, and a remediation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .gateway_exposure import FindingSeverity

# Reuse the shared severity ordering used across nail_security reports.
_SEVERITY_ORDER = {
    FindingSeverity.INFO: 0,
    FindingSeverity.LOW: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.HIGH: 3,
    FindingSeverity.CRITICAL: 4,
}

SOURCE_EXCLUDES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "site-packages",
}

SCANNABLE_SUFFIXES = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs",
    ".json", ".yaml", ".yml", ".toml", ".tf", ".hcl",
    ".env", ".sh", ".cfg", ".ini", ".txt",
}

# Files whose whole purpose is to carry environment values.
ENV_FILE_NAMES = re.compile(r"(^|/|\\)(\.env(\.[\w-]+)?|.*\.env|env\.[\w-]+)$", re.I)
COMPOSE_FILE_NAMES = re.compile(r"docker-compose[\w.-]*\.ya?ml$", re.I)

# ── AVE-2025-0040: full parent environment handed to a child process ─────────
FULL_ENV_INHERITANCE = re.compile(
    r"os\.environ\.copy\(\)|dict\(\s*os\.environ\s*\)|\{\s*\*\*\s*os\.environ",
)
SUBPROCESS_SPAWN = re.compile(
    r"subprocess\.(?:Popen|run|call|check_call|check_output)\b"
    r"|os\.(?:system|popen|execv?e?)\b"
    r"|asyncio\.create_subprocess_(?:exec|shell)\b",
)
# MCP / tool-executor stdio spawns that copy the parent env by default.
MCP_STDIO_SPAWN = re.compile(
    r"StdioServerParameters|MCPServerStdio|stdio_client\(|ClientSession\("
    r"|MCP\(\s*[\"']|Tool\(\s*command|CodeInterpreter\(",
)
# Untrusted third-party launchers — code we did not write, running with our env.
UNTRUSTED_LAUNCHER = re.compile(
    r"\b(?:npx|pipx|uvx|bunx|pnpm\s+dlx|pip\s+install|npm\s+install|"
    r"bash\s+-c|sh\s+-c|curl\s+[^\n]*\|\s*(?:bash|sh))\b",
)
EXPLICIT_ENV_KW = re.compile(r"\benv\s*=")

# ── AVE-2025-0028: long-lived secret material sitting in source/env ──────────
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], FindingSeverity], ...] = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), FindingSeverity.CRITICAL),
    ("AWS temporary key id", re.compile(r"\bASIA[0-9A-Z]{16}\b"), FindingSeverity.HIGH),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"), FindingSeverity.CRITICAL),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"), FindingSeverity.CRITICAL),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"), FindingSeverity.CRITICAL),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"), FindingSeverity.CRITICAL),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), FindingSeverity.HIGH),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"), FindingSeverity.HIGH),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"), FindingSeverity.CRITICAL),
    ("Generic bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{24,}\b"), FindingSeverity.MEDIUM),
)

# Secret-shaped assignment. NAME looks like a secret; VALUE is a real literal,
# not an env lookup or placeholder. Quoted form is scanned in every file; the
# bare `KEY=value` form (unquoted) is scanned only in env/compose/shell files,
# where that syntax is the norm and source-code false positives don't apply.
_SECRET_NAME = r"[A-Za-z0-9_]*(?:SECRET|SECRET_KEY|API_KEY|APIKEY|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|ACCESS_KEY)[A-Za-z0-9_]*"
SECRET_ASSIGNMENT = re.compile(
    rf"""(?P<name>{_SECRET_NAME})\s*[:=]\s*(?P<q>["'])(?P<val>[^"'\n]{{8,}})(?P=q)""",
    re.I,
)
SECRET_ASSIGNMENT_BARE = re.compile(
    rf"""(?m)^\s*(?:export\s+)?(?P<name>{_SECRET_NAME})\s*[:=]\s*(?P<val>[^\s"'#][^\s#\n]{{5,}})\s*$""",
    re.I,
)
PLACEHOLDER_VALUE = re.compile(
    r"^(?:x{3,}|<[^>]+>|\{\{[^}]+\}\}|\$\{[^}]+\}|changeme|your[-_ ]?|placeholder|example|dummy|redacted|none|null|true|false|\d+)$",
    re.I,
)
ENV_LOOKUP_HINT = re.compile(r"os\.(?:getenv|environ)|getenv\(|process\.env|Deno\.env|System\.getenv")

# ── AVE-2025-0026: wildcard / administrator cloud scope ──────────────────────
WILDCARD_IAM = re.compile(
    r"\"(?:Action|Resource)\"\s*:\s*\"\*\""
    r"|\"(?:Action|Resource)\"\s*:\s*\[\s*\"\*\"\s*\]"
    r"|AdministratorAccess"
    r"|\brole/.*[Aa]dmin\b",
)
BROAD_OAUTH_SCOPE = re.compile(
    r"scope[s]?\s*[:=]\s*[\"'][^\"']*\b(?:\*|admin|write:org|repo\b|root|full_access|offline_access)\b",
    re.I,
)

# Hardening signals that indicate least-privilege / short-lived credential use.
GOOD_PRACTICE = re.compile(
    r"assume_role|AssumeRole|get_secret_value|SecretsManager|secretsmanager|"
    r"HashiCorp|hvac\.|vault\.|WorkloadIdentity|OIDC|sts\.|short[_-]?lived|"
    r"IRSA|IamRole|instance_profile",
    re.I,
)


@dataclass
class CredentialFinding:
    """A single static credential-scope finding suitable for a client report."""

    severity: FindingSeverity
    category: str
    title: str
    detail: str
    location: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""
    ave_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "location": self.location,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "ave_refs": list(self.ave_refs),
        }


@dataclass
class CredentialScanReport:
    """Combined static credential-scope report."""

    target: str
    generated_at: str
    findings: list[CredentialFinding] = field(default_factory=list)
    files_scanned: int = 0
    scanner_version: str = "nail-credential-scope-r1"

    @property
    def max_severity(self) -> FindingSeverity:
        if not self.findings:
            return FindingSeverity.INFO
        return max(self.findings, key=lambda f: _SEVERITY_ORDER[f.severity]).severity

    @property
    def risk_score(self) -> float:
        if not self.findings:
            return 0.0
        points = sum(_SEVERITY_ORDER[f.severity] for f in self.findings)
        return min(1.0, points / 16.0)

    def add(
        self,
        severity: FindingSeverity,
        category: str,
        title: str,
        detail: str,
        *,
        location: str = "",
        evidence: dict[str, Any] | None = None,
        recommendation: str = "",
        ave_refs: tuple[str, ...] = (),
    ) -> None:
        self.findings.append(
            CredentialFinding(
                severity=severity,
                category=category,
                title=title,
                detail=detail,
                location=location,
                evidence=evidence or {},
                recommendation=recommendation,
                ave_refs=ave_refs,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "generated_at": self.generated_at,
            "scanner_version": self.scanner_version,
            "files_scanned": self.files_scanned,
            "max_severity": self.max_severity.value,
            "risk_score": round(self.risk_score, 3),
            "findings": [f.to_dict() for f in self.findings],
        }

    def summary(self) -> str:
        lines = [
            f"Credential-scope scan: {self.target}",
            f"Generated: {self.generated_at}",
            f"Files scanned: {self.files_scanned}",
            f"Max severity: {self.max_severity.value}",
            f"Risk score: {self.risk_score:.2f}",
            f"Findings: {len(self.findings)}",
        ]
        for finding in sorted(
            self.findings, key=lambda f: _SEVERITY_ORDER[f.severity], reverse=True
        ):
            lines.append(f"- [{finding.severity.value}] {finding.title} ({finding.location})")
        return "\n".join(lines)


def scan_source_tree(source_root: str | Path) -> CredentialScanReport:
    """Scan a source tree for over-scoped / harvestable credentials.

    Non-exploit and read-only. Returns a report whose findings map to the
    AVE-2025-0040 / -0028 / -0026 credential chain behind the Hugging Face
    incident.
    """
    root = Path(source_root).resolve()
    report = CredentialScanReport(target=str(root), generated_at=_utc_now())

    if not root.exists():
        report.add(
            FindingSeverity.HIGH,
            "input",
            "Source path not found",
            f"{root} does not exist.",
            recommendation="Provide the source tree, deployment bundle, or infra-as-code repo to scan.",
        )
        return report

    for path in _walk(root):
        text = _read_text(path)
        if text is None:
            continue
        report.files_scanned += 1
        rel = _rel(path, root)
        is_env_file = bool(ENV_FILE_NAMES.search(str(path))) or bool(
            COMPOSE_FILE_NAMES.search(path.name)
        )
        _scan_env_inheritance(report, rel, text)
        _scan_secrets(report, rel, text, is_env_file=is_env_file)
        _scan_wildcard_scope(report, rel, text)

    if not report.findings:
        report.add(
            FindingSeverity.INFO,
            "clean",
            "No over-scoped or harvestable credentials detected",
            "The static scan found no full-environment subprocess inheritance, "
            "long-lived secret material, or wildcard cloud grants.",
            recommendation=(
                "Confirm with a secrets-manager inventory and IAM access analyzer; "
                "a static scan cannot prove absence of credentials injected only at "
                "runtime."
            ),
        )

    return report


def _scan_env_inheritance(report: CredentialScanReport, rel: str, text: str) -> None:
    """AVE-2025-0040 — full parent environment handed to a child process."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        window = "\n".join(lines[idx: idx + 4])

        # Explicit full-env copy near a spawn is the textbook AVE-0040 pattern.
        if FULL_ENV_INHERITANCE.search(line):
            spawn_near = SUBPROCESS_SPAWN.search(window) or MCP_STDIO_SPAWN.search(window)
            untrusted = UNTRUSTED_LAUNCHER.search(window)
            if spawn_near or "env" in line.lower():
                sev = FindingSeverity.CRITICAL if untrusted else FindingSeverity.HIGH
                report.add(
                    sev,
                    "env_inheritance",
                    "Full parent environment copied into a child process",
                    "`os.environ.copy()` (or an equivalent full-env dict) is passed to a "
                    "spawned process. Every secret in the parent environment — cloud "
                    "keys, database URLs, model API tokens — becomes readable by that "
                    "child, including untrusted MCP servers and code interpreters.",
                    location=f"{rel}:{idx + 1}",
                    evidence={"line": line.strip()[:200], "untrusted_launcher": bool(untrusted)},
                    recommendation=(
                        "Pass an explicit least-privilege allowlist as `env=` (only the "
                        "variables the child genuinely needs). Never hand the full parent "
                        "environment to third-party or agent-controlled subprocesses."
                    ),
                    ave_refs=("AVE-2025-0040", "AVE-2025-0028"),
                )
            continue

        # A spawn of an untrusted launcher with no explicit env= inherits the
        # full parent environment by default — the same leak, implicitly.
        if UNTRUSTED_LAUNCHER.search(line) and (
            SUBPROCESS_SPAWN.search(window) or MCP_STDIO_SPAWN.search(window)
        ):
            if not EXPLICIT_ENV_KW.search(window):
                report.add(
                    FindingSeverity.HIGH,
                    "env_inheritance",
                    "Untrusted launcher spawned with inherited environment",
                    "A third-party launcher (npx/pipx/uvx/pip/shell) is spawned without "
                    "an explicit `env=`, so it inherits the full parent environment. A "
                    "compromised or typo-squatted package can silently read and exfiltrate "
                    "every secret in scope.",
                    location=f"{rel}:{idx + 1}",
                    evidence={"line": line.strip()[:200]},
                    recommendation=(
                        "Spawn tool/MCP subprocesses with a minimal explicit `env=`, pin "
                        "and hash third-party packages, and run them under a restricted "
                        "identity that holds no standing cloud credentials."
                    ),
                    ave_refs=("AVE-2025-0040", "AVE-2025-0014"),
                )


def _scan_secrets(report: CredentialScanReport, rel: str, text: str, *, is_env_file: bool) -> None:
    """AVE-2025-0028 — long-lived secret material in source or env files."""
    for label, pattern, severity in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            report.add(
                severity,
                "long_lived_secret",
                f"{label} committed in source",
                f"A {label.lower()} appears in this file. Long-lived credential material "
                "in the repository is exactly what an agent that gains file/RCE access "
                "harvests for lateral movement.",
                location=rel,
                evidence={"match_prefix": _mask(match.group(0))},
                recommendation=(
                    "Rotate the exposed credential now, move it to a secrets manager, and "
                    "issue short-lived, narrowly-scoped tokens at runtime instead of "
                    "storing standing secrets."
                ),
                ave_refs=("AVE-2025-0028", "AVE-2025-0040"),
            )

    seen_lines: set[int] = set()
    assignments = list(SECRET_ASSIGNMENT.finditer(text))
    if is_env_file:
        assignments += list(SECRET_ASSIGNMENT_BARE.finditer(text))
    for match in assignments:
        name = match.group("name")
        value = match.group("val").strip().strip("\"'")
        line = text[: match.start()].count("\n") + 1
        if line in seen_lines:
            continue
        context = text[max(0, match.start() - 40): match.start()]
        if PLACEHOLDER_VALUE.match(value):
            continue
        if ENV_LOOKUP_HINT.search(context) or ENV_LOOKUP_HINT.search(match.group(0)):
            continue
        seen_lines.add(line)
        # In a .env / compose file a literal assignment IS the standing secret;
        # in source it is a hardcoded credential. Both are harvestable.
        severity = FindingSeverity.HIGH
        detail = (
            f"`{name}` is assigned a literal value. A standing secret in the "
            "environment is readable by every subprocess and MCP server the agent "
            "spawns (AVE-2025-0040) and by anything that reaches the filesystem."
        )
        report.add(
            severity,
            "secret_in_env" if is_env_file else "long_lived_secret",
            f"Hardcoded {'environment secret' if is_env_file else 'credential'}: {name}",
            detail,
            location=f"{rel}:{line}",
            evidence={"name": name, "value_prefix": _mask(value)},
            recommendation=(
                "Source this value from a secrets manager at runtime with a short TTL and "
                "least-privilege scope; keep committed files free of live secrets."
            ),
            ave_refs=("AVE-2025-0028", "AVE-2025-0040"),
        )


def _scan_wildcard_scope(report: CredentialScanReport, rel: str, text: str) -> None:
    """AVE-2025-0026 — wildcard / administrator cloud grants (confused deputy)."""
    good = bool(GOOD_PRACTICE.search(text))
    for idx, line in enumerate(text.splitlines()):
        if WILDCARD_IAM.search(line):
            report.add(
                FindingSeverity.HIGH,
                "overscoped_grant",
                "Wildcard or administrator cloud grant",
                "An IAM/role policy grants `*` action or resource (or attaches admin "
                "access). A credential this broad is the confused-deputy lever: the "
                "wrong principal — or an agent that harvests it — can act far beyond "
                "any single task.",
                location=f"{rel}:{idx + 1}",
                evidence={"line": line.strip()[:200]},
                recommendation=(
                    "Scope the policy to the specific actions and resources the workload "
                    "needs. Replace standing admin grants with just-in-time, session-scoped "
                    "roles (STS AssumeRole / OIDC / workload identity)."
                ),
                ave_refs=("AVE-2025-0026", "AVE-2025-0028"),
            )
        elif BROAD_OAUTH_SCOPE.search(line):
            report.add(
                FindingSeverity.MEDIUM if good else FindingSeverity.HIGH,
                "overscoped_grant",
                "Broad OAuth / token scope requested",
                "A token or OAuth scope grants broad write/admin/offline access. Broad "
                "scopes turn any credential leak into lateral movement.",
                location=f"{rel}:{idx + 1}",
                evidence={"line": line.strip()[:200]},
                recommendation=(
                    "Request the narrowest scope that works and prefer read-only, "
                    "resource-scoped, short-lived tokens."
                ),
                ave_refs=("AVE-2025-0026",),
            )


def report_to_markdown(report: CredentialScanReport) -> str:
    """Render a client-readable markdown report."""
    lines = [
        "# Credential-Scope Scan",
        "",
        f"- Target: `{report.target}`",
        f"- Generated: `{report.generated_at}`",
        f"- Files scanned: `{report.files_scanned}`",
        f"- Max severity: `{report.max_severity.value}`",
        f"- Risk score: `{report.risk_score:.2f}`",
        "",
        "> Maps the OpenAI/Hugging Face credential chain "
        "(AVE-2025-0040 → -0028 → -0026) onto your source tree.",
        "",
        "## Findings",
        "",
    ]
    ordered = sorted(
        report.findings, key=lambda f: _SEVERITY_ORDER[f.severity], reverse=True
    )
    for finding in ordered:
        lines.extend(
            [
                f"### [{finding.severity.value.upper()}] {finding.title}",
                "",
                f"- Location: `{finding.location}`" if finding.location else "",
                f"- Category: `{finding.category}`",
                f"- AVE: {', '.join(finding.ave_refs) if finding.ave_refs else 'n/a'}",
                "",
                finding.detail,
                "",
            ]
        )
        if finding.evidence:
            lines.append("```json")
            lines.append(json.dumps(finding.evidence, indent=2, sort_keys=True))
            lines.append("```")
            lines.append("")
        if finding.recommendation:
            lines.append(f"Recommendation: {finding.recommendation}")
            lines.append("")
    return "\n".join(line for line in lines).rstrip() + "\n"


# ── helpers ──────────────────────────────────────────────────────────────────

def _walk(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SOURCE_EXCLUDES for part in path.parts):
            continue
        if path.suffix.lower() in SCANNABLE_SUFFIXES or ENV_FILE_NAMES.search(path.name):
            files.append(path)
    return files


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > 2_000_000:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _mask(value: str) -> str:
    value = value.strip()
    if len(value) <= 8:
        return value[:2] + "…"
    return value[:6] + "…" + f"({len(value)} chars)"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
