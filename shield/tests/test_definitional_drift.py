"""Tests for DefinitionalDriftDetector — AVE-2026-0037 Semantic Fragmentation.

Covers extraction (structured + free-text), structural divergence, the
silent both-lineage-clean case, orthogonality to TaintVault laundering, the
optional embedding tier, and the false-positive guard.
"""
from __future__ import annotations

import pytest

from shield.taint_vault import TaintVault, TrustLevel
from shield.definitional_drift import (
    DefinitionalDriftDetector,
    DefinitionFingerprint,
    cosine_divergence,
    jaccard_divergence,
    make_hybrid_divergence,
    default_embed_fn,
    structural_extractor,
    tokenise_definition,
    normalise_term,
    CLEAN_TRUST_FLOOR,
)


# ── P6 semantic tier: deterministic fake embedding ────────────────────────────

def _fake_embed(text):
    """Concept-axis embedding: synonyms collapse to the same vector.

    Axes: (user-concept, login-concept, transaction-concept). Lets tests show
    the semantic tier resolving 'users' vs 'accounts' that the structural tier
    cannot.
    """
    t = text.lower()
    user = 1.0 if ("user" in t or "account" in t) else 0.0
    login = 1.0 if ("login" in t or "logged" in t) else 0.0
    txn = 1.0 if ("transaction" in t or "purchase" in t) else 0.0
    return (user, login, txn)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _store_def(vault, agent_id, term, expr, *, trust=TrustLevel.VERIFIED, derived_from=None):
    return vault.store(
        f"{term} := {expr}",
        trust_score=trust,
        derived_from=derived_from,
        metadata={"agent_id": agent_id, "definition": {"term": term, "expr": expr}},
    )


# ── Tokenisation ──────────────────────────────────────────────────────────────

def test_tokenise_drops_operator_words():
    # "minus" / "-" both vanish; operands survive identically
    assert tokenise_definition("gross minus refunds") == tokenise_definition("gross - refunds")
    assert tokenise_definition("gross minus refunds") == frozenset({"gross", "refunds"})


def test_normalise_term_canonicalises():
    assert normalise_term("  Active   User ") == "active user"


# ── Extraction: structured records ────────────────────────────────────────────

def test_structural_extractor_reads_metadata_record():
    vault = TaintVault()
    e = _store_def(vault, "A", "revenue", "gross minus refunds")
    exts = structural_extractor(vault.lookup(e.fact_id))
    assert len(exts) == 1
    assert exts[0].term == "revenue"
    assert exts[0].tokens == frozenset({"gross", "refunds"})


def test_structural_extractor_handles_list_of_records():
    vault = TaintVault()
    e = vault.store(
        "policy glossary",
        metadata={"agent_id": "A", "definition": [
            {"term": "revenue", "expr": "gross minus refunds"},
            {"term": "churn", "expr": "cancellations over subscribers"},
        ]},
    )
    exts = structural_extractor(vault.lookup(e.fact_id))
    assert {x.term for x in exts} == {"revenue", "churn"}


def test_extractor_returns_empty_for_non_definition_fact():
    vault = TaintVault()
    e = vault.store("the weather is nice today", metadata={"agent_id": "A"})
    assert structural_extractor(vault.lookup(e.fact_id)) == []


# ── Extraction: free-text fallback ────────────────────────────────────────────

@pytest.mark.parametrize("content", [
    "revenue := gross minus refunds",
    "revenue is defined as gross minus refunds",
    "revenue means gross minus refunds",
    "we define revenue as gross minus refunds",
])
def test_free_text_patterns(content):
    vault = TaintVault()
    e = vault.store(content, metadata={"agent_id": "A"})   # no structured record
    exts = structural_extractor(vault.lookup(e.fact_id))
    assert any(x.term == "revenue" and "gross" in x.tokens and "refunds" in x.tokens
               for x in exts)


# ── Core detection ────────────────────────────────────────────────────────────

