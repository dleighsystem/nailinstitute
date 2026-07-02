#!/usr/bin/env python3
"""Run a safe AI gateway exposure assessment.

Examples:
    python scripts/scan_ai_gateway_exposure.py --url https://client.example
    python scripts/scan_ai_gateway_exposure.py --source-root ./client-app --json
    python scripts/scan_ai_gateway_exposure.py --url https://client.example \
        --auth-header 'Authorization: Bearer ...'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nail_security.gateway_exposure import (  # noqa: E402
    GatewayExposureScanner,
    GatewayScanReport,
    report_to_markdown,
    scan_source_tree,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safe LiteLLM/MCP/FastAPI gateway exposure scanner.",
    )
    parser.add_argument("--url", help="Authorized target base URL to scan.")
    parser.add_argument(
        "--source-root",
        help="Optional source tree, requirements bundle, or SBOM directory to inspect.",
    )
    parser.add_argument(
        "--auth-header",
        action="append",
        default=[],
        metavar="NAME: VALUE",
        help="Optional header used only for authenticated confirmation probes.",
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--skip-host-header-probe",
        action="store_true",
        help="Skip the invalid Host header boundary check.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown.")
    parser.add_argument("--output", help="Write report to this file.")

    args = parser.parse_args(argv)

    if not args.url and not args.source_root:
        parser.error("provide --url, --source-root, or both")

    reports: list[GatewayScanReport] = []

    if args.url:
        scanner = GatewayExposureScanner(
            args.url,
            timeout_s=args.timeout,
            auth_headers=_parse_headers(args.auth_header),
            host_header_probe=not args.skip_host_header_probe,
        )
        reports.append(scanner.scan())

    if args.source_root:
        reports.append(scan_source_tree(args.source_root))

    if args.json:
        rendered = json.dumps([r.to_dict() for r in reports], indent=2, sort_keys=True)
    else:
        rendered = "\n\n".join(report_to_markdown(r) for r in reports)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)

    return _exit_code(reports)


def _parse_headers(raw_headers: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in raw_headers:
        if ":" not in raw:
            raise SystemExit(f"bad --auth-header {raw!r}; expected 'Name: value'")
        name, value = raw.split(":", 1)
        parsed[name.strip()] = value.strip()
    return parsed


def _exit_code(reports: list[GatewayScanReport]) -> int:
    severe = {"high", "critical"}
    for report in reports:
        if report.max_severity.value in severe:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

