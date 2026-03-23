#!/usr/bin/env bash
exec "$(dirname "$0")/docker-ops-clean.sh" "$@"

# ═══════════════════════════════════════════════════════════════════════════






















































































































































































































































































































































































































































































































































































































































































































































































        assert isinstance(report["fitness_trajectory"], list)        assert isinstance(report["red_signatures"], list)        assert isinstance(report["evolved_thresholds"], dict)        assert report["seasons_completed"] == 2        report = c.export_report()        c.run_forever()        c.schedule.max_seasons = 2        c = Collider.quick()    def test_report_includes_all_sections(self):        assert len(c2.arena.red.population) > 0        assert c2.arena.red.generation == gen1        c2.load_checkpoint()        c2.checkpoint_dir = tmp_path        c2 = Collider.quick()        # Load into new collider        c.save_checkpoint()        gen1 = c.arena.red.generation        c.run_cycle()        c.checkpoint_dir = tmp_path        c = Collider.quick()    def test_checkpoint_preserves_evolution(self, tmp_path):            assert "fitness" in sig            assert "genes" in sig            assert "attack_type" in sig        for sig in sigs:        sigs = c.export_red_signatures()        c.run_cycle()        c = Collider.quick()    def test_red_signatures_exportable(self):            assert 0.0 <= val <= 1.0, f"{name}={val} out of range"        for name, val in thresholds.items():        # All threshold values should be 0.0-1.0        assert isinstance(thresholds, dict)        thresholds = c.export_thresholds()        c.run_cycle()        c = Collider.quick()    def test_evolved_thresholds_exportable(self):            assert "severity" in card            assert "title" in card            assert "ave_id" in card        for card in cards:        cards = c.draft_ave_cards()        c.run_forever()        c.schedule.max_seasons = 3        c = Collider.quick()    def test_season_cards_format(self):        assert "attack_genes" in card        assert card["severity"] == "high"        assert card["ave_id"].startswith("AVE-ARENA-")        card = bt.draft_ave_card()        )            generation=10,            season=1,            outcome=outcome,            vector=vec,            attack_type=AttackType.JAILBREAK,            breakthrough_id="int-test",        bt = Breakthrough(        )            breach=True,            detections=(),            payload=payload,            blue_score=0.05,            red_score=0.95,            verdict=Verdict.RED_WIN,            round_number=0,            battle_id="test",        outcome = BattleOutcome(        from arena.defences import DetectionResult, DefenceCategory        from arena.battle import BattleOutcome, Verdict        payload = vec.generate()        vec.fitness = 0.95        vec = AttackVector.random(AttackType.JAILBREAK)    def test_breakthrough_produces_ave_card(self):class TestIntegrationColliderAVE:# ═══════════════════════════════════════════════════════════════════════════# Integration: Collider → AVE# ═══════════════════════════════════════════════════════════════════════════        assert isinstance(bts, list)        bts = c.breakthroughs        c.run_cycle()        c = Collider.quick()    def test_breakthroughs_property(self):        assert isinstance(c.results[0], SeasonResult)        assert len(c.results) >= 1        c.run_cycle()        c = Collider.quick()    def test_results_property(self):            assert len(prompt) > 0        for _, prompt in expansions.items():        assert len(expansions) == min(3, len(top_reds))        expansions = expander.expand_batch(top_reds)        top_reds = c.arena.red.best(n=3)        # Expand top Red vectors        c.run_cycle()        c = Collider.quick()        expander = LLMExpander(MockBackend())        """Collider + LLM expander integration."""    def test_collider_with_expander(self):            assert key in report, f"Missing key: {key}"        for key in required_keys:        ]            "evolved_thresholds", "red_signatures", "fitness_trajectory",            "breach_rate", "breakthroughs", "draft_ave_cards",            "total_battles", "total_red_wins", "total_blue_wins",            "collider_id", "seasons_completed", "generation",        required_keys = [        report = c.export_report()        c.run_cycle()        c = Collider.quick()    def test_export_report_structure(self):        assert isinstance(breakthroughs, list)        # Breakthroughs may or may not occur — just check hook wiring works        c.run_forever()        c.schedule.max_seasons = 5        c.hooks = hooks        c = Collider.quick()        )            on_breakthrough=lambda bt: breakthroughs.append(bt),        hooks = ColliderHooks(        breakthroughs = []    def test_breakthrough_hook(self):        assert len(cps) >= 1        assert len(ends) >= 1        assert len(starts) >= 1        cps = [e for e in events if e[0] == "cp"]        ends = [e for e in events if e[0] == "end"]        starts = [e for e in events if e[0] == "start"]        c.run_cycle()        c.hooks = hooks        c = Collider.quick()        )            on_checkpoint=lambda cp: events.append(("cp", cp.season)),            on_season_end=lambda r: events.append(("end", r.summary()["total_battles"])),            on_season_start=lambda s: events.append(("start", s)),        hooks = ColliderHooks(        events = []    def test_hooks_fire(self):        assert c2._seasons_completed == 4        assert c2._total_battles > s1_battles        c2.run_forever()        c2.schedule.max_seasons = 4        # Phase 3: Resume and run more        assert c2._seasons_completed == 2        assert c2._total_battles == s1_battles        assert c2.load_checkpoint()        c2.checkpoint_dir = tmp_path        c2 = Collider.quick()        # Phase 2: Restore        assert s1_gen > 0        assert s1_battles > 0        s1_gen = c.arena.red.generation        s1_battles = c._total_battles        c.run_forever()        c.schedule.max_seasons = 2        c.checkpoint_dir = tmp_path        c = Collider.quick()        # Phase 1: Run        """Run → checkpoint → restore → resume → export."""    def test_full_lifecycle(self, tmp_path):class TestE2ECollider:# ═══════════════════════════════════════════════════════════════════════════# E2E Collider Lifecycle# ═══════════════════════════════════════════════════════════════════════════        assert "Collider" in captured.out or "Dashboard" in captured.out        captured = capsys.readouterr()        main(["dashboard", "--checkpoint-dir", str(tmp_path)])        main(["run", "--quick", "--checkpoint-dir", str(tmp_path)])        from arena.cli import main    def test_dashboard_after_run(self, capsys, tmp_path):        assert "collider_id" in captured.out        # Should contain JSON        captured = capsys.readouterr()        main(["export", "--checkpoint-dir", str(tmp_path), "--format", "json"])        main(["run", "--quick", "--checkpoint-dir", str(tmp_path)])        from arena.cli import main    def test_export_json(self, capsys, tmp_path):        assert "Season" in captured.out or "season" in captured.out.lower()        captured = capsys.readouterr()        main(["status", "--checkpoint-dir", str(tmp_path)])        main(["run", "--quick", "--checkpoint-dir", str(tmp_path)])        from arena.cli import main    def test_status_after_run(self, capsys, tmp_path):        assert "Season" in captured.out or "Collider" in captured.out        captured = capsys.readouterr()        main(["run", "--quick", "--rounds", "2"])        from arena.cli import main    def test_run_custom_rounds(self, capsys):        assert "No checkpoint" in captured.out        captured = capsys.readouterr()        main(["resume", "--checkpoint-dir", str(tmp_path)])        from arena.cli import main    def test_resume_no_checkpoint(self, capsys, tmp_path):        assert "No checkpoint" in captured.out        captured = capsys.readouterr()        main(["dashboard", "--checkpoint-dir", str(tmp_path)])        from arena.cli import main    def test_dashboard_no_checkpoint(self, capsys, tmp_path):        assert "No checkpoint" in captured.out        captured = capsys.readouterr()        main(["export", "--checkpoint-dir", str(tmp_path)])        from arena.cli import main    def test_export_no_checkpoint(self, capsys, tmp_path):        assert "No checkpoint" in captured.out        captured = capsys.readouterr()        main(["status", "--checkpoint-dir", str(tmp_path)])        from arena.cli import main    def test_status_no_checkpoint(self, capsys, tmp_path):        assert "Collider" in captured.out or "Season" in captured.out        captured = capsys.readouterr()        main(["run", "--quick"])        from arena.cli import main    def test_run_quick(self, capsys):        assert "Pathology Collider" in captured.out or "arena" in captured.out        captured = capsys.readouterr()        main([])        from arena.cli import main    def test_no_args_prints_help(self, capsys):class TestCLI:# ═══════════════════════════════════════════════════════════════════════════# CLI# ═══════════════════════════════════════════════════════════════════════════        assert isinstance(backend, LLMBackend)        backend = auto_backend()    def test_returns_backend_instance(self):            assert isinstance(backend, (MockBackend, OllamaBackend))            backend = auto_backend()            # NIM won't be reachable, so should fall through        with patch.dict(os.environ, {"NIM_BASE_URL": "http://fake:8000/v1/chat/completions"}):    def test_prefers_nim_if_set(self):            assert isinstance(backend, (MockBackend, OllamaBackend, NIMBackend))            backend = auto_backend()            # Neither Ollama nor NIM will be available in test        with patch.dict(os.environ, {}, clear=True):    def test_falls_back_to_mock(self):class TestAutoBackend:        assert expander.expansion_count == 2        expander.expand_attack(vec)        expander.expand_attack(vec)        vec = AttackVector.random()        expander = LLMExpander(MockBackend())    def test_expansion_count(self):        assert len(results) == 3        results = expander.expand_batch(vectors, max_expansions=3)        vectors = [AttackVector.random() for _ in range(10)]        expander = LLMExpander(MockBackend())    def test_expand_batch_limited(self):            assert len(prompt) > 0        for vid, prompt in results.items():        assert len(results) == 5        results = expander.expand_batch(vectors)        vectors = [AttackVector.random() for _ in range(5)]        expander = LLMExpander(MockBackend())    def test_expand_batch(self):        assert len(result) > 0        result = expander.expand_attack(vec)        vec = AttackVector.random(AttackType.MEMORY_POISONING)        expander = LLMExpander(MockBackend())    def test_expand_unknown_type(self):        assert len(result) > 0        result = expander.expand_attack(vec)        vec = AttackVector.random(AttackType.SLEEPER_PAYLOAD)        expander = LLMExpander(MockBackend())    def test_expand_sleeper(self):        assert len(result) > 0        result = expander.expand_attack(vec)        vec = AttackVector.random(AttackType.CREDENTIAL_HARVEST)        expander = LLMExpander(MockBackend())    def test_expand_credential_harvest(self):        assert len(result) > 0        result = expander.expand_attack(vec)        vec = AttackVector.random(AttackType.JAILBREAK)        expander = LLMExpander(MockBackend())    def test_expand_jailbreak(self):        assert len(result) > 0        assert isinstance(result, str)        result = expander.expand_attack(vec)        vec = AttackVector.random(AttackType.PROMPT_INJECTION)        expander = LLMExpander(MockBackend())    def test_expand_attack(self):class TestLLMExpander:# ═══════════════════════════════════════════════════════════════════════════# LLM Expander# ═══════════════════════════════════════════════════════════════════════════            assert b.base_url == "http://env:8000/v1/chat/completions"            b = NIMBackend()        with patch.dict(os.environ, {"NIM_BASE_URL": "http://env:8000/v1/chat/completions"}):    def test_env_url(self):        assert "custom" in b.base_url        b = NIMBackend(base_url="http://custom:8000/v1/chat/completions")    def test_custom_url(self):            assert "nim-nemotron" in b.base_url            b = NIMBackend()        with patch.dict(os.environ, {}, clear=True):    def test_default_url(self):class TestNIMBackend:            assert b.host == "http://env:11434"            b = OllamaBackend()        with patch.dict(os.environ, {"OLLAMA_HOST": "http://env:11434"}):    def test_env_host(self):        assert b.host == "http://custom:11434"        b = OllamaBackend(host="http://custom:11434")    def test_custom_host(self):            assert "11434" in b.host            b = OllamaBackend()        with patch.dict(os.environ, {}, clear=True):    def test_default_host(self):class TestOllamaBackend:        assert r.content == "matched"        r = m.generate("s", "try jailbreak attack")        m = MockBackend(responses={"JAILBREAK": "matched"})    def test_case_insensitive_matching(self):        assert m._call_count == 2        m.generate("s", "u")        m.generate("s", "u")        m = MockBackend()    def test_call_count(self):        assert r.content == "Got it!"        r = m.generate("sys", "Try prompt injection")        m = MockBackend(responses={"injection": "Got it!"})    def test_generate_custom_response(self):        assert r.model == "mock"        assert "[MOCK]" in r.content        r = m.generate("sys", "user msg")        m = MockBackend()    def test_generate_default(self):        assert m.available() is True        m = MockBackend()    def test_available(self):class TestMockBackend:        assert r.model == ""        assert r.content == ""        r = LLMResponse(content="")    def test_empty_response(self):        assert r.latency_ms == 100.5        assert r.tokens_used == 42        r = LLMResponse(content="x", model="m", tokens_used=42, latency_ms=100.5)    def test_with_metadata(self):        assert r.tokens_used == 0        assert r.model == "test"        assert r.content == "hello"        r = LLMResponse(content="hello", model="test")    def test_basic(self):class TestLLMResponse:# ═══════════════════════════════════════════════════════════════════════════# LLM Backend# ═══════════════════════════════════════════════════════════════════════════        assert c2._total_battles == c1._total_battles        assert c2._seasons_completed == c1._seasons_completed        assert loaded is True        loaded = c2.load_checkpoint()        c2.checkpoint_dir = tmp_path        c2 = Collider.quick()        c1.save_checkpoint()        c1.run_cycle()        c1.checkpoint_dir = tmp_path        c1 = Collider.quick()    def test_load_checkpoint(self, tmp_path):        assert cp.total_battles > 0        assert (tmp_path / "checkpoint.json").exists()        cp = c.save_checkpoint()        c.run_cycle()        c.checkpoint_dir = tmp_path        c = Collider.quick()    def test_save_checkpoint(self, tmp_path):        assert "evolved_thresholds" in report        assert "draft_ave_cards" in report        assert "total_battles" in report        assert "collider_id" in report        report = c.export_report()        c.run_cycle()        c = Collider.quick()    def test_export_report(self):        assert isinstance(sigs, list)        sigs = c.export_red_signatures()        c.run_cycle()        c = Collider.quick()    def test_export_red_signatures(self):        assert len(thresholds) > 0        assert isinstance(thresholds, dict)        thresholds = c.export_thresholds()        c.run_cycle()        c = Collider.quick()    def test_export_thresholds(self):        assert isinstance(cards, list)        # May or may not have breakthroughs — just check it doesn't crash        cards = c.draft_ave_cards()        c.run_cycle()        c = Collider.quick()    def test_draft_ave_cards(self):        assert status["total_battles"] > 0        assert status["generation"] > 0        assert status["seasons_completed"] >= 1        status = c.status()        c.run_cycle()        c = Collider.quick()    def test_status_after_run(self):        assert c._running is False        c.stop()        c._running = True        c = Collider.quick()    def test_stop(self):        assert c._seasons_completed == 2        c.run_forever()        c.schedule.max_seasons = 2        c = Collider.quick()    def test_run_forever_stops_at_max(self):        assert c._total_battles > battles_after_1        r2 = c.run_cycle()        battles_after_1 = c._total_battles        r1 = c.run_cycle()        c.schedule.max_seasons = 0        c.schedule.seasons_per_cycle = 2        c = Collider.quick()    def test_run_cycle_accumulates(self):        assert c._total_battles > 0        assert c._seasons_completed >= 1        assert len(results) == 1  # quick = 1 season per cycle        results = c.run_cycle()        c = Collider.quick()    def test_run_cycle(self):        assert status["breakthroughs"] == 0        assert status["total_battles"] == 0        assert status["seasons_completed"] == 0        assert status["running"] is False        status = c.status()        c = Collider.quick()    def test_initial_status(self):        assert c.schedule.rounds_per_season == 50        assert c.arena.red.population_size == 200        c = Collider.production()    def test_production_factory(self):        assert c.arena.red.population_size == 50        c = Collider.standard()    def test_standard_factory(self):        assert c.schedule.max_seasons == 2        assert c.arena.red.population_size == 10        c = Collider.quick()    def test_quick_factory(self):class TestCollider:# ═══════════════════════════════════════════════════════════════════════════# Collider# ═══════════════════════════════════════════════════════════════════════════        assert gens == [(5, {"best": 0.8})]        hooks.on_generation(5, {"best": 0.8})        )            on_generation=lambda g, s: gens.append((g, s)),        hooks = ColliderHooks(        gens = []    def test_generation_hook(self):        assert checkpoints == ["fake_cp"]        hooks.on_checkpoint("fake_cp")        )            on_checkpoint=lambda cp: checkpoints.append(cp),        hooks = ColliderHooks(        checkpoints = []    def test_checkpoint_hook(self):        assert breakthroughs == ["fake_bt"]        hooks.on_breakthrough("fake_bt")        )            on_breakthrough=lambda bt: breakthroughs.append(bt),        hooks = ColliderHooks(        breakthroughs = []    def test_breakthrough_hook(self):        assert called == [("start", 1)]        hooks.on_season_start(1)        )            on_season_start=lambda s: called.append(("start", s)),        hooks = ColliderHooks(        called = []    def test_custom_hooks(self):        assert hooks.on_shutdown is None        assert hooks.on_generation is None        assert hooks.on_checkpoint is None        assert hooks.on_breakthrough is None        assert hooks.on_season_end is None        assert hooks.on_season_start is None        hooks = ColliderHooks()    def test_default_hooks_are_none(self):class TestColliderHooks:# ═══════════════════════════════════════════════════════════════════════════# ColliderHooks# ═══════════════════════════════════════════════════════════════════════════        assert s.checkpoint_every == 3        s = Schedule(checkpoint_every=3)    def test_checkpoint_every(self):        assert s.max_seasons == 5        assert s.rounds_per_season == 25        s = Schedule(rounds_per_season=25, max_seasons=5)    def test_custom(self):        assert s.cooldown_seconds == 1.0        assert s.rounds_per_season == 50        s = Schedule.nightly()    def test_nightly(self):        assert s.max_seasons == 0  # unlimited        assert s.rounds_per_season == 10        s = Schedule.standard()    def test_standard(self):        assert s.max_seasons == 2        assert s.rounds_per_season == 3        s = Schedule.quick()    def test_quick(self):class TestSchedule:# ═══════════════════════════════════════════════════════════════════════════# Schedule# ═══════════════════════════════════════════════════════════════════════════        assert loaded.blue_thresholds == thresholds        loaded = Checkpoint.load(path)        cp.save(path)        path = tmp_path / "cp.json"        cp.blue_thresholds = thresholds        cp = Checkpoint.empty()        thresholds = {f"det_{i}": 0.1 * i for i in range(10)}    def test_checkpoint_round_trip_preserves_blue(self, tmp_path):        assert loaded.metadata["arena_mode"] == "production"        loaded = Checkpoint.load(path)        cp.save(path)        path = tmp_path / "cp.json"        cp.metadata = {"arena_mode": "production", "uptime": 3600}        cp = Checkpoint.empty()    def test_load_metadata(self, tmp_path):        assert data["timestamp"] > 0        assert "timestamp" in data            data = json.load(f)        with open(path) as f:        cp.save(path)        path = tmp_path / "cp.json"        cp = Checkpoint.empty()    def test_save_includes_timestamp(self, tmp_path):        assert cp1.collider_id != cp2.collider_id        cp2 = Checkpoint.empty()        cp1 = Checkpoint.empty()    def test_empty_generates_unique_ids(self):        assert len(d["fitness_trajectory"]) == 10        # Should only include last 10        d = cp.to_dict()        ]            {"generation": i, "best": i * 0.1} for i in range(25)        cp.fitness_trajectory = [        cp = Checkpoint.empty()    def test_to_dict_truncates_trajectory(self):        assert len(loaded.breakthroughs) == 2        loaded = Checkpoint.load(path)        cp.save(path)        path = tmp_path / "cp.json"        ]            {"breakthrough_id": "b2", "attack_type": "prompt_injection"},            {"breakthrough_id": "b1", "attack_type": "jailbreak"},        cp.breakthroughs = [        cp = Checkpoint.empty()    def test_load_restores_breakthroughs(self, tmp_path):        assert path.exists()        cp.save(path)        path = tmp_path / "nested" / "deep" / "cp.json"        cp = Checkpoint.empty()    def test_save_creates_directories(self, tmp_path):        assert loaded.total_red_wins == 30        assert loaded.total_battles == 100        assert loaded.blue_thresholds == {"detector_a": 0.7}        assert len(loaded.red_population) == 1        assert loaded.generation == 15        assert loaded.season == 3        assert loaded.collider_id == "save-test"        loaded = Checkpoint.load(path)        assert path.exists()        cp.save(path)        path = tmp_path / "cp.json"        )            total_breakthroughs=2,            total_blue_wins=60,            total_red_wins=30,            total_battles=100,            fitness_trajectory=[{"generation": 1, "best": 0.8}],            breakthroughs=[{"breakthrough_id": "b1"}],            blue_thresholds={"detector_a": 0.7},            red_population=[{"vector_id": "v1", "attack_type": "jailbreak"}],            generation=15,            season=3,            collider_id="save-test",        cp = Checkpoint(    def test_save_and_load(self, tmp_path):        assert d["red_population_size"] == 0        assert d["total_battles"] == 0        assert d["season"] == 0        assert "collider_id" in d        d = cp.to_dict()        cp = Checkpoint.empty()    def test_to_dict(self):        assert cp.total_battles == 0        assert cp.red_population == []        assert cp.generation == 0        assert cp.season == 0        assert cp.collider_id == "test-id"        cp = Checkpoint.empty("test-id")    def test_empty_checkpoint(self):class TestCheckpoint:# ═══════════════════════════════════════════════════════════════════════════# Checkpoint# ═══════════════════════════════════════════════════════════════════════════from arena.battle import BattleOutcome, Verdictfrom arena.swarm import RedSwarmfrom arena.defences import BlueBridge, DefenceConfigfrom arena.vectors import AttackVector, AttackTypefrom arena.arena import Arena, Breakthrough, SeasonResult)    auto_backend,    OllamaBackend,    NIMBackend,    MockBackend,    LLMResponse,    LLMExpander,    LLMBackend,from arena.llm_backend import (from arena.collider import Checkpoint, Collider, ColliderHooks, Scheduleimport pytestfrom unittest.mock import MagicMock, patchfrom pathlib import Pathimport timeimport tempfileimport osimport json"""  • test_integration_*        — Collider → AVE card pipeline (6)  • test_e2e_collider_*       — End-to-end collider lifecycle (7)  • test_cli_*                — CLI argument parsing and commands (10)  • test_auto_backend_*       — Backend auto-detection (3)  • test_llm_expander_*       — LLMExpander attack expansion (8)  • test_nim_backend_*        — NIMBackend configuration (3)  • test_ollama_backend_*     — OllamaBackend configuration (3)  • test_mock_backend_*       — MockBackend generate/available (5)  • test_llm_response_*       — LLMResponse dataclass (3)  • test_collider_*           — Collider lifecycle, run_cycle, status (15)  • test_collider_hooks_*     — Hook callback system (5)  • test_schedule_*           — Schedule presets and configuration (5)  • test_checkpoint_*         — Checkpoint save/load/serialization (10)83 tests covering:# NAIL Institute — Docker Quick Commands
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./docker-ops.sh start          Start core stack (Nemotron + app)
#   ./docker-ops.sh start-full     Start everything (all 6 NIM + app)
#   ./docker-ops.sh start-guards   Start guardrails NIM models + app
#   ./docker-ops.sh rebuild        Rebuild app after code changes
#   ./docker-ops.sh test           Run full test suite in container
#   ./docker-ops.sh logs           Tail application logs
#   ./docker-ops.sh status         Show container health
#   ./docker-ops.sh stop           Stop everything
#   ./docker-ops.sh gpu            Show GPU memory usage per container
#   ./docker-ops.sh shell          Open bash in the app container
#
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
RST='\033[0m'

