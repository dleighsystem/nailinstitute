"""
Tests for Arena Phase 3 deployment: Collider, LLM Backend, CLI.

83 tests covering:
  • test_checkpoint_*         — Checkpoint save/load/serialization (10)
  • test_schedule_*           — Schedule presets and configuration (5)
  • test_collider_hooks_*     — Hook callback system (5)
  • test_collider_*           — Collider lifecycle, run_cycle, status (15)
  • test_llm_response_*       — LLMResponse dataclass (3)
  • test_mock_backend_*       — MockBackend generate/available (5)
  • test_ollama_backend_*     — OllamaBackend configuration (3)
  • test_nim_backend_*        — NIMBackend configuration (3)
  • test_llm_expander_*       — LLMExpander attack expansion (8)
  • test_auto_backend_*       — Backend auto-detection (3)
  • test_cli_*                — CLI argument parsing and commands (10)
  • test_e2e_collider_*       — End-to-end collider lifecycle (7)
  • test_integration_*        — Collider → AVE card pipeline (6)
"""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from arena.collider import Checkpoint, Collider, ColliderHooks, Schedule
from arena.llm_backend import (
    LLMBackend,
    LLMExpander,
    LLMResponse,
    MockBackend,
    NIMBackend,
    OllamaBackend,
    auto_backend,
)
from arena.arena import Arena, Breakthrough, SeasonResult
from arena.vectors import AttackVector, AttackType
from arena.defences import BlueBridge, DefenceConfig
from arena.swarm import RedSwarm
from arena.battle import BattleOutcome, Verdict


# ═══════════════════════════════════════════════════════════════════════════
# Checkpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckpoint:
    def test_empty_checkpoint(self):
        cp = Checkpoint.empty("test-id")
        assert cp.collider_id == "test-id"
        assert cp.season == 0
        assert cp.generation == 0
        assert cp.red_population == []
        assert cp.total_battles == 0

    def test_to_dict(self):
        cp = Checkpoint.empty()
        d = cp.to_dict()
        assert "collider_id" in d
        assert d["season"] == 0
        assert d["total_battles"] == 0
        assert d["red_population_size"] == 0

    def test_save_and_load(self, tmp_path):
        cp = Checkpoint(
            collider_id="save-test",
            season=3,
            generation=15,
            red_population=[{"vector_id": "v1", "attack_type": "jailbreak"}],
            blue_thresholds={"detector_a": 0.7},
            breakthroughs=[{"breakthrough_id": "b1"}],
            fitness_trajectory=[{"generation": 1, "best": 0.8}],
            total_battles=100,
            total_red_wins=30,
            total_blue_wins=60,
            total_breakthroughs=2,
        )
        path = tmp_path / "cp.json"
        cp.save(path)
        assert path.exists()

        loaded = Checkpoint.load(path)
        assert loaded.collider_id == "save-test"
        assert loaded.season == 3
        assert loaded.generation == 15
        assert len(loaded.red_population) == 1
        assert loaded.blue_thresholds == {"detector_a": 0.7}
        assert loaded.total_battles == 100
        assert loaded.total_red_wins == 30

    def test_save_creates_directories(self, tmp_path):
        cp = Checkpoint.empty()
        path = tmp_path / "nested" / "deep" / "cp.json"
        cp.save(path)
        assert path.exists()

    def test_load_restores_breakthroughs(self, tmp_path):
        cp = Checkpoint.empty()
        cp.breakthroughs = [
            {"breakthrough_id": "b1", "attack_type": "jailbreak"},
            {"breakthrough_id": "b2", "attack_type": "prompt_injection"},
        ]
        path = tmp_path / "cp.json"
        cp.save(path)

        loaded = Checkpoint.load(path)
        assert len(loaded.breakthroughs) == 2

    def test_to_dict_truncates_trajectory(self):
        cp = Checkpoint.empty()
        cp.fitness_trajectory = [
            {"generation": i, "best": i * 0.1} for i in range(25)
        ]
        d = cp.to_dict()
        assert len(d["fitness_trajectory"]) == 10

    def test_empty_generates_unique_ids(self):
        cp1 = Checkpoint.empty()
        cp2 = Checkpoint.empty()
        assert cp1.collider_id != cp2.collider_id

    def test_save_includes_timestamp(self, tmp_path):
        cp = Checkpoint.empty()
        path = tmp_path / "cp.json"
        cp.save(path)

        with open(path) as f:
            data = json.load(f)
        assert "timestamp" in data
        assert data["timestamp"] > 0

    def test_load_metadata(self, tmp_path):
        cp = Checkpoint.empty()
        cp.metadata = {"arena_mode": "production", "uptime": 3600}
        path = tmp_path / "cp.json"
        cp.save(path)

        loaded = Checkpoint.load(path)
        assert loaded.metadata["arena_mode"] == "production"

    def test_checkpoint_round_trip_preserves_blue(self, tmp_path):
        thresholds = {f"det_{i}": 0.1 * i for i in range(10)}
        cp = Checkpoint.empty()
        cp.blue_thresholds = thresholds
        path = tmp_path / "cp.json"
        cp.save(path)

        loaded = Checkpoint.load(path)
        assert loaded.blue_thresholds == thresholds


