"""
Tests for the AVE (Agentic Vulnerabilities & Exposures) package.

Coverage:
  - Schema data types (creation, serialisation, display)
  - Registry (lookup, search, counts, filters)
  - Card integrity (no duplicates, required fields, consistent IDs)
"""

import json
import pytest

from ave import (
    AVECard, Category, Severity, Status,
    EnvironmentVector, Defence, Evidence,
    lookup, search, all_cards,
    cards_by_severity, cards_by_category, cards_by_status,
    card_count,
)


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestCategory:
    def test_all_values_are_strings(self):
        for cat in Category:
            assert isinstance(cat.value, str)

    def test_expected_categories_exist(self):
        expected = {"memory", "consensus", "injection", "resource", "drift",
                    "alignment", "social", "tool", "temporal", "structural",
                    "credential", "delegation", "fabrication", "emergent"}
        actual = {c.value for c in Category}
        assert expected == actual

    def test_category_count(self):
        assert len(Category) == 14


class TestSeverity:
    def test_severity_levels(self):
        assert len(Severity) == 5
        expected = {"critical", "high", "medium", "low", "info"}
        assert {s.value for s in Severity} == expected


class TestStatus:
    def test_status_values(self):
        assert len(Status) == 5
        expected = {"proven", "proven_mitigated", "theoretical",
                    "not_proven", "in_progress"}
        assert {s.value for s in Status} == expected


class TestEnvironmentVector:
    def test_defaults(self):
        env = EnvironmentVector()
        assert env.frameworks == ()
        assert env.models_tested == ()
        assert env.multi_agent is False
        assert env.tools_required is False
        assert env.memory_required is False
        assert env.rag_required is False
        assert env.min_context_window is None

    def test_frozen(self):
        env = EnvironmentVector(multi_agent=True)
        with pytest.raises(AttributeError):
            env.multi_agent = False  # type: ignore

    def test_custom_values(self):
        env = EnvironmentVector(
            frameworks=("LangGraph", "CrewAI"),
            models_tested=("nemotron:70b",),
            multi_agent=True,
            tools_required=True,
            min_context_window=128_000,
        )
        assert "LangGraph" in env.frameworks
        assert env.min_context_window == 128_000


class TestEvidence:
    def test_minimal(self):
        e = Evidence(experiment_id="exp1")
        assert e.experiment_id == "exp1"
        assert e.data_file == ""
        assert e.p_value is None
        assert e.cross_model is False

    def test_full(self):
        e = Evidence(
            experiment_id="exp26",
            data_file="exp24_25_26_results.json",
            key_metric="exploitation_rate",
            key_value="100%",
            p_value=0.0002,
            sample_size=100,
            cross_model=True,
        )
        assert e.p_value == 0.0002
        assert e.cross_model is True

    def test_frozen(self):
        e = Evidence(experiment_id="exp1")
        with pytest.raises(AttributeError):
            e.experiment_id = "exp2"  # type: ignore


class TestDefence:
    def test_minimal(self):
        d = Defence(name="Token Monitor")
        assert d.name == "Token Monitor"
        assert d.layer == ""
        assert d.rmap_module == ""

    def test_full(self):
        d = Defence(
            name="ImmuneDaemon",
            layer="L1–L4",
            effectiveness="90% detection",
            rmap_module="rmap.immune",
            nail_monitor_detector="ConsensusParalysisDetector",
        )
        assert "rmap" in d.rmap_module


