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
    - circuit_breaker:    TTL enforcer, token/cost breaker, state rollback
    - firewall:           Egress policy, semantic firewall, action gate
    - guard_client:       NAIL Guard model client (dual-agent supervisor)
    - remediation:        Auto-generated remediation playbooks from diagnostics
    - config:             YAML-driven harness configuration loader
    - mcp_server:         MCP server exposing quantum detection tools
    - evaluator_optimizer: Red/Blue team loop with VQC scoring
"""

__version__ = "0.2.0"

from .util import ollama_call, extract_json, extract_xml
from .agent_client import NailAgentClient, AgentOptions
from .memory import MemoryManager
from .circuit_breaker import TTLEnforcer, TokenCircuitBreaker, StateRollback
from .firewall import EgressPolicy, SemanticFirewall, ActionGate
from .guard_client import GuardClient, GuardVerdict
from .hooks import SafetyGate, AuditLogger, create_hooks
from .remediation import RemediationEngine, DiagnosticResult, RemediationReport
from .config import HarnessConfig

__all__ = [
    # Core agent
    "ollama_call",
    "extract_json",
    "extract_xml",
    "NailAgentClient",
    "AgentOptions",
    "MemoryManager",
    # Circuit breakers (Tier 2)
    "TTLEnforcer",
    "TokenCircuitBreaker",
    "StateRollback",
    # Firewall & egress (Tier 2)
    "EgressPolicy",
    "SemanticFirewall",
    "ActionGate",
    # Guard model client (Tier 2)
    "GuardClient",
    "GuardVerdict",
    # Safety hooks
    "SafetyGate",
    "AuditLogger",
    "create_hooks",
    # Remediation (Tier 1)
    "RemediationEngine",
    "DiagnosticResult",
    "RemediationReport",
    # Configuration
    "HarnessConfig",
    "__version__",
]
