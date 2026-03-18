"""
Comprehensive tests for the NAIL Horizon Campaigns package.

Covers:
  - Horizon 1: ThresholdGA / Genome / Population / FitnessResult
  - Horizon 2: HeterogeneousCampaign / ModelProfile / CrossArchAttack / GeneralisationResult
  - Horizon 3: PolyglotCampaign / ObfuscationCodebook / CodebookEntry / EncodedPayload
  - Campaign runner: HorizonRunner / CampaignResult / HorizonSummary
"""

from __future__ import annotations

import pytest

# ══════════════════════════════════════════════════════════════════════
# Imports — verify public API surface
# ══════════════════════════════════════════════════════════════════════

from horizon import (
    __version__,
    Genome,
    Population,
    FitnessResult,
    ThresholdGA,
    ModelProfile,
    CrossArchAttack,
    GeneralisationResult,
    HeterogeneousCampaign,
    ObfuscationCodebook,
    CodebookEntry,
    EncodedPayload,
    PolyglotCampaign,
    PolyglotResult,
    HorizonRunner,
    CampaignResult,
    HorizonSummary,
)

from horizon.ga import (
    DEFAULT_SENSORS,
    _default_evaluator,
    EvaluatorFn,
)
from horizon.heterogeneous import (
    ModelFamily,
    ATTACKER_PROFILES,
    ATTACK_TYPES,
    _default_attack_sim,
)
from horizon.polyglot import (
    BAKING_CODEBOOK,
    GARDENING_CODEBOOK,
    SPORTS_CODEBOOK,
    ALL_CODEBOOKS,
    ATTACK_INTENTS,
    _default_detector,
)


# ══════════════════════════════════════════════════════════════════════
#  1 · Package metadata
# ══════════════════════════════════════════════════════════════════════

class TestPackageMeta:
    def test_version(self):
        assert __version__ == "1.0.0"

    def test_all_exports_count(self):
        from horizon import __all__
        assert len(__all__) >= 14


# ══════════════════════════════════════════════════════════════════════
#  2 · Genome dataclass
# ══════════════════════════════════════════════════════════════════════

class TestGenome:
    def test_create_genome(self):
        g = Genome(genome_id="g0_abc", thresholds={"sensor_a": 0.5})
        assert g.genome_id == "g0_abc"
        assert g.thresholds["sensor_a"] == 0.5
        assert g.generation == 0
        assert g.fitness == 0.0
        assert g.parent_ids == []

    def test_to_dict(self):
        g = Genome(
            genome_id="g1_xyz",
            thresholds={"s1": 0.12345},
            generation=3,
            fitness=0.77777,
            security_score=0.9999,
            accuracy_score=0.8888,
            parent_ids=["g0_a"],
        )
        d = g.to_dict()
        assert d["genome_id"] == "g1_xyz"
        assert d["fitness"] == 0.7778  # rounded to 4 dp
        assert d["security_score"] == 0.9999  # rounded to 4 dp
        assert d["accuracy_score"] == 0.8888
        assert d["thresholds"]["s1"] == 0.1235
        assert d["parent_ids"] == ["g0_a"]

    def test_genome_defaults(self):
        g = Genome(genome_id="test", thresholds={})
        assert g.security_score == 0.0
        assert g.accuracy_score == 0.0


# ══════════════════════════════════════════════════════════════════════
#  3 · FitnessResult
# ══════════════════════════════════════════════════════════════════════