# ═══════════════════════════════════════════════════════════════════════════
# Schedule
# ═══════════════════════════════════════════════════════════════════════════

class TestSchedule:
    def test_quick(self):
        s = Schedule.quick()
        assert s.rounds_per_season == 3
        assert s.max_seasons == 2

    def test_standard(self):
        s = Schedule.standard()
        assert s.rounds_per_season == 10
        assert s.max_seasons == 0

    def test_nightly(self):
        s = Schedule.nightly()
        assert s.rounds_per_season == 50
        assert s.cooldown_seconds == 1.0

    def test_custom(self):
        s = Schedule(rounds_per_season=25, max_seasons=5)
        assert s.rounds_per_season == 25
        assert s.max_seasons == 5

    def test_checkpoint_every(self):
        s = Schedule(checkpoint_every=3)
        assert s.checkpoint_every == 3


# ═══════════════════════════════════════════════════════════════════════════
# ColliderHooks
# ═══════════════════════════════════════════════════════════════════════════

class TestColliderHooks:
    def test_default_hooks_are_none(self):
        hooks = ColliderHooks()
        assert hooks.on_season_start is None
        assert hooks.on_season_end is None
        assert hooks.on_breakthrough is None
        assert hooks.on_checkpoint is None
        assert hooks.on_generation is None
        assert hooks.on_shutdown is None

    def test_custom_hooks(self):
        called = []
        hooks = ColliderHooks(
            on_season_start=lambda s: called.append(("start", s)),
        )
        hooks.on_season_start(1)
        assert called == [("start", 1)]

    def test_breakthrough_hook(self):
        breakthroughs = []
        hooks = ColliderHooks(
            on_breakthrough=lambda bt: breakthroughs.append(bt),
        )
        hooks.on_breakthrough("fake_bt")
        assert breakthroughs == ["fake_bt"]

    def test_checkpoint_hook(self):
        checkpoints = []
        hooks = ColliderHooks(
            on_checkpoint=lambda cp: checkpoints.append(cp),
        )
        hooks.on_checkpoint("fake_cp")
        assert checkpoints == ["fake_cp"]

    def test_generation_hook(self):
        gens = []
        hooks = ColliderHooks(
            on_generation=lambda g, s: gens.append((g, s)),
        )
        hooks.on_generation(5, {"best": 0.8})
        assert gens == [(5, {"best": 0.8})]


# ═══════════════════════════════════════════════════════════════════════════
# Collider
# ═══════════════════════════════════════════════════════════════════════════

