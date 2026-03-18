"""
Tests for the enrichment engine and public repo generation.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile

import pytest

import ave
from ave.enrich import (
    enrich_all, enrich_card,
    _AVSS_VECTORS, _RELATED_AVES, _POC_DATA, _build_timeline,
)
from ave.scoring import AVSSScore, compute_avss
from ave.timeline import CardTimeline, LifecycleStage
from ave.poc import ProofOfConcept, PoCStatus
from ave.export import export_database, card_to_json, card_to_markdown


# ═══════════════════════════════════════════════════════════════════════════
# ENRICHMENT TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestEnrichAll:
    """Test bulk enrichment of the entire registry."""

    def setup_method(self):
        """Reset enrichment state before each test."""
        # Clear enrichment from all cards
        for card in ave.all_cards():
            card.avss_score = None
            card.timeline = None
            card.poc = None
            card.related_aves = ()

    def test_enrich_all_returns_counts(self):
        result = enrich_all()
        assert isinstance(result, dict)
        assert "avss" in result
        assert "timeline" in result
        assert "poc" in result
        assert "related" in result

    def test_enrich_all_populates_avss(self):
        enrich_all()
        scored = [c for c in ave.all_cards() if c.avss_score is not None]
        assert len(scored) == len(ave.all_cards())  # Every card gets a score

    def test_enrich_all_populates_timelines(self):
        enrich_all()
        with_tl = [c for c in ave.all_cards() if c.timeline is not None]
        assert len(with_tl) == len(ave.all_cards())

    def test_enrich_all_populates_pocs(self):
        enrich_all()
        with_poc = [c for c in ave.all_cards() if c.poc is not None]
        assert len(with_poc) == len(_POC_DATA)  # PoCs only for cards with data
        assert len(with_poc) >= 15

    def test_enrich_all_populates_related(self):
        enrich_all()
        with_rel = [c for c in ave.all_cards() if c.related_aves]
        # At least the cards in _RELATED_AVES should have cross-refs
        assert len(with_rel) >= len(_RELATED_AVES)

    def test_enrich_idempotent(self):
        """Running enrich_all twice should not double-enrich."""
        r1 = enrich_all()
        r2 = enrich_all()
        # Second run should find nothing to do
        assert r2["avss"] == 0
        assert r2["timeline"] == 0
        assert r2["poc"] == 0
        assert r2["related"] == 0


class TestEnrichCard:
    """Test per-card enrichment."""

    def setup_method(self):
        for card in ave.all_cards():
            card.avss_score = None
            card.timeline = None
            card.poc = None
            card.related_aves = ()

    def test_enrich_single_card(self):
        card = ave.lookup("AVE-2025-0001")
        enrich_card(card)
        assert card.avss_score is not None
        assert card.timeline is not None
        assert card.poc is not None
        assert len(card.related_aves) > 0

    def test_enrich_card_without_poc_data(self):
        card = ave.lookup("AVE-2025-0004")  # Prompt Inbreeding — no PoC sketch
        enrich_card(card)
        assert card.avss_score is not None
        assert card.timeline is not None
        assert card.poc is None  # No PoC data defined
        assert len(card.related_aves) > 0  # But has related AVEs

    def test_enrich_theoretical_card(self):
        card = ave.lookup("AVE-2025-0030")  # Semantic Trojan Horse — theoretical
        enrich_card(card)
        assert card.avss_score is not None
        assert card.timeline is not None
        # Theoretical should NOT have confirmed or mitigated events
        stages = [e.stage for e in card.timeline.events]
        assert LifecycleStage.CONFIRMED not in stages
        assert LifecycleStage.MITIGATED not in stages

    def test_enrich_mitigated_card(self):
        card = ave.lookup("AVE-2025-0001")  # Sleeper Payload — proven_mitigated
        enrich_card(card)
        stages = [e.stage for e in card.timeline.events]
        assert LifecycleStage.DISCOVERED in stages
        assert LifecycleStage.CONFIRMED in stages
        assert LifecycleStage.PUBLISHED in stages
        assert LifecycleStage.MITIGATED in stages


class TestAVSSVectors:
    """Test AVSS vector definitions cover all cards."""

    def test_all_cards_have_vectors(self):
        """Every card in the registry should have an AVSS vector."""
        for card in ave.all_cards():
            assert card.ave_id in _AVSS_VECTORS, f"Missing AVSS vector for {card.ave_id}"

    def test_vectors_produce_valid_scores(self):
        for ave_id, vector in _AVSS_VECTORS.items():
            score = compute_avss(vector)
            assert 0.0 <= score.overall_score <= 10.0, f"Bad score for {ave_id}: {score.overall_score}"
            assert score.severity_label in ("none", "low", "medium", "high", "critical")

    def test_critical_cards_score_high(self):
        """Cards marked critical should score >= 7.0."""
        for card in ave.all_cards():
            if card.severity.value == "critical":
                vector = _AVSS_VECTORS[card.ave_id]
                score = compute_avss(vector)
                assert score.overall_score >= 7.0, (
                    f"{card.ave_id} ({card.name}) is critical but AVSS={score.overall_score}"
                )

    def test_medium_cards_not_critical_score(self):
        """Medium-severity cards should not score as critical (>= 9.0)."""
        for card in ave.all_cards():
            if card.severity.value == "medium":
                vector = _AVSS_VECTORS[card.ave_id]
                score = compute_avss(vector)
                assert score.overall_score < 9.0, (
                    f"{card.ave_id} ({card.name}) is medium but AVSS={score.overall_score}"
                )


class TestRelatedAVEs:
    """Test cross-reference integrity."""

    def test_bidirectional_references(self):
        """If A references B, B should reference A."""
        for ave_id, related in _RELATED_AVES.items():
            for rel_id in related:
                assert rel_id in _RELATED_AVES, (
                    f"{ave_id} references {rel_id} but {rel_id} has no related_aves entry"
                )
                assert ave_id in _RELATED_AVES[rel_id], (
                    f"{ave_id} references {rel_id} but {rel_id} doesn't reference back"
                )

    def test_no_self_references(self):
        """Cards should not reference themselves."""
        for ave_id, related in _RELATED_AVES.items():
            assert ave_id not in related, f"{ave_id} references itself"

    def test_all_referenced_cards_exist(self):
        """All referenced AVE IDs should exist in the registry."""
        for ave_id, related in _RELATED_AVES.items():
            assert ave.lookup(ave_id) is not None, f"Source {ave_id} not in registry"
            for rel_id in related:
                assert ave.lookup(rel_id) is not None, f"Referenced {rel_id} not in registry"


class TestTimelines:
    """Test timeline generation."""

    def test_all_timelines_have_discovery(self):
        enrich_all()
        for card in ave.all_cards():
            assert card.timeline is not None
            stages = [e.stage for e in card.timeline.events]
            assert LifecycleStage.DISCOVERED in stages

    def test_proven_cards_have_confirmed(self):
        enrich_all()
        for card in ave.all_cards():
            if card.status.value in ("proven", "proven_mitigated"):
                stages = [e.stage for e in card.timeline.events]
                assert LifecycleStage.CONFIRMED in stages, (
                    f"{card.ave_id} is {card.status.value} but has no CONFIRMED event"
                )

    def test_mitigated_cards_have_mitigated_event(self):
        enrich_all()
        for card in ave.all_cards():
            if card.status.value == "proven_mitigated":
                assert card.timeline.is_mitigated, f"{card.ave_id} should be mitigated"


class TestPoCs:
    """Test PoC generation."""

    def test_poc_ids_match_card_ids(self):
        enrich_all()
        for card in ave.all_cards():
            if card.poc is not None:
                assert card.ave_id in card.poc.poc_id

    def test_poc_status_verified(self):
        enrich_all()
        for card in ave.all_cards():
            if card.poc is not None:
                assert card.poc.status == PoCStatus.VERIFIED

    def test_poc_has_artifacts(self):
        enrich_all()
        for card in ave.all_cards():
            if card.poc is not None:
                assert card.poc.artifact_count > 0, f"{card.ave_id} PoC has no artifacts"


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC REPO GENERATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPublicRepoExport:
    """Test generating the publishable ave-database directory."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Ensure cards are enriched
        for card in ave.all_cards():
            card.avss_score = None
            card.timeline = None
            card.poc = None
            card.related_aves = ()
        enrich_all()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_export_creates_directory_structure(self):
        result = export_database(ave.all_cards(), self.tmpdir)
        assert os.path.isdir(os.path.join(self.tmpdir, "cards"))
        assert os.path.isfile(os.path.join(self.tmpdir, "README.md"))
        assert os.path.isfile(os.path.join(self.tmpdir, "index.json"))

    def test_export_creates_card_files(self):
        export_database(ave.all_cards(), self.tmpdir)
        cards_dir = os.path.join(self.tmpdir, "cards")
        json_files = [f for f in os.listdir(cards_dir) if f.endswith(".json")]
        md_files = [f for f in os.listdir(cards_dir) if f.endswith(".md")]
        assert len(json_files) == len(ave.all_cards())
        assert len(md_files) == len(ave.all_cards())

    def test_export_json_contains_avss(self):
        export_database(ave.all_cards(), self.tmpdir)
        json_path = os.path.join(self.tmpdir, "cards", "AVE-2025-0001.json")
        with open(json_path) as f:
            data = json.load(f)
        assert "avss_score" in data
        assert data["avss_score"] is not None
        assert "overall_score" in data["avss_score"]

    def test_export_json_contains_timeline(self):
        export_database(ave.all_cards(), self.tmpdir)
        json_path = os.path.join(self.tmpdir, "cards", "AVE-2025-0001.json")
        with open(json_path) as f:
            data = json.load(f)
        assert "timeline" in data
        assert data["timeline"] is not None
        assert "events" in data["timeline"]

    def test_export_json_contains_related(self):
        export_database(ave.all_cards(), self.tmpdir)
        json_path = os.path.join(self.tmpdir, "cards", "AVE-2025-0001.json")
        with open(json_path) as f:
            data = json.load(f)
        assert "related_aves" in data
        assert len(data["related_aves"]) >= 3

    def test_export_markdown_contains_avss_section(self):
        export_database(ave.all_cards(), self.tmpdir)
        md_path = os.path.join(self.tmpdir, "cards", "AVE-2025-0001.md")
        with open(md_path) as f:
            content = f.read()
        assert "## AVSS Score" in content
        assert "/10.0" in content

    def test_export_markdown_contains_timeline(self):
        export_database(ave.all_cards(), self.tmpdir)
        md_path = os.path.join(self.tmpdir, "cards", "AVE-2025-0001.md")
        with open(md_path) as f:
            content = f.read()
        assert "## Timeline" in content
        assert "discovered" in content

    def test_export_markdown_contains_related(self):
        export_database(ave.all_cards(), self.tmpdir)
        md_path = os.path.join(self.tmpdir, "cards", "AVE-2025-0001.md")
        with open(md_path) as f:
            content = f.read()
        assert "## Related AVEs" in content

    def test_export_index_json_valid(self):
        export_database(ave.all_cards(), self.tmpdir)
        index_path = os.path.join(self.tmpdir, "index.json")
        with open(index_path) as f:
            data = json.load(f)
        assert data["total_cards"] == len(ave.all_cards())
        assert len(data["cards"]) == len(ave.all_cards())

    def test_export_severity_index(self):
        export_database(ave.all_cards(), self.tmpdir)
        sev_path = os.path.join(self.tmpdir, "severity_index.json")
        with open(sev_path) as f:
            data = json.load(f)
        assert "critical" in data
        assert "high" in data
        assert "medium" in data

    def test_readme_contains_all_cards(self):
        export_database(ave.all_cards(), self.tmpdir)
        readme_path = os.path.join(self.tmpdir, "README.md")
        with open(readme_path) as f:
            content = f.read()
        for card in ave.all_cards():
            assert card.ave_id in content

    def test_export_json_only(self):
        result = export_database(
            ave.all_cards(), self.tmpdir,
            include_markdown=False, include_index=False,
        )
        assert result["json"] == len(ave.all_cards())
        assert result["markdown"] == 0

    def test_export_markdown_only(self):
        result = export_database(
            ave.all_cards(), self.tmpdir,
            include_json=False, include_index=False,
        )
        assert result["markdown"] == len(ave.all_cards())
        assert result["json"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# END-TO-END: Enrich → Export → Verify
# ═══════════════════════════════════════════════════════════════════════════

class TestEndToEndEnrichExport:
    """Full pipeline: enrich all cards, export, verify integrity."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        for card in ave.all_cards():
            card.avss_score = None
            card.timeline = None
            card.poc = None
            card.related_aves = ()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_pipeline(self):
        # Step 1: Enrich
        counts = enrich_all()
        assert counts["avss"] == len(ave.all_cards())
        assert counts["timeline"] == len(ave.all_cards())

        # Step 2: Export
        result = export_database(ave.all_cards(), self.tmpdir)
        assert result["json"] == len(ave.all_cards())
        assert result["markdown"] == len(ave.all_cards())

        # Step 3: Verify every JSON file is valid
        cards_dir = os.path.join(self.tmpdir, "cards")
        for card in ave.all_cards():
            json_path = os.path.join(cards_dir, f"{card.ave_id}.json")
            assert os.path.exists(json_path), f"Missing JSON for {card.ave_id}"
            with open(json_path) as f:
                data = json.load(f)
            assert data["ave_id"] == card.ave_id
            assert data["name"] == card.name
            # AVSS should be present
            if card.avss_score:
                assert data["avss_score"]["overall_score"] == card.avss_score.overall_score

    def test_enriched_card_round_trip_json(self):
        """Enriched card → JSON → parse → verify all fields present."""
        enrich_all()
        card = ave.lookup("AVE-2025-0001")
        json_str = card_to_json(card)
        data = json.loads(json_str)

        assert data["ave_id"] == "AVE-2025-0001"
        assert data["avss_score"]["overall_score"] > 0
        assert data["timeline"]["event_count"] > 0
        assert len(data["related_aves"]) >= 3
        assert "poc" in data
