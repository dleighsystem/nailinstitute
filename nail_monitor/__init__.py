"""
nail-monitor: Real-Time Pathology Detection for LLM Agent Systems
================================================================

A production-grade monitoring toolkit that detects behavioral pathologies
and infrastructure vulnerabilities in LLM multi-agent systems, based on
the NAIL Institute research findings.

DETECTORS:
  - InbreedingDetector: Monitors prompt/output convergence over time
  - ConsensusParalysisDetector: Detects deadlocked multi-agent consensus
  - BlameDetector: Identifies blame cascade patterns in agent communications
  - EngagementDecayDetector: Tracks declining output quality/effort
  - SchemaCoercionDetector: Catches Pydantic-style silent data loss
  - GoodhartDetector: Monitors for metric gaming / score inflation

USAGE:
  from nail_monitor import NailMonitor

  monitor = NailMonitor()
  monitor.enable_all()

  # In your agent loop:
  monitor.observe(agent_name="writer", output=text, metadata={...})
  alerts = monitor.check()
  
  for alert in alerts:
      print(f"⚠️  {alert.severity}: {alert.detector} — {alert.message}")

INSTALL:
  pip install -e nail_monitor/
"""

from __future__ import annotations

import importlib
import sys

from .nail_monitor import *  # noqa: F401,F403
from .nail_monitor import __version__ as __version__

_SUBMODULES = (
    "breaker",
    "detectors",
    "detectors_v2",
    "detectors_v3",
    "detectors_v4",
    "detectors_v5",
    "detectors_v6",
    "detectors_v7",
    "detectors_v8",
    "detectors_v9",
    "flight_recorder",
    "monitor",
    "registry",
    "types",
)

for _name in _SUBMODULES:
    sys.modules.setdefault(
        f"{__name__}.{_name}",
        importlib.import_module(f"{__name__}.nail_monitor.{_name}"),
    )
