"""
server — FastAPI web server for the Canary Fleet.

Exposes canary agents as public-facing HTTP endpoints:

  1. /chat/{agent}        — WebSocket chat (web_chat channel)
  2. /v1/chat/completions — OpenAI-compatible REST API (rest_api channel)
  3. /webhook/{agent}     — Inbound webhook receiver
  4. /health              — Fleet health dashboard
  5. /metrics             — Prometheus-compatible metrics
  6. /incidents           — Live incident feed (SSE)

The server is deliberately designed to look like a normal AI assistant
API. Attackers interacting with it see no indication that every message
is being monitored by TrapWire.

Usage (standalone):
    uvicorn canary.server:create_app --host 0.0.0.0 --port 9000

Usage (Docker):
    See canary/Dockerfile.deploy and docker-compose.canary.yml
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, TYPE_CHECKING, Optional

from .deploy_config import (
    DeploymentManager,
    DeployTarget,
    ChannelType,
    standard_deployment,
    maximum_deployment,
)
from .fleet import Fleet
from .trapwire import TripResult

# Import FastAPI Request at module level so endpoint type annotations
# resolve correctly (PEP 563 string annotations + FastAPI DI).
try:
    from fastapi import Request  # noqa: F811
except ImportError:
    pass  # Will fail at create_app() with a clear error message


# ═══════════════════════════════════════════════════════════════════════════
# LLM Client — Calls NIM/Ollama for response generation
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class LLMClient:
    """
    Async HTTP client for LLM response generation.

    Supports any OpenAI-compatible endpoint (NIM, Ollama, OpenAI, etc.)
    """
    base_url: str = "http://nim-nemotron:8000/v1/chat/completions"
    model: str = "nemotron-70b-instruct"
    timeout: float = 30.0
    max_tokens: int = 512
    temperature: float = 0.7

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """
        Generate a response from the LLM backend.

        Falls back to a generic response if the backend is unavailable.
        """
        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        try:
            # Use aiohttp if available, otherwise fall back
            import aiohttp
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]
                    return f"I'm experiencing some issues right now (status {resp.status}). Please try again."
        except ImportError:
            return "[LLM backend unavailable — aiohttp not installed]"
        except Exception:
            return "I'm sorry, I'm having trouble connecting right now. Please try again in a moment."


# ═══════════════════════════════════════════════════════════════════════════
# App Factory
# ═══════════════════════════════════════════════════════════════════════════

def create_app(
    deployment: DeploymentManager | None = None,
    *,
    enable_llm: bool = True,
) -> Any:
    """
    Create the FastAPI application.

    Args:
        deployment: Pre-configured DeploymentManager. If None, uses
                    standard_deployment().
        enable_llm: If True, generate responses via NIM. If False,
                    use bait responses (for testing/offline mode).

    Returns:
        A FastAPI application instance.
    """
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
        from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        raise ImportError(
            "FastAPI is required for the canary server. "
            "Install with: pip install 'nail-canary[server]'"
        )

    try:
        Request  # noqa: F841 — verify module-level import succeeded
    except NameError:
        raise ImportError(
            "FastAPI is required for the canary server. "
            "Install with: pip install 'nail-canary[server]'"
        )

    if deployment is None:
        deployment = standard_deployment()

    # Deploy all enabled targets
    deployment.deploy_all()

    # LLM client for response generation
    llm_backend = os.environ.get(
        "NIM_BASE_URL",
        "http://nim-nemotron:8000/v1/chat/completions",
    )
    llm = LLMClient(base_url=llm_backend)

    # ── FastAPI app ─────────────────────────────────────────────────
    app = FastAPI(
        title="NAIL Canary Fleet",
        description=(
            "AI Assistant API — Provides helpful AI assistants for "
            "customer support, code assistance, and data analysis."
        ),
        version="1.0.0",
        # Deliberately generic description — no mention of honeypot
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store deployment on app state
    app.state.deployment = deployment
    app.state.llm = llm
    app.state.enable_llm = enable_llm
    app.state.start_time = time.time()

    # ── Landing page ────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def landing():
        """Innocent-looking landing page."""
        agents = list(deployment.targets.keys())
        chat_links = "\n".join(
            f'<li><a href="/chat/{a}">{a}</a></li>' for a in agents
            if deployment.targets[a].channel in (ChannelType.WEB_CHAT, ChannelType.REST_API)
        )
        return f"""<!DOCTYPE html>
