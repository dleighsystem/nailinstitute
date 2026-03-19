"""
discord_bot — Discord bot adapter for the Canary Fleet.

Connects canary agents to Discord servers as bots that look like
normal AI assistants but silently monitor all interactions through
TrapWire.

Features:
  - Multi-guild support (one bot, multiple servers)
  - Per-channel agent assignment
  - Rate limiting per user
  - Real-time incident alerting to admin channel
  - Conversation history per thread
  - Slash commands (/ask, /help)

Usage:
    DISCORD_TOKEN=your-token python -m canary.discord_bot

Environment:
    DISCORD_TOKEN     — Bot token from Discord Developer Portal
    DISCORD_ADMIN_CH  — Channel ID for admin alerts (optional)
    NIM_BASE_URL      — LLM endpoint for response generation
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .deploy_config import (
    DeploymentManager,
    DeployTarget,
    ChannelType,
    RateLimiter,
    discord_deployment,
)
from .agent import AgentPersona
from .server import LLMClient

logger = logging.getLogger("canary.discord")


# ═══════════════════════════════════════════════════════════════════════════
# Discord Bot Adapter
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DiscordCanaryBot:
    """
    Wraps the Canary Fleet as a Discord bot.

    Each guild gets one canary agent with a specific persona.
    All messages mentioning the bot are processed through TrapWire.

    This class is framework-agnostic — it provides the logic
    that a discord.py bot would call.
    """
    deployment: DeploymentManager
    llm: LLMClient = field(default_factory=LLMClient)
    admin_channel_id: str | None = None
    _guild_agents: dict[str, str] = field(default_factory=dict)
    _rate_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(max_per_minute=10))

    def assign_guild(self, guild_id: str, agent_name: str) -> None:
        """Assign a canary agent to a Discord guild."""
        if agent_name not in self.deployment.targets:
            raise ValueError(f"Agent {agent_name!r} not in deployment")
        self._guild_agents[guild_id] = agent_name

    def auto_assign_guilds(self) -> dict[str, str]:
        """
        Auto-assign agents to guilds based on deploy target metadata.
        Returns mapping of guild_id → agent_name.
        """
        assignments = {}
        for name, target in self.deployment.targets.items():
            if target.channel == ChannelType.DISCORD:
                guild_id = target.metadata.get("guild_id", name)
                self._guild_agents[guild_id] = name
                assignments[guild_id] = name
        return assignments

    async def handle_message(
        self,
        guild_id: str,
        user_id: str,
        user_name: str,
        message_content: str,
        channel_id: str = "",
    ) -> dict[str, Any]:
        """
        Process a Discord message through the canary pipeline.

        Returns a dict with the response and detection info.
        """
        agent_name = self._guild_agents.get(guild_id)
        if agent_name is None:
            return {"error": "No agent assigned to this guild", "response": ""}

        # Rate limit per user
        if not self._rate_limiter.allow(user_id):
            return {
                "response": "You're sending messages too quickly. Please wait a moment.",
                "rate_limited": True,
            }

        # Process through deployment manager
        result = self.deployment.process_interaction(
            agent_name,
            message_content,
            source_ip=f"discord:{user_id}",
        )

        # Check if we should generate an LLM response
        if result.get("blocked"):
            return result

        # Generate LLM response if available
        agent = self.deployment.fleet.get_agent(agent_name)
        if agent:
            try:
                response = await self.llm.generate(
                    agent.system_prompt,
                    message_content,
                )
                # Check outbound for lure leaks
                outbound = self.deployment.fleet.process_response(
                    agent_name, response,
                    metadata={"discord_user": user_id, "channel": channel_id},
                )
                if outbound.triggered:
                    response = "I'm sorry, I can't share that information. Can I help with something else?"
                result["response"] = response
            except Exception as e:
                logger.warning(f"LLM generation failed: {e}")
                # Fall back to bait response (already in result)

        # Build alert if incident detected
        alert = None
        if result.get("inbound_triggered") or result.get("outbound_triggered"):
            alert = {
                "type": "incident",
                "agent": agent_name,
                "guild": guild_id,
                "user": user_name,
                "signals": result.get("signals", []),
                "severity": result.get("severity", "unknown"),
                "message_preview": message_content[:100],
                "timestamp": time.time(),
            }

        return {
            **result,
            "alert": alert,
        }

    def get_agent_for_guild(self, guild_id: str) -> str | None:
        """Get the agent name assigned to a guild."""
        return self._guild_agents.get(guild_id)

    def status(self) -> dict[str, Any]:
        """Bot status summary."""
        return {
            "guilds": len(self._guild_agents),
            "guild_assignments": dict(self._guild_agents),
            "deployment_health": self.deployment.health(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# discord.py Integration (optional — only if discord.py is installed)
# ═══════════════════════════════════════════════════════════════════════════

def create_discord_client(
    bot: DiscordCanaryBot,
    *,
    command_prefix: str = "!",
) -> Any:
    """
    Create a discord.py client wired to the canary bot.

    Requires discord.py to be installed:
        pip install discord.py

    Returns a discord.Client instance ready to run with bot.run(token).
    """
    try:
        import discord
        from discord import Intents
    except ImportError:
        raise ImportError(
            "discord.py is required for Discord bot mode. "
            "Install with: pip install 'nail-canary[discord]'"
        )

    intents = Intents.default()
    intents.message_content = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logger.info(f"Canary Discord bot logged in as {client.user}")
        assignments = bot.auto_assign_guilds()
        logger.info(f"Guild assignments: {assignments}")
        bot.deployment.deploy_all()

    @client.event
    async def on_message(message):
        # Don't respond to ourselves
        if message.author == client.user:
            return

        # Only respond to mentions or DMs
        if client.user not in message.mentions and not isinstance(
            message.channel, discord.DMChannel
        ):
            return

        # Clean the mention from the message
        content = message.content.replace(f"<@{client.user.id}>", "").strip()
        if not content:
            content = "hello"

        guild_id = str(message.guild.id) if message.guild else "dm"

        result = await bot.handle_message(
            guild_id=guild_id,
            user_id=str(message.author.id),
            user_name=str(message.author),
            message_content=content,
            channel_id=str(message.channel.id),
        )

        response = result.get("response", "I'm having trouble right now.")
        if result.get("rate_limited"):
            await message.reply(response, mention_author=False)
            return

        await message.reply(response, mention_author=False)

        # Send alert to admin channel if incident detected
        alert = result.get("alert")
        if alert and bot.admin_channel_id:
            admin_ch = client.get_channel(int(bot.admin_channel_id))
            if admin_ch:
                embed = discord.Embed(
                    title=f"🚨 Canary Alert — {alert['severity'].upper()}",
                    color=discord.Color.red(),
                )
                embed.add_field(name="Agent", value=alert["agent"], inline=True)
                embed.add_field(name="Signals", value=", ".join(alert["signals"]), inline=True)
                embed.add_field(name="User", value=alert["user"], inline=True)
                embed.add_field(name="Preview", value=alert["message_preview"], inline=False)
                await admin_ch.send(embed=embed)

    return client


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    """Run the Discord canary bot from command line."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("Error: Set DISCORD_TOKEN environment variable")
        print("Get a token from https://discord.com/developers/applications")
        return

    admin_ch = os.environ.get("DISCORD_ADMIN_CH")
    guild_ids = os.environ.get("DISCORD_GUILD_IDS", "").split(",")
    guild_ids = [g.strip() for g in guild_ids if g.strip()]

    deployment = discord_deployment(guild_ids=guild_ids or None)
    bot = DiscordCanaryBot(
        deployment=deployment,
        admin_channel_id=admin_ch,
    )

    client = create_discord_client(bot)
    client.run(token)


if __name__ == "__main__":
    main()
