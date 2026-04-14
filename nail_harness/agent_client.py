"""
NAIL Harness — Agent Client
==============================

Equivalent to Anthropic's ClaudeSDKClient + ClaudeAgentOptions.
Orchestrates a tool-using agent loop against local Ollama models
with hook support, memory integration, and quantum detection.

Design philosophy (from Anthropic's "Building Effective Agents"):
  - Keep the agent loop simple: query → tool_use → observation → repeat
  - Tools should be extremely well-documented (descriptions are part of the prompt)
  - Let the model drive — provide tools, not rigid workflows
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .util import ollama_call, ollama_call_full, ollama_chat, extract_json, LLMResponse


# ═══════════════════════════════════════════════════════════════════════════
# Tool definition
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Tool:
    """
    A tool the agent can invoke.

    Mirrors Anthropic's tool definition schema used in Claude API.
    """
    name: str
    description: str
    parameters: dict = field(default_factory=dict)   # JSON Schema
    handler: Optional[Callable] = None               # Python callable

    def to_prompt_description(self) -> str:
        """Format tool for inclusion in system prompt."""
        params_desc = ""
        if self.parameters.get("properties"):
            params_desc = "\n  Parameters:\n"
            for name, spec in self.parameters["properties"].items():
                required = name in self.parameters.get("required", [])
                req_tag = " (REQUIRED)" if required else ""
                params_desc += f"    - {name}{req_tag}: {spec.get('description', spec.get('type', 'any'))}\n"
        return f"**{self.name}**: {self.description}{params_desc}"


# ═══════════════════════════════════════════════════════════════════════════
# Agent Options (equivalent to ClaudeAgentOptions)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class AgentOptions:
    """
    Configuration for a NAIL agent.

    Maps to Anthropic's ClaudeAgentOptions:
      - model           → Ollama model name
      - system_prompt    → Agent personality + context
      - tools           → Available tools
      - context_path    → Path to NAIL_CONTEXT.md (persistent context)
      - max_turns       → Safety cap on agentic loop iterations
      - hooks           → Pre/post tool-use callbacks
      - memory_path     → Active Forgetting memory directory
    """
    model: str = "nemotron:70b"
    system_prompt: str = ""
    tools: list[Tool] = field(default_factory=list)
    context_path: Optional[str] = None       # Path to NAIL_CONTEXT.md
    agent_prompt_path: Optional[str] = None  # Path to .nail/agents/*.md
    max_turns: int = 20
    temperature: float = 0.1
    max_tokens: int = 4096

    # Hook callbacks
    pre_tool_use: Optional[Callable] = None   # (tool_name, tool_input) -> bool (allow?)
    post_tool_use: Optional[Callable] = None  # (tool_name, tool_input, tool_output) -> None

    # Memory
    memory_path: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# Agent turn record
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class AgentTurn:
    """One turn in the agent loop."""
    turn_id: str = ""
    role: str = ""           # "user", "assistant", "tool_result"
    content: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_output: str = ""
    tokens: int = 0
    elapsed_s: float = 0.0
    timestamp: str = ""
    blocked: bool = False    # True if pre_tool_use hook rejected


# ═══════════════════════════════════════════════════════════════════════════
# NailAgentClient (equivalent to ClaudeSDKClient)
# ═══════════════════════════════════════════════════════════════════════════

class NailAgentClient:
    """
    Autonomous agent client that runs a tool-using loop against Ollama.

    Equivalent to Anthropic's ClaudeSDKClient.  The agent loop:
      1. Build system prompt (context + tools + agent definition)
      2. Send conversation to LLM
      3. If LLM requests a tool → execute (with hooks) → feed result back
      4. If LLM gives final answer → return

    Usage:
        client = NailAgentClient(options)
        result = client.run("Analyze this agent telemetry for anomalies")
        print(result.content)
    """

    def __init__(self, options: AgentOptions):
        self.options = options
        self.history: list[dict] = []
        self.turns: list[AgentTurn] = []
        self.session_id = str(uuid.uuid4())[:8]
        self.total_tokens = 0
        self.total_elapsed = 0.0

        # Load persistent context (NAIL_CONTEXT.md)
        self._context = ""
        if options.context_path:
            ctx_path = Path(options.context_path)
            if ctx_path.exists():
                self._context = ctx_path.read_text()

        # Load agent definition (e.g., .nail/agents/red_team.md)
        self._agent_def = ""
        if options.agent_prompt_path:
            agent_path = Path(options.agent_prompt_path)
            if agent_path.exists():
                self._agent_def = agent_path.read_text()

        # Build tool registry
        self._tool_registry: dict[str, Tool] = {t.name: t for t in options.tools}

    def _build_system_prompt(self) -> str:
        """Assemble full system prompt from components."""
        parts = []

        # Agent definition (from .nail/agents/*.md)
        if self._agent_def:
            parts.append(self._agent_def)

        # User-provided system prompt
        if self.options.system_prompt:
            parts.append(self.options.system_prompt)

        # Persistent context (NAIL_CONTEXT.md)
        if self._context:
            parts.append(f"\n<nail_context>\n{self._context}\n</nail_context>")

        # Tool descriptions
        if self._tool_registry:
            tool_section = "\n<available_tools>\n"
            tool_section += "You have the following tools available. To use a tool, "
            tool_section += "respond with a JSON object inside <tool_use> tags:\n"
            tool_section += '<tool_use>{"tool": "tool_name", "input": {...}}</tool_use>\n\n'
            for tool in self._tool_registry.values():
                tool_section += tool.to_prompt_description() + "\n"
            tool_section += "\nWhen you have a final answer, respond normally without tool_use tags.\n"
            tool_section += "</available_tools>\n"
            parts.append(tool_section)

        return "\n\n".join(parts)

    def _parse_tool_calls(self, text: str) -> list[dict]:
        """Extract tool calls from LLM response."""
        import re
        calls = []
        for match in re.finditer(r"<tool_use>(.*?)</tool_use>", text, re.DOTALL):
            try:
                parsed = json.loads(match.group(1).strip())
                if isinstance(parsed, dict) and "tool" in parsed:
                    calls.append(parsed)
            except json.JSONDecodeError:
                continue
        return calls

    def _execute_tool(self, tool_name: str, tool_input: dict) -> tuple[str, bool]:
        """
        Execute a tool with pre/post hooks.

        Returns:
            (result_text, was_blocked)
        """
        # Pre-tool hook (safety gate)
        if self.options.pre_tool_use:
            allowed = self.options.pre_tool_use(tool_name, tool_input)
            if not allowed:
                return (
                    f"⛔ Tool '{tool_name}' blocked by safety hook. "
                    "The action was flagged as potentially unsafe.",
                    True,
                )

        # Execute
        tool = self._tool_registry.get(tool_name)
        if not tool:
            return f"❌ Unknown tool: '{tool_name}'. Available: {list(self._tool_registry.keys())}", False

        if not tool.handler:
            return f"❌ Tool '{tool_name}' has no handler registered.", False

        try:
            result = tool.handler(**tool_input)
            result_text = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        except Exception as e:
            result_text = f"❌ Tool error: {type(e).__name__}: {e}"

        # Post-tool hook (audit logging)
        if self.options.post_tool_use:
            try:
                self.options.post_tool_use(tool_name, tool_input, result_text)
            except Exception:
                pass  # Hooks should never break the agent loop

        return result_text, False

    def run(self, prompt: str, verbose: bool = True) -> AgentTurn:
        """
        Run the full agent loop until the model gives a final answer
        or the turn limit is reached.

        Args:
            prompt:  The user's request
            verbose: If True, print activity to console

        Returns:
            The final AgentTurn with the model's answer
        """
        system_prompt = self._build_system_prompt()
        self.history.append({"role": "user", "content": prompt})

        if verbose:
            print(f"🤖 [{self.session_id}] Agent started (model={self.options.model})")

        for turn_num in range(self.options.max_turns):
            # Call LLM
            resp = ollama_chat(
                messages=self.history,
                system_prompt=system_prompt,
                model=self.options.model,
                temperature=self.options.temperature,
                max_tokens=self.options.max_tokens,
            )

            self.total_tokens += resp.total_tokens
            self.total_elapsed += resp.elapsed_seconds

            content = resp.content

            # Check for tool calls
            tool_calls = self._parse_tool_calls(content)

            if not tool_calls:
                # Final answer — no tools requested
                turn = AgentTurn(
                    turn_id=f"{self.session_id}-{turn_num}",
                    role="assistant",
                    content=content,
                    tokens=resp.total_tokens,
                    elapsed_s=resp.elapsed_seconds,
                    timestamp=datetime.now().isoformat(),
                )
                self.turns.append(turn)
                self.history.append({"role": "assistant", "content": content})

                if verbose:
                    print(f"✅ [{self.session_id}] Final answer (turn {turn_num+1}, "
                          f"{self.total_tokens} tokens, {self.total_elapsed:.1f}s)")

                return turn

            # Execute tool calls
            self.history.append({"role": "assistant", "content": content})

            for call in tool_calls:
                tool_name = call.get("tool", "")
                tool_input = call.get("input", {})

                if verbose:
                    print(f"  🔧 [{self.session_id}] Tool: {tool_name}({list(tool_input.keys())})")

                result_text, blocked = self._execute_tool(tool_name, tool_input)

                turn = AgentTurn(
                    turn_id=f"{self.session_id}-{turn_num}-{tool_name}",
                    role="tool_result",
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=result_text,
                    tokens=resp.total_tokens,
                    elapsed_s=resp.elapsed_seconds,
                    timestamp=datetime.now().isoformat(),
                    blocked=blocked,
                )
                self.turns.append(turn)

                # Feed result back to the conversation
                self.history.append({
                    "role": "user",
                    "content": f"<tool_result name=\"{tool_name}\">\n{result_text}\n</tool_result>",
                })

        # Turn limit reached
        if verbose:
            print(f"⚠️  [{self.session_id}] Turn limit ({self.options.max_turns}) reached")

        return AgentTurn(
            turn_id=f"{self.session_id}-timeout",
            role="assistant",
            content="[Turn limit reached — agent did not converge on a final answer]",
            tokens=self.total_tokens,
            elapsed_s=self.total_elapsed,
            timestamp=datetime.now().isoformat(),
        )

    def get_stats(self) -> dict:
        """Return session statistics."""
        return {
            "session_id": self.session_id,
            "model": self.options.model,
            "total_turns": len(self.turns),
            "total_tokens": self.total_tokens,
            "total_elapsed_s": round(self.total_elapsed, 1),
            "tools_used": [t.tool_name for t in self.turns if t.tool_name],
            "tools_blocked": sum(1 for t in self.turns if t.blocked),
        }

    def reset(self):
        """Clear conversation state for a new session."""
        self.history = []
        self.turns = []
        self.session_id = str(uuid.uuid4())[:8]
        self.total_tokens = 0
        self.total_elapsed = 0.0