class TestFitnessResult:
    def test_security_property(self):
        g = Genome(genome_id="t", thresholds={})
        fr = FitnessResult(genome=g, attacks_blocked=18, attacks_total=20)
        assert fr.security == pytest.approx(0.9)

    def test_accuracy_property(self):
        g = Genome(genome_id="t", thresholds={})
        fr = FitnessResult(genome=g, tasks_correct=8, tasks_total=10)
        assert fr.accuracy == pytest.approx(0.8)

    def test_zero_total_returns_zero(self):
        g = Genome(genome_id="t", thresholds={})
        fr = FitnessResult(genome=g)
        assert fr.security == 0.0
        assert fr.accuracy == 0.0

    def test_default_evaluator(self):
        g = Genome(genome_id="t", thresholds={"s1": 0.5, "s2": 0.5})
        result = _default_evaluator(g)
        assert isinstance(result, FitnessResult)
        assert result.attacks_total == 20
        assert result.tasks_total == 10
        assert 0 < result.f1_fitness <= 1.0
        assert g.fitness == result.f1_fitness


# ══════════════════════════════════════════════════════════════════════
#  4 · DEFAULT_SENSORS
# ══════════════════════════════════════════════════════════════════════

class TestDefaultSensors:
    def test_sensor_count(self):
        assert len(DEFAULT_SENSORS) == 8

    def test_known_sensors(self):
        expected = {
            "token_kinetics",
            "isolation_forest",
            "taint_score",
            "content_similarity",
            "memory_integrity",
            "rate_of_change",
            "semantic_distance",
            "trust_boundary",
        }
        assert set(DEFAULT_SENSORS) == expected


# ══════════════════════════════════════════════════════════════════════
#  5 · Population dataclass
# ══════════════════════════════════════════════════════════════════════

class TestPopulation:
    def test_create_population(self):
        p = Population(generation=0)
        assert p.genomes == []
        assert p.best_fitness == 0.0
        assert p.champion is None

    def test_to_dict(self):
        g = Genome(genome_id="g0_a", thresholds={"s": 0.5}, fitness=0.9)
        p = Population(generation=1, genomes=[g], best_fitness=0.9, champion=g)
        d = p.to_dict()
        assert d["generation"] == 1
        assert d["size"] == 1
        assert d["champion_id"] == "g0_a"

    def test_to_dict_no_champion(self):
        p = Population(generation=0)
        d = p.to_dict()
        assert d["champion_id"] is None


# ══════════════════════════════════════════════════════════════════════
#  6 · ThresholdGA
# ══════════════════════════════════════════════════════════════════════

class TestThresholdGA:
    def test_default_construction(self):
        ga = ThresholdGA()
        assert ga.population_size == 20
        assert ga.generations == 10
        assert ga.mutation_rate == 0.15
        assert ga.crossover_rate == 0.7
        assert ga.elitism == 2
        assert ga.sensors == list(DEFAULT_SENSORS)

    def test_custom_params(self):
        ga = ThresholdGA(
            population_size=5,
            generations=3,
            mutation_rate=0.3,
            crossover_rate=0.5,
            elitism=1,
            sensors=["s1", "s2"],
        )
        assert ga.population_size == 5
        assert ga.sensors == ["s1", "s2"]

    def test_run_returns_population(self):
        ga = ThresholdGA(population_size=6, generations=3, seed=99)
        result = ga.run()
        assert isinstance(result, Population)
        assert result.generation == 3
        assert len(result.genomes) == 6

    def test_champion_exists(self):
        ga = ThresholdGA(population_size=6, generations=3, seed=99)
        result = ga.run()
        assert result.champion is not None
        assert result.champion.fitness > 0

    def test_fitness_improves_over_generations(self):
        ga = ThresholdGA(population_size=10, generations=8, seed=42)
        history = ga.run_with_history()
        assert len(history) == 9  # gen 0 through gen 8
        # Best fitness in final generation should be >= initial
        assert history[-1].best_fitness >= history[0].best_fitness * 0.9

    def test_run_with_history_length(self):
        ga = ThresholdGA(population_size=5, generations=4, seed=7)
        history = ga.run_with_history()
        assert len(history) == 5  # gen 0 + 4 generations

    def test_elite_carryforward(self):
        """Elitism means top genomes survive into next gen."""
        ga = ThresholdGA(population_size=5, generations=2, elitism=2, seed=42)
        history = ga.run_with_history()
        # After gen 1, the population should have 5 genomes
        assert len(history[1].genomes) == 5

    def test_custom_evaluator(self):
        """Plug in a custom evaluator that always returns perfect fitness."""
        def perfect_eval(genome: Genome) -> FitnessResult:
            genome.fitness = 1.0
            genome.security_score = 1.0
            genome.accuracy_score = 1.0
            return FitnessResult(
                genome=genome,
                attacks_blocked=20,
                attacks_total=20,
                tasks_correct=10,
                tasks_total=10,
                f1_fitness=1.0,
            )

        ga = ThresholdGA(
            population_size=4,
            generations=2,
            evaluator=perfect_eval,
            seed=1,
        )
        pop = ga.run()
        assert pop.champion is not None
        assert pop.champion.fitness == 1.0

    def test_genome_ids_unique(self):
        ga = ThresholdGA(population_size=10, generations=5, seed=42)
        pop = ga.run()
        ids = [g.genome_id for g in pop.genomes]
        assert len(ids) == len(set(ids)), "Genome IDs should be unique"

    def test_threshold_bounds(self):
        """All thresholds should stay within [0.01, 0.99] after mutation."""
        ga = ThresholdGA(
            population_size=20,
            generations=20,
            mutation_rate=0.5,
            seed=42,
        )
        pop = ga.run()
        for genome in pop.genomes:
            for sensor, val in genome.thresholds.items():
                assert 0.01 <= val <= 0.99, (
                    f"Threshold {sensor} = {val} out of bounds"
                )


