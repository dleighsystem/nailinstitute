"""
Horizon 1 — Threshold Optimization Genetic Algorithm.

Evolve bridge defence thresholds to find the mathematical equilibrium
where security is maximised AND task accuracy stays above 80%.

Each Genome encodes a set of sensor thresholds (TokenKinetics, Isolation
Forest, Taint scores, etc.) and is evaluated via an F1-style fitness
function balancing security and competency.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Genome:
    """A candidate bridge configuration — a vector of threshold floats."""
    genome_id: str
    thresholds: dict[str, float]         # sensor_name → threshold  (0.0–1.0)
    generation: int = 0
    fitness: float = 0.0
    security_score: float = 0.0          # 0.0–1.0  (1.0 = zero intrusions)
    accuracy_score: float = 0.0          # 0.0–1.0  (1.0 = perfect task accuracy)
    parent_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "genome_id": self.genome_id,
            "generation": self.generation,
            "fitness": round(self.fitness, 4),
            "security_score": round(self.security_score, 4),
            "accuracy_score": round(self.accuracy_score, 4),
            "thresholds": {k: round(v, 4) for k, v in self.thresholds.items()},
            "parent_ids": self.parent_ids,
        }


# ── Sensor names (from Exp20 Pathology Collider) ────────────────────

DEFAULT_SENSORS: list[str] = [
    "token_kinetics",
    "isolation_forest",
    "taint_score",
    "content_similarity",
    "memory_integrity",
    "rate_of_change",
    "semantic_distance",
    "trust_boundary",
]


@dataclass
class FitnessResult:
    """Result of evaluating a genome against an attack battery."""
    genome: Genome
    attacks_blocked: int = 0
    attacks_total: int = 0
    tasks_correct: int = 0
    tasks_total: int = 0
    f1_fitness: float = 0.0

    @property
    def security(self) -> float:
        return self.attacks_blocked / self.attacks_total if self.attacks_total > 0 else 0.0

    @property
    def accuracy(self) -> float:
        return self.tasks_correct / self.tasks_total if self.tasks_total > 0 else 0.0


# ── Fitness evaluator type ───────────────────────────────────────────

EvaluatorFn = Callable[[Genome], FitnessResult]


def _default_evaluator(genome: Genome) -> FitnessResult:
    """
    Deterministic synthetic evaluator for offline testing.

    Simulates the trade-off: tight thresholds → high security, low accuracy.
    """
    avg_threshold = sum(genome.thresholds.values()) / len(genome.thresholds)
    # Security increases as thresholds tighten (lower avg)
    security = max(0.0, min(1.0, 1.0 - avg_threshold + 0.2))
    # Accuracy decreases as thresholds are too tight
    accuracy = max(0.0, min(1.0, avg_threshold + 0.3))

    # F1-style harmonic mean (security as precision, accuracy as recall)
    if security + accuracy > 0:
        f1 = 2 * (security * accuracy) / (security + accuracy)
    else:
        f1 = 0.0

    genome.fitness = f1
    genome.security_score = security
    genome.accuracy_score = accuracy

    total_attacks = 20
    total_tasks = 10
    return FitnessResult(
        genome=genome,
        attacks_blocked=int(security * total_attacks),
        attacks_total=total_attacks,
        tasks_correct=int(accuracy * total_tasks),
        tasks_total=total_tasks,
        f1_fitness=f1,
    )


@dataclass
class Population:
    """A generation of genomes."""
    generation: int
    genomes: list[Genome] = field(default_factory=list)
    best_fitness: float = 0.0
    avg_fitness: float = 0.0
    champion: Genome | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "size": len(self.genomes),
            "best_fitness": round(self.best_fitness, 4),
            "avg_fitness": round(self.avg_fitness, 4),
            "champion_id": self.champion.genome_id if self.champion else None,
        }


class ThresholdGA:
    """
    Genetic Algorithm for bridge threshold optimization.

    Usage::

        ga = ThresholdGA(population_size=20, generations=10)
        result = ga.run()
        print(result.champion.thresholds)
    """

    def __init__(
        self,
        *,
        population_size: int = 20,
        generations: int = 10,
        mutation_rate: float = 0.15,
        crossover_rate: float = 0.7,
        elitism: int = 2,
        sensors: list[str] | None = None,
        evaluator: EvaluatorFn | None = None,
        seed: int = 42,
    ) -> None:
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.elitism = elitism
        self.sensors = sensors or list(DEFAULT_SENSORS)
        self._evaluator = evaluator or _default_evaluator
        self._rng = random.Random(seed)
        self._gen_counter = 0

    # ── public ───────────────────────────────────────────────────────

    def run(self) -> Population:
        """Execute the full GA and return the final population."""
        pop = self._init_population()
        history: list[Population] = [pop]

        for gen in range(1, self.generations + 1):
            pop = self._evolve(pop, gen)
            history.append(pop)

        return pop

    def run_with_history(self) -> list[Population]:
        """Execute GA returning all generations."""
        pop = self._init_population()
        history: list[Population] = [pop]

        for gen in range(1, self.generations + 1):
            pop = self._evolve(pop, gen)
            history.append(pop)

        return history

    # ── internals ────────────────────────────────────────────────────

    def _make_genome_id(self, gen: int) -> str:
        raw = f"g{gen}_{self._gen_counter}"
        self._gen_counter += 1
        h = hashlib.md5(raw.encode()).hexdigest()[:6]
        return f"g{gen}_{h}"

    def _random_thresholds(self) -> dict[str, float]:
        return {s: self._rng.uniform(0.1, 0.9) for s in self.sensors}

    def _init_population(self) -> Population:
        genomes: list[Genome] = []
        for _ in range(self.population_size):
            g = Genome(
                genome_id=self._make_genome_id(0),
                thresholds=self._random_thresholds(),
                generation=0,
            )
            self._evaluate(g)
            genomes.append(g)
        return self._build_population(0, genomes)

    def _evaluate(self, genome: Genome) -> FitnessResult:
        result = self._evaluator(genome)
        genome.fitness = result.f1_fitness
        genome.security_score = result.security
        genome.accuracy_score = result.accuracy
        return result

    def _build_population(self, gen: int, genomes: list[Genome]) -> Population:
        pop = Population(generation=gen, genomes=genomes)
        if genomes:
            pop.best_fitness = max(g.fitness for g in genomes)
            pop.avg_fitness = sum(g.fitness for g in genomes) / len(genomes)
            pop.champion = max(genomes, key=lambda g: g.fitness)
        return pop

    def _select(self, pop: Population) -> Genome:
        """Tournament selection (k=3)."""
        candidates = self._rng.sample(pop.genomes, min(3, len(pop.genomes)))
        return max(candidates, key=lambda g: g.fitness)

    def _crossover(self, p1: Genome, p2: Genome, gen: int) -> Genome:
        """Uniform crossover."""
        child_thresholds: dict[str, float] = {}
        for sensor in self.sensors:
            if self._rng.random() < 0.5:
                child_thresholds[sensor] = p1.thresholds[sensor]
            else:
                child_thresholds[sensor] = p2.thresholds[sensor]
        return Genome(
            genome_id=self._make_genome_id(gen),
            thresholds=child_thresholds,
            generation=gen,
            parent_ids=[p1.genome_id, p2.genome_id],
        )

    def _mutate(self, genome: Genome) -> None:
        """Per-gene Gaussian mutation."""
        for sensor in self.sensors:
            if self._rng.random() < self.mutation_rate:
                delta = self._rng.gauss(0, 0.1)
                genome.thresholds[sensor] = max(
                    0.01, min(0.99, genome.thresholds[sensor] + delta)
                )

    def _evolve(self, pop: Population, gen: int) -> Population:
        """Create next generation via selection, crossover, mutation."""
        # Elite carry-forward
        sorted_genomes = sorted(pop.genomes, key=lambda g: g.fitness, reverse=True)
        new_genomes: list[Genome] = []
        for elite in sorted_genomes[: self.elitism]:
            clone = Genome(
                genome_id=self._make_genome_id(gen),
                thresholds=dict(elite.thresholds),
                generation=gen,
                parent_ids=[elite.genome_id],
            )
            self._evaluate(clone)
            new_genomes.append(clone)

        # Fill remaining via crossover + mutation
        while len(new_genomes) < self.population_size:
            p1 = self._select(pop)
            p2 = self._select(pop)
            if self._rng.random() < self.crossover_rate:
                child = self._crossover(p1, p2, gen)
            else:
                child = Genome(
                    genome_id=self._make_genome_id(gen),
                    thresholds=dict(p1.thresholds),
                    generation=gen,
                    parent_ids=[p1.genome_id],
                )
            self._mutate(child)
            self._evaluate(child)
            new_genomes.append(child)

        return self._build_population(gen, new_genomes)
