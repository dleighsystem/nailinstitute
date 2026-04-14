"""
NAIL Institute — Experiment 30: Ship of Theseus
=================================================

Lifecycle Defense Frontier 1: Continuous Uptime Attrition

Tests whether an agent's defended accuracy degrades over extended
continuous operation due to "Latent Space Dementia" — progressive
memory bloat causing semantic flattening and priority confusion.

Simulates 30 days of continuous operation:
  - 10,000 tasks fired at the agent without memory reset
  - Vector DB accumulates context summaries (never flushed)
  - Defense layers run continuously

Measures:
  - At what task count does accuracy drop below 36%?
  - Does an "Active Forgetting" protocol (semantic dedup + decay)
    prevent dementia?
  - Memory size, semantic diversity, and retrieval precision over time

Two arms:
  A) Control:  Standard RAG — memories accumulate without pruning
  B) Treatment: Active Forgetting — redundant vectors deleted, old entries decayed

Usage:
    python -m experiments.exp30_ship_of_theseus.run
    python -m experiments.exp30_ship_of_theseus.run --tasks 1000 --checkpoint-every 100
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import PRIMARY_MODEL, FAST_MODEL, DATA_DIR, LOGS_DIR
from shared.logger import ExperimentLogger


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

RESULTS_DIR = Path(__file__).parent / "results"

# Simulated task categories (financial agent scenario)
TASK_CATEGORIES = [
    "revenue_analysis", "expense_audit", "client_onboarding",
    "risk_assessment", "compliance_check", "market_research",
    "portfolio_review", "fraud_detection", "cash_flow_forecast",
    "vendor_evaluation", "tax_calculation", "hr_policy_review",
]

# Task complexity distribution (weighted)
COMPLEXITY_WEIGHTS = {
    "simple": 0.50,
    "moderate": 0.35,
    "complex": 0.15,
}


# ═══════════════════════════════════════════════════════════════════════════
# Long-Running Memory Store (simulated Vector DB)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """A single memory entry in the agent's persistent store."""
    entry_id: str
    content: str
    category: str
    task_num: int
    timestamp: float
    trust_score: float = 1.0
    access_count: int = 0
    last_accessed: float = 0.0
    content_hash: str = ""
    semantic_cluster: int = -1

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.md5(self.content[:200].encode()).hexdigest()[:12]


class PersistentMemoryStore:
    """
    Simulated vector DB that accumulates memories over extended operation.

    Tracks memory bloat, semantic diversity, and retrieval quality.
    Does NOT auto-prune — that's the Active Forgetting layer's job.
    """

    def __init__(self, max_retrieval: int = 10):
        self.entries: dict[str, MemoryEntry] = {}
        self.max_retrieval = max_retrieval
        self._insertion_count = 0
        self._retrieval_count = 0
        self._duplicate_count = 0
        self._size_history: list[int] = []

    def store(self, content: str, category: str, task_num: int,
              trust_score: float = 1.0) -> str:
        """Store a memory entry. Returns entry_id."""
        entry_id = f"mem_{task_num}_{uuid.uuid4().hex[:6]}"
        entry = MemoryEntry(
            entry_id=entry_id,
            content=content,
            category=category,
            task_num=task_num,
            timestamp=time.time(),
            trust_score=trust_score,
        )

        # Check for near-duplicates (same hash = same content prefix)
        existing_hashes = {e.content_hash for e in self.entries.values()}
        if entry.content_hash in existing_hashes:
            self._duplicate_count += 1

        self.entries[entry_id] = entry
        self._insertion_count += 1
        return entry_id

    def retrieve(self, query_category: str, max_results: Optional[int] = None) -> list[MemoryEntry]:
        """
        Retrieve relevant memories for a task.

        Simulates embedding-based retrieval by filtering on category
        + recency + trust score weighting.
        """
        max_results = max_results or self.max_retrieval
        self._retrieval_count += 1

        candidates = []
        for entry in self.entries.values():
            # Relevance score: category match + recency + trust
            relevance = 0.0
            if entry.category == query_category:
                relevance += 0.5
            # Recency decay (older = less relevant)
            age = time.time() - entry.timestamp
            recency = math.exp(-age / 86400)  # Decay over ~1 day sim time
            relevance += 0.3 * recency
            relevance += 0.2 * entry.trust_score
            candidates.append((relevance, entry))

        # Sort by relevance (descending)
        candidates.sort(key=lambda x: x[0], reverse=True)

        results = []
        for _, entry in candidates[:max_results]:
            entry.access_count += 1
            entry.last_accessed = time.time()
            results.append(entry)

        return results

    def get_semantic_diversity(self) -> float:
        """
        Measure semantic diversity: unique content hashes / total entries.
        Low diversity = semantic flattening (dementia signal).
        """
        if not self.entries:
            return 1.0
        unique_hashes = len({e.content_hash for e in self.entries.values()})
        return unique_hashes / len(self.entries)

    def get_category_distribution(self) -> dict[str, int]:
        """Count memories per category."""
        dist: dict[str, int] = {}
        for entry in self.entries.values():
            dist[entry.category] = dist.get(entry.category, 0) + 1
        return dist

    @property
    def size(self) -> int:
        return len(self.entries)

    def snapshot(self) -> dict:
        """Record current state for time-series analysis."""
        snapshot = {
            "total_entries": self.size,
            "unique_content": len({e.content_hash for e in self.entries.values()}),
            "semantic_diversity": round(self.get_semantic_diversity(), 4),
            "duplicate_count": self._duplicate_count,
            "insertion_count": self._insertion_count,
            "retrieval_count": self._retrieval_count,
            "category_distribution": self.get_category_distribution(),
        }
        self._size_history.append(self.size)
        return snapshot