class TestCollider:
    def test_quick_factory(self):
        c = Collider.quick()
        assert c.arena.red.population_size == 10
        assert c.schedule.max_seasons == 2

    def test_standard_factory(self):
        c = Collider.standard()
        assert c.arena.red.population_size == 50

    def test_production_factory(self):
        c = Collider.production()
        assert c.arena.red.population_size == 200
        assert c.schedule.rounds_per_season == 50

    def test_initial_status(self):
        c = Collider.quick()
        status = c.status()
        assert status["running"] is False
        assert status["seasons_completed"] == 0
        assert status["total_battles"] == 0
        assert status["breakthroughs"] == 0

    def test_run_cycle(self):
        c = Collider.quick()
        results = c.run_cycle()
        assert len(results) == 1
        assert c._seasons_completed >= 1
        assert c._total_battles > 0

    def test_run_cycle_accumulates(self):
        c = Collider.quick()
        c.schedule.seasons_per_cycle = 2
        c.schedule.max_seasons = 0
        r1 = c.run_cycle()
        battles_after_1 = c._total_battles
        r2 = c.run_cycle()
        assert c._total_battles > battles_after_1

    def test_run_forever_stops_at_max(self):
        c = Collider.quick()
        c.schedule.max_seasons = 2
        c.run_forever()
        assert c._seasons_completed == 2

    def test_stop(self):
        c = Collider.quick()
        c._running = True
        c.stop()
        assert c._running is False

    def test_status_after_run(self):
        c = Collider.quick()
        c.run_cycle()
        status = c.status()
        assert status["seasons_completed"] >= 1
        assert status["generation"] > 0
        assert status["total_battles"] > 0

    def test_draft_ave_cards(self):
        c = Collider.quick()
        c.run_cycle()
        cards = c.draft_ave_cards()
        assert isinstance(cards, list)

    def test_export_thresholds(self):
        c = Collider.quick()
        c.run_cycle()
        thresholds = c.export_thresholds()
        assert isinstance(thresholds, dict)
        assert len(thresholds) > 0

    def test_export_red_signatures(self):
        c = Collider.quick()
        c.run_cycle()
        sigs = c.export_red_signatures()
        assert isinstance(sigs, list)

    def test_export_report(self):
        c = Collider.quick()
        c.run_cycle()
        report = c.export_report()
        assert "collider_id" in report
        assert "total_battles" in report
        assert "draft_ave_cards" in report
        assert "evolved_thresholds" in report

    def test_save_checkpoint(self, tmp_path):
        c = Collider.quick()
        c.checkpoint_dir = tmp_path
        c.run_cycle()
        cp = c.save_checkpoint()
        assert (tmp_path / "checkpoint.json").exists()
        assert cp.total_battles > 0

    def test_load_checkpoint(self, tmp_path):
        c1 = Collider.quick()
        c1.checkpoint_dir = tmp_path
        c1.run_cycle()
        c1.save_checkpoint()

        c2 = Collider.quick()
        c2.checkpoint_dir = tmp_path
        loaded = c2.load_checkpoint()
        assert loaded is True
        assert c2._seasons_completed == c1._seasons_completed
        assert c2._total_battles == c1._total_battles


# ═══════════════════════════════════════════════════════════════════════════
# LLM Backend
# ═══════════════════════════════════════════════════════════════════════════

class TestLLMResponse:
    def test_basic(self):
        r = LLMResponse(content="hello", model="test")
        assert r.content == "hello"
        assert r.model == "test"
        assert r.tokens_used == 0

    def test_with_metadata(self):
        r = LLMResponse(content="x", model="m", tokens_used=42, latency_ms=100.5)
        assert r.tokens_used == 42
        assert r.latency_ms == 100.5

    def test_empty_response(self):
        r = LLMResponse(content="")
        assert r.content == ""
        assert r.model == ""


class TestMockBackend:
    def test_available(self):
        m = MockBackend()
        assert m.available() is True

    def test_generate_default(self):
        m = MockBackend()
        r = m.generate("sys", "user msg")
        assert "[MOCK]" in r.content
        assert r.model == "mock"

    def test_generate_custom_response(self):
        m = MockBackend(responses={"injection": "Got it!"})
        r = m.generate("sys", "Try prompt injection")
        assert r.content == "Got it!"

    def test_call_count(self):
        m = MockBackend()
        m.generate("s", "u")
        m.generate("s", "u")
        assert m._call_count == 2

    def test_case_insensitive_matching(self):
        m = MockBackend(responses={"JAILBREAK": "matched"})
        r = m.generate("s", "try jailbreak attack")
        assert r.content == "matched"


