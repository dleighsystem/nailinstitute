"""Safe exposure checks for AI gateway and MCP deployments.

The scanner in this module is intentionally non-exploitative. It looks for
route exposure, weak deployment boundaries, and dependency evidence around
LiteLLM/MCP/FastAPI-style gateways without sending command payloads or asking a
service to execute a tool.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


LITELLM_PATCHED_VERSION = "1.83.7"
STARLETTE_PATCHED_VERSION = "1.0.1"

MCP_TEST_ENDPOINTS = (
    "/mcp-rest/test/connection",
    "/mcp-rest/test/tools/list",
)

SENSITIVE_GET_ENDPOINTS = (
    "/metrics",
    "/incidents",
    "/admin/signatures",
    "/admin/draft-cards",
    "/clients",
    "/subscribers",
    "/docs",
    "/openapi.json",
    "/status",
)

SOURCE_EXCLUDES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "__tests__",
    "node_modules",
    "dist",
    "build",
    "tests",
}


class FindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_ORDER = {
    FindingSeverity.INFO: 0,
    FindingSeverity.LOW: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.HIGH: 3,
    FindingSeverity.CRITICAL: 4,
}


@dataclass
class HttpProbeResult:
    """One HTTP probe result."""

    method: str
    path: str
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body_snippet: str = ""
    error: str = ""
    elapsed_ms: float = 0.0
    auth_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "headers": self.headers,
            "body_snippet": self.body_snippet,
            "error": self.error,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "auth_used": self.auth_used,
        }


@dataclass
class GatewayFinding:
    """A scanner finding suitable for a client-facing report."""

    severity: FindingSeverity
    title: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "title": self.title,
            "detail": self.detail,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass
class GatewayScanReport:
    """Combined HTTP/source scan report."""

    target: str
    generated_at: str
    findings: list[GatewayFinding] = field(default_factory=list)
    probes: list[HttpProbeResult] = field(default_factory=list)
    scanner_version: str = "nail-gateway-exposure-r1"

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
        return min(1.0, points / 12.0)

    def add_finding(
        self,
        severity: FindingSeverity,
        title: str,
        detail: str,
        *,
        evidence: dict[str, Any] | None = None,
        recommendation: str = "",
    ) -> None:
        self.findings.append(
            GatewayFinding(
                severity=severity,
                title=title,
                detail=detail,
                evidence=evidence or {},
                recommendation=recommendation,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "generated_at": self.generated_at,
            "scanner_version": self.scanner_version,
            "max_severity": self.max_severity.value,
            "risk_score": round(self.risk_score, 3),
            "findings": [f.to_dict() for f in self.findings],
            "probes": [p.to_dict() for p in self.probes],
        }

    def summary(self) -> str:
        lines = [
            f"Gateway exposure scan: {self.target}",
            f"Generated: {self.generated_at}",
            f"Max severity: {self.max_severity.value}",
            f"Risk score: {self.risk_score:.2f}",
            f"Findings: {len(self.findings)}",
        ]
        for finding in self.findings:
            lines.append(f"- [{finding.severity.value}] {finding.title}")
        return "\n".join(lines)


class GatewayExposureScanner:
    """Non-exploit HTTP scanner for AI gateway exposure checks."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 5.0,
        headers: dict[str, str] | None = None,
        auth_headers: dict[str, str] | None = None,
        host_header_probe: bool = True,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_s = timeout_s
        self.headers = dict(headers or {})
        self.auth_headers = dict(auth_headers or {})
        self.host_header_probe = host_header_probe

    def scan(self) -> GatewayScanReport:
        report = GatewayScanReport(
            target=self.base_url,
            generated_at=_utc_now(),
        )

        baseline = self._probe("GET", "/", use_auth=False)
        report.probes.append(baseline)
        self._check_cors(report, baseline)
        self._check_identity_headers(report, baseline)

        health = self._first_successful_get(("/health", "/healthz", "/"), report)
        openapi = self._probe("GET", "/openapi.json", use_auth=False)
        report.probes.append(openapi)
        self._check_cors(report, openapi)
        self._check_openapi(report, openapi)

        self._scan_mcp_test_endpoints(report)
        self._scan_sensitive_get_endpoints(report)

        if self.host_header_probe and health and health.status and 200 <= health.status < 300:
            self._check_host_header_boundary(report, health.path)

        if not report.findings:
            report.add_finding(
                FindingSeverity.INFO,
                "No obvious AI gateway exposure detected",
                "The non-exploit probes did not find reachable MCP test routes, "
                "public admin routes, or obvious LiteLLM version evidence.",
                recommendation=(
                    "Confirm with dependency inventory and reverse-proxy logs; this "
                    "scanner cannot prove absence of a vulnerable route hidden behind "
                    "auth or a non-standard path."
                ),
            )

        return report

    def _first_successful_get(
        self,
        paths: tuple[str, ...],
        report: GatewayScanReport,
    ) -> HttpProbeResult | None:
        fallback = None
        for path in paths:
            probe = self._probe("GET", path, use_auth=False)
            report.probes.append(probe)
            self._check_cors(report, probe)
            if fallback is None:
                fallback = probe
            if probe.status and 200 <= probe.status < 300:
                return probe
        return fallback

    def _scan_mcp_test_endpoints(self, report: GatewayScanReport) -> None:
        payload = {
            "nail_probe": "route_presence_only",
            "execute": False,
        }
        for path in MCP_TEST_ENDPOINTS:
            unauth = self._probe("POST", path, json_body=payload, use_auth=False)
            report.probes.append(unauth)

            if unauth.status in (401, 403, 404, 405):
                continue
            if unauth.status is None:
                continue

            severity = FindingSeverity.HIGH
            if 200 <= unauth.status < 300:
                severity = FindingSeverity.CRITICAL

            report.add_finding(
                severity,
                "LiteLLM/MCP test endpoint reachable without authentication",
                (
                    f"{path} returned HTTP {unauth.status} to an unauthenticated "
                    "inert probe. A validation error still indicates the route is "
                    "reachable and parsing requests."
                ),
                evidence={
                    "path": path,
                    "status": unauth.status,
                    "body_snippet": unauth.body_snippet,
                },
                recommendation=(
                    "Upgrade LiteLLM to at least "
                    f"{LITELLM_PATCHED_VERSION}, block this route at the reverse "
                    "proxy, and restrict MCP/gateway admin surfaces to trusted "
                    "networks."
                ),
            )

            if self.auth_headers:
                auth = self._probe("POST", path, json_body=payload, use_auth=True)
                report.probes.append(auth)

    def _scan_sensitive_get_endpoints(self, report: GatewayScanReport) -> None:
        for path in SENSITIVE_GET_ENDPOINTS:
            probe = self._probe("GET", path, use_auth=False)
            report.probes.append(probe)
            self._check_cors(report, probe)
            if not probe.status or probe.status in (401, 403, 404, 405):
                continue
            if not 200 <= probe.status < 300:
                continue

            severity = FindingSeverity.LOW
            if path.startswith("/admin") or path in {"/clients", "/subscribers", "/incidents"}:
                severity = FindingSeverity.HIGH
            elif path == "/metrics":
                severity = FindingSeverity.MEDIUM

            report.add_finding(
                severity,
                "Sensitive gateway endpoint reachable without authentication",
                f"{path} returned HTTP {probe.status} without credentials.",
                evidence={
                    "path": path,
                    "status": probe.status,
                    "body_snippet": probe.body_snippet,
                },
                recommendation=(
                    "Require authentication and network allowlisting for admin, "
                    "telemetry, metrics, and incident endpoints. Public docs/openapi "
                    "should be a conscious production choice."
                ),
            )

    def _check_host_header_boundary(self, report: GatewayScanReport, path: str) -> None:
        probe = self._probe(
            "GET",
            path,
            use_auth=False,
            override_headers={"Host": "nail-invalid-host.invalid"},
        )
        report.probes.append(probe)
        if probe.status and 200 <= probe.status < 300:
            report.add_finding(
                FindingSeverity.MEDIUM,
                "Invalid Host header accepted",
                (
                    "The service returned success for a request with an invalid "
                    "Host header. This is not proof of the Starlette issue, but it "
                    "weakens gateway/proxy boundary assumptions."
                ),
                evidence={"path": path, "status": probe.status},
                recommendation=(
                    "Configure TrustedHostMiddleware or an equivalent reverse-proxy "
                    "host allowlist, and avoid auth decisions that rely on mutable "
                    "Host/X-Forwarded headers."
                ),
            )

    def _check_openapi(self, report: GatewayScanReport, probe: HttpProbeResult) -> None:
        if not probe.status or not 200 <= probe.status < 300 or not probe.body_snippet:
            return
        body = probe.body_snippet
        lower = body.lower()
        if "litellm" in lower:
            version = _extract_first_version(body)
            if version and _version_lt(version, LITELLM_PATCHED_VERSION):
                report.add_finding(
                    FindingSeverity.HIGH,
                    "LiteLLM version below patched floor advertised",
                    (
                        f"OpenAPI metadata appears to reference LiteLLM {version}, "
                        f"below {LITELLM_PATCHED_VERSION}."
                    ),
                    evidence={"version": version},
                    recommendation=f"Upgrade LiteLLM to at least {LITELLM_PATCHED_VERSION}.",
                )
            else:
                report.add_finding(
                    FindingSeverity.INFO,
                    "LiteLLM-like API metadata observed",
                    "OpenAPI metadata references LiteLLM or an AI gateway facade.",
                    evidence={"version": version or "unknown"},
                    recommendation="Verify LiteLLM and Starlette dependency versions from source or SBOM.",
                )

        for path in MCP_TEST_ENDPOINTS:
            if path in body:
                report.add_finding(
                    FindingSeverity.HIGH,
                    "MCP test route advertised in OpenAPI",
                    f"{path} is visible in the public OpenAPI schema.",
                    evidence={"path": path},
                    recommendation=(
                        "Remove test/admin routes from public schemas and require "
                        "authentication/network allowlisting if they must exist."
                    ),
                )

    def _check_cors(self, report: GatewayScanReport, probe: HttpProbeResult) -> None:
        origin = _header(probe.headers, "access-control-allow-origin")
        credentials = _header(probe.headers, "access-control-allow-credentials")
        if origin == "*" and credentials and credentials.lower() == "true":
            report.add_finding(
                FindingSeverity.MEDIUM,
                "Wildcard CORS with credentials enabled",
                (
                    f"{probe.path} returned Access-Control-Allow-Origin: * with "
                    "Access-Control-Allow-Credentials: true."
                ),
                evidence={"path": probe.path, "status": probe.status},
                recommendation=(
                    "Use explicit trusted origins for browser-accessible AI gateway "
                    "routes, especially admin and credential-bearing endpoints."
                ),
            )

    def _check_identity_headers(self, report: GatewayScanReport, probe: HttpProbeResult) -> None:
        text = " ".join([probe.body_snippet, " ".join(probe.headers.values())]).lower()
        if "litellm" not in text:
            return
        version = _extract_first_version(text)
        if version and _version_lt(version, LITELLM_PATCHED_VERSION):
            report.add_finding(
                FindingSeverity.HIGH,
                "LiteLLM version below patched floor observed",
                f"Response metadata appears to disclose LiteLLM {version}.",
                evidence={"version": version, "path": probe.path},
                recommendation=f"Upgrade LiteLLM to at least {LITELLM_PATCHED_VERSION}.",
            )

    def _probe(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        use_auth: bool,
        override_headers: dict[str, str] | None = None,
    ) -> HttpProbeResult:
        url = urljoin(self.base_url, path.lstrip("/"))
        headers = {
            "User-Agent": "NAIL-Gateway-Exposure-Scanner/1.0",
            "X-NAIL-Probe": "exposure-check",
            **self.headers,
        }
        if use_auth:
            headers.update(self.auth_headers)
        if override_headers:
            headers.update(override_headers)

        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read(4096)
                return HttpProbeResult(
                    method=method,
                    path=path,
                    status=resp.status,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    body_snippet=_decode_snippet(raw),
                    elapsed_ms=(time.monotonic() - start) * 1000,
                    auth_used=use_auth,
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096)
            return HttpProbeResult(
                method=method,
                path=path,
                status=exc.code,
                headers={k.lower(): v for k, v in exc.headers.items()},
                body_snippet=_decode_snippet(raw),
                elapsed_ms=(time.monotonic() - start) * 1000,
                auth_used=use_auth,
            )
        except Exception as exc:
            return HttpProbeResult(
                method=method,
                path=path,
                status=None,
                error=str(exc),
                elapsed_ms=(time.monotonic() - start) * 1000,
                auth_used=use_auth,
            )


