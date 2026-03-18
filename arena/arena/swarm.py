"""
Red Swarm — GA-evolved attack population.

Maintains a population of AttackVectors and evolves them each generation.
Fitness = how effectively an attack breaches the Blue Bridge.

Uses tournament selection + uniform crossover + Gaussian mutation,
following the same GA paradigm as rmap.crucible but specialised for
adversarial attack evolution.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from .vectors import AttackType, AttackVector, ATTACK_GENE_NAMES


@dataclass
class SwarmStats:
    """Statistics for a single generation of the Red Swarm."""
    generation: int
    population_size: int
    best_fitness: float
    mean_fitness: float
    worst_fitness: float
    best_vector: AttackVector | None = None
    type_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "population_size": self.population_size,
            "best_fitness": round(self.best_fitness, 6),
            "mean_fitness": round(self.mean_fitness, 6),
            "worst_fitness": round(self.worst_fitness, 6),
            "best_vector_id": self.best_vector.vector_id if self.best_vector else None,
            "type_distribution": self.type_distribution,
        }


def _tournament_select(population: list[AttackVector], k: int = 3) -> AttackVector:
    """Tournament selection: pick k random, return the fittest."""
    candidates = random.sample(population, min(k, len(population)))
    return max(candidates, key=lambda v: v.fitness)


class RedSwarm:
    """
    Genetic-algorithm driven attack population.

    Usage:
        swarm = RedSwarm(population_size=50)
        swarm.seed()                      # Create random initial population
        for gen in range(100):
            for vec in swarm.population:
                payload = vec.generate()
                score = evaluate_against_blue(payload)
                vec.fitness = score
            stats = swarm.evolve()         # Select, crossover, mutate → next gen
    """

    def __init__(
        self,
        population_size: int = 50,
        mutation_rate: float = 0.2,
        mutation_sigma: float = 0.1,
        elite_fraction: float = 0.1,
        tournament_k: int = 3,
    ):
        self.population_size = population_size
        self.mutation_rate = mutation_rate
        self.mutation_sigma = mutation_sigma
        self.elite_fraction = elite_fraction
        self.tournament_k = tournament_k
        self.population: list[AttackVector] = []
        self.generation = 0
        self.history: list[SwarmStats] = []

    def seed(
        self,
        attack_types: list[AttackType] | None = None,
        population: list[AttackVector] | None = None,
    ) -> None:
        """
        Initialise the population.

        If `population` is provided, use it directly.
        Otherwise generate random vectors, optionally constrained to
        the given attack_types.
        """
        if population is not None:
            self.population = list(population)
            self.population_size = len(self.population)
            return

        types = attack_types or list(AttackType)
        self.population = [
            AttackVector.random(
                attack_type=random.choice(types),
                generation=0,
            )
            for _ in range(self.population_size)
        ]
        self.generation = 0

    def stats(self) -> SwarmStats:
        """Compute statistics for the current population."""
        if not self.population:
            return SwarmStats(
                generation=self.generation,
                population_size=0,
                best_fitness=0.0,
                mean_fitness=0.0,
                worst_fitness=0.0,
            )

        fits = [v.fitness for v in self.population]
        best_vec = max(self.population, key=lambda v: v.fitness)

        # Attack type distribution
        dist: dict[str, int] = {}
        for v in self.population:
            key = v.attack_type.value
            dist[key] = dist.get(key, 0) + 1

        return SwarmStats(
            generation=self.generation,
            population_size=len(self.population),
            best_fitness=max(fits),
            mean_fitness=sum(fits) / len(fits),
            worst_fitness=min(fits),
            best_vector=best_vec,
            type_distribution=dist,
        )

    def evolve(self) -> SwarmStats:
        """
        Run one generation of evolution.

        1. Record stats
        2. Elitism — carry forward top N%
        3. Tournament selection + crossover → fill remaining slots
        4. Mutation
        5. Increment generation counter
        """
        if not self.population:
            raise ValueError("Cannot evolve empty population — call seed() first")

        # Record pre-evolution stats
        gen_stats = self.stats()
        self.history.append(gen_stats)

        self.generation += 1

        # Sort by fitness descending
        ranked = sorted(self.population, key=lambda v: v.fitness, reverse=True)

        # Elite preservation
        n_elite = max(1, int(self.population_size * self.elite_fraction))
        elites = ranked[:n_elite]

        # Breed the rest
        offspring: list[AttackVector] = []
        while len(offspring) < self.population_size - n_elite:
            parent_a = _tournament_select(ranked, self.tournament_k)
            parent_b = _tournament_select(ranked, self.tournament_k)
            child = AttackVector.crossover(parent_a, parent_b, self.generation)
            child = AttackVector.mutate(child, self.mutation_rate, self.mutation_sigma)
            offspring.append(child)

        # Reset fitness for new generation (elites keep theirs as warm start)
        for v in offspring:
            v.fitness = 0.0

        self.population = list(elites) + offspring
        return gen_stats

    def best(self, n: int = 1) -> list[AttackVector]:
        """Return the top-n vectors by fitness."""
        ranked = sorted(self.population, key=lambda v: v.fitness, reverse=True)
        return ranked[:n]

    def fitness_trajectory(self) -> list[dict[str, float]]:
        """Return the fitness trajectory across all recorded generations."""
        return [
            {
                "generation": s.generation,
                "best": s.best_fitness,
                "mean": s.mean_fitness,
                "worst": s.worst_fitness,
            }
            for s in self.history
        ]

    def inject(self, vectors: list[AttackVector]) -> None:
        """Inject pre-built vectors into the population (island migration)."""
        self.population.extend(vectors)
        self.population_size = len(self.population)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "population_size": self.population_size,
            "mutation_rate": self.mutation_rate,
            "mutation_sigma": self.mutation_sigma,
            "elite_fraction": self.elite_fraction,
            "stats": self.stats().to_dict(),
        }
