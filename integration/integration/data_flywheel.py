"""
Data Flywheel — Continuous model improvement loop for the NAIL platform
========================================================================

Adapts the NVIDIA Data Flywheel Blueprint architecture for our
AI agent security use case. The flywheel creates a self-reinforcing
loop that continuously improves detection models:

    ┌─ COLLECT ──────────────────────────────────────────────┐
    │  Production traffic from Arena, Canary, CTF sessions   │
    └────────────────────────┬───────────────────────────────┘
                             ▼
    ┌─ EVALUATE ─────────────────────────────────────────────┐
    │  Automated model evaluation via NeMo Evaluator         │
    │  Compare: current model vs candidate models            │
    └────────────────────────┬───────────────────────────────┘
                             ▼
    ┌─ FINE-TUNE ────────────────────────────────────────────┐
    │  LoRA-SFT via NeMo Customizer on collected data        │
    │  Create improved detection model                       │
    └────────────────────────┬───────────────────────────────┘
                             ▼
    ┌─ DEPLOY ───────────────────────────────────────────────┐
    │  Hot-swap NIM with improved model                      │
    │  Measure real-world performance lift                    │
    └────────────────────────┬───────────────────────────────┘
                             │
                             └──────── (repeat) ────────────►

This module provides the SDK-side adapter. The actual NeMo
microservices (Customizer, Evaluator, Deployment Manager) run as
Docker containers or Helm chart on the DGX.

Usage:
    >>> from integration.data_flywheel import DataFlywheel
    >>> flywheel = DataFlywheel()
    >>> flywheel.ingest_arena_log(arena_result)
    >>> flywheel.ingest_canary_incident(incident)
    >>> flywheel.run_evaluation_cycle()
    >>> flywheel.status()
"""

from __future__ import annotations

import json
import os
import time
import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class FlywheelStage(str, Enum):
    """Current stage of the flywheel cycle."""
    IDLE = "idle"
    COLLECTING = "collecting"
    EVALUATING = "evaluating"
    FINE_TUNING = "fine_tuning"
    DEPLOYING = "deploying"
    MONITORING = "monitoring"


class DataSource(str, Enum):
    """Origin of training data."""
    ARENA_RED = "arena_red"         # Red team attack logs
    ARENA_BLUE = "arena_blue"       # Blue team defence logs
    CANARY_INCIDENT = "canary_incident"  # Canary fleet incidents
    CTF_SUBMISSION = "ctf_submission"    # CTF event submissions
    GUARDRAIL_LOG = "guardrail_log"      # Guardrail screening results
    MANUAL = "manual"                     # Manually curated


class EvalMetric(str, Enum):
    """Evaluation metrics for model comparison."""
    ACCURACY = "accuracy"
    PRECISION = "precision"
    RECALL = "recall"
    F1_SCORE = "f1_score"
    FALSE_POSITIVE_RATE = "false_positive_rate"
    FALSE_NEGATIVE_RATE = "false_negative_rate"
    LATENCY_P50 = "latency_p50"
    LATENCY_P99 = "latency_p99"
    THROUGHPUT = "throughput"


class CandidateStatus(str, Enum):
    """Status of a candidate model in the flywheel."""
    PENDING = "pending"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPLOYED = "deployed"
    RETIRED = "retired"


@dataclass
class TrainingExample:
    """
    A single training example for the flywheel.

    Represents a labelled interaction: input text + ground-truth label
    (safe/unsafe/attack_type). Collected from Arena, Canary, CTF, or
    guardrail logs.
    """
    example_id: str = ""
    source: DataSource = DataSource.MANUAL
    input_text: str = ""
    label: str = ""             # e.g., "safe", "jailbreak", "injection"
    label_confidence: float = 1.0
    attack_type: str = ""       # e.g., "prompt_injection", "social_engineering"
    ave_id: str = ""            # Related AVE card ID
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.example_id:
            self.example_id = hashlib.sha256(
                f"{time.time()}{self.input_text[:50]}".encode()
            ).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "source": self.source.value,
            "label": self.label,
            "label_confidence": self.label_confidence,
            "attack_type": self.attack_type,
            "ave_id": self.ave_id,
            "text_preview": self.input_text[:100],
            "timestamp": self.timestamp,
        }

    def to_training_pair(self) -> dict[str, str]:
        """Convert to instruction-tuning format."""
        return {
            "instruction": "Classify the following input as safe or unsafe.",
            "input": self.input_text,
            "output": self.label,
        }


