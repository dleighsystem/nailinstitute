"""
NAIL Integration — End-to-end cross-package wiring.

Connects:
  AVE (vulnerability catalogue) →
  Canary (honeypot fleet) →
  Arena (Red/Blue evolution) →
  CTF (crowdsourced red-teaming) →
  ThreatFeed (live threat intelligence pipeline)

into a unified Discover → Publish → Protect pipeline.
"""

__version__ = "1.0.0"

from .pipeline import Pipeline, PipelineEvent
from .agent_connector import AgentConnector, Provider, LLMRequest, LLMResponse
from .guardrails import GuardrailChain, GuardResult, ChainResult
from .pii_detector import PIIDetector, DetectionResult, LureLeakageResult
from .data_flywheel import DataFlywheel, FlywheelCycle
from .openshell_sandbox import OpenShellManager, SandboxPolicy, Sandbox

__all__ = [
    "Pipeline",
    "PipelineEvent",
    "AgentConnector",
    "Provider",
    "LLMRequest",
    "LLMResponse",
    "GuardrailChain",
    "GuardResult",
    "ChainResult",
    "PIIDetector",
    "DetectionResult",
    "LureLeakageResult",
    "DataFlywheel",
    "FlywheelCycle",
    "OpenShellManager",
    "SandboxPolicy",
    "Sandbox",
]