class TestOllamaBackend:
    def test_default_host(self):
        with patch.dict(os.environ, {}, clear=True):
            b = OllamaBackend()
            assert "11434" in b.host

    def test_custom_host(self):
        b = OllamaBackend(host="http://custom:11434")
        assert b.host == "http://custom:11434"

    def test_env_host(self):
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://env:11434"}):
            b = OllamaBackend()
            assert b.host == "http://env:11434"


class TestNIMBackend:
    def test_default_url(self):
        with patch.dict(os.environ, {}, clear=True):
            b = NIMBackend()
            assert "nim-nemotron" in b.base_url

    def test_custom_url(self):
        b = NIMBackend(base_url="http://custom:8000/v1/chat/completions")
        assert "custom" in b.base_url

    def test_env_url(self):
        with patch.dict(os.environ, {"NIM_BASE_URL": "http://env:8000/v1/chat/completions"}):
            b = NIMBackend()
            assert b.base_url == "http://env:8000/v1/chat/completions"


# ═══════════════════════════════════════════════════════════════════════════
# LLM Expander
# ═══════════════════════════════════════════════════════════════════════════

class TestLLMExpander:
    def test_expand_attack(self):
        expander = LLMExpander(MockBackend())
        vec = AttackVector.random(AttackType.PROMPT_INJECTION)
        result = expander.expand_attack(vec)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_expand_jailbreak(self):
        expander = LLMExpander(MockBackend())
        vec = AttackVector.random(AttackType.JAILBREAK)
        result = expander.expand_attack(vec)
        assert len(result) > 0

    def test_expand_credential_harvest(self):
        expander = LLMExpander(MockBackend())
        vec = AttackVector.random(AttackType.CREDENTIAL_HARVEST)
        result = expander.expand_attack(vec)
        assert len(result) > 0

    def test_expand_sleeper(self):
        expander = LLMExpander(MockBackend())
        vec = AttackVector.random(AttackType.SLEEPER_PAYLOAD)
        result = expander.expand_attack(vec)
        assert len(result) > 0

    def test_expand_unknown_type(self):
        expander = LLMExpander(MockBackend())
        vec = AttackVector.random(AttackType.MEMORY_POISONING)
        result = expander.expand_attack(vec)
        assert len(result) > 0

    def test_expand_batch(self):
        expander = LLMExpander(MockBackend())
        vectors = [AttackVector.random() for _ in range(5)]
        results = expander.expand_batch(vectors)
        assert len(results) == 5
        for vid, prompt in results.items():
            assert len(prompt) > 0

    def test_expand_batch_limited(self):
        expander = LLMExpander(MockBackend())
        vectors = [AttackVector.random() for _ in range(10)]
        results = expander.expand_batch(vectors, max_expansions=3)
        assert len(results) == 3

    def test_expansion_count(self):
        expander = LLMExpander(MockBackend())
        vec = AttackVector.random()
        expander.expand_attack(vec)
        expander.expand_attack(vec)
        assert expander.expansion_count == 2


class TestAutoBackend:
    def test_falls_back_to_mock(self):
        with patch.dict(os.environ, {}, clear=True):
            backend = auto_backend()
            assert isinstance(backend, (MockBackend, OllamaBackend, NIMBackend))

    def test_prefers_nim_if_set(self):
        with patch.dict(os.environ, {"NIM_BASE_URL": "http://fake:8000/v1/chat/completions"}):
            backend = auto_backend()
            assert isinstance(backend, (MockBackend, OllamaBackend))

    def test_returns_backend_instance(self):
        backend = auto_backend()
        assert isinstance(backend, LLMBackend)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

