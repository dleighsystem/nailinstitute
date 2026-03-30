"""
NAIL Harness — Autonomous Agent Defense Framework
====================================================

Composable agent architecture for the NAIL Institute,
inspired by Anthropic's harness patterns and powered
by local Ollama models + quantum VQC detection.

Components:
    - util:               Ollama wrapper (equivalent to Anthropic's util.py)
    - agent_client:       NailAgentClient (query loop with tool routing)
    - memory:             Active Forgetting memory manager
    - hooks:              Pre/Post tool-use audit & safety hooks
    - mcp_server:         MCP server exposing quantum detection tools
    - evaluator_optimizer: Red/Blue team loop with VQC scoring
"""

__version__ = "0.1.0"

from .util import ollama_call, extract_json, extract_xml
from .agent_client import NailAgentClient, AgentOptions
from .memory import MemoryManager

__all__ = [
    "ollama_call",
    "extract_json",
    "extract_xml",
    "NailAgentClient",
    "AgentOptions",
    "MemoryManager",
    "__version__",
]
