"""
RMAP Phase 4 — Evolutionary Crucible
=======================================
A generic Genetic Algorithm framework for evolving agent configurations.

The Crucible takes a set of GeneDef specifications (name, min, max, is_int)
and an arbitrary fitness function, then evolves a population of genomes to
maximise that fitness.  This is completely domain-agnostic — it can optimise
LLM defense thresholds, prompt weights, or any other numeric search space.

Operators:
    - Uniform crossover (per-gene coin flip)
    - Gaussian mutation (sigma = 10% of gene range)
    - Tournament selection (configurable pool size)
    - Elitism (top-N survive unchanged)

Based on: NAIL Experiment 20 — Pathology Collider GA Optimizer
"""

from __future__ import annotations

import copy
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


# ═══════════════════════════════════════════════════════════════════════════
# GENE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GeneDef:
    """
    Definition of a single gene (tunable parameter).

    Args:
        name:   Unique identifier for this gene.
        lo:     Minimum allowed value (inclusive).
        hi:     Maximum allowed value (inclusive).
        is_int: If True, values are rounded to nearest integer.
    """
    name: str
    lo: float
    hi: float
    is_int: bool = False

    @property
    def range(self) -> float:
        return self.hi - self.lo

    def clamp(self, value: float) -> float:
        """Clamp value to [lo, hi] and optionally round to int."""
        v = max(self.lo, min(self.hi, value))
        if self.is_int:
            v = int(round(v))
        return v

    def random_value(self) -> float:
        """Sample a random value within bounds."""
        v = random.uniform(self.lo, self.hi)
        if self.is_int:
            v = int(round(v))
        return v


# ═══════════════════════════════════════════════════════════════════════════
# GENOME
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Genome:
    """
    A single candidate solution: a dict of gene-name → value, plus fitness.

    Create via:
        genome = Genome.random(gene_defs, generation=0)
        genome = Genome.from_dict(gene_defs, {"gene1": 0.5, "gene2": 3})
    """
    genes: dict[str, float]
    fitness: float = 0.0
    generation: int = 0
    metadata: dict = field(default_factory=dict)
    genome_id: str = ""

    def __post_init__(self):
        if not self.genome_id:
            self.genome_id = f"g{self.generation}_{random.randint(1000, 9999)}"

    def to_dict(self) -> dict:
        return {
            "genome_id": self.genome_id,
            "generation": self.generation,
            "fitness": round(self.fitness, 6),
            "genes": {k: round(v, 6) if isinstance(v, float) else v
                      for k, v in self.genes.items()},
            "metadata": self.metadata,
        }

    @staticmethod
    def random(gene_defs: list[GeneDef], generation: int = 0) -> Genome:
        """Create a genome with random gene values within bounds."""
        genes = {gd.name: gd.random_value() for gd in gene_defs}
        return Genome(genes=genes, generation=generation)

    @staticmethod
    def from_dict(
        gene_defs: list[GeneDef],
        values: dict[str, float],
        generation: int = 0,
        genome_id: str = "",
    ) -> Genome:
        """Create a genome from an explicit dict of gene values (clamped to bounds)."""
        gd_map = {gd.name: gd for gd in gene_defs}
        genes = {}
        for name, val in values.items():
            if name in gd_map:
                genes[name] = gd_map[name].clamp(val)
            else:
                genes[name] = val  # pass-through for unknown genes
        # Fill missing genes with midpoint
        for gd in gene_defs:
            if gd.name not in genes:
                mid = (gd.lo + gd.hi) / 2
                genes[gd.name] = gd.clamp(mid)
        return Genome(genes=genes, generation=generation, genome_id=genome_id)


# ═══════════════════════════════════════════════════════════════════════════
# GENETIC OPERATORS  (module-level, reusable)
# ═══════════════════════════════════════════════════════════════════════════

def crossover(
    gene_defs: list[GeneDef],
    parent_a: Genome,
    parent_b: Genome,
    generation: int,
) -> Genome:
    """Uniform crossover: each gene has 50% chance from either parent."""
    child_genes = {}
    for gd in gene_defs:
        if random.random() < 0.5:
            child_genes[gd.name] = parent_a.genes.get(gd.name, gd.random_value())
        else:
            child_genes[gd.name] = parent_b.genes.get(gd.name, gd.random_value())
    return Genome(genes=child_genes, generation=generation)


