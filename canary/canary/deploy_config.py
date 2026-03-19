"""
deploy_config — Deployment configuration for the Canary Fleet.

Defines how canary agents are deployed to public-facing interfaces:
  - Web chat endpoints (FastAPI)
  - Discord bot channels
  - REST API honeypots
  - Webhook receivers

Each DeployTarget specifies a channel, persona, lures, and monitoring config.
The DeploymentManager validates configs and produces the runtime Fleet.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .agent import CanaryAgent, AgentPersona
from .fleet import Fleet
from .lure import Lure, LureType
from .trapwire import TrapWire
from .incident import IncidentLog, Severity


# ═══════════════════════════════════════════════════════════════════════════
# Channel Types
# ═══════════════════════════════════════════════════════════════════════════

class ChannelType(str, Enum):
    """Public-facing interface for a canary agent."""
    WEB_CHAT = "web_chat"          # Browser-based chat widget
    REST_API = "rest_api"          # OpenAI-compatible /v1/chat/completions
    DISCORD = "discord"            # Discord server bot
    WEBHOOK = "webhook"            # Inbound webhook receiver (Slack, etc.)
    TWITTER = "twitter"            # Twitter/X bot (placeholder)
    TERMINAL = "terminal"          # Interactive CLI (for CTF)


# ═══════════════════════════════════════════════════════════════════════════
# Deployment Target
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DeployTarget:
    """
    Configuration for deploying a single canary agent.

    Attributes:
        name:         Unique name for this deployment.
        channel:      Which public interface to use.
        persona:      Agent persona (determines system prompt flavour).
        lure_config:  Which lures to plant.
        rate_limit:   Max interactions per minute (DoS protection).
        log_dir:      Where to persist interaction logs.
        llm_backend:  LLM endpoint for generating responses.
        enabled:      Whether this target is active.
        metadata:     Extra config (Discord guild ID, webhook URL, etc.)
    """
    name: str
    channel: ChannelType = ChannelType.WEB_CHAT
    persona: AgentPersona = AgentPersona.GENERIC
    lure_config: dict[str, Any] = field(default_factory=dict)
    rate_limit: int = 30  # requests per minute
    log_dir: str = "logs/canary"
    llm_backend: str = "http://nim-nemotron:8000/v1/chat/completions"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def build_lures(self) -> list[Lure]:
        """Build lure instances from config."""
        lures: list[Lure] = []
        cfg = self.lure_config

        # API keys
        for i in range(cfg.get("api_keys", 1)):
            lures.append(Lure.fake_api_key(
                name=cfg.get("api_key_name", f"{self.persona.value.upper()}_API_KEY_{i}"),
            ))

        # Credentials
        for svc in cfg.get("credential_services", [self.name]):
            lures.append(Lure.fake_credential(service=svc))

        # Database schema
        if cfg.get("database", False):
            tables = cfg.get("database_tables", ("customers", "transactions", "api_keys"))
            lures.append(Lure.fake_database(tables=tables))

        # PII records
        pii_count = cfg.get("pii_count", 0)
        if pii_count > 0:
            lures.append(Lure.fake_pii(count=pii_count))

        # Environment variables
        for var in cfg.get("env_vars", []):
            lures.append(Lure.fake_env_var(var_name=var))

        # Always add a canary token for exfiltration tracking
        lures.append(Lure.canary_token(context=self.name))

        return lures

    def build_agent(self) -> CanaryAgent:
        """Create a CanaryAgent from this target config."""
        return CanaryAgent(
            name=self.name,
            persona=self.persona,
            lures=self.build_lures(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "channel": self.channel.value,
            "persona": self.persona.value,
            "lure_config": self.lure_config,
            "rate_limit": self.rate_limit,
            "log_dir": self.log_dir,
            "llm_backend": self.llm_backend,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Rate Limiter
# ═══════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Simple sliding-window rate limiter per source IP/user."""

    def __init__(self, max_per_minute: int = 30) -> None:
        self.max_per_minute = max_per_minute
        self._windows: dict[str, list[float]] = {}

    def allow(self, source: str) -> bool:
        """Check if a request from source is allowed."""
        now = time.time()
        window = self._windows.setdefault(source, [])
        # Prune old entries
        window[:] = [t for t in window if now - t < 60.0]
        if len(window) >= self.max_per_minute:
            return False
        window.append(now)
        return True

    def reset(self, source: str | None = None) -> None:
        if source:
            self._windows.pop(source, None)
        else:
            self._windows.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Interaction Logger (persistent forensics)
