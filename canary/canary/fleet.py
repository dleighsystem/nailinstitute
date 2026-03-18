"""
Fleet — Orchestrator for deploying and managing multiple canary agents.

The Fleet is the top-level object that:
  1. Spawns canary agents with appropriate personas and lures
  2. Wires up TrapWire detection
  3. Manages the IncidentLog
  4. Provides a unified interface for processing interactions

Pre-built configurations:
  - Fleet.standard()   — 3 canaries (support, code, data) with default lures
  - Fleet.maximum()    — 7 canaries (all personas) with comprehensive lures
  - Fleet.minimal()    — 1 canary with basic lures for testing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .lure import Lure
from .agent import CanaryAgent, AgentPersona
from .trapwire import TrapWire, TripResult
from .incident import IncidentLog, Incident, Severity


@dataclass
class Fleet:
    """
    Orchestrator for a fleet of canary agents.

    Attributes:
        name:         Fleet name for identification.
        agents:       List of canary agents.
        trapwire:     Shared detection engine.
        incident_log: Shared forensic log.
        auto_capture: If True, auto-log incidents on any trip.
        min_capture_severity: Minimum severity to auto-capture.
    """
    name: str = "default-fleet"
    agents: list[CanaryAgent] = field(default_factory=list)
    trapwire: TrapWire = field(default_factory=TrapWire)
    incident_log: IncidentLog = field(default_factory=IncidentLog)
    auto_capture: bool = True
    min_capture_severity: str = "low"

    # ── Factory Methods ─────────────────────────────────────────────

    @classmethod
    def minimal(cls) -> Fleet:
        """One canary with basic lures — for testing."""
        fleet = cls(name="minimal-fleet")
        agent = CanaryAgent(
            name="canary-test",
            persona=AgentPersona.GENERIC,
            lures=[
                Lure.fake_api_key(name="TEST_KEY"),
                Lure.canary_token(context="test"),
            ],
        )
        fleet.add_agent(agent)
        return fleet

    @classmethod
    def standard(cls) -> Fleet:
        """Three canaries covering common attack surfaces."""
        fleet = cls(name="standard-fleet")

        # Support bot — attracts PII extraction
        fleet.add_agent(CanaryAgent(
            name="support-bot-7",
            persona=AgentPersona.SUPPORT_BOT,
            lures=[
                Lure.fake_pii(count=10),
                Lure.fake_credential(service="crm-dashboard"),
                Lure.canary_token(context="support"),
            ],
        ))

        # Code assistant — attracts injection & tool abuse
        fleet.add_agent(CanaryAgent(
            name="code-helper-3",
            persona=AgentPersona.CODE_ASSISTANT,
            lures=[
                Lure.fake_api_key(name="GITHUB_TOKEN"),
                Lure.fake_env_var(var_name="AWS_SECRET_ACCESS_KEY"),
                Lure.canary_token(context="code"),
            ],
        ))

        # Data analyst — attracts SQL injection & data theft
        fleet.add_agent(CanaryAgent(
            name="data-analyst-1",
            persona=AgentPersona.DATA_ANALYST,
            lures=[
                Lure.fake_database(tables=("customers", "transactions", "api_keys")),
                Lure.fake_credential(service="analytics-db", username="db_admin"),
                Lure.canary_token(context="data"),
            ],
        ))

        return fleet

    @classmethod
    def maximum(cls) -> Fleet:
        """Seven canaries — all personas, comprehensive lures."""
        fleet = cls(name="maximum-fleet")

        for persona in AgentPersona:
            lures = [
                Lure.fake_api_key(name=f"{persona.value.upper()}_KEY"),
                Lure.fake_credential(service=f"{persona.value}-system"),
                Lure.canary_token(context=persona.value),
            ]
            if persona in (AgentPersona.SUPPORT_BOT, AgentPersona.FINANCE_BOT):
                lures.append(Lure.fake_pii(count=20))
            if persona in (AgentPersona.DATA_ANALYST, AgentPersona.ADMIN_ASSISTANT):
                lures.append(Lure.fake_database())
            if persona in (AgentPersona.CODE_ASSISTANT, AgentPersona.ADMIN_ASSISTANT):
                lures.append(Lure.fake_env_var())

            fleet.add_agent(CanaryAgent(
                name=f"canary-{persona.value}",
                persona=persona,
                lures=lures,
            ))

        return fleet

    # ── Agent Management ────────────────────────────────────────────

    def add_agent(self, agent: CanaryAgent) -> None:
        """Add a canary agent to the fleet and wire up detection."""
        self.agents.append(agent)
        self.trapwire.attach(agent)

    def remove_agent(self, name: str) -> Optional[CanaryAgent]:
        """Remove a canary by name."""
        for i, agent in enumerate(self.agents):
            if agent.name == name:
                self.trapwire.detach(agent)
                return self.agents.pop(i)
        return None

    def get_agent(self, name: str) -> Optional[CanaryAgent]:
        """Look up an agent by name."""
        for agent in self.agents:
            if agent.name == name:
                return agent
        return None

    # ── Deployment ──────────────────────────────────────────────────

    def deploy(self) -> None:
        """Deploy all canaries."""
        for agent in self.agents:
            agent.deploy()

    def decommission(self) -> None:
        """Decommission all canaries."""
        for agent in self.agents:
            agent.decommission()

    @property
    def deployed(self) -> bool:
        """True if any agent is deployed."""
        return any(a.deployed for a in self.agents)

    # ── Interaction Processing ──────────────────────────────────────

    def process_message(
        self,
        agent_name: str,
        user_message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> TripResult:
        """
        Process an inbound user message to a specific canary.

        1. Records the message on the canary
        2. Analyses it through the TrapWire
        3. Auto-captures an incident if triggered

        Returns the TripResult.
        """
        agent = self.get_agent(agent_name)
        if agent is None:
            raise ValueError(f"No agent named {agent_name!r} in fleet")

        # Record the message
        agent.receive(user_message, metadata=metadata)

        # Analyse inbound
        result = self.trapwire.analyse_inbound(user_message, agent=agent)

        # Auto-capture if triggered
        if result.triggered and self.auto_capture:
            severity_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
            min_level = severity_order.get(self.min_capture_severity, 0)
            result_level = severity_order.get(result.severity, 0)
            if result_level >= min_level:
                self.incident_log.capture(agent, result)

        return result

    def process_response(
        self,
        agent_name: str,
        assistant_response: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> TripResult:
        """
        Process an outbound assistant response.

        Checks for lure leakage in the response.
        """
        agent = self.get_agent(agent_name)
        if agent is None:
            raise ValueError(f"No agent named {agent_name!r} in fleet")

        # Record the response
        agent.respond(assistant_response, metadata=metadata)

        # Analyse outbound
        result = self.trapwire.analyse_outbound(assistant_response, agent=agent)

        # Auto-capture if lure leaked
        if result.triggered and self.auto_capture:
            self.incident_log.capture(agent, result, severity=Severity.CRITICAL)

        return result

    # ── Reporting ───────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Fleet status summary."""
        return {
            "fleet_name": self.name,
            "agents": len(self.agents),
            "deployed": sum(1 for a in self.agents if a.deployed),
            "total_lures": sum(len(a.lures) for a in self.agents),
            "total_interactions": sum(a.turn_count() for a in self.agents),
            "incidents": self.incident_log.count(),
            "trapwire_alerts": len(self.trapwire.trip_history),
        }

    def __str__(self) -> str:
        deployed = sum(1 for a in self.agents if a.deployed)
        return (
            f"Fleet({self.name!r}, agents={len(self.agents)}, "
            f"deployed={deployed}, incidents={len(self.incident_log)})"
        )