class TestAVECard:
    @pytest.fixture
    def sample_card(self):
        return AVECard(
            ave_id="AVE-TEST-0001",
            name="Test Vulnerability",
            aliases=("TestVuln", "SampleBug"),
            category=Category.MEMORY,
            severity=Severity.HIGH,
            status=Status.PROVEN,
            summary="A test vulnerability for unit testing.",
            mechanism="Exploits test infrastructure.",
            blast_radius="None — this is a test.",
            prerequisite="pytest",
            environment=EnvironmentVector(
                frameworks=("pytest",),
                models_tested=("test-model",),
            ),
            evidence=(
                Evidence(experiment_id="test1", key_metric="pass_rate", key_value="100%"),
            ),
            defences=(
                Defence(name="TestDefence", layer="L0"),
            ),
            cwe_mapping="CWE-000",
        )

    def test_creation(self, sample_card):
        assert sample_card.ave_id == "AVE-TEST-0001"
        assert sample_card.name == "Test Vulnerability"
        assert sample_card.category == Category.MEMORY
        assert sample_card.severity == Severity.HIGH
        assert sample_card.status == Status.PROVEN

    def test_aliases(self, sample_card):
        assert "TestVuln" in sample_card.aliases
        assert len(sample_card.aliases) == 2

    def test_evidence_access(self, sample_card):
        assert len(sample_card.evidence) == 1
        assert sample_card.evidence[0].experiment_id == "test1"

    def test_defence_access(self, sample_card):
        assert len(sample_card.defences) == 1
        assert sample_card.defences[0].name == "TestDefence"

    def test_to_dict(self, sample_card):
        d = sample_card.to_dict()
        assert isinstance(d, dict)
        assert d["ave_id"] == "AVE-TEST-0001"
        assert d["category"] == "memory"
        assert d["severity"] == "high"
        assert d["status"] == "proven"
        assert isinstance(d["aliases"], list)
        assert isinstance(d["evidence"], list)
        assert isinstance(d["defences"], list)

    def test_to_dict_json_serialisable(self, sample_card):
        d = sample_card.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["ave_id"] == "AVE-TEST-0001"

    def test_short(self, sample_card):
        s = sample_card.short()
        assert "AVE-TEST-0001" in s
        assert "HIGH" in s
        assert "Test Vulnerability" in s
        assert "proven" in s

    def test_str(self, sample_card):
        s = str(sample_card)
        assert "AVE-TEST-0001" in s
        assert "Test Vulnerability" in s
        assert "memory" in s
        assert "high" in s
        assert "TestDefence" in s
        assert "test1" in s

    def test_defaults(self):
        card = AVECard(ave_id="AVE-TEST-0002", name="Minimal")
        assert card.category == Category.EMERGENT
        assert card.severity == Severity.MEDIUM
        assert card.status == Status.THEORETICAL
        assert card.evidence == ()
        assert card.defences == ()


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestAllCards:
    def test_returns_list(self):
        cards = all_cards()
        assert isinstance(cards, list)

    def test_at_least_36_cards(self):
        """We defined 36 cards (29 experiment + 7 theoretical/extra)."""
        assert len(all_cards()) >= 36

    def test_all_are_ave_cards(self):
        for card in all_cards():
            assert isinstance(card, AVECard)


class TestLookup:
    def test_first_card(self):
        card = lookup("AVE-2025-0001")
        assert card is not None
        assert card.name == "Sleeper Payload Injection"

    def test_last_experiment_card(self):
        card = lookup("AVE-2025-0029")
        assert card is not None
        assert card.name == "Temporal Sleeper Agent"

    def test_theoretical_card(self):
        card = lookup("AVE-2025-0030")
        assert card is not None
        assert card.status == Status.THEORETICAL

    def test_nonexistent_returns_none(self):
        assert lookup("AVE-9999-9999") is None

    def test_confused_deputy(self):
        card = lookup("AVE-2025-0026")
        assert card is not None
        assert "100%" in card.evidence[0].key_value
        assert card.severity == Severity.CRITICAL

    def test_bystander_effect(self):
        card = lookup("AVE-2025-0021")
        assert card is not None
        assert "80%" in card.evidence[0].key_value