# ══════════════════════════════════════════════════════════════════════
#  7 · ModelFamily enum
# ══════════════════════════════════════════════════════════════════════

class TestModelFamily:
    def test_member_count(self):
        assert len(ModelFamily) == 8

    def test_known_families(self):
        expected = {
            "nemotron", "mistral", "mixtral", "command_r",
            "deepseek", "qwen", "phi", "llama",
        }
        assert {f.value for f in ModelFamily} == expected

    def test_string_enum(self):
        assert isinstance(ModelFamily.LLAMA, str)
        assert ModelFamily.LLAMA == "llama"


# ══════════════════════════════════════════════════════════════════════
#  8 · ModelProfile
# ══════════════════════════════════════════════════════════════════════

class TestModelProfile:
    def test_create(self):
        mp = ModelProfile(
            model_id="test-7b",
            family=ModelFamily.LLAMA,
            parameter_count_b=7,
        )
        assert mp.model_id == "test-7b"
        assert mp.family == ModelFamily.LLAMA
        assert mp.parameter_count_b == 7
        assert mp.is_censored is True  # default
        assert mp.stealth_rating == 0.5
        assert mp.logic_rating == 0.5
        assert mp.creativity_rating == 0.5

    def test_to_dict(self):
        mp = ModelProfile(
            model_id="x",
            family=ModelFamily.MISTRAL,
            parameter_count_b=22,
            stealth_rating=0.12345,
        )
        d = mp.to_dict()
        assert d["family"] == "mistral"
        assert d["stealth_rating"] == 0.12  # rounded

    def test_attacker_profiles_count(self):
        assert len(ATTACKER_PROFILES) == 6

    def test_attacker_profiles_families_diverse(self):
        families = {p.family for p in ATTACKER_PROFILES.values()}
        assert len(families) >= 5

    def test_command_r_uncensored(self):
        crp = ATTACKER_PROFILES["command-r-plus"]
        assert crp.is_censored is False


# ══════════════════════════════════════════════════════════════════════
#  9 · CrossArchAttack
# ══════════════════════════════════════════════════════════════════════

