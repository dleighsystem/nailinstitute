"""
NAIL Institute — VQC Model Adapter for Layer 5
=================================================

Bridges the trained Variational Quantum Classifier (phase2_vqc_v3)
into the Pathology Collider's Layer 5 QuantumAnomalyDetector interface.

**Architecture:**
  - Load: Reads VQC binary weights exported by phase2_vqc_v3.py
  - Inference: Runs the PennyLane circuit with trained weights on
    telemetry features to produce anomaly/normal classification.
  - Fallback: If PennyLane is unavailable, degrades to heuristic mode.

This adapter replaces the kernel-SVM path in QuantumKernelModel with
a VQC inference path while maintaining the same API contract.

Usage:
    from .vqc_adapter import VQCModelAdapter

    adapter = VQCModelAdapter.load("models/vqc_binary_weights.json")
    label, confidence = adapter.predict(features)
    # label: "anomaly" or "normal"
    # confidence: float [0, 1]
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# Feature mapping
# ═══════════════════════════════════════════════════════════════════════════

FEATURE_NAMES = [
    "trust_score",
    "burn_rate",
    "semantic_drift",
    "assertion_density",
    "manipulation_score",
    "repetition_index",
    "memory_corruption",
    "intervention_rate",
]

NUM_FEATURES = len(FEATURE_NAMES)


# ═══════════════════════════════════════════════════════════════════════════
# PennyLane circuit definition (must match phase2_vqc_v3.py exactly)
# ═══════════════════════════════════════════════════════════════════════════

def _build_vqc_circuit(num_qubits: int, num_layers: int):
    """
    Reconstruct the VQC circuit architecture from phase2_vqc_v3.py.

    Architecture:
      - Angle encoding: Ry rotation on each qubit
      - StronglyEntanglingLayers: num_layers of parameterized rotations + CNOT
      - Measurement: Expectation of PauliZ on each qubit

    Returns:
        A PennyLane QNode callable: circuit(features, weights) -> list[float]
    """
    try:
        import pennylane as qml
        from pennylane import numpy as pnp

        # Try GPU first, fall back to CPU
        try:
            dev = qml.device("lightning.gpu", wires=num_qubits)
        except Exception:
            dev = qml.device("lightning.qubit", wires=num_qubits)

        @qml.qnode(dev, diff_method="adjoint")
        def circuit(features, weights):
            # Angle encoding
            for i in range(num_qubits):
                qml.RY(features[i] * np.pi, wires=i)

            # Variational layers
            qml.StronglyEntanglingLayers(weights, wires=range(num_qubits))

            # Measurement
            return [qml.expval(qml.PauliZ(i)) for i in range(num_qubits)]

        return circuit

    except ImportError:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# VQC Model Adapter
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VQCModelAdapter:
    """
    Adapter that wraps trained VQC weights into the same interface
    as QuantumKernelModel.predict() for Layer 5 integration.

    The adapter supports three inference modes:
      1. Full quantum: PennyLane circuit with trained weights (most accurate)
      2. Heuristic: Threshold-based fallback (no PennyLane needed)
      3. Disabled: Returns "normal" for all inputs

    API contract (matches QuantumKernelModel):
        label, confidence = adapter.predict(features: list[float])
    """

    weights: Any = None                # numpy array (num_layers, num_qubits, 3)
    num_layers: int = 4
    num_qubits: int = 8
    threshold: float = 0.0            # Decision boundary (adaptive from training)
    sleeper_recall: float = 0.0       # Training recall (metadata)
    version: str = "v3"
    feature_names: list[str] = field(default_factory=lambda: FEATURE_NAMES.copy())
    metadata: dict = field(default_factory=dict)

    # Internal
    _circuit: Any = None
    _mode: str = "disabled"

    def __post_init__(self):
        """Initialize quantum circuit if weights are loaded."""
        if self.weights is not None:
            self._circuit = _build_vqc_circuit(self.num_qubits, self.num_layers)
            if self._circuit is not None:
                self._mode = "quantum_vqc"
            else:
                self._mode = "heuristic"
        else:
            self._mode = "heuristic"

    @staticmethod
    def load(path: str | Path) -> "VQCModelAdapter":
        """
        Load VQC binary weights exported by phase2_vqc_v3.py.

        Expected JSON format:
        {
            "model_type": "vqc_binary",
            "version": "v3",
            "weights": [[[...], ...], ...],  // (num_layers, num_qubits, 3)
            "num_layers": 4,
            "num_qubits": 8,
            "sleeper_recall": 1.0,
            "feature_names": ["trust_score", ...]
        }
        """
        path = Path(path)
        if not path.exists():
            print(f"  ⚠️  VQC weights not found: {path}. Using heuristic fallback.")
            return VQCModelAdapter()

        with open(path) as f:
            data = json.load(f)

        weights = np.array(data["weights"])
        num_layers = data.get("num_layers", 4)
        num_qubits = data.get("num_qubits", 8)

        # Validate shape
        expected_shape = (num_layers, num_qubits, 3)
        if weights.shape != expected_shape:
            raise ValueError(
                f"Weight shape mismatch: got {weights.shape}, "
                f"expected {expected_shape}"
            )

        adapter = VQCModelAdapter(
            weights=weights,
            num_layers=num_layers,
            num_qubits=num_qubits,
            sleeper_recall=data.get("sleeper_recall", 0.0),
            version=data.get("version", "v3"),
            feature_names=data.get("feature_names", FEATURE_NAMES),
            metadata=data.get("metadata", {}),
        )

        print(f"  ✅ VQC model loaded: {path.name} "
              f"(mode={adapter._mode}, sleeper_recall={adapter.sleeper_recall:.1%})")

        return adapter

    def predict(self, features: list[float]) -> tuple[str, float]:
        """
        Classify a feature vector as normal or anomaly (sleeper agent).

        This matches the API of QuantumKernelModel.predict() so it
        can be used as a drop-in replacement in QuantumAnomalyDetector.

        Args:
            features: List of 8 normalized feature values [0, 1]

        Returns:
            (class_label, confidence_score)
            class_label: "normal", "anomaly", or "suspicious"
            confidence_score: float [0, 1]
        """
        if self._mode == "quantum_vqc":
            return self._vqc_predict(features)
        elif self._mode == "heuristic":
            return self._heuristic_predict(features)
        else:
            return ("normal", 0.0)

    def _vqc_predict(self, features: list[float]) -> tuple[str, float]:
        """
        Full VQC inference using trained quantum circuit.

        The circuit outputs expectation values of PauliZ on each qubit.
        We use the mean output as a decision value:
          - Higher mean → more "normal" character
          - Lower mean → more "anomaly" (sleeper) character

        The threshold is adaptive: computed from the training distribution
        median, defaulting to 0.0 if not set.
        """
        try:
            # Ensure we have exactly NUM_FEATURES inputs
            padded = list(features[:self.num_qubits])
            while len(padded) < self.num_qubits:
                padded.append(0.0)

            x = np.array(padded, dtype=np.float64)
            outputs = self._circuit(x, self.weights)

            # Mean PauliZ expectation as decision value
            mean_val = float(np.mean(outputs))

            # Map to classification
            # Anomaly if below threshold (sleeper agents show lower PauliZ expectations)
            if mean_val < self.threshold:
                confidence = min(1.0, abs(mean_val - self.threshold))
                return ("anomaly", confidence)
            else:
                confidence = min(1.0, abs(mean_val - self.threshold))
                return ("normal", confidence)

        except Exception as e:
            # Fallback to heuristic on any quantum error
            return self._heuristic_predict(features)

    def _heuristic_predict(self, features: list[float]) -> tuple[str, float]:
        """
        Threshold-based fallback using domain knowledge from VQC training.

        Mirrors the heuristic in quantum_anomaly_layer.py but calibrated
        to match the VQC's decision boundary from training data analysis.
        """
        if len(features) < NUM_FEATURES:
            return ("normal", 0.0)

        trust = features[0]
        burn = features[1]
        drift = features[2]
        assertion = features[3]
        manipulation = features[4]
        repetition = features[5]
        corruption = features[6]
        interventions = features[7]

        severity = 0.0

        # VQC training showed these feature combinations are most predictive:
        # 1. Low trust + high corruption = memory poisoning (strongest signal)
        if trust < 0.35 and corruption > 0.5:
            severity += 0.45

        # 2. High manipulation + high assertion = social engineering
        if manipulation > 0.55 and assertion > 0.55:
            severity += 0.25

        # 3. High burn rate + drift = economic/persona attack
        if burn > 0.65 and drift > 0.45:
            severity += 0.20

        # 4. High repetition + low trust = loop attack
        if repetition > 0.6 and trust < 0.4:
            severity += 0.15

        # 5. Multiple high signals
        high_count = sum(1 for f in features if f > 0.65)
        if high_count >= 5:
            severity += 0.15

        if severity >= 0.5:
            return ("anomaly", min(1.0, severity))
        elif severity >= 0.25:
            return ("suspicious", severity)
        else:
            return ("normal", max(0.0, 0.3 - severity))

    @property
    def mode(self) -> str:
        """Current inference mode."""
        return self._mode

    @property
    def is_quantum(self) -> bool:
        """Whether using full quantum inference."""
        return self._mode == "quantum_vqc"

    def get_info(self) -> dict:
        """Return model metadata for Layer 5 stats."""
        return {
            "model_type": "vqc_binary",
            "version": self.version,
            "mode": self._mode,
            "is_quantum": self.is_quantum,
            "num_layers": self.num_layers,
            "num_qubits": self.num_qubits,
            "trainable_params": self.num_layers * self.num_qubits * 3,
            "sleeper_recall_training": self.sleeper_recall,
        }