class TestSemanticFragmentation:
    """AVE-2026-0037 — Context Integrity Layer pathology (CIL P1)."""

    def test_card_exists(self):
        card = lookup("AVE-2026-0037")
        assert card is not None
        assert card.name == "Semantic Fragmentation"

    def test_classification(self):
        card = lookup("AVE-2026-0037")
        assert card.category == Category.STRUCTURAL
        assert card.severity == Severity.HIGH
        assert card.status == Status.IN_PROGRESS

    def test_is_a_multi_agent_pathology(self):
        """Fragmentation is intrinsically inter-agent — must require multi-agent."""
        card = lookup("AVE-2026-0037")
        assert card.environment.multi_agent is True

    def test_defended_by_definitional_drift_detector(self):
        card = lookup("AVE-2026-0037")
        assert card.defences, "Semantic Fragmentation must name its CIL defence"
        assert any(
            d.nail_monitor_detector == "DefinitionalDriftDetector"
            for d in card.defences
        )

    def test_orthogonal_to_memory_laundering(self):
        """Distinct from the memory-poisoning family — different root cause."""
        card = lookup("AVE-2026-0037")
        assert card.category != Category.MEMORY

    def test_cross_references_memory_laundering_after_enrich(self):
        """enrich populates the cross-link to AVE-2025-0001 (Sleeper/Memory)."""
        import copy
        from ave.enrich import enrich_card
        # Deep-copy so we don't mutate the shared registry instance and pollute
        # other tests that assert raw cards have empty related_aves.
        card = copy.deepcopy(lookup("AVE-2026-0037"))
        enrich_card(card)
        assert "AVE-2025-0001" in card.related_aves

    def test_found_via_search_aliases(self):
        results = search(keyword="definitional drift")
        assert any(c.ave_id == "AVE-2026-0037" for c in results)

    def test_in_progress_has_no_evidence_yet(self):
        """IN_PROGRESS by design — evidence lands with exp39 (P3), not P1."""
        card = lookup("AVE-2026-0037")
        assert card.status == Status.IN_PROGRESS
        assert card.evidence == ()

    def test_collider(self):
        card = lookup("AVE-2025-0020")
        assert card is not None
        assert "0.8066" in card.evidence[0].key_value


class TestSearch:
    def test_by_category_memory(self):
        results = search(category=Category.MEMORY)
        assert len(results) >= 3  # exp1, exp9, exp22, exp34
        for card in results:
            assert card.category == Category.MEMORY

    def test_by_severity_critical(self):
        results = search(severity=Severity.CRITICAL)
        assert len(results) >= 5
        for card in results:
            assert card.severity == Severity.CRITICAL

    def test_by_status_theoretical(self):
        results = search(status=Status.THEORETICAL)
        assert len(results) >= 3
        for card in results:
            assert card.status == Status.THEORETICAL

    def test_by_keyword(self):
        results = search(keyword="sycophancy")
        assert len(results) >= 1
        assert any("Sycophantic" in c.name for c in results)

    def test_by_keyword_case_insensitive(self):
        r1 = search(keyword="memory")
        r2 = search(keyword="MEMORY")
        assert len(r1) == len(r2)

    def test_combined_filters(self):
        results = search(category=Category.TOOL, severity=Severity.CRITICAL)
        assert len(results) >= 1
        for card in results:
            assert card.category == Category.TOOL
            assert card.severity == Severity.CRITICAL

    def test_empty_search_returns_all(self):
        results = search()
        assert len(results) == len(all_cards())

    def test_no_match_returns_empty(self):
        results = search(keyword="xyzzy_nonexistent_12345")
        assert results == []


class TestCardsBySeverity:
    def test_critical(self):
        results = cards_by_severity(Severity.CRITICAL)
        assert len(results) >= 5
        for c in results:
            assert c.severity == Severity.CRITICAL

    def test_info_may_be_zero(self):
        results = cards_by_severity(Severity.INFO)
        assert isinstance(results, list)


class TestCardsByCategory:
    def test_alignment(self):
        results = cards_by_category(Category.ALIGNMENT)
        assert len(results) >= 3
        for c in results:
            assert c.category == Category.ALIGNMENT

    def test_tool(self):
        results = cards_by_category(Category.TOOL)
        assert len(results) >= 2