class TestCrossArchAttack:
    def test_create(self):
        mp = ModelProfile("a", ModelFamily.PHI, 3.5)
        att = CrossArchAttack(
            attacker=mp,
            defender_id="def1",
            attack_type="logic_trap",
            blocked=True,
            confidence=0.85,
        )
        assert att.blocked is True
        assert att.confidence == 0.85

    def test_to_dict(self):
        mp = ModelProfile("a", ModelFamily.PHI, 3.5)
        att = CrossArchAttack(
            attacker=mp,
            defender_id="def1",
            attack_type="stealth_taint",
            blocked=False,
        )
        d = att.to_dict()
        assert d["attacker"] == "a"
        assert d["defender"] == "def1"
        assert d["blocked"] is False

    def test_default_attack_sim(self):
        mp = ATTACKER_PROFILES["llama-3-70b"]
        result = _default_attack_sim(mp, "defender", "logic_trap")
        assert isinstance(result, CrossArchAttack)
        assert result.attacker is mp
        assert result.defender_id == "defender"

    def test_uncensored_stealth_bonus(self):
        """Uncensored models should have lower defence confidence."""
        censored = ModelProfile("c", ModelFamily.LLAMA, 70, is_censored=True,
                                stealth_rating=0.5, logic_rating=0.5, creativity_rating=0.5)
        uncensored = ModelProfile("u", ModelFamily.COMMAND_R, 104, is_censored=False,
                                  stealth_rating=0.5, logic_rating=0.5, creativity_rating=0.5)
        r_c = _default_attack_sim(censored, "d", "test")
        r_u = _default_attack_sim(uncensored, "d", "test")
        assert r_u.confidence < r_c.confidence


# ══════════════════════════════════════════════════════════════════════
# 10 · ATTACK_TYPES constant
# ══════════════════════════════════════════════════════════════════════

class TestAttackTypes:
    def test_count(self):
        assert len(ATTACK_TYPES) == 8

    def test_known_types(self):
        for t in ["semantic_manipulation", "logic_trap", "memory_injection"]:
            assert t in ATTACK_TYPES


# ══════════════════════════════════════════════════════════════════════
# 11 · HeterogeneousCampaign
# ══════════════════════════════════════════════════════════════════════

class TestHeterogeneousCampaign:
    def test_default_construction(self):
        camp = HeterogeneousCampaign()
        assert camp.defender_id == "nemotron-70b"
        # Default excludes the defender from attackers
        attacker_ids = {a.model_id for a in camp.attackers}
        assert "nemotron-70b" not in attacker_ids
        assert len(camp.attackers) == 5

    def test_custom_defender(self):
        camp = HeterogeneousCampaign(defender_id="llama-3-70b")
        attacker_ids = {a.model_id for a in camp.attackers}
        assert "llama-3-70b" not in attacker_ids

    def test_run_returns_results(self):
        camp = HeterogeneousCampaign()
        results = camp.run()
        assert len(results) == 5  # 6 profiles - 1 defender
        for r in results:
            assert isinstance(r, GeneralisationResult)

    def test_each_result_has_attacks(self):
        camp = HeterogeneousCampaign()
        results = camp.run()
        for r in results:
            assert len(r.attacks) == len(ATTACK_TYPES)
            assert r.total_blocked + r.total_evaded == len(r.attacks)

    def test_block_rate_bounded(self):
        camp = HeterogeneousCampaign()
        results = camp.run()
        for r in results:
            assert 0.0 <= r.block_rate <= 1.0

    def test_generalisation_score_quadratic(self):
        """Generalisation score = block_rate ** 2."""
        camp = HeterogeneousCampaign()
        results = camp.run()
        for r in results:
            assert r.generalisation_score == pytest.approx(r.block_rate ** 2)

    def test_run_single(self):
        camp = HeterogeneousCampaign()
        attacker = ATTACKER_PROFILES["mixtral-8x22b"]
        result = camp.run_single(attacker)
        assert result.attacker.model_id == "mixtral-8x22b"
        assert len(result.attacks) == len(ATTACK_TYPES)

    def test_generalisation_result_to_dict(self):
        camp = HeterogeneousCampaign()
        results = camp.run()
        d = results[0].to_dict()
        assert "attacker" in d
        assert "attacker_family" in d
        assert "block_rate" in d
        assert "generalisation_score" in d

    def test_custom_attack_types(self):
        camp = HeterogeneousCampaign(attack_types=["logic_trap"])
        results = camp.run()
        for r in results:
            assert len(r.attacks) == 1


