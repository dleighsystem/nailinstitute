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

__all__ = ["Pipeline", "PipelineEvent"]
