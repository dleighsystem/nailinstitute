"""Rendered report + tamper-evident attestation."""

import pytest

from compliance import (
    ComplianceAttestation,
    Jurisdiction,
    Party,
    RiskTier,
    WorkflowProfile,
    attest,
    evaluate,
    render_markdown,
)


class _FakeChainEntry:
    def __init__(self, entry_hash):
        self.entry_hash = entry_hash


class _FakeChain:
    """Duck-typed shield HashChain: append(source=, canonical_sha256=) -> entry."""
    def __init__(self):
        self.entries = []

    def append(self, *, source, canonical_sha256):
        entry = _FakeChainEntry(f"c-{len(self.entries)}-{canonical_sha256[:8]}")
        self.entries.append((source, canonical_sha256))
        return entry


def _report(caps=frozenset()):
    return evaluate(WorkflowProfile(
        "claims-agent", Party.DEPLOYER, RiskTier.HIGH, capabilities=caps,
        jurisdictions=(Jurisdiction.EU, Jurisdiction.UK, Jurisdiction.US)))


def test_markdown_lists_gaps_by_jurisdiction():
    md = render_markdown(_report())
    assert "# Compliance Gap Report — claims-agent" in md
    assert "NON-COMPLIANT" in md
    assert "EU — European Union" in md
    assert "UK — United Kingdom" in md
    assert "US — United States" in md
    assert "⚠️ Gaps" in md
    assert "missing:" in md
    assert "not legal advice" in md.lower()


def test_markdown_shows_satisfied_evidence():
    caps = {"human_oversight", "operational_logging", "post_market_monitoring"}
    md = render_markdown(_report(caps))
    assert "✅ Satisfied" in md
    assert "EU-AIA-ART26" in md          # deployer monitoring satisfied
    assert "fleet" in md                 # evidence component rendered


def test_attestation_hash_is_deterministic():
    r = _report()
    a1 = attest(r)
    a2 = attest(r)
    assert a1.content_hash == a2.content_hash
    assert len(a1.content_hash) == 64
    assert set(a1.jurisdictions) == {"eu", "uk", "us"}
    assert a1.compliant is False


def test_attestation_changes_with_content():
    bare = attest(_report())
    better = attest(_report({"human_oversight", "operational_logging", "post_market_monitoring"}))
    assert bare.content_hash != better.content_hash


def test_attestation_anchors_into_hash_chain():
    chain = _FakeChain()
    a = attest(_report(), chain=chain)
    assert a.chain_id is not None and a.chain_id.startswith("c-")
    assert chain.entries[0][1] == a.content_hash        # the anchored digest matches
    md = render_markdown(_report(), attestation=a)
    assert f"sha256:{a.content_hash}" in md
    assert f"chain `{a.chain_id}`" in md


def test_attestation_anchors_into_real_shield_chain_if_available(tmp_path):
    HashChain = pytest.importorskip("shield.chain").HashChain
    a = attest(_report(), chain=HashChain(str(tmp_path / "chain.jsonl")))
    assert a.chain_id and len(a.chain_id) >= 16         # a real entry_hash was returned