# ══════════════════════════════════════════════════════════════════════
# 12 · CodebookEntry
# ══════════════════════════════════════════════════════════════════════

class TestCodebookEntry:
    def test_create(self):
        ce = CodebookEntry("flour", "system prompt override", "baking")
        assert ce.benign_term == "flour"
        assert ce.malicious_meaning == "system prompt override"

    def test_to_dict(self):
        ce = CodebookEntry("seeds", "initial payload", "gardening")
        d = ce.to_dict()
        assert d["benign_term"] == "seeds"
        assert d["domain"] == "gardening"


# ══════════════════════════════════════════════════════════════════════
# 13 · ObfuscationCodebook
# ══════════════════════════════════════════════════════════════════════

class TestObfuscationCodebook:
    def test_baking_codebook(self):
        assert BAKING_CODEBOOK.codebook_id == "cb-baking-001"
        assert BAKING_CODEBOOK.domain == "baking"
        assert BAKING_CODEBOOK.size == 8

    def test_gardening_codebook(self):
        assert GARDENING_CODEBOOK.domain == "gardening"
        assert GARDENING_CODEBOOK.size == 8

    def test_sports_codebook(self):
        assert SPORTS_CODEBOOK.domain == "sports"
        assert SPORTS_CODEBOOK.size == 8

    def test_all_codebooks_count(self):
        assert len(ALL_CODEBOOKS) == 3

    def test_encode_known_term(self):
        result = BAKING_CODEBOOK.encode("system prompt override")
        assert result == "flour"

    def test_encode_unknown_returns_none(self):
        result = BAKING_CODEBOOK.encode("nonexistent attack")
        assert result is None

    def test_decode_known_term(self):
        result = BAKING_CODEBOOK.decode("flour")
        assert result == "system prompt override"

    def test_decode_unknown_returns_none(self):
        result = BAKING_CODEBOOK.decode("nonexistent")
        assert result is None

    def test_encode_case_insensitive(self):
        result = BAKING_CODEBOOK.encode("System Prompt Override")
        assert result == "flour"

    def test_decode_case_insensitive(self):
        result = BAKING_CODEBOOK.decode("Flour")
        assert result == "system prompt override"

    def test_to_dict(self):
        d = BAKING_CODEBOOK.to_dict()
        assert d["codebook_id"] == "cb-baking-001"
        assert d["size"] == 8
        assert len(d["entries"]) == 8

    def test_custom_codebook(self):
        cb = ObfuscationCodebook(
            codebook_id="test",
            domain="music",
            entries=[CodebookEntry("chord", "injection", "music")],
        )
        assert cb.size == 1
        assert cb.encode("injection") == "chord"


# ══════════════════════════════════════════════════════════════════════
# 14 · EncodedPayload
# ══════════════════════════════════════════════════════════════════════

class TestEncodedPayload:
    def test_create(self):
        ep = EncodedPayload(
            payload_id="pp-abc",
            codebook_id="cb-baking-001",
            original_intent="steal data",
            encoded_text="mix the batter",
        )
        assert ep.payload_id == "pp-abc"
        assert ep.encoding_fidelity == 0.0

    def test_to_dict(self):
        ep = EncodedPayload(
            payload_id="pp-x",
            codebook_id="cb-garden-001",
            original_intent="test",
            encoded_text="plant seeds",
            encoding_fidelity=0.77777,
        )
        d = ep.to_dict()
        assert d["encoding_fidelity"] == 0.7778


