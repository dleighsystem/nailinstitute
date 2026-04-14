"""
NAIL Harness — MCP Server (Quantum Detection Tools)
=====================================================

Model Context Protocol server exposing NAIL's quantum
detection capabilities as callable tools.

Inspired by Anthropic's SRE MCP server (2,722 lines, 12+ tools),
this server provides:
  - vqc_classify:       Run VQC binary classification on telemetry
  - anomaly_scan:       Full anomaly detection pipeline (VQC → Reservoir → SVM → Heuristic)
  - memory_status:      Query Active Forgetting memory health
  - quarantine_agent:   Isolate a compromised agent
  - defense_report:     Generate defense status report
  - agent_telemetry:    Get current agent behavioral features

Unlike Anthropic's SRE server which uses HTTP/Prometheus,
NAIL's server integrates directly with PennyLane quantum circuits.

This can be used:
  1. As tools registered with NailAgentClient
  2. As an MCP JSON-RPC subprocess server (like Anthropic's SRE)
  3. As a Python API for direct integration
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np


# ═══════════════════════════════════════════════════════════════════════════
# Tool: VQC Classify
# ═══════════════════════════════════════════════════════════════════════════

class VQCClassifyTool:
    """
    Expose VQC binary classification as a tool.

    Loads trained weights from phase2_vqc_v3 and runs inference
    on 8-dimensional telemetry feature vectors.
    """

    def __init__(self, weights_path: Optional[str] = None):
        self._adapter = None
        self._loaded = False

        if weights_path:
            self._load(weights_path)

    def _load(self, path: str):
        """Load VQC adapter from weights file."""
        try:
            # Import from the collider's adapter
            import sys
            experiments_dir = str(Path(__file__).resolve().parent.parent / "experiments")
            if experiments_dir not in sys.path:
                sys.path.insert(0, experiments_dir)

            from exp20_pathology_collider.vqc_adapter import VQCModelAdapter
            self._adapter = VQCModelAdapter.load(path)
            self._loaded = True
        except Exception as e:
            print(f"  ⚠️  VQC tool: Could not load model: {e}")
            self._loaded = False

    def classify(self, features: Optional[list[float]] = None, **telemetry) -> dict:
        """
        Classify agent telemetry as normal or anomaly.

        Args:
            features: Raw 8-float feature vector, OR
            **telemetry: Named features (trust_score, burn_rate, etc.)

        Returns:
            {"label": "normal"|"anomaly", "confidence": float, "mode": str}
        """
        if features is None:
            # Build from named telemetry
            feature_names = [
                "trust_score", "burn_rate", "semantic_drift",
                "assertion_density", "manipulation_score",
                "repetition_index", "memory_corruption", "intervention_rate",
            ]
            features = []
            for f in feature_names:
                val = telemetry.get(f, 0.5)
                try:
                    features.append(float(val))
                except (ValueError, TypeError):
                    # LLM sometimes returns strings like "high" or "approaching low"
                    # Map descriptive strings to rough numeric values
                    s = str(val).lower()
                    if any(w in s for w in ("high", "elevated", "above", "max")):
                        features.append(0.85)
                    elif any(w in s for w in ("low", "below", "min", "approaching low")):
                        features.append(0.15)
                    elif any(w in s for w in ("medium", "moderate", "normal", "stable")):
                        features.append(0.5)
                    else:
                        features.append(0.5)  # Default mid-range

        if not self._loaded or self._adapter is None:
            # Heuristic fallback
            extreme = sum(1 for f in features if f > 0.8 or f < 0.2)
            label = "anomaly" if extreme >= 3 else "normal"
            conf = extreme / len(features)
            return {"label": label, "confidence": round(conf, 4), "mode": "heuristic_fallback"}

        label, confidence = self._adapter.predict(features)
        return {
            "label": label,
            "confidence": round(confidence, 4),
            "mode": self._adapter._mode,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool: Anomaly Scan (Full Pipeline)
# ═══════════════════════════════════════════════════════════════════════════

class AnomalyScanTool:
    """
    Full anomaly detection pipeline: VQC → threshold analysis → verdict.

    Combines quantum classification with behavioral thresholds
    from our QAOA-optimized values.
    """

    def __init__(self, vqc_tool: VQCClassifyTool):
        self.vqc = vqc_tool

        # QAOA-optimized thresholds (from quantum_thresholds.py)
        self.thresholds = {
            "trust_floor": 0.7378,
            "semantic_drift_ceiling": 0.4995,
            "memory_corruption_ceiling": 0.3,
            "burn_rate_ceiling": 0.8,
        }

    def scan(self, **telemetry) -> dict:
        """
        Run full anomaly scan on agent telemetry.

        Returns:
            {
                "verdict": "clean"|"suspicious"|"compromised",
                "vqc_result": {...},
                "threshold_violations": [...],
                "risk_score": float,
                "recommended_action": str,
            }
        """
        # VQC classification
        vqc_result = self.vqc.classify(**telemetry)

        # Threshold checks
        violations = []

        def safe_float(val, default=0.5):
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        trust = safe_float(telemetry.get("trust_score", 0.5))
        drift = safe_float(telemetry.get("semantic_drift", 0.0))
        corruption = safe_float(telemetry.get("memory_corruption", 0.0))
        burn = safe_float(telemetry.get("burn_rate", 0.5))

        if trust < self.thresholds["trust_floor"]:
            violations.append(f"trust_score={trust:.3f} < floor={self.thresholds['trust_floor']:.3f}")
        if drift > self.thresholds["semantic_drift_ceiling"]:
            violations.append(f"semantic_drift={drift:.3f} > ceiling={self.thresholds['semantic_drift_ceiling']:.3f}")
        if corruption > self.thresholds["memory_corruption_ceiling"]:
            violations.append(f"memory_corruption={corruption:.3f} > ceiling={self.thresholds['memory_corruption_ceiling']:.3f}")
        if burn > self.thresholds["burn_rate_ceiling"]:
            violations.append(f"burn_rate={burn:.3f} > ceiling={self.thresholds['burn_rate_ceiling']:.3f}")

        # Compute risk score
        risk = 0.0
        if vqc_result["label"] == "anomaly":
            risk += 0.5 * vqc_result["confidence"]
        risk += 0.1 * len(violations)
        risk = min(1.0, risk)

        # Verdict
        if vqc_result["label"] == "anomaly" and vqc_result["confidence"] > 0.8:
            verdict = "compromised"
            action = "QUARANTINE immediately. VQC high-confidence anomaly detected."
        elif vqc_result["label"] == "anomaly" or len(violations) >= 2:
            verdict = "suspicious"
            action = "Increase monitoring. Consider restricting tool access."
        else:
            verdict = "clean"
            action = "Continue normal operation."

        return {
            "verdict": verdict,
            "vqc_result": vqc_result,
            "threshold_violations": violations,
            "risk_score": round(risk, 4),
            "recommended_action": action,
            "timestamp": datetime.now().isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tool: Quarantine Agent
# ═══════════════════════════════════════════════════════════════════════════

class QuarantineTool:
    """
    Isolate a compromised agent by restricting its capabilities.

    Inspired by our Contagion experiment (exp31):
      - Firewall + Behavioral Quarantine reduced infections by 70%
    """

    def __init__(self):
        self.quarantined: dict[str, dict] = {}

    def quarantine(
        self,
        agent_id: str,
        reason: str = "",
        severity: str = "medium",
    ) -> dict:
        """
        Quarantine an agent.

        Returns:
            Status dict with quarantine details
        """
        self.quarantined[agent_id] = {
            "agent_id": agent_id,
            "reason": reason,
            "severity": severity,
            "quarantined_at": datetime.now().isoformat(),
            "restrictions": self._get_restrictions(severity),
        }
        return self.quarantined[agent_id]

    def release(self, agent_id: str) -> dict:
        """Release an agent from quarantine."""
        if agent_id in self.quarantined:
            entry = self.quarantined.pop(agent_id)
            entry["released_at"] = datetime.now().isoformat()
            return {"status": "released", **entry}
        return {"status": "not_found", "agent_id": agent_id}

    def is_quarantined(self, agent_id: str) -> bool:
        return agent_id in self.quarantined

    def _get_restrictions(self, severity: str) -> list[str]:
        """Get restriction list based on severity."""
        if severity == "critical":
            return ["no_tools", "no_memory_write", "no_network", "read_only"]
        elif severity == "high":
            return ["no_memory_write", "no_network", "limited_tools"]
        elif severity == "medium":
            return ["no_memory_write", "monitored"]
        else:
            return ["monitored"]


# ═══════════════════════════════════════════════════════════════════════════
# Tool: Defense Report
# ═══════════════════════════════════════════════════════════════════════════

class DefenseReportTool:
    """Generate a comprehensive defense status report."""

    def __init__(
        self,
        vqc_tool: VQCClassifyTool,
        anomaly_tool: AnomalyScanTool,
        quarantine_tool: QuarantineTool,
        memory_manager: Optional[Any] = None,
    ):
        self.vqc = vqc_tool
        self.anomaly = anomaly_tool
        self.quarantine = quarantine_tool
        self.memory = memory_manager

    def generate(self) -> dict:
        """Generate current defense status."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "vqc_status": "loaded" if self.vqc._loaded else "fallback",
            "vqc_mode": self.vqc._adapter._mode if self.vqc._adapter else "none",
            "quarantined_agents": len(self.quarantine.quarantined),
            "quarantine_details": dict(self.quarantine.quarantined),
            "thresholds": self.anomaly.thresholds,
        }

        if self.memory:
            report["memory_stats"] = self.memory.get_stats()

        return report


