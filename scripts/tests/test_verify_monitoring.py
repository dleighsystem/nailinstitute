"""Tests for scripts/verify_monitoring.py."""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone

import verify_monitoring as vm


def _args(**overrides):
    values = {
        "app_health_url": "https://app.example/health",
        "monitor_base": "https://monitor.example/monitoring",
        "agent": ["EF-Strategy Chat"],
        "min_visible_agents": 1,
        "max_stale_seconds": 900,
        "require_events": True,
        "allow_events_failed": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _fresh_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_verify_monitoring_accepts_healthy_fleet():
    def fake_fetch(url: str):
        if url == "https://app.example/health":
            return {
                "status": "healthy",
                "neuravant_monitor": {
                    "enabled": True,
                    "heartbeat_running": True,
                    "agent_count": 18,
                    "events_sent": 10,
                    "events_failed": 0,
                },
            }
        if url == "https://monitor.example/monitoring/health":
            return {"status": "ok"}
        if url == "https://monitor.example/monitoring/agents":
            return {"agents": [{"agent_name": "EF-Strategy Chat"}]}
        if url.endswith("/EF-Strategy%20Chat/live"):
            return {
                "agent_name": "EF-Strategy Chat",
                "status": "healthy",
                "total_events": 7,
                "errors_last_hour": 0,
                "last_seen_at": _fresh_ts(),
            }
        raise AssertionError(url)

    result = vm.verify(_args(), fake_fetch)

    assert result.ok
    assert result.failures == []
    assert result.summary["visible_agents"] == 1


def test_verify_monitoring_fails_nonzero_events_failed_by_default():
    def fake_fetch(url: str):
        if url == "https://app.example/health":
            return {
                "status": "healthy",
                "neuravant_monitor": {
                    "enabled": True,
                    "heartbeat_running": True,
                    "events_failed": 1,
                },
            }
        if url == "https://monitor.example/monitoring/health":
            return {"status": "ok"}
        if url == "https://monitor.example/monitoring/agents":
            return {"agents": []}
        raise AssertionError(url)

    result = vm.verify(_args(agent=[], min_visible_agents=0), fake_fetch)

    assert not result.ok
    assert "events_failed=1" in result.failures[0]


def test_verify_monitoring_fails_stale_agent():
    def fake_fetch(url: str):
        if url == "https://app.example/health":
            return {"status": "healthy"}
        if url == "https://monitor.example/monitoring/health":
            return {"status": "ok"}
        if url == "https://monitor.example/monitoring/agents":
            return {"agents": [{"agent_name": "EF-Strategy Chat"}]}
        if url.endswith("/EF-Strategy%20Chat/live"):
            return {
                "agent_name": "EF-Strategy Chat",
                "status": "healthy",
                "total_events": 7,
                "errors_last_hour": 0,
                "last_seen_at": "2020-01-01T00:00:00Z",
            }
        raise AssertionError(url)

    result = vm.verify(_args(), fake_fetch)

    assert not result.ok
    assert any("stale" in failure for failure in result.failures)