def test_silent_divergence_both_clean():
    """The headline case: two clean lineages, contradictory definitions."""
    vault = TaintVault()
    _store_def(vault, "underwriter-A", "revenue", "gross minus refunds")
    _store_def(vault, "underwriter-B", "revenue", "gross")

    findings = DefinitionalDriftDetector(vault).scan()
    assert len(findings) == 1
    f = findings[0]
    assert f.term == "revenue"
    assert {f.agent_a, f.agent_b} == {"underwriter-A", "underwriter-B"}
    assert f.divergence > 0.30
    assert f.both_lineage_clean is True


def test_aligned_definitions_no_finding():
    """False-positive guard — identical meaning must not flag."""
    vault = TaintVault()
    _store_def(vault, "A", "revenue", "gross minus refunds")
    _store_def(vault, "B", "revenue", "gross - refunds")   # same operands
    assert DefinitionalDriftDetector(vault).scan() == []


def test_same_agent_contradiction_is_ignored():
    """Cross-agent only — intra-agent self-contradiction is a different pathology."""
    vault = TaintVault()
    _store_def(vault, "A", "revenue", "gross minus refunds")
    _store_def(vault, "A", "revenue", "gross")
    assert DefinitionalDriftDetector(vault).scan() == []


def test_different_terms_never_compared():
    vault = TaintVault()
    _store_def(vault, "A", "revenue", "gross")
    _store_def(vault, "B", "churn", "cancellations")
    assert DefinitionalDriftDetector(vault).scan() == []


def test_small_difference_below_threshold_not_flagged():
    vault = TaintVault()
    # 3 shared operands, 1 extra on B → Jaccard distance = 1 - 3/4 = 0.25 < 0.30
    _store_def(vault, "A", "margin", "price cost tax")
    _store_def(vault, "B", "margin", "price cost tax discount")
    assert DefinitionalDriftDetector(vault, divergence_threshold=0.30).scan() == []


def test_threshold_is_configurable():
    vault = TaintVault()
    _store_def(vault, "A", "margin", "price cost tax")
    _store_def(vault, "B", "margin", "price cost tax discount")   # divergence 0.25
    assert DefinitionalDriftDetector(vault, divergence_threshold=0.20).scan()


# ── Trust / orthogonality ─────────────────────────────────────────────────────

def test_divergence_with_tainted_lineage_not_silent():
    """One definition derived from a hostile source → both_lineage_clean False."""
    vault = TaintVault()
    _store_def(vault, "A", "revenue", "gross minus refunds")
    poison = vault.store("evil input", source_chain_id="u-evil", trust_score=TrustLevel.HOSTILE)
    vault.derive(
        "revenue := gross",
        parent_ids=[poison.fact_id],
        metadata={"agent_id": "B", "definition": {"term": "revenue", "expr": "gross"}},
    )
    findings = DefinitionalDriftDetector(vault).scan()
    assert len(findings) == 1
    assert findings[0].both_lineage_clean is False


def test_orthogonal_to_memory_laundering():
    """Two clean lineages: TaintVault flags NO laundering, drift detector DOES flag."""
    vault = TaintVault()
    a = _store_def(vault, "A", "revenue", "gross minus refunds")
    b = _store_def(vault, "B", "revenue", "gross")

    # TaintVault is silent — neither fact's trust was laundered.
    assert not vault.detect_laundering(a.fact_id).laundering_detected
    assert not vault.detect_laundering(b.fact_id).laundering_detected
    assert vault.scan_for_laundering() == []

    # The drift detector catches what TaintVault structurally cannot.
    findings = DefinitionalDriftDetector(vault).scan()
    assert len(findings) == 1
    assert findings[0].both_lineage_clean is True


def test_silent_findings_sort_first():
    vault = TaintVault()
    # tainted divergence on "churn"
    _store_def(vault, "A", "churn", "cancellations")
    poison = vault.store("evil", source_chain_id="u-evil", trust_score=TrustLevel.HOSTILE)
    vault.derive("churn := logins", parent_ids=[poison.fact_id],
                 metadata={"agent_id": "B", "definition": {"term": "churn", "expr": "logins"}})
    # clean divergence on "revenue"
    _store_def(vault, "A", "revenue", "gross minus refunds")
    _store_def(vault, "B", "revenue", "net income taxes")

    findings = DefinitionalDriftDetector(vault).scan()
    assert len(findings) == 2
    assert findings[0].both_lineage_clean is True   # silent case ranked first