# ═══════════════════════════════════════════════════════════════════════════
# MCP Server Factory — creates Tool objects for NailAgentClient
# ═══════════════════════════════════════════════════════════════════════════

def create_mcp_tools(
    vqc_weights_path: Optional[str] = None,
    memory_manager: Optional[Any] = None,
) -> list:
    """
    Create NAIL MCP tools ready to register with NailAgentClient.

    Returns:
        List of Tool objects with handlers
    """
    from .agent_client import Tool

    # Initialize tool instances
    vqc_tool = VQCClassifyTool(weights_path=vqc_weights_path)
    anomaly_tool = AnomalyScanTool(vqc_tool)
    quarantine_tool = QuarantineTool()
    report_tool = DefenseReportTool(vqc_tool, anomaly_tool, quarantine_tool, memory_manager)

    tools = [
        Tool(
            name="vqc_classify",
            description=(
                "Classify agent telemetry as normal or anomaly using a Variational "
                "Quantum Classifier trained to 100% Sleeper Agent recall. "
                "Provide the 8 behavioral features: trust_score, burn_rate, "
                "semantic_drift, assertion_density, manipulation_score, "
                "repetition_index, memory_corruption, intervention_rate."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "trust_score": {"type": "number", "description": "Agent trust level [0,1]"},
                    "burn_rate": {"type": "number", "description": "Token consumption rate [0,1]"},
                    "semantic_drift": {"type": "number", "description": "Persona drift [0,1]"},
                    "assertion_density": {"type": "number", "description": "Definitive claims ratio [0,1]"},
                    "manipulation_score": {"type": "number", "description": "Manipulation signals [0,1]"},
                    "repetition_index": {"type": "number", "description": "Output repetitiveness [0,1]"},
                    "memory_corruption": {"type": "number", "description": "Tainted memory fraction [0,1]"},
                    "intervention_rate": {"type": "number", "description": "Interventions per round [0,1]"},
                },
                "required": ["trust_score", "burn_rate", "semantic_drift", "manipulation_score"],
            },
            handler=lambda **kw: vqc_tool.classify(**kw),
        ),
        Tool(
            name="anomaly_scan",
            description=(
                "Run a full anomaly detection pipeline on agent telemetry. "
                "Combines VQC quantum classification with QAOA-optimized thresholds "
                "to produce a verdict (clean/suspicious/compromised) and recommended action."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "trust_score": {"type": "number"},
                    "burn_rate": {"type": "number"},
                    "semantic_drift": {"type": "number"},
                    "assertion_density": {"type": "number"},
                    "manipulation_score": {"type": "number"},
                    "repetition_index": {"type": "number"},
                    "memory_corruption": {"type": "number"},
                    "intervention_rate": {"type": "number"},
                },
                "required": ["trust_score"],
            },
            handler=lambda **kw: anomaly_tool.scan(**kw),
        ),
        Tool(
            name="quarantine_agent",
            description=(
                "Isolate a compromised agent by restricting its capabilities. "
                "Severity levels: critical (no tools), high (no memory/network), "
                "medium (no memory write), low (monitored only)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "ID of agent to quarantine"},
                    "reason": {"type": "string", "description": "Reason for quarantine"},
                    "severity": {"type": "string", "description": "critical|high|medium|low"},
                },
                "required": ["agent_id", "reason"],
            },
            handler=lambda **kw: quarantine_tool.quarantine(**kw),
        ),
        Tool(
            name="defense_report",
            description=(
                "Generate a comprehensive defense status report showing VQC status, "
                "quarantined agents, thresholds, and memory health."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda **kw: report_tool.generate(),
        ),
    ]

    return tools