def scan_source_tree(source_root: str | Path) -> GatewayScanReport:
    """Scan a source tree or dependency bundle for gateway exposure signals."""
    root = Path(source_root).resolve()
    report = GatewayScanReport(
        target=str(root),
        generated_at=_utc_now(),
        scanner_version="nail-gateway-source-r1",
    )
    if not root.exists():
        report.add_finding(
            FindingSeverity.HIGH,
            "Source path not found",
            f"{root} does not exist.",
            recommendation="Provide the client source tree, requirements bundle, or SBOM export.",
        )
        return report

    dependency_files = _dependency_files(root)
    if not dependency_files:
        report.add_finding(
            FindingSeverity.MEDIUM,
            "No dependency manifest or lockfile found",
            "The scanner did not find requirements, pyproject, poetry, pip, or uv lock files.",
            recommendation=(
                "Request an SBOM or dependency manifest so LiteLLM, FastAPI, and "
                "Starlette versions can be verified."
            ),
        )

    for path in dependency_files:
        text = _read_text(path)
        if not text:
            continue
        _scan_dependency_text(report, path, text, "litellm", LITELLM_PATCHED_VERSION)
        _scan_dependency_text(report, path, text, "starlette", STARLETTE_PATCHED_VERSION)

    source_files = _source_files(root)
    route_hits: list[str] = []
    fastapi_seen = False
    trusted_host_seen = False
    open_admin_seen: list[str] = []

    for path in source_files:
        text = _read_text(path)
        if not text:
            continue
        for endpoint in MCP_TEST_ENDPOINTS:
            if _has_route_definition_for_endpoint(text, endpoint):
                route_hits.append(f"{path}:{endpoint}")
        if "FastAPI(" in text or "from fastapi" in text:
            fastapi_seen = True
        if "TrustedHostMiddleware" in text or "allowed_hosts" in text:
            trusted_host_seen = True
        if re.search(r"if\s+not\s+\w*admin_token\s*:\s*\n\s*return", text):
            open_admin_seen.append(str(path))

    for hit in route_hits:
        report.add_finding(
            FindingSeverity.HIGH,
            "MCP test route present in source",
            "A LiteLLM/MCP test endpoint string was found in the source tree.",
            evidence={"hit": hit},
            recommendation="Remove, guard, or reverse-proxy block MCP test endpoints in production.",
        )

    if fastapi_seen and not trusted_host_seen:
        report.add_finding(
            FindingSeverity.MEDIUM,
            "FastAPI app found without obvious Host allowlisting",
            "The source references FastAPI but no TrustedHostMiddleware/allowed_hosts pattern was found.",
            recommendation=(
                "Confirm host allowlisting is enforced at the app or reverse-proxy "
                "layer, especially for AI gateways and admin surfaces."
            ),
        )

    for path in open_admin_seen:
        report.add_finding(
            FindingSeverity.HIGH,
            "Admin token appears optional",
            "Source contains a pattern where an empty admin token opens admin access.",
            evidence={"path": path},
            recommendation=(
                "Fail closed in production: require a configured admin token or "
                "disable admin routes entirely when no token is set."
            ),
        )

    if not report.findings:
        report.add_finding(
            FindingSeverity.INFO,
            "No obvious source/dependency exposure signals detected",
            "No risky LiteLLM/MCP route strings or vulnerable dependency pins were detected.",
            recommendation="Confirm with runtime HTTP scan and production reverse-proxy configuration.",
        )

    return report