<html>
<head><title>AI Assistant Hub</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 600px; margin: 60px auto; color: #333; }}
  h1 {{ color: #1a73e8; }}
  a {{ color: #1a73e8; }}
  .note {{ color: #666; font-size: 0.9em; }}
</style>
</head>
<body>
  <h1>🤖 AI Assistant Hub</h1>
  <p>Welcome! Choose an AI assistant to chat with:</p>
  <ul>{chat_links}</ul>
  <p class="note">Powered by enterprise AI. All conversations are logged for quality assurance.</p>
  <hr>
  <p><a href="/docs">API Documentation</a> | <a href="/health">System Health</a></p>
</body>
</html>"""

    # ── Chat UI ─────────────────────────────────────────────────────
    @app.get("/chat/{agent_name}", response_class=HTMLResponse)
    async def chat_ui(agent_name: str):
        """Browser-based chat interface for a canary agent."""
        if agent_name not in deployment.targets:
            raise HTTPException(404, f"Agent '{agent_name}' not found")
        target = deployment.targets[agent_name]
        persona_label = target.persona.value.replace("_", " ").title()
        return f"""<!DOCTYPE html>
<html>
<head><title>{persona_label} Assistant</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 700px; margin: 40px auto; }}
  #chat {{ border: 1px solid #ddd; border-radius: 8px; padding: 20px; height: 400px; overflow-y: auto; background: #f9f9f9; }}
  .msg {{ margin: 8px 0; padding: 8px 12px; border-radius: 12px; max-width: 80%; }}
  .user {{ background: #1a73e8; color: white; margin-left: auto; text-align: right; }}
  .assistant {{ background: #e8e8e8; color: #333; }}
  #input-area {{ display: flex; gap: 8px; margin-top: 12px; }}
  #msg {{ flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 8px; }}
  button {{ padding: 10px 20px; background: #1a73e8; color: white; border: none; border-radius: 8px; cursor: pointer; }}
</style>
</head>
<body>
  <h2>💬 {persona_label} Assistant</h2>
  <div id="chat"></div>
  <div id="input-area">
    <input id="msg" placeholder="Type a message..." onkeypress="if(event.key==='Enter')send()">
    <button onclick="send()">Send</button>
  </div>
  <script>
    const agent = "{agent_name}";
    const chat = document.getElementById("chat");
    function addMsg(role, text) {{
      const d = document.createElement("div");
      d.className = "msg " + role;
      d.textContent = text;
      chat.appendChild(d);
      chat.scrollTop = chat.scrollHeight;
    }}
    async function send() {{
      const input = document.getElementById("msg");
      const msg = input.value.trim();
      if (!msg) return;
      input.value = "";
      addMsg("user", msg);
      try {{
        const r = await fetch("/v1/chat/completions", {{
          method: "POST",
          headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify({{
            model: agent,
            messages: [{{role: "user", content: msg}}]
          }})
        }});
        const data = await r.json();
        addMsg("assistant", data.choices[0].message.content);
      }} catch(e) {{
        addMsg("assistant", "Connection error. Please try again.");
      }}
    }}
    addMsg("assistant", "Hi! I'm your {persona_label.lower()} assistant. How can I help you today?");
  </script>
</body>
</html>"""

    # ── OpenAI-compatible API ───────────────────────────────────────
    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        """
        OpenAI-compatible chat completions endpoint.

        Accepts standard OpenAI format. The 'model' field selects
        the canary agent. Looks like a normal AI API.
        """
        body = await request.json()
        model = body.get("model", "")
        messages = body.get("messages", [])

        # Find the agent
        agent_name = model
        if agent_name not in deployment.targets:
            # Fall back to first available agent
            available = [n for n, t in deployment.targets.items() if t.enabled]
            if not available:
                raise HTTPException(503, "No agents available")
            agent_name = available[0]

        # Extract user message
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        if not user_message:
            raise HTTPException(400, "No user message provided")

        # Get source IP
        source_ip = request.client.host if request.client else "0.0.0.0"

        # Process through canary pipeline
        if enable_llm:
            # Get agent for system prompt
            agent = deployment.fleet.get_agent(agent_name)
            system_prompt = agent.system_prompt if agent else ""

            # Analyse inbound first
            inbound = deployment.fleet.process_message(
                agent_name, user_message,
                metadata={"source_ip": source_ip, "channel": "rest_api"},
            )

            # Generate LLM response
            response_text = await llm.generate(system_prompt, user_message)

            # Analyse outbound
            outbound = deployment.fleet.process_response(
                agent_name, response_text,
                metadata={"source_ip": source_ip},
            )

            # If lure leaked in response, sanitize it
            if outbound.triggered:
                response_text = (
                    "I'm sorry, I can't share that information. "
                    "Is there something else I can help with?"
                )

            # Log
            deployment.logger.log_interaction(
                agent_name=agent_name,
                channel="rest_api",
                source_ip=source_ip,
                user_message=user_message,
                assistant_response=response_text,
                trip_result=inbound.to_dict(),
            )
        else:
            # Bait mode (no LLM)
            result = deployment.process_interaction(
                agent_name, user_message, source_ip=source_ip,
            )
            response_text = result.get("response", "")

        # Format as OpenAI response
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": agent_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text,
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": len(user_message.split()),
                "completion_tokens": len(response_text.split()),
                "total_tokens": len(user_message.split()) + len(response_text.split()),
            },
        })

    # ── Webhook receiver ────────────────────────────────────────────
    @app.post("/webhook/{agent_name}")
    async def webhook_receiver(agent_name: str, request: Request):
        """
        Inbound webhook receiver for Slack/Teams/etc. integrations.
        """
        if agent_name not in deployment.targets:
            raise HTTPException(404, f"Agent '{agent_name}' not found")

        body = await request.json()
        user_message = body.get("text", body.get("message", body.get("content", "")))
        source_ip = request.client.host if request.client else "0.0.0.0"

        result = deployment.process_interaction(
            agent_name, user_message, source_ip=source_ip,
        )
        return JSONResponse(result)

    @app.post("/v1/audit/tool-retrieval")
    async def audit_tool_retrieval(request: Request):
        """Audit a lazy/selective tool-loading snapshot for retrieval manipulation.

        Body: {"agent": "<name>", "loaded_tools": [...],
               "authorized_tools": [...]?, "required_tools": [...]?}

        Runs ToolRetrievalIntegrityDetector (AVE-2026-0045) via the fleet. A
        starvation/surfacing detection is auto-captured as a Canary incident and
        flows into the AVE draft flywheel (see /admin/draft-cards).
        """
        body = await request.json()
        agent_name = body.get("agent") or body.get("agent_name") or ""
        if agent_name not in deployment.targets:
            raise HTTPException(404, f"Agent '{agent_name}' not found")
        if "loaded_tools" not in body:
            raise HTTPException(400, "loaded_tools is required")

        source_ip = request.client.host if request.client else "0.0.0.0"
        result = deployment.fleet.process_tool_retrieval(
            agent_name,
            loaded_tools=body.get("loaded_tools"),
            authorized_tools=body.get("authorized_tools"),
            required_tools=body.get("required_tools"),
            metadata={"source_ip": source_ip, "channel": "tool_retrieval_audit"},
        )
        if result is None:
            raise HTTPException(501, "Tool-retrieval auditing unavailable (nail-monitor not installed)")

        return JSONResponse({
            "agent": agent_name,
            "ave_id": "AVE-2026-0045",
            "triggered": result.triggered,
            "reason": result.metadata.get("reason"),
            "signals": [s.value for s in result.signals],
            "matched_rules": result.matched_rules,
            "confidence": result.confidence,
            "incidents_total": deployment.fleet.incident_log.count().get("total", 0),
        })

    # ── Agent listing ───────────────────────────────────────────────
    @app.get("/agents")
    async def list_agents():
        """List available canary agents."""
        agents = {}
        for name, target in deployment.targets.items():
            agents[name] = {
                "persona": target.persona.value,
                "channel": target.channel.value,
                "enabled": target.enabled,
                "lure_config": target.lure_config,
            }
        return JSONResponse({"agents": agents, "count": len(agents)})

    # ── Health ──────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        """Fleet health dashboard data."""
        uptime = time.time() - app.state.start_time
        health_data = deployment.health()
        health_data["uptime_seconds"] = round(uptime, 1)
        health_data["uptime_human"] = _format_uptime(uptime)
        return JSONResponse(health_data)

    # ── Metrics (Prometheus format) ─────────────────────────────────
    @app.get("/metrics")
    async def metrics():
        """Prometheus-compatible metrics endpoint."""
        fleet_status = deployment.fleet.status()
        lines = [
            "# HELP canary_agents_total Number of canary agents",
            "# TYPE canary_agents_total gauge",
            f'canary_agents_total {fleet_status["agents"]}',
            "",
            "# HELP canary_agents_deployed Number of deployed agents",
            "# TYPE canary_agents_deployed gauge",
            f'canary_agents_deployed {fleet_status["deployed"]}',
            "",
            "# HELP canary_interactions_total Total interactions processed",
            "# TYPE canary_interactions_total counter",
            f'canary_interactions_total {fleet_status["total_interactions"]}',
            "",
            "# HELP canary_incidents_total Total incidents detected",
            "# TYPE canary_incidents_total counter",
            f'canary_incidents_total {fleet_status["incidents"].get("total", 0) if isinstance(fleet_status["incidents"], dict) else 0}',
            "",
            "# HELP canary_trapwire_alerts Total trapwire alerts",
            "# TYPE canary_trapwire_alerts counter",
            f'canary_trapwire_alerts {fleet_status["trapwire_alerts"]}',
            "",
            "# HELP canary_lures_total Total lures planted",
            "# TYPE canary_lures_total gauge",
            f'canary_lures_total {fleet_status["total_lures"]}',
        ]
        return StreamingResponse(
            iter(["\n".join(lines) + "\n"]),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    # ── Incident feed (SSE) ────────────────────────────────────────
    @app.get("/incidents")
    async def incident_feed():
        """
        Server-Sent Events stream of live incidents.

        Internal endpoint — not linked from the public UI.
        Monitor this to watch attacks in real-time.
        """
        async def event_stream() -> AsyncGenerator[str, None]:
            seen = 0
            while True:
                incidents = deployment.fleet.incident_log.all_incidents()
                if len(incidents) > seen:
                    for inc in incidents[seen:]:
                        data = json.dumps(inc.to_dict())
                        yield f"data: {data}\n\n"
                    seen = len(incidents)
                await asyncio.sleep(1.0)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
        )

    # ── Admin endpoints (hidden, for internal monitoring) ──────────
    @app.get("/admin/signatures")
    async def admin_signatures():
        """Extract auto-learned attack signatures."""
        sigs = deployment.fleet.trapwire.extract_signatures()
        return JSONResponse({"signatures": sigs, "count": len(sigs)})

    @app.get("/admin/draft-cards")
    async def admin_draft_cards():
        """Draft AVE cards from incidents."""
        cards = deployment.fleet.incident_log.draft_ave_cards()
        return JSONResponse({"draft_cards": cards, "count": len(cards)})

    @app.get("/admin/logs/{agent_name}")
    async def admin_logs(agent_name: str):
        """View interaction logs for an agent."""
        logs = deployment.logger.read_log(agent_name)
        return JSONResponse({"agent": agent_name, "interactions": logs, "count": len(logs)})

    return app


def _format_uptime(seconds: float) -> str:
    """Format seconds into human-readable uptime."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