class TestCardsByStatus:
    def test_proven(self):
        results = cards_by_status(Status.PROVEN)
        assert len(results) >= 10

    def test_proven_mitigated(self):
        results = cards_by_status(Status.PROVEN_MITIGATED)
        assert len(results) >= 3

    def test_not_proven(self):
        results = cards_by_status(Status.NOT_PROVEN)
        assert len(results) >= 1  # Deceptive alignment


class TestCardCount:
    def test_returns_dict(self):
        counts = card_count()
        assert isinstance(counts, dict)
        assert "total" in counts
        assert "by_severity" in counts
        assert "by_category" in counts
        assert "by_status" in counts

    def test_total_matches_all_cards(self):
        counts = card_count()
        assert counts["total"] == len(all_cards())

    def test_severity_sums_to_total(self):
        counts = card_count()
        sev_sum = sum(counts["by_severity"].values())
        assert sev_sum == counts["total"]

    def test_category_sums_to_total(self):
        counts = card_count()
        cat_sum = sum(counts["by_category"].values())
        assert cat_sum == counts["total"]


# ═══════════════════════════════════════════════════════════════════════════
# DATA INTEGRITY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestCardIntegrity:
    def test_no_duplicate_ids(self):
        ids = [c.ave_id for c in all_cards()]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_all_ids_follow_format(self):
        import re
        pattern = re.compile(r"^AVE-\d{4}-\d{4}$")
        for card in all_cards():
            assert pattern.match(card.ave_id), f"Bad ID format: {card.ave_id}"

    def test_all_have_names(self):
        for card in all_cards():
            assert card.name, f"{card.ave_id} has empty name"

    def test_all_have_summaries(self):
        for card in all_cards():
            assert card.summary, f"{card.ave_id} has empty summary"

    def test_all_have_mechanisms(self):
        for card in all_cards():
            assert card.mechanism, f"{card.ave_id} has empty mechanism"

    def test_proven_cards_have_evidence(self):
        """Every PROVEN or PROVEN_MITIGATED card must have at least one evidence pointer."""
        for card in all_cards():
            if card.status in (Status.PROVEN, Status.PROVEN_MITIGATED):
                assert card.evidence, f"{card.ave_id} ({card.name}) is {card.status.value} but has no evidence"

    def test_mitigated_cards_have_defences(self):
        """Every PROVEN_MITIGATED card must have at least one defence."""
        for card in all_cards():
            if card.status == Status.PROVEN_MITIGATED:
                assert card.defences, f"{card.ave_id} ({card.name}) is mitigated but has no defences"

    def test_experiment_ids_are_plausible(self):
        """All experiment IDs should look like exp1, exp2, ..., exp29 or similar."""
        import re
        pattern = re.compile(r"^exp\d+")
        for card in all_cards():
            for e in card.evidence:
                assert pattern.match(e.experiment_id), (
                    f"{card.ave_id} has weird experiment_id: {e.experiment_id}"
                )

    def test_sequential_ids(self):
        """IDs should be sequential from 0001."""
        ids = sorted(c.ave_id for c in all_cards())
        for i, ave_id in enumerate(ids):
            expected_num = i + 1
            actual_num = int(ave_id.split("-")[-1])
            assert actual_num == expected_num, (
                f"Gap in IDs: expected {expected_num:04d}, got {actual_num:04d}"
            )

    def test_all_cards_serialisable(self):
        """Every card must survive JSON round-trip."""
        for card in all_cards():
            d = card.to_dict()
            s = json.dumps(d)
            parsed = json.loads(s)
            assert parsed["ave_id"] == card.ave_id

    def test_all_cards_have_short(self):
        for card in all_cards():
            s = card.short()
            assert card.ave_id in s
            assert card.name in s

    def test_all_cards_have_str(self):
        for card in all_cards():
            s = str(card)
            assert card.ave_id in s
