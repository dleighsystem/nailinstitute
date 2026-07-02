#!/usr/bin/env python3
"""Verify production NAIL monitoring from public read-side endpoints."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


FetchJson = Callable[[str], dict[str, Any]]


@dataclass
class CheckResult:
    ok: bool = True
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.ok = False
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{url} failed: {exc}") from exc
    try:
        parsed = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{url} did not return JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{url} returned {type(parsed).__name__}, expected object")
    return parsed


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalise_agents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    agents = payload.get("agents", payload)
    if isinstance(agents, dict):
        agents = list(agents.values())
    if not isinstance(agents, list):
        return []
    return [agent for agent in agents if isinstance(agent, dict)]


def event_count(agent: dict[str, Any]) -> int:
    for key in ("total_events", "events", "requests_last_hour"):
        value = agent.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def verify(args: argparse.Namespace, get_json: FetchJson = fetch_json) -> CheckResult:
    result = CheckResult()
    monitor_base = args.monitor_base.rstrip("/")

    try:
        app_health = get_json(args.app_health_url)
    except Exception as exc:
        result.fail(f"app health fetch failed: {exc}")
        app_health = {}

    app_status = str(app_health.get("status", "")).lower()
    if app_status not in {"healthy", "ok", "up"}:
        result.fail(f"app health status is not healthy: {app_status or 'missing'}")

    neuravant = app_health.get("neuravant_monitor")
    if isinstance(neuravant, dict):
        if neuravant.get("enabled") is False:
            result.fail("neuravant_monitor.enabled is false")
        if neuravant.get("heartbeat_enabled") is False:
            result.warn("neuravant_monitor.heartbeat_enabled is false")
        if neuravant.get("heartbeat_running") is False:
            result.fail("neuravant_monitor.heartbeat_running is false")
        failed_events = int(neuravant.get("events_failed") or 0)
        if failed_events and not args.allow_events_failed:
            result.fail(f"app health reports events_failed={failed_events}")
        result.summary["app_monitor"] = {
            "agent_count": neuravant.get("agent_count"),
            "events_sent": neuravant.get("events_sent"),
            "events_failed": failed_events,
            "last_success_at": neuravant.get("last_success_at"),
            "heartbeat_running": neuravant.get("heartbeat_running"),
        }
    else:
        result.warn("app health has no neuravant_monitor object")

    try:
        monitor_health = get_json(f"{monitor_base}/health")
    except Exception as exc:
        result.fail(f"monitor health fetch failed: {exc}")
        monitor_health = {}

    monitor_status = str(monitor_health.get("status", "")).lower()
    if monitor_status not in {"healthy", "ok", "up"}:
        result.fail(f"monitor health status is not healthy: {monitor_status or 'missing'}")
    result.summary["monitor_health"] = monitor_health

    try:
        agents_payload = get_json(f"{monitor_base}/agents")
    except Exception as exc:
        result.fail(f"agents fetch failed: {exc}")
        agents_payload = {}

    agents = normalise_agents(agents_payload)
    result.summary["visible_agents"] = len(agents)
    if len(agents) < args.min_visible_agents:
        result.fail(
            f"visible agents {len(agents)} < required {args.min_visible_agents}"
        )

    by_name = {
        str(agent.get("agent_name") or agent.get("name") or agent.get("agent") or ""): agent
        for agent in agents
    }
    now = datetime.now(timezone.utc)
    checked_agents: dict[str, Any] = {}
    for agent_name in args.agent:
        agent = by_name.get(agent_name)
        live_url = f"{monitor_base}/agents/{urllib.parse.quote(agent_name, safe='')}/live"
        try:
            live = get_json(live_url)
            if live:
                agent = live
        except Exception as exc:
            if agent is None:
                result.fail(f"{agent_name}: live fetch failed and agent was not listed: {exc}")
                continue
            result.warn(f"{agent_name}: live fetch failed, using agents list: {exc}")

        if agent is None:
            result.fail(f"{agent_name}: missing from monitoring agents")
            continue

        status = str(agent.get("status", "")).lower()
        if status != "healthy":
            result.fail(f"{agent_name}: status={status or 'missing'}")

        errors_last_hour = int(agent.get("errors_last_hour") or 0)
        if errors_last_hour > 0:
            result.fail(f"{agent_name}: errors_last_hour={errors_last_hour}")

        count = event_count(agent)
        if args.require_events and count <= 0:
            result.fail(f"{agent_name}: no monitored events recorded")

        last_seen = parse_timestamp(agent.get("last_seen_at"))
        if last_seen is None:
            result.fail(f"{agent_name}: last_seen_at missing or invalid")
            age_s = None
        else:
            age_s = max(0, int((now - last_seen).total_seconds()))
            if age_s > args.max_stale_seconds:
                result.fail(
                    f"{agent_name}: last_seen_at is stale ({age_s}s > {args.max_stale_seconds}s)"
                )

        checked_agents[agent_name] = {
            "status": status,
            "events": count,
            "errors_last_hour": errors_last_hour,
            "last_seen_at": agent.get("last_seen_at"),
            "last_seen_age_s": age_s,
        }

    result.summary["checked_agents"] = checked_agents
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-health-url", required=True)
    parser.add_argument("--monitor-base", required=True)
    parser.add_argument("--agent", action="append", default=[])
    parser.add_argument("--min-visible-agents", type=int, default=1)
    parser.add_argument("--max-stale-seconds", type=int, default=900)
    parser.add_argument("--require-events", action="store_true")
    parser.add_argument(
        "--allow-events-failed",
        action="store_true",
        help="Do not fail on app health events_failed > 0. Use only for known historical counters.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = verify(args)
    print(json.dumps({
        "ok": result.ok,
        "failures": result.failures,
        "warnings": result.warnings,
        "summary": result.summary,
    }, indent=2, sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