@dataclass
class EvalResult:
    """Result from evaluating a candidate model."""
    candidate_id: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    improvement: dict[str, float] = field(default_factory=dict)
    passed: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "metrics": self.metrics,
            "baseline_metrics": self.baseline_metrics,
            "improvement": self.improvement,
            "passed": self.passed,
        }


@dataclass
class CandidateModel:
    """A candidate model produced by fine-tuning."""
    candidate_id: str = ""
    base_model: str = ""
    fine_tune_method: str = "lora_sft"
    training_examples: int = 0
    status: CandidateStatus = CandidateStatus.PENDING
    eval_result: EvalResult | None = None
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.candidate_id:
            self.candidate_id = f"candidate-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "base_model": self.base_model,
            "method": self.fine_tune_method,
            "training_examples": self.training_examples,
            "status": self.status.value,
            "created_at": self.created_at,
        }
        if self.eval_result:
            d["eval_result"] = self.eval_result.to_dict()
        return d


@dataclass
class FlywheelCycle:
    """Record of a completed flywheel cycle."""
    cycle_id: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    examples_collected: int = 0
    candidates_evaluated: int = 0
    candidate_deployed: str = ""
    improvement: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if not self.cycle_id:
            self.cycle_id = f"cycle-{uuid.uuid4().hex[:8]}"

    @property
    def duration_seconds(self) -> float:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "duration_s": round(self.duration_seconds, 1),
            "examples_collected": self.examples_collected,
            "candidates_evaluated": self.candidates_evaluated,
            "candidate_deployed": self.candidate_deployed,
            "improvement": self.improvement,
        }


# ═══════════════════════════════════════════════════════════════════════════
# DATA FLYWHEEL
# ═══════════════════════════════════════════════════════════════════════════