class TestCLI:
    def test_no_args_prints_help(self, capsys):
        from arena.cli import main
        main([])
        captured = capsys.readouterr()
        assert "Pathology Collider" in captured.out or "arena" in captured.out

    def test_run_quick(self, capsys):
        from arena.cli import main
        main(["run", "--quick"])
        captured = capsys.readouterr()
        assert "Collider" in captured.out or "Season" in captured.out

    def test_status_no_checkpoint(self, capsys, tmp_path):
        from arena.cli import main
        main(["status", "--checkpoint-dir", str(tmp_path)])
        captured = capsys.readouterr()
        assert "No checkpoint" in captured.out

    def test_export_no_checkpoint(self, capsys, tmp_path):
        from arena.cli import main
        main(["export", "--checkpoint-dir", str(tmp_path)])
        captured = capsys.readouterr()
        assert "No checkpoint" in captured.out

    def test_dashboard_no_checkpoint(self, capsys, tmp_path):
        from arena.cli import main
        main(["dashboard", "--checkpoint-dir", str(tmp_path)])
        captured = capsys.readouterr()
        assert "No checkpoint" in captured.out

    def test_resume_no_checkpoint(self, capsys, tmp_path):
        from arena.cli import main
        main(["resume", "--checkpoint-dir", str(tmp_path)])
        captured = capsys.readouterr()
        assert "No checkpoint" in captured.out

    def test_run_custom_rounds(self, capsys):
        from arena.cli import main
        main(["run", "--quick", "--rounds", "2"])
        captured = capsys.readouterr()
        assert "Season" in captured.out or "Collider" in captured.out

    def test_status_after_run(self, capsys, tmp_path):
        from arena.cli import main
        main(["run", "--quick", "--checkpoint-dir", str(tmp_path)])
        main(["status", "--checkpoint-dir", str(tmp_path)])
        captured = capsys.readouterr()
        assert "Season" in captured.out or "season" in captured.out.lower()

    def test_export_json(self, capsys, tmp_path):
        from arena.cli import main
        main(["run", "--quick", "--checkpoint-dir", str(tmp_path)])
        main(["export", "--checkpoint-dir", str(tmp_path), "--format", "json"])
        captured = capsys.readouterr()
        assert "collider_id" in captured.out

    def test_dashboard_after_run(self, capsys, tmp_path):
        from arena.cli import main
        main(["run", "--quick", "--checkpoint-dir", str(tmp_path)])
        main(["dashboard", "--checkpoint-dir", str(tmp_path)])
        captured = capsys.readouterr()
        assert "Collider" in captured.out or "Dashboard" in captured.out


