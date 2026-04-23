"""Tests for M6: signed advisory channel + ave-database hot-reload."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

# Sibling-package shim for arsenal — same trick the production code uses.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "arsenal"))

from arsenal.keys import generate_keypair  # noqa: E402

from threatfeed.advisory import (  # noqa: E402
    Advisory, AdvisoryKind, Severity, Mitigation,
    AdvisoryError, sign_advisory, verify_bundle, parse_bundle,
)
from threatfeed.advisory_channel import (  # noqa: E402
    Channel, Watcher, DuplicateAdvisory,
)
from threatfeed.ave_reload import AveReloader, load_snapshot  # noqa: E402
from threatfeed.advisory_cli import main as cli_main  # noqa: E402


# ── advisory data model ─────────────────────────────────────────────
def test_advisory_new_sets_window():
    adv = Advisory.new(
        id="ADV-X-1", kind="cve", severity="high",
        title="t", summary="s", affects=["model:foo*"], ttl_s=3600,
    )
    assert adv.expires_at - adv.issued_at == 3600
    assert adv.is_active()
    assert not adv.is_expired()
    assert adv.severity_rank() == 3


def test_advisory_matches_glob():
    adv = Advisory.new(
        id="ADV-X-2", kind="technique", severity="medium",
        title="t", summary="s",
        affects=["model:mistral:*", "tool:refunds.*"],
    )
    assert adv.matches(model="mistral:7b-instruct")
    assert not adv.matches(model="llama:8b")
    assert adv.matches(tool="refunds.issue")
    assert not adv.matches(tool="tickets.read")


def test_canonical_bytes_stable_across_runs():
    a = Advisory.new(id="ADV-Z", kind="cve", severity="low",
                     title="x", summary="y", affects=["model:a"])
    b1 = a.canonical_bytes()
    b2 = a.canonical_bytes()
    assert b1 == b2
    # canonical encoding is sort_keys + no whitespace
    assert b" " not in b1


# ── sign / verify roundtrip ─────────────────────────────────────────
def test_sign_and_verify_roundtrip(tmp_path):
    key = generate_keypair(directory=tmp_path)
    adv = Advisory.new(id="ADV-1", kind="cve", severity="critical",
                       title="t", summary="s", affects=["model:foo"])
    bundle = sign_advisory(adv, key=key)
    assert "signature" in bundle and "payload" in bundle
    parsed = verify_bundle(bundle, trusted_keys=[key])
    assert parsed.id == "ADV-1"
    assert parsed.severity == Severity.CRITICAL


def test_verify_rejects_tampered(tmp_path):
    key = generate_keypair(directory=tmp_path)
    adv = Advisory.new(id="ADV-T", kind="cve", severity="low",
                       title="t", summary="s", affects=["model:x"])
    bundle = sign_advisory(adv, key=key)
    bundle["payload"]["severity"] = "critical"  # escalate after signing
    with pytest.raises(AdvisoryError):
        verify_bundle(bundle, trusted_keys=[key])


def test_verify_rejects_wrong_key(tmp_path):
    k1 = generate_keypair(directory=tmp_path / "k1")
    k2 = generate_keypair(directory=tmp_path / "k2")
    adv = Advisory.new(id="ADV-W", kind="cve", severity="low",
                       title="t", summary="s", affects=["model:x"])
    bundle = sign_advisory(adv, key=k1)
    with pytest.raises(AdvisoryError):
        verify_bundle(bundle, trusted_keys=[k2])


def test_parse_bundle_rejects_malformed():
    with pytest.raises(AdvisoryError):
        parse_bundle({"signature": "x"})  # missing payload


# ── channel: publish / replay / dedupe ──────────────────────────────
def test_channel_publish_and_replay(tmp_path):
    key = generate_keypair(directory=tmp_path / "keys")
    ch = Channel(directory=tmp_path / "advisories")

    for i in range(3):
        adv = Advisory.new(id=f"ADV-2026-{i:04d}", kind="cve",
                           severity="medium", title=f"t{i}",
                           summary="", affects=["model:x"])
        ch.publish(sign_advisory(adv, key=key))

    out = list(ch.replay(trusted_keys=[key]))
    assert [a.id for a in out] == [f"ADV-2026-{i:04d}" for i in range(3)]


def test_channel_rejects_duplicate(tmp_path):
    key = generate_keypair(directory=tmp_path / "keys")
    ch = Channel(directory=tmp_path / "ch")
    adv = Advisory.new(id="ADV-DUP", kind="cve", severity="low",
                       title="t", summary="", affects=["model:x"])
    ch.publish(sign_advisory(adv, key=key))
    with pytest.raises(DuplicateAdvisory):
        ch.publish(sign_advisory(adv, key=key))
    # but allow_replace works
    ch.publish(sign_advisory(adv, key=key), allow_replace=True)


def test_channel_replay_skips_bad_signatures(tmp_path):
    k1 = generate_keypair(directory=tmp_path / "k1")
    k2 = generate_keypair(directory=tmp_path / "k2")
    ch = Channel(directory=tmp_path / "ch")
    good = Advisory.new(id="GOOD", kind="cve", severity="low",
                        title="g", summary="", affects=["model:x"])
    bad = Advisory.new(id="BAD", kind="cve", severity="low",
                       title="b", summary="", affects=["model:x"])
    ch.publish(sign_advisory(good, key=k1))
    ch.publish(sign_advisory(bad, key=k2))   # signed by untrusted key
    out = list(ch.replay(trusted_keys=[k1]))
    assert [a.id for a in out] == ["GOOD"]


# ── watcher ─────────────────────────────────────────────────────────
def test_watcher_dispatches_only_new(tmp_path):
    key = generate_keypair(directory=tmp_path / "k")
    ch = Channel(directory=tmp_path / "ch")
    received: list[str] = []
    w = Watcher(ch, trusted_keys=[key])
    w.on_advisory(lambda a: received.append(a.id))

    a1 = Advisory.new(id="A1", kind="cve", severity="low",
                      title="", summary="", affects=["model:x"])
    ch.publish(sign_advisory(a1, key=key))
    w.poll_once()
    assert received == ["A1"]

    # Second poll: no change.
    w.poll_once()
    assert received == ["A1"]

    # Add another, poll picks it up only.
    a2 = Advisory.new(id="A2", kind="cve", severity="low",
                      title="", summary="", affects=["model:x"])
    ch.publish(sign_advisory(a2, key=key))
    w.poll_once()
    assert received == ["A1", "A2"]


def test_watcher_callback_exception_does_not_kill_watcher(tmp_path):
    key = generate_keypair(directory=tmp_path / "k")
    ch = Channel(directory=tmp_path / "ch")
    seen: list[str] = []
    w = Watcher(ch, trusted_keys=[key])
    w.on_advisory(lambda a: (_ for _ in ()).throw(RuntimeError("boom")))
    w.on_advisory(lambda a: seen.append(a.id))

    adv = Advisory.new(id="A-BOOM", kind="cve", severity="low",
                       title="", summary="", affects=["model:x"])
    ch.publish(sign_advisory(adv, key=key))
    w.poll_once()
    assert seen == ["A-BOOM"]


# ── ave-database hot-reload ─────────────────────────────────────────
def _seed_ave_db(d: Path, *, version="1.0.0", n_cards=2,
                 generated_at="2026-04-23T00:00:00Z") -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.json").write_text(json.dumps({
        "schema_version": version,
        "generated_at": generated_at,
        "total_cards": n_cards,
        "cards": [
            {"ave_id": f"AVE-2026-{i:04d}", "name": f"x{i}",
             "category": "memory", "severity": "high",
             "status": "proven_mitigated"}
            for i in range(n_cards)
        ],
    }))
    (d / "severity_index.json").write_text(json.dumps({"high": n_cards}))


def test_load_snapshot(tmp_path):
    _seed_ave_db(tmp_path)
    snap = load_snapshot(tmp_path)
    assert snap.total_cards == 2
    assert snap.by_id("AVE-2026-0001")["name"] == "x1"
    assert "memory" in snap.categories()
    assert len(snap.by_severity("high")) == 2
    assert len(snap.content_hash) == 16


def test_reloader_no_change_returns_false(tmp_path):
    _seed_ave_db(tmp_path)
    r = AveReloader(tmp_path)
    assert r.reload() is False  # nothing changed


def test_reloader_picks_up_disk_change(tmp_path):
    _seed_ave_db(tmp_path)
    received: list = []
    r = AveReloader(tmp_path, on_reload=lambda s: received.append(s))
    old_hash = r.snapshot.content_hash
    _seed_ave_db(tmp_path, n_cards=5,
                 generated_at="2026-04-23T01:00:00Z")
    assert r.reload() is True
    assert r.snapshot.total_cards == 5
    assert r.snapshot.content_hash != old_hash
    assert len(received) == 1


def test_reloader_reacts_to_advisory(tmp_path):
    _seed_ave_db(tmp_path)
    r = AveReloader(tmp_path)
    # advisory of kind POLICY should NOT trigger
    pol = Advisory.new(id="P", kind="policy", severity="low",
                       title="", summary="", affects=["model:x"])
    assert r.react_to_advisory(pol) is False

    # advisory of kind TECHNIQUE SHOULD trigger when content has changed
    _seed_ave_db(tmp_path, n_cards=7, generated_at="2026-04-23T02:00:00Z")
    tech = Advisory.new(id="T", kind="technique", severity="high",
                        title="", summary="", affects=["model:x"])
    assert r.react_to_advisory(tech) is True
    assert r.snapshot.total_cards == 7


# ── CLI ──────────────────────────────────────────────────────────────
def test_cli_publish_and_verify_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NAIL_ARSENAL_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("NAIL_ADVISORY_DIR", str(tmp_path / "ch"))

    rc = cli_main([
        "publish",
        "--id", "ADV-CLI-1",
        "--kind", "technique",
        "--severity", "high",
        "--title", "test advisory",
        "--summary", "hello",
        "--affects", "model:mistral:*",
        "--affects", "tool:refunds.*",
        "--ave-ref", "AVE-2025-0001",
        "--action", "block",
        "--ttl", "3600",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out

    bundle_path = next((tmp_path / "ch" / "bundles").glob("*.json"))
    rc = cli_main(["verify", "--bundle", str(bundle_path)])
    assert rc == 0


def test_cli_replay(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NAIL_ARSENAL_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("NAIL_ADVISORY_DIR", str(tmp_path / "ch"))
    cli_main(["publish", "--id", "ADV-R-1", "--kind", "cve",
              "--severity", "low", "--title", "t",
              "--affects", "model:x"])
    cli_main(["publish", "--id", "ADV-R-2", "--kind", "cve",
              "--severity", "low", "--title", "t",
              "--affects", "model:x"])
    capsys.readouterr()  # discard
    rc = cli_main(["replay", "--verify"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ADV-R-1" in out and "ADV-R-2" in out