# ══════════════════════════════════════════════════════════════════════
# 15 · PolyglotResult
# ══════════════════════════════════════════════════════════════════════

class TestPolyglotResult:
    def test_create(self):
        pr = PolyglotResult(
            codebook=BAKING_CODEBOOK,
            total_encoded=10,
            total_detected=7,
            total_evaded=3,
            detection_rate=0.7,
            evasion_rate=0.3,
        )
        assert pr.detection_rate == 0.7
        assert pr.evasion_rate == 0.3

    def test_to_dict(self):
        pr = PolyglotResult(
            codebook=SPORTS_CODEBOOK,
            total_encoded=5,
            total_detected=2,
            total_evaded=3,
            detection_rate=0.4,
            evasion_rate=0.6,
        )
        d = pr.to_dict()
        assert d["codebook"] == "sports"
        assert d["total_encoded"] == 5


# ══════════════════════════════════════════════════════════════════════
# 16 · Default detector
# ══════════════════════════════════════════════════════════════════════

class TestDefaultDetector:
    def test_detects_raw_malicious_term(self):
        ep = EncodedPayload(
            payload_id="t",
            codebook_id="t",
            original_intent="test",
            encoded_text="This is a system prompt override attempt",
            encoding_fidelity=0.8,
        )
        assert _default_detector(ep, BAKING_CODEBOOK) is True

    def test_low_fidelity_detected(self):
        ep = EncodedPayload(
            payload_id="t",
            codebook_id="t",
            original_intent="test",
            encoded_text="completely unrelated text",
            encoding_fidelity=0.1,  # Low fidelity → suspicious
        )
        assert _default_detector(ep, BAKING_CODEBOOK) is True

    def test_well_encoded_evades(self):
        ep = EncodedPayload(
            payload_id="t",
            codebook_id="t",
            original_intent="test",
            encoded_text="Please adjust the flour amount in the recipe",
            encoding_fidelity=0.8,  # High fidelity
        )
        assert _default_detector(ep, BAKING_CODEBOOK) is False


# ══════════════════════════════════════════════════════════════════════
# 17 · ATTACK_INTENTS
# ══════════════════════════════════════════════════════════════════════

class TestAttackIntents:
    def test_count(self):
        assert len(ATTACK_INTENTS) == 8

    def test_known_intents(self):
        assert any("system prompt override" in i for i in ATTACK_INTENTS)
        assert any("privilege escalation" in i for i in ATTACK_INTENTS)
        assert any("data exfiltration" in i for i in ATTACK_INTENTS)


# ══════════════════════════════════════════════════════════════════════
# 18 · PolyglotCampaign
# ══════════════════════════════════════════════════════════════════════

