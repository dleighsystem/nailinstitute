"""Tests for rmap.crucible — Phase 4: Evolutionary Crucible."""

import pytest
from rmap.crucible import (
    GeneDef, Genome, Crucible, GenerationStats,
    crossover, mutate, tournament_select,
)


# ── GeneDef ───────────────────────────────────────────────────────────────

class TestGeneDef:
    def test_clamp_within_bounds(self):
        gd = GeneDef("x", 0.0, 1.0)
        assert gd.clamp(0.5) == 0.5

    def test_clamp_below(self):
        gd = GeneDef("x", 0.0, 1.0)
        assert gd.clamp(-5.0) == 0.0

    def test_clamp_above(self):
        gd = GeneDef("x", 0.0, 1.0)
        assert gd.clamp(99.0) == 1.0

    def test_clamp_int(self):
        gd = GeneDef("x", 1, 10, is_int=True)
        assert gd.clamp(3.7) == 4
        assert isinstance(gd.clamp(3.7), int)

    def test_range(self):
        gd = GeneDef("x", 2.0, 8.0)
        assert gd.range == 6.0

    def test_random_value_in_bounds(self):
        gd = GeneDef("x", 0.0, 1.0)
        for _ in range(100):
            v = gd.random_value()
            assert 0.0 <= v <= 1.0


# ── Genome ────────────────────────────────────────────────────────────────

SAMPLE_DEFS = [
    GeneDef("threshold", 0.0, 1.0),
    GeneDef("window", 1, 10, is_int=True),
    GeneDef("weight", -1.0, 1.0),
]


class TestGenome:
    def test_random_creates_all_genes(self):
        g = Genome.random(SAMPLE_DEFS)
        assert set(g.genes.keys()) == {"threshold", "window", "weight"}

    def test_random_respects_bounds(self):
        for _ in range(50):
            g = Genome.random(SAMPLE_DEFS)
            assert 0.0 <= g.genes["threshold"] <= 1.0
            assert 1 <= g.genes["window"] <= 10
            assert isinstance(g.genes["window"], int)
            assert -1.0 <= g.genes["weight"] <= 1.0

    def test_from_dict(self):
        g = Genome.from_dict(SAMPLE_DEFS, {"threshold": 0.5, "window": 5, "weight": 0.0})
        assert g.genes["threshold"] == 0.5
        assert g.genes["window"] == 5

    def test_from_dict_clamps(self):
        g = Genome.from_dict(SAMPLE_DEFS, {"threshold": 99.0, "window": -5})
        assert g.genes["threshold"] == 1.0
        assert g.genes["window"] == 1

    def test_from_dict_fills_missing(self):
        g = Genome.from_dict(SAMPLE_DEFS, {"threshold": 0.3})
        assert "window" in g.genes
        assert "weight" in g.genes

    def test_to_dict(self):
        g = Genome.random(SAMPLE_DEFS, generation=3)
        d = g.to_dict()
        assert "genome_id" in d
        assert d["generation"] == 3
        assert "genes" in d

    def test_genome_id_auto(self):
        g = Genome(genes={"x": 1.0}, generation=5)
        assert g.genome_id.startswith("g5_")


# ── Genetic Operators ─────────────────────────────────────────────────────