# ── Gating / serialisation ────────────────────────────────────────────────────

def test_has_unresolved_conflicts():
    vault = TaintVault()
    detector = DefinitionalDriftDetector(vault)
    assert detector.has_unresolved_conflicts() is False
    _store_def(vault, "A", "revenue", "gross minus refunds")
    _store_def(vault, "B", "revenue", "gross")
    assert detector.has_unresolved_conflicts() is True


def test_finding_to_dict():
    vault = TaintVault()
    _store_def(vault, "A", "revenue", "gross minus refunds")
    _store_def(vault, "B", "revenue", "gross")
    d = DefinitionalDriftDetector(vault).scan()[0].to_dict()
    assert d["term"] == "revenue"
    assert d["both_lineage_clean"] is True
    assert len(d["fact_ids"]) == 2
    assert "revenue" in d["explanation"]


def test_unknown_agent_label_when_metadata_missing():
    vault = TaintVault()
    vault.store("revenue := gross minus refunds",
                metadata={"definition": {"term": "revenue", "expr": "gross minus refunds"}})
    vault.store("revenue := gross",
                metadata={"agent_id": "B", "definition": {"term": "revenue", "expr": "gross"}})
    findings = DefinitionalDriftDetector(vault).scan()
    assert len(findings) == 1
    assert "<unknown-agent>" in {findings[0].agent_a, findings[0].agent_b}


# ── Divergence functions ──────────────────────────────────────────────────────

def test_jaccard_identical_is_zero():
    fp = lambda toks: DefinitionFingerprint("t", "a", "f", "d", frozenset(toks), 0.9)
    assert jaccard_divergence(fp({"x", "y"}), fp({"x", "y"})) == 0.0


def test_jaccard_disjoint_is_one():
    fp = lambda aid, toks: DefinitionFingerprint("t", aid, "f", "d", frozenset(toks), 0.9)
    assert jaccard_divergence(fp("a", {"x"}), fp("b", {"y"})) == 1.0


def test_jaccard_both_empty_is_zero():
    fp = lambda aid: DefinitionFingerprint("t", aid, "f", "d", frozenset(), 0.9)
    assert jaccard_divergence(fp("a"), fp("b")) == 0.0


def test_cosine_divergence_tier():
    a = DefinitionFingerprint("t", "a", "f1", "d1", frozenset(), 0.9, embedding=(1.0, 0.0))
    b = DefinitionFingerprint("t", "b", "f2", "d2", frozenset(), 0.9, embedding=(0.0, 1.0))
    assert cosine_divergence(a, b) == pytest.approx(1.0)
    same = DefinitionFingerprint("t", "b", "f3", "d3", frozenset(), 0.9, embedding=(1.0, 0.0))
    assert cosine_divergence(a, same) == pytest.approx(0.0, abs=1e-9)


def test_cosine_requires_embeddings():
    a = DefinitionFingerprint("t", "a", "f", "d", frozenset(), 0.9)
    b = DefinitionFingerprint("t", "b", "f", "d", frozenset(), 0.9)
    with pytest.raises(ValueError):
        cosine_divergence(a, b)


def test_detector_uses_injected_divergence_fn():
    """A custom divergence_fn is actually consulted by scan()."""
    vault = TaintVault()
    # Distinct operands, but jaccard distance 0.25 < default threshold → the
    # structural default would flag nothing. The custom fn must override.
    _store_def(vault, "A", "margin", "price cost tax")
    _store_def(vault, "B", "margin", "price cost tax discount")

    calls = {"n": 0}

    def always_divergent(a, b):
        calls["n"] += 1
        return 1.0

    findings = DefinitionalDriftDetector(vault, divergence_fn=always_divergent).scan()
    assert calls["n"] == 1            # the injected fn was invoked on the cross-agent pair
    assert len(findings) == 1         # ...and its verdict drove the finding
    assert findings[0].divergence == 1.0


# ── P6: semantic / embedding tier (flag-gated) ────────────────────────────────

def test_semantic_requires_embed_fn():
    vault = TaintVault()
    with pytest.raises(ValueError):
        DefinitionalDriftDetector(vault, semantic=True)