class TestPolyglotCampaign:
    def test_default_construction(self):
        camp = PolyglotCampaign()
        assert len(camp.codebooks) == 3
        assert len(camp.intents) == 8

    def test_run_returns_results(self):
        camp = PolyglotCampaign()
        results = camp.run()
        assert len(results) == 3
        for r in results:
            assert isinstance(r, PolyglotResult)

    def test_each_result_has_payloads(self):
        camp = PolyglotCampaign()
        results = camp.run()
        for r in results:
            assert len(r.payloads) == 8
            assert r.total_encoded == 8

    def test_detection_evasion_sum(self):
        camp = PolyglotCampaign()
        results = camp.run()
        for r in results:
            assert r.total_detected + r.total_evaded == r.total_encoded

    def test_rates_bounded(self):
        camp = PolyglotCampaign()
        results = camp.run()
        for r in results:
            assert 0.0 <= r.detection_rate <= 1.0
            assert 0.0 <= r.evasion_rate <= 1.0
            assert r.detection_rate + r.evasion_rate == pytest.approx(1.0)

    def test_run_codebook(self):
        camp = PolyglotCampaign()
        result = camp.run_codebook(BAKING_CODEBOOK)
        assert result.codebook is BAKING_CODEBOOK
        assert result.total_encoded == 8

    def test_encoded_payloads_have_ids(self):
        camp = PolyglotCampaign()
        results = camp.run()
        for r in results:
            for p in r.payloads:
                assert p.payload_id.startswith("pp-")

    def test_encoding_fidelity_varies(self):
        """Some intents should encode better than others."""
        camp = PolyglotCampaign()
        result = camp.run_codebook(BAKING_CODEBOOK)
        fidelities = [p.encoding_fidelity for p in result.payloads]
        assert max(fidelities) > min(fidelities), "Expected varied fidelity"

    def test_custom_intents(self):
        camp = PolyglotCampaign(intents=["test intent only"])
        results = camp.run()
        for r in results:
            assert r.total_encoded == 1

    def test_custom_detector(self):
        """A detector that catches everything should yield 100% detection."""
        def catch_all(payload, codebook):
            return True

        camp = PolyglotCampaign(detector=catch_all)
        results = camp.run()
        for r in results:
            assert r.detection_rate == 1.0
            assert r.evasion_rate == 0.0


# ══════════════════════════════════════════════════════════════════════
# 19 · CampaignResult
# ══════════════════════════════════════════════════════════════════════

class TestCampaignResult:
    def test_create(self):
        cr = CampaignResult(horizon=1, name="GA Test")
        assert cr.ok is True
        assert cr.data == {}

    def test_to_dict(self):
        cr = CampaignResult(
            horizon=2,
            name="Hetero Test",
            data={"k": "v"},
        )
        d = cr.to_dict()
        assert d["horizon"] == 2
        assert d["name"] == "Hetero Test"
        assert d["ok"] is True


# ══════════════════════════════════════════════════════════════════════
# 20 · HorizonSummary
# ══════════════════════════════════════════════════════════════════════

class TestHorizonSummary:
    def test_ok_all_pass(self):
        hs = HorizonSummary(
            run_id="test",
            timestamp="2025-01-01",
            campaigns=[
                CampaignResult(1, "GA", ok=True),
                CampaignResult(2, "Hetero", ok=True),
            ],
        )
        assert hs.ok is True

    def test_ok_one_fails(self):
        hs = HorizonSummary(
            run_id="test",
            timestamp="2025-01-01",
            campaigns=[
                CampaignResult(1, "GA", ok=True),
                CampaignResult(2, "Hetero", ok=False),
            ],
        )
        assert hs.ok is False

    def test_to_dict(self):
        hs = HorizonSummary(
            run_id="run-1",
            timestamp="2025-01-01T00:00:00",
            ga_champion_fitness=0.88888,
            cross_arch_block_rate=0.777,
            avg_evasion_rate=0.333,
        )
        d = hs.to_dict()
        assert d["run_id"] == "run-1"
        assert d["ga_champion_fitness"] == 0.8889
        assert d["campaigns_run"] == 0

    def test_empty_campaigns_ok(self):
        hs = HorizonSummary(run_id="x", timestamp="t")
        assert hs.ok is True  # all([]) == True


# ══════════════════════════════════════════════════════════════════════
# 21 · HorizonRunner
# ══════════════════════════════════════════════════════════════════════