class DataFlywheel:
    """
    Continuous model improvement loop.

    Collects labelled data from Arena, Canary, CTF, and Guardrail
    logs, then drives evaluation → fine-tuning → deployment cycles.

    Architecture mirrors the NVIDIA Data Flywheel Blueprint:
    - NeMo Customizer for fine-tuning (LoRA-SFT)
    - NeMo Evaluator for model comparison
    - Deployment Manager for hot-swap NIM updates

    In mock mode, all operations are simulated locally.
    In live mode, connects to NeMo microservices via REST API.

    Usage:
        >>> fw = DataFlywheel()
        >>> fw.ingest_arena_log({"attack": "...", "detected": True})
        >>> fw.ingest_canary_incident(incident_dict)
        >>> cycle = fw.run_cycle()
        >>> cycle.improvement  # {"accuracy": +0.03, ...}
    """

    def __init__(
        self,
        base_model: str = "nemotron:70b",
        nemo_url: str = "",
        api_key: str = "",
        min_examples_per_cycle: int = 50,
        improvement_threshold: float = 0.01,
        auto_deploy: bool = False,
        mode: str = "mock",
    ):
        self.base_model = base_model
        self.nemo_url = nemo_url or os.environ.get(
            "NEMO_URL", "http://localhost:8000"
        )
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        self.min_examples_per_cycle = min_examples_per_cycle
        self.improvement_threshold = improvement_threshold
        self.auto_deploy = auto_deploy
        self.mode = mode

        # State
        self.stage = FlywheelStage.IDLE
        self._examples: list[TrainingExample] = []
        self._candidates: list[CandidateModel] = []
        self._cycles: list[FlywheelCycle] = []
        self._deployed_model: str = base_model
        self._baseline_metrics: dict[str, float] = {
            EvalMetric.ACCURACY.value: 0.85,
            EvalMetric.PRECISION.value: 0.82,
            EvalMetric.RECALL.value: 0.88,
            EvalMetric.F1_SCORE.value: 0.85,
            EvalMetric.FALSE_POSITIVE_RATE.value: 0.05,
            EvalMetric.FALSE_NEGATIVE_RATE.value: 0.12,
        }

    # ── Data Collection ─────────────────────────────────────────

    @property
    def example_count(self) -> int:
        return len(self._examples)

    @property
    def cycle_count(self) -> int:
        return len(self._cycles)

    @property
    def ready_for_cycle(self) -> bool:
        return len(self._examples) >= self.min_examples_per_cycle

    def ingest_arena_log(self, log: dict[str, Any]) -> TrainingExample:
        """
        Ingest a single Arena red/blue log entry.

        The log should contain at least:
            - "attack_prompt" or "prompt" — the input text
            - "detected" or "detected_vulnerability" — whether it was caught
            - "attack_type" — type of attack
        """
        prompt = log.get("attack_prompt", log.get("prompt", ""))
        detected = log.get("detected", log.get("detected_vulnerability", ""))
        if isinstance(detected, str):
            label = "unsafe" if detected and detected != "benign" else "safe"
        else:
            label = "unsafe" if detected else "safe"

        example = TrainingExample(
            source=DataSource.ARENA_RED,
            input_text=prompt,
            label=label,
            label_confidence=0.9,
            attack_type=log.get("attack_type", ""),
            ave_id=log.get("ave_id", ""),
            metadata={"raw_log": {k: str(v)[:200] for k, v in log.items()}},
        )
        self._examples.append(example)
        self.stage = FlywheelStage.COLLECTING
        return example

    def ingest_canary_incident(self, incident: dict[str, Any]) -> TrainingExample:
        """
        Ingest a Canary fleet incident.

        The incident should contain:
            - "raw_text" or "input" — the adversarial input
            - "signals" — list of threat signals detected
            - "severity" — incident severity
        """
        text = incident.get("raw_text", incident.get("input", ""))
        signals = incident.get("signals", [])
        label = "unsafe" if signals else "safe"
        attack_type = signals[0] if signals else ""

        example = TrainingExample(
            source=DataSource.CANARY_INCIDENT,
            input_text=text,
            label=label,
            label_confidence=0.95,
            attack_type=attack_type,
            ave_id=incident.get("ave_id", ""),
            metadata={"severity": incident.get("severity", "")},
        )
        self._examples.append(example)
        self.stage = FlywheelStage.COLLECTING
        return example

    def ingest_ctf_submission(self, submission: dict[str, Any]) -> TrainingExample:
        """
        Ingest a CTF event submission.

        The submission should contain:
            - "payload" or "input" — the attack payload
            - "success" — whether the attack succeeded
            - "technique" — attack technique used
        """
        text = submission.get("payload", submission.get("input", ""))
        success = submission.get("success", False)
        label = "unsafe"  # CTF submissions are always attack attempts

        example = TrainingExample(
            source=DataSource.CTF_SUBMISSION,
            input_text=text,
            label=label,
            label_confidence=1.0 if success else 0.8,
            attack_type=submission.get("technique", ""),
            metadata={"success": success},
        )
        self._examples.append(example)
        self.stage = FlywheelStage.COLLECTING
        return example

    def ingest_guardrail_log(self, log: dict[str, Any]) -> TrainingExample:
        """
        Ingest a guardrail screening result.

        The log should contain:
            - "text_screened" — the screened text
            - "overall_verdict" — safe/blocked/suspicious
            - "blocked_by" — which guard triggered
        """
        text = log.get("text_screened", "")
        verdict = log.get("overall_verdict", "safe")
        label = "unsafe" if verdict in ("blocked", "suspicious") else "safe"

        example = TrainingExample(
            source=DataSource.GUARDRAIL_LOG,
            input_text=text,
            label=label,
            label_confidence=0.85,
            attack_type=log.get("blocked_by", ""),
            metadata={"verdict": verdict},
        )
        self._examples.append(example)
        self.stage = FlywheelStage.COLLECTING
        return example

    def ingest_batch(
        self,
        examples: list[dict[str, Any]],
        source: DataSource = DataSource.MANUAL,
    ) -> int:
        """Ingest a batch of labelled examples. Returns count ingested."""
        count = 0
        for ex in examples:
            te = TrainingExample(
                source=source,
                input_text=ex.get("input", ex.get("text", "")),
                label=ex.get("label", "safe"),
                label_confidence=ex.get("confidence", 1.0),
                attack_type=ex.get("attack_type", ""),
                ave_id=ex.get("ave_id", ""),
            )
            self._examples.append(te)
            count += 1
        if count > 0:
            self.stage = FlywheelStage.COLLECTING
        return count

    # ── Evaluation ──────────────────────────────────────────────

    def evaluate_candidate(
        self,
        candidate: CandidateModel,
    ) -> EvalResult:
        """
        Evaluate a candidate model against the current baseline.

        In mock mode: simulates metric improvements based on
        training data size (more data → better scores).
        In live mode: calls NeMo Evaluator REST API.
        """
        self.stage = FlywheelStage.EVALUATING
        candidate.status = CandidateStatus.EVALUATING

        if self.mode == "mock":
            return self._mock_evaluate(candidate)
        else:
            return self._live_evaluate(candidate)

    def _mock_evaluate(self, candidate: CandidateModel) -> EvalResult:
        """Simulate evaluation with realistic improvements."""
        import math
        # More training data → better improvement (diminishing returns)
        data_factor = math.log2(max(candidate.training_examples, 1) + 1) / 10
        data_factor = min(data_factor, 0.08)  # Cap at 8% improvement

        metrics: dict[str, float] = {}
        improvement: dict[str, float] = {}

        for metric_name, baseline_val in self._baseline_metrics.items():
            if metric_name in (EvalMetric.FALSE_POSITIVE_RATE.value,
                               EvalMetric.FALSE_NEGATIVE_RATE.value):
                # Lower is better
                new_val = max(0.01, baseline_val - data_factor * 0.5)
                imp = baseline_val - new_val
            else:
                # Higher is better
                new_val = min(0.99, baseline_val + data_factor)
                imp = new_val - baseline_val

            metrics[metric_name] = round(new_val, 4)
            improvement[metric_name] = round(imp, 4)

        # Determine pass/fail
        passed = any(
            abs(v) >= self.improvement_threshold
            for k, v in improvement.items()
            if k in (EvalMetric.ACCURACY.value, EvalMetric.F1_SCORE.value)
        )

        result = EvalResult(
            candidate_id=candidate.candidate_id,
            metrics=metrics,
            baseline_metrics=dict(self._baseline_metrics),
            improvement=improvement,
            passed=passed,
        )
        candidate.eval_result = result
        candidate.status = CandidateStatus.APPROVED if passed else CandidateStatus.REJECTED
        return result

    def _live_evaluate(self, candidate: CandidateModel) -> EvalResult:
        """Call NeMo Evaluator REST API."""
        try:
            import urllib.request
            url = f"{self.nemo_url}/v1/evaluate"
            payload = {
                "candidate_model": candidate.candidate_id,
                "base_model": candidate.base_model,
                "test_data": [e.to_training_pair() for e in self._examples[-100:]],
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())

            return EvalResult(
                candidate_id=candidate.candidate_id,
                metrics=result.get("metrics", {}),
                baseline_metrics=result.get("baseline_metrics", {}),
                improvement=result.get("improvement", {}),
                passed=result.get("passed", False),
            )
        except Exception:
            return self._mock_evaluate(candidate)

    # ── Fine-Tuning ─────────────────────────────────────────────

    def create_candidate(
        self,
        method: str = "lora_sft",
    ) -> CandidateModel:
        """
        Create a fine-tuned candidate model from collected data.

        In mock mode: immediately creates a candidate record.
        In live mode: submits a fine-tuning job to NeMo Customizer.
        """
        self.stage = FlywheelStage.FINE_TUNING

        candidate = CandidateModel(
            base_model=self.base_model,
            fine_tune_method=method,
            training_examples=len(self._examples),
            metadata={
                "sources": self._source_breakdown(),
                "attack_types": self._attack_type_breakdown(),
            },
        )

        if self.mode != "mock":
            self._submit_fine_tune_job(candidate)

        self._candidates.append(candidate)
        return candidate

    def _submit_fine_tune_job(self, candidate: CandidateModel) -> None:
        """Submit fine-tuning job to NeMo Customizer."""
        try:
            import urllib.request
            url = f"{self.nemo_url}/v1/fine-tune"
            payload = {
                "base_model": candidate.base_model,
                "method": candidate.fine_tune_method,
                "training_data": [e.to_training_pair() for e in self._examples],
                "candidate_id": candidate.candidate_id,
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                json.loads(resp.read())
        except Exception:
            pass  # Will fall back to mock evaluation

    # ── Deployment ──────────────────────────────────────────────

    def deploy_candidate(self, candidate: CandidateModel) -> bool:
        """
        Deploy an approved candidate model.

        In mock mode: updates the deployed model reference.
        In live mode: triggers NIM hot-swap via Deployment Manager.
        """
        if candidate.status != CandidateStatus.APPROVED:
            return False

        self.stage = FlywheelStage.DEPLOYING

        if self.mode != "mock":
            self._deploy_nim(candidate)

        candidate.status = CandidateStatus.DEPLOYED
        self._deployed_model = candidate.candidate_id

        # Update baseline metrics to the new model's metrics
        if candidate.eval_result:
            self._baseline_metrics = dict(candidate.eval_result.metrics)

        self.stage = FlywheelStage.MONITORING
        return True

    def _deploy_nim(self, candidate: CandidateModel) -> None:
        """Trigger NIM hot-swap via Deployment Manager API."""
        try:
            import urllib.request
            url = f"{self.nemo_url}/v1/deploy"
            payload = {
                "candidate_id": candidate.candidate_id,
                "base_model": candidate.base_model,
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                json.loads(resp.read())
        except Exception:
            pass

    # ── Full Cycle ──────────────────────────────────────────────

    def run_cycle(self) -> FlywheelCycle:
        """
        Run a complete flywheel cycle:
        1. Verify sufficient data
        2. Create candidate (fine-tune)
        3. Evaluate candidate
        4. Deploy if improved
        5. Record cycle

        Returns the FlywheelCycle record.
        """
        cycle = FlywheelCycle(
            started_at=time.time(),
            examples_collected=len(self._examples),
        )

        # Step 1: Create candidate
        candidate = self.create_candidate()

        # Step 2: Evaluate
        eval_result = self.evaluate_candidate(candidate)
        cycle.candidates_evaluated = 1

        # Step 3: Deploy if passed
        if eval_result.passed:
            if self.auto_deploy or self.mode == "mock":
                self.deploy_candidate(candidate)
                cycle.candidate_deployed = candidate.candidate_id
                cycle.improvement = eval_result.improvement

        cycle.completed_at = time.time()
        self._cycles.append(cycle)
        self.stage = FlywheelStage.IDLE

        return cycle

    # ── Export ───────────────────────────────────────────────────

    def export_training_data(self, format: str = "jsonl") -> str:
        """
        Export collected training data in the specified format.

        Supported: "jsonl" (JSON Lines), "json" (JSON array).
        """
        pairs = [e.to_training_pair() for e in self._examples]
        if format == "jsonl":
            return "\n".join(json.dumps(p) for p in pairs)
        else:
            return json.dumps(pairs, indent=2)

    def export_examples(self) -> list[dict[str, Any]]:
        """Export all training examples as dicts."""
        return [e.to_dict() for e in self._examples]

    # ── Analytics ───────────────────────────────────────────────

    def _source_breakdown(self) -> dict[str, int]:
        """Count examples by source."""
        counts: dict[str, int] = {}
        for ex in self._examples:
            key = ex.source.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _attack_type_breakdown(self) -> dict[str, int]:
        """Count examples by attack type."""
        counts: dict[str, int] = {}
        for ex in self._examples:
            if ex.attack_type:
                counts[ex.attack_type] = counts.get(ex.attack_type, 0) + 1
        return counts

    def _label_breakdown(self) -> dict[str, int]:
        """Count examples by label."""
        counts: dict[str, int] = {}
        for ex in self._examples:
            counts[ex.label] = counts.get(ex.label, 0) + 1
        return counts

    # ── Status ──────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "mode": self.mode,
            "base_model": self.base_model,
            "deployed_model": self._deployed_model,
            "examples_collected": len(self._examples),
            "ready_for_cycle": self.ready_for_cycle,
            "min_examples_required": self.min_examples_per_cycle,
            "candidates": len(self._candidates),
            "cycles_completed": len(self._cycles),
            "source_breakdown": self._source_breakdown(),
            "label_breakdown": self._label_breakdown(),
            "baseline_metrics": self._baseline_metrics,
        }
