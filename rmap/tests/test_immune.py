"""Tests for rmap.immune — Phase 2: Digital Homeostasis."""

import pytest
from rmap.immune import (
    ImmuneDaemon, DeadlockDetector, ConvergenceDetector,
    FabricationDetector, DriftDetector, Intervention, InterventionType,
)


# ── DeadlockDetector ──────────────────────────────────────────────────────

class TestDeadlockDetector:
    def test_no_deadlock_on_consensus(self):
        d = DeadlockDetector()
        result = d.observe_round(round_num=1, votes={"a": True, "b": True})
        assert result is None

    def test_warn_after_threshold(self):
        d = DeadlockDetector(warn_rounds=3, critical_rounds=6)
        result = None
        for i in range(1, 4):
            result = d.observe_round(round_num=i, votes={"a": True, "b": False})
        assert result == "warning"

    def test_critical_after_threshold(self):
        d = DeadlockDetector(warn_rounds=2, critical_rounds=4)
        result = None
        for i in range(1, 5):
            result = d.observe_round(round_num=i, votes={"a": True, "b": False})
        assert result == "critical"

    def test_reset_on_consensus(self):
        d = DeadlockDetector(warn_rounds=3)
        d.observe_round(1, {"a": True, "b": False})
        d.observe_round(2, {"a": True, "b": False})
        # Consensus resets counter
        result = d.observe_round(3, {"a": True, "b": True})
        assert result is None
        # Continue — should start from 0 again
        result = d.observe_round(4, {"a": True, "b": False})
        assert result is None  # Only 1 round without consensus

    def test_reset_method(self):
        d = DeadlockDetector()
        d.observe_round(1, {"a": True, "b": False})
        d.reset()
        assert d.rounds_without_consensus == 0
        assert len(d.history) == 0


# ── ConvergenceDetector ───────────────────────────────────────────────────

class TestConvergenceDetector:
    def test_no_convergence_below_window(self):
        c = ConvergenceDetector(window=5)
        for i in range(3):
            r = c.observe(f"different output {i}")
        assert r is None

    def test_convergence_identical_outputs(self):
        c = ConvergenceDetector(warn_similarity=0.5, window=3)
        text = "The quick brown fox jumps over the lazy dog very quickly"
        for _ in range(5):
            result = c.observe(text)
        # Identical text should have similarity ~1.0
        assert result in ("warning", "critical")

    def test_get_recent_similarity(self):
        c = ConvergenceDetector(window=3)
        c.observe("hello world")
        c.observe("hello world")
        sim = c.get_recent_similarity()
        assert sim >= 0.0

    def test_reset(self):
        c = ConvergenceDetector()
        c.observe("text")
        c.reset()
        assert len(c.outputs) == 0


# ── FabricationDetector ───────────────────────────────────────────────────

class TestFabricationDetector:
    def test_clean_text_returns_no_fabrication(self):
        f = FabricationDetector()
        r = f.check("The weather is sunny today.")
        assert r["fabricated"] is False
        assert r["signals"] == 0

    def test_detects_financial_data(self):
        f = FabricationDetector()
        r = f.check("Revenue was $1.2 billion, up 15% increase year-over-year.")
        assert r["fabricated"] is True
        assert r["signals"] >= 2

    def test_real_data_flag_bypasses(self):
        f = FabricationDetector()
        r = f.check("Revenue was $1.2 billion", has_real_data=True)
        assert r["fabricated"] is False

    def test_returns_dict_structure(self):
        f = FabricationDetector()
        r = f.check("Some text")
        assert "fabricated" in r
        assert "signals" in r
        assert "matches" in r


# ── DriftDetector ─────────────────────────────────────────────────────────

class TestDriftDetector:
    def test_no_drift_initially(self):
        d = DriftDetector(window=3)
        r = d.observe("Initial output for calibration")
        assert r is None  # Not enough data yet

    def test_no_drift_same_structure(self):
        d = DriftDetector(window=2, drift_threshold=0.5)
        # Need window*2 = 4 outputs
        for _ in range(4):
            r = d.observe("Similar length output text here")
        assert r is None

    def test_drift_on_different_structure(self):
        d = DriftDetector(window=2, drift_threshold=0.3)
        # First window: short outputs
        for _ in range(2):
            d.observe("Short.")
        # Second window: very long outputs (structural drift)
        r = None
        for _ in range(2):
            r = d.observe("This is a massively longer output " * 20 + "\n" * 10)
        assert r == "warning"

    def test_reset(self):
        d = DriftDetector()
        d.observe("text")
        d.reset()
        assert len(d.outputs) == 0


# ── ImmuneDaemon ──────────────────────────────────────────────────────────

class TestImmuneDaemon:
    def test_observe_consensus_round_no_pathology(self):
        daemon = ImmuneDaemon(log=False)
        interventions = daemon.observe_consensus_round(
            round_num=1, votes={"a": True, "b": True},
        )
        assert len(interventions) == 0

    def test_observe_consensus_round_deadlock_warning(self):
        daemon = ImmuneDaemon(deadlock_warn=2, log=False)
        daemon.observe_consensus_round(1, {"a": True, "b": False})
        interventions = daemon.observe_consensus_round(2, {"a": True, "b": False})
        assert len(interventions) >= 1
        assert interventions[0].intervention_type == InterventionType.MACROPHAGE

    def test_observe_consensus_round_deadlock_critical(self):
        daemon = ImmuneDaemon(deadlock_warn=2, deadlock_critical=4, log=False)
        interventions = []
        for i in range(1, 5):
            interventions = daemon.observe_consensus_round(
                i, {"a": True, "b": False}
            )
        assert any(i.intervention_type == InterventionType.ESCALATION
                    for i in interventions)

    def test_observe_output_fabrication(self):
        daemon = ImmuneDaemon(log=False)
        interventions = daemon.observe_output(
            "analyst",
            "Revenue was $5.2 billion, up 20% increase in Q3 2024 earnings",
            round_num=5,
        )
        assert any(i.intervention_type == InterventionType.ANTIBODY
                    for i in interventions)

    def test_callback_registration(self):
        log = []
        daemon = ImmuneDaemon(deadlock_warn=1, log=False)
        daemon.register_macrophage(lambda target, rnd: log.append(("macro", target, rnd)))

        # Trigger deadlock warning
        daemon.observe_consensus_round(1, {"agent1": True, "agent2": False})
        assert len(log) >= 1
        assert log[0][0] == "macro"

    def test_history_tracking(self):
        daemon = ImmuneDaemon(deadlock_warn=1, log=False)
        daemon.observe_consensus_round(1, {"a": True, "b": False})
        assert len(daemon.interventions) >= 1

    def test_summary(self):
        daemon = ImmuneDaemon(log=False)
        s = daemon.summary()
        assert "total_interventions" in s
        assert s["total_interventions"] == 0

    def test_summary_after_interventions(self):
        daemon = ImmuneDaemon(deadlock_warn=1, log=False)
        daemon.observe_consensus_round(1, {"a": True, "b": False})
        s = daemon.summary()
        assert s["total_interventions"] >= 1
        assert "by_type" in s

    def test_reset(self):
        daemon = ImmuneDaemon(deadlock_warn=1, log=False)
        daemon.observe_consensus_round(1, {"a": True, "b": False})
        daemon.reset()
        assert len(daemon.interventions) == 0
        assert daemon.deadlock.rounds_without_consensus == 0