def report_to_markdown(report: GatewayScanReport) -> str:
    """Render a client-readable markdown report."""
    lines = [
        "# AI Gateway Exposure Scan",
        "",
        f"- Target: `{report.target}`",
        f"- Generated: `{report.generated_at}`",
        f"- Max severity: `{report.max_severity.value}`",
        f"- Risk score: `{report.risk_score:.2f}`",
        "",
        "## Findings",
        "",
    ]
    for finding in report.findings:
        lines.extend(
            [
                f"### [{finding.severity.value.upper()}] {finding.title}",
                "",
                finding.detail,
                "",
            ]
        )
        if finding.evidence:
            lines.append("Evidence:")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(finding.evidence, indent=2, sort_keys=True))
            lines.append("```")
            lines.append("")
        if finding.recommendation:
            lines.append(f"Recommendation: {finding.recommendation}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _dependency_files(root: Path) -> list[Path]:
    names = {
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-prod.txt",
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
    }
    return [p for p in _walk(root) if p.name in names or p.name.startswith("requirements")]


def _source_files(root: Path) -> list[Path]:
    suffixes = {".py", ".toml", ".yaml", ".yml", ".txt", ".md"}
    return [p for p in _walk(root) if p.suffix.lower() in suffixes]


def _walk(root: Path) -> list[Path]:
    files: list[Path] = []
    if root.is_file():
        return [root]
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SOURCE_EXCLUDES for part in path.parts):
            continue
        files.append(path)
    return files