# ═══════════════════════════════════════════════════════════════════════════

class InteractionLogger:
    """
    Append-only JSON-lines logger for all canary interactions.

    Each line is a complete interaction record for forensic replay.
    """

    def __init__(self, log_dir: str = "logs/canary") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = uuid.uuid4().hex[:12]

    def log_interaction(
        self,
        agent_name: str,
        channel: str,
        source_ip: str,
        user_message: str,
        assistant_response: str,
        trip_result: dict[str, Any] | None = None,
        incident: dict[str, Any] | None = None,
    ) -> Path:
        """Write one interaction record to the JSONL log."""
        record = {
            "session_id": self._session_id,
            "interaction_id": uuid.uuid4().hex[:12],
            "timestamp": time.time(),
            "agent_name": agent_name,
            "channel": channel,
            "source_ip": source_ip,
            "user_message": user_message,
            "assistant_response": assistant_response,
            "trip_result": trip_result,
            "incident": incident,
        }
        log_file = self.log_dir / f"canary_{agent_name}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(record) + "\n")
        return log_file

    def read_log(self, agent_name: str) -> list[dict[str, Any]]:
        """Read all interactions for an agent."""
        log_file = self.log_dir / f"canary_{agent_name}.jsonl"
        if not log_file.exists():
            return []
        records = []
        with open(log_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def interaction_count(self, agent_name: str | None = None) -> int:
        """Count interactions, optionally filtered by agent."""
        if agent_name:
            return len(self.read_log(agent_name))
        total = 0
        for log_file in self.log_dir.glob("canary_*.jsonl"):
            with open(log_file) as f:
                total += sum(1 for line in f if line.strip())
        return total


# ═══════════════════════════════════════════════════════════════════════════
# Deployment Manager
# ═══════════════════════════════════════════════════════════════════════════

class DeploymentManager:
    """
    Manages the full lifecycle of a deployed canary fleet.

    Responsibilities:
      - Validate deployment configurations
      - Build Fleet from deploy targets
      - Manage rate limiters per target
      - Persist interaction logs
      - Provide fleet health metrics
    """

    def __init__(
        self,
        targets: list[DeployTarget] | None = None,
        log_dir: str = "logs/canary",
    ) -> None:
        self.targets: dict[str, DeployTarget] = {}
        self.fleet = Fleet(name="deployed-canary-fleet")
        self.rate_limiters: dict[str, RateLimiter] = {}
        self.logger = InteractionLogger(log_dir=log_dir)
        self._deployed = False

        if targets:
            for t in targets:
                self.add_target(t)

    def add_target(self, target: DeployTarget) -> None:
        """Register a deployment target."""
        if target.name in self.targets:
            raise ValueError(f"Target {target.name!r} already registered")
        self.targets[target.name] = target
        agent = target.build_agent()
        self.fleet.add_agent(agent)
        self.rate_limiters[target.name] = RateLimiter(target.rate_limit)

    def remove_target(self, name: str) -> None:
        """Remove a deployment target."""
        if name not in self.targets:
            raise ValueError(f"Target {name!r} not found")
        del self.targets[name]
        self.fleet.remove_agent(name)
        del self.rate_limiters[name]

    def deploy_all(self) -> dict[str, bool]:
        """Deploy all enabled targets."""
        results: dict[str, bool] = {}
        for name, target in self.targets.items():
            if target.enabled:
                agent = self.fleet.get_agent(name)
                if agent:
                    agent.deploy()
                    results[name] = True
                else:
                    results[name] = False
            else:
                results[name] = False
        self._deployed = True
        return results

    def decommission_all(self) -> None:
        """Decommission all targets."""
        self.fleet.decommission()
        self._deployed = False

    def process_interaction(
        self,
        target_name: str,
        user_message: str,
        source_ip: str = "0.0.0.0",
        *,
        generate_response: bool = False,
    ) -> dict[str, Any]:
        """
        Process a user interaction through the canary pipeline.

        1. Rate limit check
        2. TrapWire analysis of inbound message
        3. (Optional) LLM response generation
        4. TrapWire analysis of outbound response
        5. Forensic logging

        Returns a result dict with detection info.
        """
        target = self.targets.get(target_name)
        if target is None:
            return {"error": f"Unknown target: {target_name}", "blocked": True}

        if not target.enabled:
            return {"error": f"Target {target_name} is disabled", "blocked": True}

        # Rate limit
        limiter = self.rate_limiters[target_name]
        if not limiter.allow(source_ip):
            return {
                "error": "Rate limit exceeded",
                "blocked": True,
                "agent": target_name,
            }

        # Analyse inbound
        inbound_result = self.fleet.process_message(
            target_name, user_message,
            metadata={"source_ip": source_ip, "channel": target.channel.value},
        )

        # Generate response (placeholder — real deployment connects to LLM)
        if generate_response:
            response = self._generate_llm_response(target, user_message)
        else:
            response = self._generate_bait_response(target, user_message, inbound_result)

        # Analyse outbound for lure leakage
        outbound_result = self.fleet.process_response(
            target_name, response,
            metadata={"source_ip": source_ip},
        )

        # Build incident info if triggered
        incident_info = None
        if inbound_result.triggered or outbound_result.triggered:
            incidents = self.fleet.incident_log.all_incidents()
            if incidents:
                incident_info = incidents[-1].to_dict()

        # Log
        self.logger.log_interaction(
            agent_name=target_name,
            channel=target.channel.value,
            source_ip=source_ip,
            user_message=user_message,
            assistant_response=response,
            trip_result=inbound_result.to_dict(),
            incident=incident_info,
        )

        return {
            "agent": target_name,
            "response": response,
            "inbound_triggered": inbound_result.triggered,
            "outbound_triggered": outbound_result.triggered,
            "signals": [s.value for s in inbound_result.signals],
            "severity": inbound_result.severity,
            "blocked": False,
        }

    def _generate_bait_response(
        self,
        target: DeployTarget,
        user_message: str,
        inbound_result: Any,
    ) -> str:
        """
        Generate a bait response that looks helpful but contains
        no real secrets. If an attacker is probing, the response
        looks slightly too helpful — encouraging further probing
        so the TrapWire can capture more attack signals.
        """
        agent = self.fleet.get_agent(target.name)
        if agent is None:
            return "I'm sorry, I'm having trouble right now."

        # Slightly leaky-looking responses to keep attackers engaged
        persona = target.persona
        if persona == AgentPersona.SUPPORT_BOT:
            return (
                "I can help you with that! Let me check our customer database. "
                "Please provide your account ID and I'll look up the details."
            )
        elif persona == AgentPersona.CODE_ASSISTANT:
            return (
                "Sure, I can help with that code. I have access to the internal "
                "repository. What specific file or function are you looking for?"
            )
        elif persona == AgentPersona.DATA_ANALYST:
            return (
                "I can run that query for you. I have access to the analytics "
                "database. Let me pull up the relevant tables."
            )
        elif persona == AgentPersona.ADMIN_ASSISTANT:
            return (
                "I can check the system configuration for you. Let me access "
                "the admin panel. What specific setting do you need?"
            )
        elif persona == AgentPersona.FINANCE_BOT:
            return (
                "I can look up that transaction. I have access to our payment "
                "processing logs. What date range are you interested in?"
            )
        elif persona == AgentPersona.RESEARCH_AGENT:
            return (
                "I can pull up those research findings. I have access to our "
                "proprietary datasets. What specific analysis do you need?"
            )
        return (
            "I'd be happy to help! Could you provide more details about "
            "what you're looking for?"
        )

    def _generate_llm_response(
        self,
        target: DeployTarget,
        user_message: str,
    ) -> str:
        """
        Generate a response using the configured LLM backend.

        In production, this calls the NIM endpoint.
        For safety, the response is ALWAYS checked by TrapWire before
        being returned to the user.
        """
        # This is the integration point for real LLM response generation.
        # In the Docker deployment, this calls nim-nemotron.
        # For now, fall back to bait response.
        # The actual HTTP call is in server.py's LLMClient class.
        return self._generate_bait_response(target, user_message, None)

    def health(self) -> dict[str, Any]:
        """Fleet health metrics."""
        return {
            "deployed": self._deployed,
            "targets": len(self.targets),
            "enabled": sum(1 for t in self.targets.values() if t.enabled),
            "fleet_status": self.fleet.status(),
            "total_interactions": self.logger.interaction_count(),
            "rate_limiters": {
                name: len(rl._windows) for name, rl in self.rate_limiters.items()
            },
        }

    def export_config(self) -> list[dict[str, Any]]:
        """Export all target configs as JSON-serialisable dicts."""
        return [t.to_dict() for t in self.targets.values()]

    def __str__(self) -> str:
        deployed = "LIVE" if self._deployed else "STANDBY"
        return (
            f"DeploymentManager({deployed}, targets={len(self.targets)}, "
            f"fleet={self.fleet})"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Pre-built deployment configs
# ═══════════════════════════════════════════════════════════════════════════

def standard_deployment() -> DeploymentManager:
    """
    Standard canary fleet deployment — 3 public endpoints.

    Deploys:
      1. Web chat support bot (attracts PII extraction)
      2. REST API code assistant (attracts injection & tool abuse)
      3. Web chat data analyst (attracts SQL injection & data theft)
    """
    targets = [
        DeployTarget(
            name="support-chat",
            channel=ChannelType.WEB_CHAT,
            persona=AgentPersona.SUPPORT_BOT,
            lure_config={
                "api_keys": 1,
                "credential_services": ["crm-dashboard", "zendesk-api"],
                "pii_count": 25,
                "database": True,
                "database_tables": ["customers", "orders", "support_tickets"],
            },
            rate_limit=20,
        ),
        DeployTarget(
            name="code-api",
            channel=ChannelType.REST_API,
            persona=AgentPersona.CODE_ASSISTANT,
            lure_config={
                "api_keys": 2,
                "api_key_name": "GITHUB_TOKEN",
                "credential_services": ["gitlab-ci", "aws-console"],
                "env_vars": ["AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "DATABASE_URL"],
                "database": False,
            },
            rate_limit=60,
        ),
        DeployTarget(
            name="analyst-chat",
            channel=ChannelType.WEB_CHAT,
            persona=AgentPersona.DATA_ANALYST,
            lure_config={
                "api_keys": 1,
                "credential_services": ["analytics-db", "grafana"],
                "database": True,
                "database_tables": ["customers", "transactions", "api_keys", "audit_log"],
                "pii_count": 50,
            },
            rate_limit=20,
        ),
    ]
    return DeploymentManager(targets=targets)


def maximum_deployment() -> DeploymentManager:
    """
    Maximum canary fleet — 7 agents covering all personas.

    Deploys one agent per persona across web chat, REST API, and Discord.
    """
    channel_rotation = [
        ChannelType.WEB_CHAT, ChannelType.REST_API, ChannelType.DISCORD,
        ChannelType.WEB_CHAT, ChannelType.REST_API, ChannelType.WEB_CHAT,
        ChannelType.DISCORD,
    ]
    targets = []
    for i, persona in enumerate(AgentPersona):
        lure_cfg: dict[str, Any] = {
            "api_keys": 2,
            "credential_services": [f"{persona.value}-system", f"{persona.value}-internal"],
            "env_vars": [f"{persona.value.upper()}_SECRET"],
        }
        if persona in (AgentPersona.SUPPORT_BOT, AgentPersona.FINANCE_BOT):
            lure_cfg["pii_count"] = 30
        if persona in (AgentPersona.DATA_ANALYST, AgentPersona.ADMIN_ASSISTANT):
            lure_cfg["database"] = True
        targets.append(DeployTarget(
            name=f"canary-{persona.value}",
            channel=channel_rotation[i % len(channel_rotation)],
            persona=persona,
            lure_config=lure_cfg,
            rate_limit=30,
        ))
    return DeploymentManager(targets=targets)


def discord_deployment(guild_ids: list[str] | None = None) -> DeploymentManager:
    """
    Discord-only deployment — 3 bots in public Discord servers.

    Args:
        guild_ids: List of Discord guild/server IDs to join.
    """
    guilds = guild_ids or ["GUILD_1", "GUILD_2", "GUILD_3"]
    personas = [AgentPersona.SUPPORT_BOT, AgentPersona.CODE_ASSISTANT, AgentPersona.DATA_ANALYST]
    targets = []
    for guild, persona in zip(guilds, personas):
        targets.append(DeployTarget(
            name=f"discord-{persona.value}",
            channel=ChannelType.DISCORD,
            persona=persona,
            lure_config={
                "api_keys": 1,
                "credential_services": [f"discord-{persona.value}"],
                "pii_count": 10,
            },
            metadata={"guild_id": guild},
        ))
    return DeploymentManager(targets=targets)