def test_default_is_structural_backward_compatible():
    """Without semantic=True the detector ignores embeddings entirely."""
    vault = TaintVault()
    _store_def(vault, "A", "revenue", "gross minus refunds")
    det = DefinitionalDriftDetector(vault)
    assert det.semantic is False
    assert det.fingerprints()[0].embedding is None


def test_structural_false_positives_on_synonyms():
    """Baseline: the structural tier flags synonymous phrasings (the P6 gap)."""
    vault = TaintVault()
    _store_def(vault, "A", "active_user", "users with login")
    _store_def(vault, "B", "active_user", "accounts that logged in")
    findings = DefinitionalDriftDetector(vault).scan()
    assert len(findings) == 1   # different operand nouns -> false positive


def test_semantic_tier_resolves_synonyms():
    """The embedding tier recognises the synonyms as equivalent — no false flag."""
    vault = TaintVault()
    _store_def(vault, "A", "active_user", "users with login")
    _store_def(vault, "B", "active_user", "accounts that logged in")
    findings = DefinitionalDriftDetector(vault, semantic=True, embed_fn=_fake_embed).scan()
    assert findings == []


def test_semantic_tier_still_catches_real_divergence():
    vault = TaintVault()
    _store_def(vault, "A", "active_user", "users with login")
    _store_def(vault, "B", "active_user", "users with transaction")
    findings = DefinitionalDriftDetector(vault, semantic=True, embed_fn=_fake_embed).scan()
    assert len(findings) == 1
    assert findings[0].both_lineage_clean is True


def test_fingerprints_carry_embeddings_when_semantic():
    vault = TaintVault()
    _store_def(vault, "A", "revenue", "gross minus refunds")
    fps = DefinitionalDriftDetector(vault, semantic=True, embed_fn=_fake_embed).fingerprints()
    assert fps[0].embedding is not None
    assert isinstance(fps[0].embedding, tuple)


def test_hybrid_divergence_blends_when_embeddings_present():
    a = DefinitionFingerprint("t", "a", "f1", "d1", frozenset({"x"}), 0.9, embedding=(1.0, 0.0))
    b = DefinitionFingerprint("t", "b", "f2", "d2", frozenset({"y"}), 0.9, embedding=(0.0, 1.0))
    hybrid = make_hybrid_divergence(structural_weight=0.5)
    # jaccard({x},{y}) = 1.0 ; cosine(orthogonal) = 1.0 ; blend = 1.0
    assert hybrid(a, b) == pytest.approx(1.0)
    # identical embeddings pull the blend down below pure jaccard
    b2 = DefinitionFingerprint("t", "b", "f3", "d3", frozenset({"y"}), 0.9, embedding=(1.0, 0.0))
    assert hybrid(a, b2) == pytest.approx(0.5)   # 0.5*1.0(jaccard) + 0.5*0.0(cosine)


def test_hybrid_falls_back_to_jaccard_without_embeddings():
    a = DefinitionFingerprint("t", "a", "f1", "d1", frozenset({"x"}), 0.9)   # no embedding
    b = DefinitionFingerprint("t", "b", "f2", "d2", frozenset({"x", "y"}), 0.9)
    hybrid = make_hybrid_divergence()
    assert hybrid(a, b) == pytest.approx(jaccard_divergence(a, b))


def test_detector_accepts_hybrid_divergence_fn():
    vault = TaintVault()
    _store_def(vault, "A", "active_user", "users with login")
    _store_def(vault, "B", "active_user", "accounts that logged in")
    det = DefinitionalDriftDetector(
        vault, semantic=True, embed_fn=_fake_embed,
        divergence_fn=make_hybrid_divergence(structural_weight=0.5),
    )
    assert isinstance(det.scan(), list)   # runs without error


def test_default_embed_fn_without_library_raises():
    """If sentence-transformers is absent, default_embed_fn fails loudly."""
    import importlib.util
    if importlib.util.find_spec("sentence_transformers") is not None:
        pytest.skip("sentence-transformers is installed in this environment")
    with pytest.raises(RuntimeError):
        default_embed_fn()