def _scan_dependency_text(
    report: GatewayScanReport,
    path: Path,
    text: str,
    package: str,
    patched_floor: str,
) -> None:
    mentions = _dependency_mentions(text, package)
    for line in mentions:
        version = _extract_pinned_or_min_version(line)
        evidence = {"path": str(path), "line": line.strip()}
        if version is None:
            report.add_finding(
                FindingSeverity.MEDIUM,
                f"{package} dependency is unpinned",
                f"{package} is mentioned without an obvious version floor.",
                evidence=evidence,
                recommendation=f"Pin {package} to a version at or above {patched_floor}.",
            )
        elif _version_lt(version, patched_floor):
            report.add_finding(
                FindingSeverity.HIGH,
                f"{package} dependency floor is below patched version",
                f"{package} references {version}, below the patched floor {patched_floor}.",
                evidence={**evidence, "version": version, "patched_floor": patched_floor},
                recommendation=f"Upgrade {package} to at least {patched_floor}.",
            )


def _dependency_mentions(text: str, package: str) -> list[str]:
    matches = []
    pattern = re.compile(rf"(^|[\"'\s,]){re.escape(package)}($|[<>=~!;\]\",\s])", re.I)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if pattern.search(line):
            matches.append(raw_line)
    return matches


def _has_route_definition_for_endpoint(text: str, endpoint: str) -> bool:
    lines = text.splitlines()
    markers = (
        "@app.",
        "@router.",
        "add_api_route",
        "add_route",
    )
    for index, line in enumerate(lines):
        if endpoint not in line:
            continue
        window = "\n".join(lines[max(0, index - 2):index + 3])
        if any(marker in window for marker in markers):
            return True
    return False


def _extract_pinned_or_min_version(line: str) -> str | None:
    match = re.search(r"(?:==|>=|~=|>|=)\s*([0-9]+(?:\.[0-9]+){0,3})", line)
    if match:
        return match.group(1)
    return None


def _extract_first_version(text: str) -> str | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+){1,3})", text)
    return match.group(1) if match else None


def _version_lt(left: str, right: str) -> bool:
    return _version_tuple(left) < _version_tuple(right)


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(p) for p in re.findall(r"\d+", version)[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > 2_000_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _decode_snippet(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    return text[:1000]


def _header(headers: dict[str, str], name: str) -> str:
    return headers.get(name.lower(), "")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