def mutate(
    gene_defs: list[GeneDef],
    genome: Genome,
    mutation_rate: float = 0.2,
    sigma_frac: float = 0.10,
) -> Genome:
    """
    Gaussian mutation: each gene has mutation_rate chance of perturbation.

    Args:
        gene_defs:     Gene definitions for bounds/types.
        genome:        Genome to mutate (not modified in-place).
        mutation_rate: Per-gene probability of mutation.
        sigma_frac:    Sigma as a fraction of each gene's range.
    """
    mutated = copy.deepcopy(genome)
    for gd in gene_defs:
        if random.random() < mutation_rate:
            sigma = gd.range * sigma_frac
            new_val = mutated.genes.get(gd.name, gd.random_value()) + random.gauss(0, sigma)
            mutated.genes[gd.name] = gd.clamp(new_val)
    return mutated


def tournament_select(
    population: list[Genome],
    tournament_size: int = 3,
) -> Genome:
    """Select one genome via tournament selection (highest fitness wins)."""
    contestants = random.sample(population, min(tournament_size, len(population)))
    return max(contestants, key=lambda g: g.fitness)


# ═══════════════════════════════════════════════════════════════════════════
# CRUCIBLE — The Full GA Runner
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class GenerationStats:
    """Statistics for one generation."""
    generation: int
    best_fitness: float
    avg_fitness: float
    worst_fitness: float
    best_genome_id: str
    best_genes: dict
    elapsed_seconds: float


# The fitness callback signature:
#   evaluate(genome: Genome) -> float
FitnessFunction = Callable[[Genome], float]


