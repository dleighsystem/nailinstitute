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