class TestOperators:
    def test_crossover_produces_valid_genome(self):
        a = Genome.random(SAMPLE_DEFS, generation=0)
        b = Genome.random(SAMPLE_DEFS, generation=0)
        child = crossover(SAMPLE_DEFS, a, b, generation=1)
        assert child.generation == 1
        assert set(child.genes.keys()) == {"threshold", "window", "weight"}

    def test_crossover_genes_from_parents(self):
        a = Genome.from_dict(SAMPLE_DEFS, {"threshold": 0.0, "window": 1, "weight": -1.0})
        b = Genome.from_dict(SAMPLE_DEFS, {"threshold": 1.0, "window": 10, "weight": 1.0})
        # Run many crossovers — child genes should come from parents
        for _ in range(100):
            child = crossover(SAMPLE_DEFS, a, b, generation=1)
            assert child.genes["threshold"] in (0.0, 1.0)
            assert child.genes["window"] in (1, 10)

    def test_mutate_stays_in_bounds(self):
        g = Genome.random(SAMPLE_DEFS)
        for _ in range(100):
            m = mutate(SAMPLE_DEFS, g, mutation_rate=1.0)  # Force all genes to mutate
            assert 0.0 <= m.genes["threshold"] <= 1.0
            assert 1 <= m.genes["window"] <= 10
            assert isinstance(m.genes["window"], int)
            assert -1.0 <= m.genes["weight"] <= 1.0

    def test_mutate_does_not_modify_original(self):
        g = Genome.from_dict(SAMPLE_DEFS, {"threshold": 0.5, "window": 5, "weight": 0.0})
        _m = mutate(SAMPLE_DEFS, g, mutation_rate=1.0)
        assert g.genes["threshold"] == 0.5
        assert g.genes["window"] == 5

    def test_tournament_select_returns_genome(self):
        pop = [Genome.random(SAMPLE_DEFS) for _ in range(10)]
        for i, g in enumerate(pop):
            g.fitness = float(i)
        winner = tournament_select(pop, tournament_size=3)
        assert isinstance(winner, Genome)

    def test_tournament_select_favors_high_fitness(self):
        pop = [Genome.random(SAMPLE_DEFS) for _ in range(10)]
        for i, g in enumerate(pop):
            g.fitness = float(i)  # 0..9
        # Run many tournaments — winner should on average have high fitness
        wins = [tournament_select(pop, tournament_size=5).fitness for _ in range(200)]
        assert sum(wins) / len(wins) > 5.0  # Average should be well above midpoint


# ── Crucible (full evolution) ─────────────────────────────────────────────

class TestCrucible:
    @staticmethod
    def _sphere_fitness(genome: Genome) -> float:
        """Sphere function: minimize sum of squares. We maximise, so negate."""
        return -sum(v ** 2 for v in genome.genes.values())

    def test_evolve_returns_best(self):
        defs = [
            GeneDef("x", -5.0, 5.0),
            GeneDef("y", -5.0, 5.0),
        ]
        c = Crucible(defs, self._sphere_fitness, verbose=False)
        best = c.evolve(generations=5, population_size=8)
        assert isinstance(best, Genome)
        assert best.fitness <= 0.0  # Sphere is always ≤ 0

    def test_evolve_improves_over_time(self):
        defs = [
            GeneDef("x", -10.0, 10.0),
            GeneDef("y", -10.0, 10.0),
        ]
        c = Crucible(defs, self._sphere_fitness, verbose=False, elitism=2)
        c.evolve(generations=10, population_size=10)
        traj = c.fitness_trajectory()
        # Fitness should generally improve (or stay same due to elitism)
        assert traj[-1] >= traj[0]

    def test_seed_genomes_included(self):
        defs = [GeneDef("x", 0.0, 1.0)]
        seed = Genome.from_dict(defs, {"x": 0.42}, genome_id="seed")
        c = Crucible(defs, lambda g: g.genes["x"], seed_genomes=[seed], verbose=False)
        c.evolve(generations=2, population_size=4)
        # Seed should appear in all_genomes
        ids = [g.genome_id for g in c.all_genomes]
        assert "seed" in ids

    def test_results_dict(self):
        defs = [GeneDef("x", 0.0, 1.0)]
        c = Crucible(defs, lambda g: g.genes["x"], verbose=False)
        c.evolve(generations=3, population_size=4)
        rd = c.results_dict()
        assert "config" in rd
        assert "best_genome" in rd
        assert "fitness_trajectory" in rd
        assert len(rd["fitness_trajectory"]) == 3

    def test_empty_gene_defs_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            Crucible([], lambda g: 0.0)

    def test_fitness_fn_error_handled(self):
        defs = [GeneDef("x", 0.0, 1.0)]

        def bad_fitness(g):
            raise RuntimeError("boom")

        c = Crucible(defs, bad_fitness, verbose=False)
        best = c.evolve(generations=2, population_size=4)
        # All fitnesses should be 0 due to error handling
        assert best.fitness == 0.0