class Crucible:
    """
    Generic evolutionary optimiser.

    Usage:
        gene_defs = [
            GeneDef("threshold", 0.1, 0.9),
            GeneDef("window_size", 2, 10, is_int=True),
        ]

        def evaluate(genome: Genome) -> float:
            # Run your system with genome.genes and return a fitness score
            return run_experiment(genome.genes)

        crucible = Crucible(gene_defs, evaluate)
        best = crucible.evolve(generations=20, population_size=12)
        print(best.genes, best.fitness)

    Args:
        gene_defs:       List of GeneDef specifying the search space.
        fitness_fn:      Callable that takes a Genome and returns a float fitness.
        elitism:         Number of top genomes that survive unchanged.
        mutation_rate:   Per-gene mutation probability.
        sigma_frac:      Gaussian sigma as a fraction of gene range.
        tournament_size: Tournament selection pool size.
        seed_genomes:    Optional list of seed genomes (e.g. hand-tuned defaults).
        verbose:         If True, print progress to stdout.
    """

    def __init__(
        self,
        gene_defs: list[GeneDef],
        fitness_fn: FitnessFunction,
        elitism: int = 2,
        mutation_rate: float = 0.2,
        sigma_frac: float = 0.10,
        tournament_size: int = 3,
        seed_genomes: Optional[list[Genome]] = None,
        verbose: bool = True,
    ):
        if not gene_defs:
            raise ValueError("gene_defs must not be empty")

        self.gene_defs = gene_defs
        self.fitness_fn = fitness_fn
        self.elitism = elitism
        self.mutation_rate = mutation_rate
        self.sigma_frac = sigma_frac
        self.tournament_size = tournament_size
        self.seed_genomes = seed_genomes or []
        self.verbose = verbose

        # Results tracking
        self.all_genomes: list[Genome] = []
        self.generation_stats: list[GenerationStats] = []
        self.best_ever: Optional[Genome] = None

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _init_population(self, population_size: int) -> list[Genome]:
        """Create initial population with optional seed genomes."""
        population: list[Genome] = []

        # Add seeds first
        for seed in self.seed_genomes:
            cloned = copy.deepcopy(seed)
            cloned.generation = 0
            population.append(cloned)

        # Fill rest with random genomes
        while len(population) < population_size:
            population.append(Genome.random(self.gene_defs, generation=0))

        return population[:population_size]

    def _evaluate_population(self, population: list[Genome]):
        """Evaluate fitness for all genomes in the population."""
        for i, genome in enumerate(population):
            try:
                genome.fitness = self.fitness_fn(genome)
            except Exception as e:
                self._log(f"    ❌ Genome {genome.genome_id} failed: {e}")
                genome.fitness = 0.0
                genome.metadata["error"] = str(e)
            self.all_genomes.append(copy.deepcopy(genome))

    def _evolve_generation(self, population: list[Genome], gen_num: int) -> list[Genome]:
        """Create next generation via selection, crossover, mutation."""
        population.sort(key=lambda g: g.fitness, reverse=True)
        new_pop: list[Genome] = []

        # Elitism
        for i in range(min(self.elitism, len(population))):
            elite = copy.deepcopy(population[i])
            elite.generation = gen_num
            new_pop.append(elite)

        # Fill rest via crossover + mutation
        pop_size = len(population)
        while len(new_pop) < pop_size:
            parent_a = tournament_select(population, self.tournament_size)
            parent_b = tournament_select(population, self.tournament_size)
            child = crossover(self.gene_defs, parent_a, parent_b, gen_num)
            child = mutate(self.gene_defs, child, self.mutation_rate, self.sigma_frac)
            new_pop.append(child)

        return new_pop

    def evolve(
        self,
        generations: int = 20,
        population_size: int = 12,
    ) -> Genome:
        """
        Run the full evolutionary search.

        Args:
            generations:     Number of GA iterations.
            population_size: Number of genomes per generation.

        Returns:
            The best Genome found across all generations.
        """
        self._log(f"\n  🧬 Crucible: {len(self.gene_defs)} genes × "
                   f"{population_size} pop × {generations} gens")

        ga_start = time.time()
        population = self._init_population(population_size)
        self._log(f"  🧬 Initialized population of {len(population)} genomes")

        for gen in range(generations):
            gen_start = time.time()
            self._log(f"\n  ── Generation {gen + 1}/{generations} ──")

            # Evaluate
            self._evaluate_population(population)

            # Sort and stats
            population.sort(key=lambda g: g.fitness, reverse=True)
            best = population[0]
            worst = population[-1]
            avg = sum(g.fitness for g in population) / len(population)
            elapsed = time.time() - gen_start

            stats = GenerationStats(
                generation=gen + 1,
                best_fitness=round(best.fitness, 6),
                avg_fitness=round(avg, 6),
                worst_fitness=round(worst.fitness, 6),
                best_genome_id=best.genome_id,
                best_genes=best.genes.copy(),
                elapsed_seconds=round(elapsed, 2),
            )
            self.generation_stats.append(stats)

            # Update best-ever
            if self.best_ever is None or best.fitness > self.best_ever.fitness:
                self.best_ever = copy.deepcopy(best)

            self._log(f"    Best:  {best.fitness:.6f}  Avg: {avg:.6f}  "
                       f"Worst: {worst.fitness:.6f}  ({elapsed:.1f}s)")

            # Evolve (skip on last generation)
            if gen < generations - 1:
                population = self._evolve_generation(population, gen + 1)

        total = time.time() - ga_start
        self._log(f"\n  ✅ Crucible complete: best={self.best_ever.fitness:.6f} "
                   f"({self.best_ever.genome_id}) in {total:.1f}s")

        return self.best_ever  # type: ignore

    def fitness_trajectory(self) -> list[float]:
        """Return list of best-fitness-per-generation for plotting."""
        return [s.best_fitness for s in self.generation_stats]

    def results_dict(self) -> dict:
        """Serialize full results to a dict (JSON-friendly)."""
        return {
            "config": {
                "gene_count": len(self.gene_defs),
                "genes": [
                    {"name": gd.name, "lo": gd.lo, "hi": gd.hi, "is_int": gd.is_int}
                    for gd in self.gene_defs
                ],
                "elitism": self.elitism,
                "mutation_rate": self.mutation_rate,
                "sigma_frac": self.sigma_frac,
                "tournament_size": self.tournament_size,
            },
            "best_genome": self.best_ever.to_dict() if self.best_ever else None,
            "generation_stats": [
                {
                    "generation": s.generation,
                    "best_fitness": s.best_fitness,
                    "avg_fitness": s.avg_fitness,
                    "worst_fitness": s.worst_fitness,
                    "best_genome_id": s.best_genome_id,
                    "elapsed_seconds": s.elapsed_seconds,
                }
                for s in self.generation_stats
            ],
            "fitness_trajectory": self.fitness_trajectory(),
            "total_evaluations": len(self.all_genomes),
        }