banner() { echo -e "\n${BLU}══════════════════════════════════════════════════${RST}"; echo -e "${GRN}  $1${RST}"; echo -e "${BLU}══════════════════════════════════════════════════${RST}\n"; }

check_env() {
    if [ ! -f .env ]; then
        echo -e "${YLW}⚠  No .env file found. Creating from template...${RST}"
        cp .env.example .env
        echo -e "${YLW}   Edit .env and add your NGC_API_KEY before starting NIM containers.${RST}"
        echo -e "${YLW}   Then run: docker login nvcr.io -u '\$oauthtoken' -p \$(cat .env | grep NGC_API_KEY | cut -d= -f2)${RST}"
    fi
}

case "${1:-help}" in

    start)
        banner "Starting NAIL core stack (Nemotron + app)"
        check_env
        docker compose up -d nail nim-nemotron
        docker compose logs -f nail
        ;;

    start-full)
        banner "Starting FULL stack (all NIM models + app)"
        check_env
        docker compose --profile full up -d
        docker compose logs -f nail
        ;;

    start-guards)
        banner "Starting guardrails stack (4 NemoGuard + app)"
        check_env
        docker compose --profile guardrails up -d nail nim-nemotron
        docker compose logs -f nail
        ;;

    rebuild)
        banner "Rebuilding NAIL app after code changes"
        docker compose up -d --build --no-deps nail
        docker compose logs -f nail
        ;;

    test)
        banner "Running test suite in container"
        docker compose run --rm nail bash run_all_tests.sh
        ;;

    logs)
        docker compose logs -f "${2:-nail}"
        ;;

    status)
        banner "Container Status"
        docker compose ps -a
        echo ""
        echo -e "${BLU}── Health ──${RST}"
        for c in nail-platform nim-nemotron nim-jailbreak nim-content-reasoning nim-content-8b nim-safety-v3 nim-pii; do
            health=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || echo "not running")
            case "$health" in
                healthy)   icon="${GRN}✓${RST}" ;;
                unhealthy) icon="${RED}✗${RST}" ;;
                starting)  icon="${YLW}…${RST}" ;;
                *)         icon="${RED}○${RST}" ;;
            esac
            printf "  %b %-25s %s\n" "$icon" "$c" "$health"
        done
        ;;

    stop)
        banner "Stopping all containers"
        docker compose --profile full down
        ;;

    gpu)
        banner "GPU Memory Usage"
        nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader 2>/dev/null || echo "No GPU processes"
        echo ""
        nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo "nvidia-smi unavailable"
        ;;

    shell)
        docker compose exec nail bash
        ;;

    # ── Canary Fleet Commands ──────────────────────────────────────
    canary)
        banner "Starting Canary Fleet — NATIVE (no Docker, port 9000)"
        echo -e "${YLW}  Mode: bait (pattern responses, no LLM)${RST}"
        echo -e "${YLW}  To use NIM LLM: ./docker-ops.sh canary-nim${RST}"
        echo ""
        source .venv/bin/activate 2>/dev/null || true
        python -m canary.cli serve --host 0.0.0.0 --port 9000 --no-llm
        ;;

    canary-docker)
        banner "Starting Canary Fleet — Docker (bait mode, port 9000)"
        echo -e "${YLW}  No NIM/NGC required — runs standalone${RST}"
        docker compose --profile canary up -d --build canary-fleet
        echo -e "${GRN}✓ Canary fleet at http://localhost:9000${RST}"
        docker compose logs -f canary-fleet
        ;;

    canary-nim)
        banner "Starting Canary Fleet — Docker + NIM LLM"
        check_env
        docker compose --profile canary-nim up -d
        echo -e "${GRN}✓ Canary fleet (NIM) at http://localhost:9000${RST}"
        docker compose logs -f canary-fleet-nim
        ;;

    canary-full)
        banner "Starting Canary Fleet + Discord Bot + Monitor"
        check_env
        docker compose -f docker-compose.yml -f docker-compose.canary.yml --profile full up -d
        echo -e "${GRN}✓ Canary web at http://localhost:9000${RST}"
        echo -e "${GRN}✓ Discord bot active${RST}"
        echo -e "${GRN}✓ Monitor watching for incidents${RST}"
        ;;

    canary-logs)
        docker compose logs -f canary-fleet 2>/dev/null || docker compose logs -f canary-fleet-nim 2>/dev/null || echo "No canary container running"
        ;;

    canary-status)
        banner "Canary Fleet Status"
        curl -s http://localhost:9000/health | python3 -m json.tool 2>/dev/null || echo "Canary fleet not running"
        echo ""
        echo -e "${BLU}── Metrics ──${RST}"
        curl -s http://localhost:9000/metrics 2>/dev/null || echo "Metrics unavailable"
        ;;

    canary-stop)
        banner "Stopping Canary Fleet"
        docker compose --profile canary --profile canary-nim down 2>/dev/null
        ;;

    # ── Arena Collider Commands ────────────────────────────────────
    arena)
        banner "Starting Arena Collider — Native (Pathology Collider)"
        echo -e "${YLW}  Mode: standard (50 pop, 10 rounds/season)${RST}"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli run --seasons 5
        ;;

    arena-production)
        banner "Starting Arena Collider — Production 24/7"
        echo -e "${YLW}  Mode: production (200 pop, 50 rounds/season, unlimited)${RST}"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli run --production
        ;;

    arena-docker)
        banner "Starting Arena Collider — Docker"
        docker compose --profile arena up -d --build arena-collider
        echo -e "${GRN}✓ Arena collider running${RST}"
        docker compose logs -f arena-collider
        ;;

    arena-status)
        banner "Arena Collider Status"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli status
        ;;

    arena-export)
        banner "Arena Export — Breakthroughs + Thresholds"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli export
        ;;

    arena-dashboard)
        banner "Arena Dashboard"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli dashboard
        ;;

    arena-stop)
        banner "Stopping Arena Collider"
        docker compose --profile arena down 2>/dev/null
        ;;

    # ── CTF Commands ────────────────────────────────────────────────────
    ctf)
        banner "Starting CTF Server (native, weekend mode)"
        source .venv/bin/activate 2>/dev/null
        python -m ctf.cli serve --port 9200
        ;;

    ctf-quick)
        banner "Starting CTF Server (native, quick mode)"
        source .venv/bin/activate 2>/dev/null
        python -m ctf.cli serve --port 9200 --mode quick --event-name "NAIL Quick CTF"
        ;;

    ctf-docker)
        banner "Starting CTF Server in Docker"
        docker compose --profile ctf up -d --build ctf-server
        echo -e "${GRN}CTF server running on http://localhost:9200${RST}"
        docker compose logs -f ctf-server
        ;;

    ctf-simulate)
        banner "Running CTF Simulation (3 teams)"
        source .venv/bin/activate 2>/dev/null
        python -m ctf.cli simulate --teams 3
        ;;

    ctf-challenges)
        banner "Listing CTF Challenges"
        source .venv/bin/activate 2>/dev/null
        python -m ctf.cli challenges
        ;;

    ctf-status)
        banner "CTF Server Status"
        curl -s http://localhost:9200/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "CTF server not running"
        ;;

    ctf-stop)
        banner "Stopping CTF Server"
        docker compose --profile ctf down 2>/dev/null
        ;;

    *)
        echo "NAIL Docker Operations"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Core Commands:"
        echo "  start          Start core stack (Nemotron + app)"
        echo "  start-full     Start everything (all 6 NIM + app)"
        echo "  start-guards   Start guardrails NIM models + app"
        echo "  rebuild        Rebuild app after code changes (~10s)"
        echo "  test           Run full test suite in container"
        echo "  logs [name]    Tail container logs (default: nail)"
        echo "  status         Show container health"
        echo "  stop           Stop everything"
        echo "  gpu            Show GPU memory per container"
        echo "  shell          Open bash in app container"
        echo ""
        echo "Canary Fleet Commands:"
        echo "  canary         Start canary native (no Docker, bait mode)"
        echo "  canary-docker  Start canary in Docker (bait mode, no NGC)"
        echo "  canary-nim     Start canary in Docker + NIM LLM (needs NGC)"
        echo "  canary-full    Start fleet + Discord bot + monitor"
        echo "  canary-logs    Tail canary logs"
        echo "  canary-status  Show canary fleet health"
        echo "  canary-stop    Stop canary fleet"
        echo ""
        echo "Arena Collider Commands:"
        echo "  arena           Run Pathology Collider (5 seasons, native)"
        echo "  arena-production Run 24/7 production mode (native)"
        echo "  arena-docker    Run in Docker container"
        echo "  arena-status    Show collider state from checkpoint"
        echo "  arena-export    Export breakthroughs + thresholds"
        echo "  arena-dashboard Print evolution dashboard"
        echo "  arena-stop      Stop arena Docker container"
        ;;
esac