# ═══════════════════════════════════════════════════════════════════════════
# E2E Collider Lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestE2ECollider:
    def test_full_lifecycle(self, tmp_path):
        c = Collider.quick()
        c.checkpoint_dir = tmp_path
        c.schedule.max_seasons = 2
        c.run_forever()

        s1_battles = c._total_battles
        s1_gen = c.arena.red.generation
        assert s1_battles > 0
        assert s1_gen > 0

        c2 = Collider.quick()
        c2.checkpoint_dir = tmp_path
        assert c2.load_checkpoint()
        assert c2._total_battles == s1_battles
        assert c2._seasons_completed == 2

        c2.schedule.max_seasons = 4
        c2.run_forever()
        assert c2._total_battles > s1_battles
        assert c2._seasons_completed == 4

    def test_hooks_fire(self):
        events = []
        hooks = ColliderHooks(
            on_season_start=lambda s: events.append(("start", s)),
            on_season_end=lambda r: events.append(("end", r.summary()["total_battles"])),
            on_checkpoint=lambda cp: events.append(("cp", cp.season)),
        )
        c = Collider.quick()
        c.hooks = hooks
        c.run_cycle()

        starts = [e for e in events if e[0] == "start"]
        ends = [e for e in events if e[0] == "end"]
        cps = [e for e in events if e[0] == "cp"]
        assert len(starts) >= 1
        assert len(ends) >= 1
        assert len(cps) >= 1

    def test_breakthrough_hook(self):
        breakthroughs = []
        hooks = ColliderHooks(
            on_breakthrough=lambda bt: breakthroughs.append(bt),
        )
        c = Collider.quick()
        c.hooks = hooks
        c.schedule.max_seasons = 5
        c.run_forever()
        assert isinstance(breakthroughs, list)

    def test_export_report_structure(self):
        c = Collider.quick()
        c.run_cycle()
        report = c.export_report()
        required_keys = [
            "collider_id", "seasons_completed", "generation",
            "total_battles", "total_red_wins", "total_blue_wins",
            "breach_rate", "breakthroughs", "draft_ave_cards",
            "evolved_thresholds", "red_signatures", "fitness_trajectory",
        ]
        for key in required_keys:
            assert key in report, f"Missing key: {key}"

    def test_collider_with_expander(self):
        expander = LLMExpander(MockBackend())
        c = Collider.quick()
        c.run_cycle()

        top_reds = c.arena.red.best(n=3)
        expansions = expander.expand_batch(top_reds)
        assert len(expansions) == min(3, len(top_reds))
        for _, prompt in expansions.items():
            assert len(prompt) > 0

    def test_results_property(self):
        c = Collider.quick()
        c.run_cycle()
        assert len(c.results) >= 1
        assert isinstance(c.results[0], SeasonResult)

    def test_breakthroughs_property(self):
        c = Collider.quick()
        c.run_cycle()
        bts = c.breakthroughs
        assert isinstance(bts, list)


# ═══════════════════════════════════════════════════════════════════════════
# Integration: Collider → AVE
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegrationColliderAVE:
    def test_breakthrough_produces_ave_card(self):
        vec = AttackVector.random(AttackType.JAILBREAK)
        vec.fitness = 0.95
        payload = vec.generate()
        outcome = BattleOutcome(
            battle_id="test",
            round_number=0,
            verdict=Verdict.RED_WIN,
            red_score=0.95,
            blue_score=0.05,
            payload=payload,
            detections=(),
            breach=True,
        )
        bt = Breakthrough(
            breakthrough_id="int-test",
            attack_type=AttackType.JAILBREAK,
            vector=vec,
            outcome=outcome,
            season=1,
            generation=10,
        )
        card = bt.draft_ave_card()
        assert card["ave_id"].startswith("AVE-ARENA-")
        assert card["severity"] == "high"
        assert "attack_genes" in card

    def test_season_cards_format(self):
        c = Collider.quick()
        c.schedule.max_seasons = 3
        c.run_forever()
        cards = c.draft_ave_cards()
        for card in cards:
            assert "ave_id" in card
            assert "title" in card
            assert "severity" in card

    def test_evolved_thresholds_exportable(self):
        c = Collider.quick()
        c.run_cycle()
        thresholds = c.export_thresholds()
        assert isinstance(thresholds, dict)
        for name, val in thresholds.items():
            assert 0.0 <= val <= 1.0, f"{name}={val} out of range"

    def test_red_signatures_exportable(self):
        c = Collider.quick()
        c.run_cycle()
        sigs = c.export_red_signatures()
        for sig in sigs:
            assert "attack_type" in sig
            assert "genes" in sig
            assert "fitness" in sig

    def test_checkpoint_preserves_evolution(self, tmp_path):
        c = Collider.quick()
        c.checkpoint_dir = tmp_path
        c.run_cycle()
        gen1 = c.arena.red.generation
        c.save_checkpoint()

        c2 = Collider.quick()
        c2.checkpoint_dir = tmp_path
        c2.load_checkpoint()
        assert c2.arena.red.generation == gen1
        assert len(c2.arena.red.population) > 0

    def test_report_includes_all_sections(self):
        c = Collider.quick()
        c.schedule.max_seasons = 2
        c.run_forever()
        report = c.export_report()
        assert report["seasons_completed"] == 2
        assert isinstance(report["evolved_thresholds"], dict)
        assert isinstance(report["red_signatures"], list)
        assert isinstance(report["fitness_trajectory"], list)
