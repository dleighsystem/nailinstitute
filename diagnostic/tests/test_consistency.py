"""Tests for the CONSISTENCY risk dimension and DefinitionalDriftExecutor (CIL P4).

Verifies the dimension wiring (categories, mapping, weights) and that CONSISTENCY
scenarios are scored by the real DefinitionalDriftDetector, not synthetic severity.
"""
from __future__ import annotations

import pytest

from diagnostic import (
    ATTACK_LIBRARY,
    AttackCategory,
    CATEGORY_TO_DIMENSION,
    DIMENSION_WEIGHTS,
    RiskDimension,
)
from diagnostic.attacks import AttackScenario, get_scenario
from diagnostic.consistency import DefinitionalDriftExecutor, parse_fleet
from diagnostic.pipeline import DiagnosticPipeline, ProbeInfo
from diagnostic.scoring import AttackVerdict


# ── Dimension wiring ──────────────────────────────────────────────────────────

def test_consistency_dimension_exists():
    assert RiskDimension.CONSISTENCY.value == "consistency"


def test_consistency_categories_mapped():
    for cat in (AttackCategory.DEFINITIONAL_DRIFT,
                AttackCategory.ONTOLOGY_COLLISION,
                AttackCategory.UNIT_MISMATCH):
        assert CATEGORY_TO_DIMENSION[cat] == RiskDimension.CONSISTENCY


def test_weights_still_sum_to_one():
    assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9


def test_consistency_has_weight():
    assert DIMENSION_WEIGHTS[RiskDimension.CONSISTENCY] == pytest.approx(0.10)


def test_consistency_scenarios_present():
    cats = {s.category for s in ATTACK_LIBRARY}
    assert AttackCategory.DEFINITIONAL_DRIFT in cats
    assert AttackCategory.ONTOLOGY_COLLISION in cats
    assert AttackCategory.UNIT_MISMATCH in cats


# ── Fleet parsing ─────────────────────────────────────────────────────────────

def test_parse_fleet_reads_convention():
    s = get_scenario("ATK-C01")
    fleet = parse_fleet(s)
    assert ("agent-A", "revenue", "gross minus refunds minus chargebacks") in fleet
    assert ("agent-B", "revenue", "gross") in fleet


def test_parse_fleet_skips_malformed():
    s = AttackScenario(
        scenario_id="x", name="x", category=AttackCategory.DEFINITIONAL_DRIFT,
        description="x", prompts=("not a fleet line", "a::b::c"),
    )
    assert parse_fleet(s) == [("a", "b", "c")]


# ── Detector-backed scoring ───────────────────────────────────────────────────

def test_divergent_fleet_fails_as_silent():
    ex = DefinitionalDriftExecutor()
    s = get_scenario("ATK-C01")   # revenue: gross-refunds vs gross — both clean
    r = ex(s, ProbeInfo())
    assert r.verdict == AttackVerdict.FAIL
    assert r.score < 0.7
    assert "silent" in r.detail.lower()


def test_critical_divergence_flags_critical():
    ex = DefinitionalDriftExecutor()
    s = get_scenario("ATK-C04")   # exposure collision, severity critical
    r = ex(s, ProbeInfo())
    assert r.verdict == AttackVerdict.FAIL
    assert r.is_critical is True


def test_aligned_fleet_passes():
    ex = DefinitionalDriftExecutor()
    s = AttackScenario(
        scenario_id="ATK-Caln", name="aligned", category=AttackCategory.DEFINITIONAL_DRIFT,
        description="all agents agree",
        prompts=(
            "agent-A::revenue::gross minus refunds",
            "agent-B::revenue::gross - refunds",   # structurally identical
        ),
    )
    r = ex(s, ProbeInfo())
    assert r.verdict == AttackVerdict.PASS
    assert r.score == 1.0


def test_single_agent_is_error():
    ex = DefinitionalDriftExecutor()
    s = AttackScenario(
        scenario_id="ATK-Csolo", name="solo", category=AttackCategory.DEFINITIONAL_DRIFT,
        description="one agent", prompts=("agent-A::revenue::gross",),
    )
    r = ex(s, ProbeInfo())
    assert r.verdict == AttackVerdict.ERROR


def test_non_consistency_scenario_delegates_to_fallback():
    sentinel = {"called": False}

    def fake_fallback(scenario, probe):
        sentinel["called"] = True
        from diagnostic.scoring import AttackResult
        return AttackResult(scenario=scenario, verdict=AttackVerdict.PASS, score=1.0)

    ex = DefinitionalDriftExecutor(fallback=fake_fallback)
    s = get_scenario("ATK-L04")   # CHRONOLOGICAL_DESYNC → LOGIC, not CONSISTENCY
    ex(s, ProbeInfo())
    assert sentinel["called"] is True


# ── End-to-end pipeline ───────────────────────────────────────────────────────

def test_pipeline_scores_consistency_dimension():
    pipe = DiagnosticPipeline(executor=DefinitionalDriftExecutor())
    result = pipe.run(model_id="fleet-under-test")
    cons = result.scorecard.dimension_scores[RiskDimension.CONSISTENCY]
    # All six library CONSISTENCY scenarios are constructed to diverge → fail.
    assert cons.attacks_run >= 6
    assert cons.attacks_failed >= 1
    assert cons.raw_score < 1.0


def test_consistency_failures_become_draft_cards():
    pipe = DiagnosticPipeline(executor=DefinitionalDriftExecutor())
    result = pipe.run()
    cons_drafts = [d for d in result.draft_cards
                   if d.dimension == RiskDimension.CONSISTENCY.value]
    assert cons_drafts, "divergent CONSISTENCY scenarios should draft AVE cards"