# ═══════════════════════════════════════════════════════════════════════════
# Active Forgetting Protocol
# ═══════════════════════════════════════════════════════════════════════════

class ActiveForgettingProtocol:
    """
    Memory hygiene layer that prevents Latent Space Dementia.

    Three mechanisms:
      1. Semantic Deduplication — remove entries with identical content hashes
      2. Temporal Decay — delete entries older than max_age with low access
      3. Relevance Pruning — remove lowest-trust entries when memory exceeds cap

    Runs periodically (every N tasks) to keep the memory store healthy.
    """

    def __init__(
        self,
        max_entries: int = 500,
        max_age_tasks: int = 2000,
        min_access_count: int = 2,
        dedup_enabled: bool = True,
        decay_enabled: bool = True,
        prune_enabled: bool = True,
    ):
        self.max_entries = max_entries
        self.max_age_tasks = max_age_tasks
        self.min_access_count = min_access_count
        self.dedup_enabled = dedup_enabled
        self.decay_enabled = decay_enabled
        self.prune_enabled = prune_enabled

        # Statistics
        self.dedup_removed = 0
        self.decay_removed = 0
        self.prune_removed = 0
        self.cycles = 0

    def run(self, store: PersistentMemoryStore, current_task: int) -> dict:
        """
        Execute one forgetting cycle on the memory store.

        Returns dict of removal statistics.
        """
        self.cycles += 1
        removed = {"dedup": 0, "decay": 0, "prune": 0}

        # 1. Semantic deduplication
        if self.dedup_enabled:
            seen_hashes: dict[str, str] = {}  # hash -> first entry_id
            to_remove = []
            for entry_id, entry in store.entries.items():
                if entry.content_hash in seen_hashes:
                    to_remove.append(entry_id)
                else:
                    seen_hashes[entry.content_hash] = entry_id

            for entry_id in to_remove:
                del store.entries[entry_id]
                removed["dedup"] += 1
            self.dedup_removed += removed["dedup"]

        # 2. Temporal decay
        if self.decay_enabled:
            to_remove = []
            for entry_id, entry in store.entries.items():
                age = current_task - entry.task_num
                if age > self.max_age_tasks and entry.access_count < self.min_access_count:
                    to_remove.append(entry_id)

            for entry_id in to_remove:
                del store.entries[entry_id]
                removed["decay"] += 1
            self.decay_removed += removed["decay"]

        # 3. Relevance pruning (if over capacity)
        if self.prune_enabled and store.size > self.max_entries:
            # Score entries by utility: trust * access_count * recency
            scored = []
            for entry_id, entry in store.entries.items():
                age = max(1, current_task - entry.task_num)
                utility = entry.trust_score * (entry.access_count + 1) / math.log2(age + 1)
                scored.append((utility, entry_id))

            scored.sort()  # Lowest utility first
            excess = store.size - self.max_entries
            for _, entry_id in scored[:excess]:
                del store.entries[entry_id]
                removed["prune"] += 1
            self.prune_removed += removed["prune"]

        return removed

    def get_stats(self) -> dict:
        return {
            "cycles": self.cycles,
            "dedup_removed": self.dedup_removed,
            "decay_removed": self.decay_removed,
            "prune_removed": self.prune_removed,
            "total_removed": self.dedup_removed + self.decay_removed + self.prune_removed,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Task Generator (simulates 30 days of financial agent workload)
# ═══════════════════════════════════════════════════════════════════════════

class TaskGenerator:
    """
    Generates a stream of simulated financial tasks over time.

    Tasks become progressively harder (more context-dependent) to
    stress-test the agent's ability to retrieve relevant memories.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.task_count = 0

    def generate(self) -> dict:
        """Generate the next task."""
        self.task_count += 1

        category = self.rng.choice(TASK_CATEGORIES)

        # Complexity increases over time (simulates growing business)
        complexity_roll = self.rng.random()
        # Shift distribution toward complex as time progresses
        complexity_shift = min(0.2, self.task_count / 50000)
        if complexity_roll < COMPLEXITY_WEIGHTS["simple"] - complexity_shift:
            complexity = "simple"
        elif complexity_roll < (1.0 - COMPLEXITY_WEIGHTS["complex"] - complexity_shift):
            complexity = "moderate"
        else:
            complexity = "complex"

        # Tasks that reference prior context (requires good retrieval)
        requires_history = self.task_count > 100 and self.rng.random() < 0.3 + (self.task_count / 30000)

        # Ground truth answer (for accuracy scoring)
        answer_quality = self.rng.gauss(0.8, 0.1)  # Base quality
        if complexity == "complex":
            answer_quality -= 0.1  # Harder tasks = lower expected quality
        if requires_history:
            answer_quality -= 0.05  # History-dependent tasks are harder

        return {
            "task_id": f"task_{self.task_count:06d}",
            "task_num": self.task_count,
            "category": category,
            "complexity": complexity,
            "requires_history": requires_history,
            "expected_quality": max(0.0, min(1.0, answer_quality)),
            "prompt": self._generate_prompt(category, complexity, requires_history),
        }

    def _generate_prompt(self, category: str, complexity: str, requires_history: bool) -> str:
        """Generate a task prompt (synthetic, for simulation scoring)."""
        base = f"[{category.upper()}] "
        if complexity == "simple":
            base += f"Perform a standard {category.replace('_', ' ')} review."
        elif complexity == "moderate":
            base += f"Analyze the {category.replace('_', ' ')} with cross-reference to recent findings."
        else:
            base += f"Deep investigation of {category.replace('_', ' ')} — correlate with all historical context."

        if requires_history:
            base += " Reference all prior related analyses."

        return base


# ═══════════════════════════════════════════════════════════════════════════
# Accuracy Scorer (simulates agent task completion quality)
# ═══════════════════════════════════════════════════════════════════════════

class AccuracyScorer:
    """
    Models how memory bloat affects task accuracy.

    Key insight: As memory grows, retrieval precision drops (noise increases),
    which degrades the agent's ability to find relevant context.
    The accuracy function models this degradation curve.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._scores: list[float] = []

    def score_task(
        self,
        task: dict,
        memory_size: int,
        semantic_diversity: float,
        retrieved_count: int,
        relevant_retrieved: int,
    ) -> float:
        """
        Score task accuracy based on memory state.

        Accuracy degrades when:
          - Memory is large (diluted retrieval)
          - Semantic diversity is low (redundant context)
          - Retrieved relevance is poor

        Args:
            task: Task definition from TaskGenerator
            memory_size: Current memory store size
            semantic_diversity: Unique content ratio (0-1)
            retrieved_count: How many memories were retrieved
            relevant_retrieved: How many were actually relevant to the task

        Returns:
            Accuracy score (0.0 - 1.0)
        """
        base_quality = task["expected_quality"]

        # Memory bloat penalty: accuracy degrades logarithmically with memory size
        # At 100 entries: ~0% penalty, at 1000: ~10%, at 5000: ~25%, at 10000: ~35%
        bloat_penalty = 0.15 * math.log10(max(1, memory_size / 100))

        # Semantic diversity bonus: high diversity = rich context
        # Low diversity = redundant memories = confusion
        diversity_bonus = 0.1 * semantic_diversity

        # Retrieval precision: relevant / total retrieved
        if retrieved_count > 0:
            retrieval_precision = relevant_retrieved / retrieved_count
        else:
            retrieval_precision = 0.0

        precision_effect = 0.15 * retrieval_precision

        # History-dependent tasks suffer more from poor retrieval
        if task["requires_history"] and retrieval_precision < 0.3:
            bloat_penalty *= 1.5

        # Compute final accuracy
        accuracy = base_quality - bloat_penalty + diversity_bonus + precision_effect

        # Add noise
        accuracy += self.rng.gauss(0, 0.05)

        accuracy = max(0.0, min(1.0, accuracy))
        self._scores.append(accuracy)
        return accuracy

    def get_rolling_average(self, window: int = 100) -> float:
        """Get rolling average accuracy over last N tasks."""
        if not self._scores:
            return 0.0
        recent = self._scores[-window:]
        return sum(recent) / len(recent)

    def get_all_scores(self) -> list[float]:
        return self._scores.copy()


# ═══════════════════════════════════════════════════════════════════════════
# Ship of Theseus Experiment Runner
# ═══════════════════════════════════════════════════════════════════════════

class ShipOfTheseus:
    """
    Experiment 30: Tests whether agent accuracy degrades over
    extended continuous operation (Latent Space Dementia).

    Runs two arms:
      A) Control:  No memory management — accumulates indefinitely
      B) Treatment: Active Forgetting protocol enabled
    """

    def __init__(
        self,
        total_tasks: int = 10000,
        checkpoint_every: int = 500,
        forgetting_interval: int = 100,
        max_memory: int = 500,
        seed: int = 42,
    ):
        self.total_tasks = total_tasks
        self.checkpoint_every = checkpoint_every
        self.forgetting_interval = forgetting_interval
        self.max_memory = max_memory
        self.seed = seed

    def _run_arm(
        self,
        arm_name: str,
        forgetting: Optional[ActiveForgettingProtocol] = None,
    ) -> dict:
        """Run one experimental arm."""
        print(f"\n{'═' * 60}")
        print(f"  ARM: {arm_name}")
        print(f"  Tasks: {self.total_tasks} | Forgetting: {'ON' if forgetting else 'OFF'}")
        print(f"{'═' * 60}\n")

        store = PersistentMemoryStore(max_retrieval=10)
        task_gen = TaskGenerator(seed=self.seed)
        scorer = AccuracyScorer(seed=self.seed + 1)

        checkpoints: list[dict] = []
        forgetting_log: list[dict] = []
        dementia_onset_task: Optional[int] = None  # Task where rolling avg < 36%

        start = time.time()

        for task_num in range(1, self.total_tasks + 1):
            # Generate task
            task = task_gen.generate()

            # Retrieve memories
            retrieved = store.retrieve(task["category"])

            # Simulate: how many retrieved memories are actually relevant
            relevant = sum(1 for m in retrieved if m.category == task["category"])

            # Agent "processes" the task (simulated — produces memories)
            # In production, this would be the LLM call
            memories_to_store = self._simulate_task_output(task)
            for mem_content in memories_to_store:
                store.store(mem_content, task["category"], task_num)

            # Score accuracy
            accuracy = scorer.score_task(
                task=task,
                memory_size=store.size,
                semantic_diversity=store.get_semantic_diversity(),
                retrieved_count=len(retrieved),
                relevant_retrieved=relevant,
            )

            # Active Forgetting (treatment arm only)
            if forgetting and task_num % self.forgetting_interval == 0:
                removed = forgetting.run(store, task_num)
                if sum(removed.values()) > 0:
                    forgetting_log.append({
                        "task_num": task_num,
                        "removed": removed,
                        "store_size_after": store.size,
                    })

            # Checkpoint
            if task_num % self.checkpoint_every == 0:
                rolling_avg = scorer.get_rolling_average(window=100)
                mem_snapshot = store.snapshot()

                checkpoint = {
                    "task_num": task_num,
                    "rolling_accuracy": round(rolling_avg, 4),
                    "memory": mem_snapshot,
                    "elapsed_seconds": round(time.time() - start, 1),
                }
                checkpoints.append(checkpoint)

                # Detect dementia onset
                if rolling_avg < 0.36 and dementia_onset_task is None:
                    dementia_onset_task = task_num

                status = "🧠" if rolling_avg >= 0.5 else "⚠️" if rolling_avg >= 0.36 else "💀"
                print(f"  {status} Task {task_num:>6}/{self.total_tasks} | "
                      f"Accuracy: {rolling_avg:.1%} | "
                      f"Memory: {store.size:>5} entries | "
                      f"Diversity: {mem_snapshot['semantic_diversity']:.2%}")

        total_time = time.time() - start

        # Final results
        final_accuracy = scorer.get_rolling_average(window=100)
        all_scores = scorer.get_all_scores()

        return {
            "arm": arm_name,
            "total_tasks": self.total_tasks,
            "total_time_seconds": round(total_time, 1),
            "final_rolling_accuracy": round(final_accuracy, 4),
            "dementia_onset_task": dementia_onset_task,
            "dementia_onset_pct": round(
                dementia_onset_task / self.total_tasks, 2
            ) if dementia_onset_task else None,
            "final_memory_size": store.size,
            "final_semantic_diversity": round(store.get_semantic_diversity(), 4),
            "duplicate_count": store._duplicate_count,
            "checkpoints": checkpoints,
            "forgetting_stats": forgetting.get_stats() if forgetting else None,
            "forgetting_log": forgetting_log[:50],  # First 50 cycles
            "accuracy_percentiles": {
                "p10": round(sorted(all_scores)[int(len(all_scores) * 0.1)], 4),
                "p25": round(sorted(all_scores)[int(len(all_scores) * 0.25)], 4),
                "p50": round(sorted(all_scores)[int(len(all_scores) * 0.5)], 4),
                "p75": round(sorted(all_scores)[int(len(all_scores) * 0.75)], 4),
                "p90": round(sorted(all_scores)[int(len(all_scores) * 0.9)], 4),
            },
        }

    def _simulate_task_output(self, task: dict) -> list[str]:
        """
        Simulate the agent producing memory entries for a task.

        In production, these would be the agent's actual RAG summaries.
        Here we simulate realistic memory accumulation patterns.
        """
        rng = random.Random(hash(task["task_id"]))

        memories = []
        # Simple tasks produce 1-2 memories; complex produce 3-5
        if task["complexity"] == "simple":
            count = rng.randint(1, 2)
        elif task["complexity"] == "moderate":
            count = rng.randint(2, 3)
        else:
            count = rng.randint(3, 5)

        for i in range(count):
            # Generate semi-realistic summary content
            content = (
                f"Analysis of {task['category'].replace('_', ' ')} "
                f"(task {task['task_num']}): "
                f"Finding {i+1} — {'detailed' if task['complexity'] == 'complex' else 'standard'} "
                f"assessment completed."
            )
            memories.append(content)

        return memories

    def run(self) -> dict:
        """Run the full experiment: Control + Treatment arms."""

        print("\n" + "╔" + "═" * 62 + "╗")
        print("║  NAIL INSTITUTE — EXPERIMENT 30: SHIP OF THESEUS           ║")
        print("║  Lifecycle Defense: Continuous Uptime Attrition             ║")
        print("║  Does agent accuracy degrade over 30-day operation?         ║")
        print("╠" + "═" * 62 + "╣")
        print(f"║  Total tasks: {self.total_tasks:<48}║")
        print(f"║  Checkpoint every: {self.checkpoint_every:<43}║")
        print(f"║  Active Forgetting: every {self.forgetting_interval} tasks, cap {self.max_memory:<17}║")
        print("╚" + "═" * 62 + "╝")

        # Arm A: Control (no forgetting)
        control = self._run_arm("CONTROL (No Forgetting)")

        # Arm B: Treatment (Active Forgetting enabled)
        forgetting = ActiveForgettingProtocol(
            max_entries=self.max_memory,
            max_age_tasks=2000,
            min_access_count=2,
        )
        treatment = self._run_arm("TREATMENT (Active Forgetting)", forgetting=forgetting)

        # ── Comparative Analysis ────────────────────────────────────────

        print(f"\n{'╔' + '═' * 62 + '╗'}")
        print(f"{'║'}  SHIP OF THESEUS — RESULTS                                   {'║'}")
        print(f"{'╠' + '═' * 62 + '╣'}")

        print(f"\n  {'Metric':<35} | {'Control':>10} | {'Treatment':>10}")
        print(f"  {'-'*35} | {'-'*10} | {'-'*10}")
        print(f"  {'Final accuracy (100-task avg)':<35} | "
              f"{control['final_rolling_accuracy']:>9.1%} | "
              f"{treatment['final_rolling_accuracy']:>9.1%}")
        print(f"  {'Dementia onset (task #)':<35} | "
              f"{control['dementia_onset_task'] or 'Never':>10} | "
              f"{treatment['dementia_onset_task'] or 'Never':>10}")
        print(f"  {'Final memory size':<35} | "
              f"{control['final_memory_size']:>10,} | "
              f"{treatment['final_memory_size']:>10,}")
        print(f"  {'Semantic diversity':<35} | "
              f"{control['final_semantic_diversity']:>9.1%} | "
              f"{treatment['final_semantic_diversity']:>9.1%}")
        print(f"  {'Duplicate memories':<35} | "
              f"{control['duplicate_count']:>10,} | "
              f"{treatment['duplicate_count']:>10,}")
        print(f"  {'Accuracy P50':<35} | "
              f"{control['accuracy_percentiles']['p50']:>9.1%} | "
              f"{treatment['accuracy_percentiles']['p50']:>9.1%}")

        if treatment["forgetting_stats"]:
            fs = treatment["forgetting_stats"]
            print(f"\n  Active Forgetting Statistics:")
            print(f"    Cycles run: {fs['cycles']}")
            print(f"    Dedup removed: {fs['dedup_removed']}")
            print(f"    Decay removed: {fs['decay_removed']}")
            print(f"    Prune removed: {fs['prune_removed']}")
            print(f"    Total removed: {fs['total_removed']}")

        # Verdict
        delta = treatment["final_rolling_accuracy"] - control["final_rolling_accuracy"]
        if delta > 0.05:
            verdict = "✅ Active Forgetting PREVENTS Latent Space Dementia"
        elif delta > 0:
            verdict = "⚠️ Active Forgetting provides marginal improvement"
        else:
            verdict = "❌ Active Forgetting did NOT help"

        print(f"\n  {'═' * 60}")
        print(f"  VERDICT: {verdict}")
        print(f"  Accuracy delta: {delta:+.1%} (treatment - control)")
        print(f"  {'═' * 60}\n")

        # ── Save Results ────────────────────────────────────────────────

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        results_path = RESULTS_DIR / f"ship_of_theseus_{timestamp}.json"

        results = {
            "experiment": "exp30_ship_of_theseus",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "total_tasks": self.total_tasks,
                "checkpoint_every": self.checkpoint_every,
                "forgetting_interval": self.forgetting_interval,
                "max_memory": self.max_memory,
                "seed": self.seed,
            },
            "control": control,
            "treatment": treatment,
            "comparison": {
                "accuracy_delta": round(delta, 4),
                "control_dementia": control["dementia_onset_task"],
                "treatment_dementia": treatment["dementia_onset_task"],
                "verdict": verdict,
            },
        }

        with open(results_path, "w") as f:
            json.dump(results, f, indent=2, default=str)

        print(f"  💾 Results: {results_path}")
        return results


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="NAIL Experiment 30: Ship of Theseus (Latent Space Dementia)"
    )
    parser.add_argument("--tasks", type=int, default=10000,
                        help="Total tasks to simulate (default: 10000)")
    parser.add_argument("--checkpoint-every", type=int, default=500,
                        help="Checkpoint interval (default: 500)")
    parser.add_argument("--forgetting-interval", type=int, default=100,
                        help="Active Forgetting cycle interval (default: 100)")
    parser.add_argument("--max-memory", type=int, default=500,
                        help="Max memory entries before pruning (default: 500)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()

    experiment = ShipOfTheseus(
        total_tasks=args.tasks,
        checkpoint_every=args.checkpoint_every,
        forgetting_interval=args.forgetting_interval,
        max_memory=args.max_memory,
        seed=args.seed,
    )
    experiment.run()


if __name__ == "__main__":
    main()