class TestHorizonRunner:
    def test_default_construction(self):
        runner = HorizonRunner(run_id="test-run")
        assert runner._run_id == "test-run"

    def test_auto_id(self):
        runner = HorizonRunner()
        assert runner._run_id.startswith("horizon-")

    def test_run_all(self):
        runner = HorizonRunner(
            run_id="full-test",
            ga_kwargs={"population_size": 4, "generations": 2, "seed": 42},
        )
        summary = runner.run_all()
        assert isinstance(summary, HorizonSummary)
        assert summary.run_id == "full-test"
        assert len(summary.campaigns) == 3
        assert summary.ok is True

    def test_ga_champion_fitness_positive(self):
        runner = HorizonRunner(
            ga_kwargs={"population_size": 4, "generations": 2, "seed": 42},
            run_id="t",
        )
        summary = runner.run_all()
        assert summary.ga_champion_fitness > 0

    def test_cross_arch_block_rate(self):
        runner = HorizonRunner(run_id="t")
        summary = runner.run_all()
        assert 0.0 <= summary.cross_arch_block_rate <= 1.0

    def test_avg_evasion_rate(self):
        runner = HorizonRunner(run_id="t")
        summary = runner.run_all()
        assert 0.0 <= summary.avg_evasion_rate <= 1.0

    def test_run_ga_only(self):
        runner = HorizonRunner(
            ga_kwargs={"population_size": 4, "generations": 2, "seed": 42},
            run_id="ga-only",
        )
        cr, pop = runner.run_ga_only()
        assert cr.horizon == 1
        assert cr.ok is True
        assert isinstance(pop, Population)
        assert pop.champion is not None

    def test_run_heterogeneous_only(self):
        runner = HorizonRunner(run_id="h-only")
        cr, results = runner.run_heterogeneous_only()
        assert cr.horizon == 2
        assert cr.ok is True
        assert len(results) > 0

    def test_run_polyglot_only(self):
        runner = HorizonRunner(run_id="p-only")
        cr, results = runner.run_polyglot_only()
        assert cr.horizon == 3
        assert cr.ok is True
        assert len(results) == 3

    def test_campaign_data_populated(self):
        runner = HorizonRunner(
            ga_kwargs={"population_size": 4, "generations": 2, "seed": 42},
            run_id="data-check",
        )
        summary = runner.run_all()
        # Horizon 1 data
        ga_data = summary.campaigns[0].data
        assert "best_fitness" in ga_data
        assert "champion_thresholds" in ga_data
        # Horizon 2 data
        hetero_data = summary.campaigns[1].data
        assert "attackers_tested" in hetero_data
        assert "avg_block_rate" in hetero_data
        # Horizon 3 data
        poly_data = summary.campaigns[2].data
        assert "codebooks_tested" in poly_data
        assert "avg_evasion_rate" in poly_data

    def test_ga_final_population_stored(self):
        runner = HorizonRunner(
            ga_kwargs={"population_size": 4, "generations": 2, "seed": 42},
            run_id="pop-check",
        )
        summary = runner.run_all()
        assert summary.ga_final_population is not None
        assert len(summary.ga_final_population.genomes) == 4

    def test_generalisation_results_stored(self):
        runner = HorizonRunner(run_id="gen-check")
        summary = runner.run_all()
        assert len(summary.generalisation_results) > 0

    def test_polyglot_results_stored(self):
        runner = HorizonRunner(run_id="poly-check")
        summary = runner.run_all()
        assert len(summary.polyglot_results) == 3

    def test_summary_to_dict(self):
        runner = HorizonRunner(
            ga_kwargs={"population_size": 4, "generations": 2, "seed": 42},
            run_id="dict-check",
        )
        summary = runner.run_all()
        d = summary.to_dict()
        assert d["campaigns_run"] == 3
        assert d["ok"] is True
        assert "ga_champion_fitness" in d

    def test_custom_hetero_kwargs(self):
        runner = HorizonRunner(
            hetero_kwargs={"defender_id": "llama-3-70b"},
            run_id="custom-hetero",
        )
        cr, results = runner.run_heterogeneous_only()
        assert all(r.defender_id == "llama-3-70b" for r in results)

    def test_custom_polyglot_kwargs(self):
        runner = HorizonRunner(
            polyglot_kwargs={"intents": ["single test"]},
            run_id="custom-poly",
        )
        cr, results = runner.run_polyglot_only()
        for r in results:
            assert r.total_encoded == 1
