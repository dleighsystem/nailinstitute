"""Tests for scripts/nail_deploy.py — cert-as-deployment-gate."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import nail_deploy as nd
from arsenal.keys import generate_keypair
from arsenal.signing import sign_blob


def _good_cert(*, model="mistral:7b-instruct", scope="general",
               composite=0.85, rating="AA",
               issued_at: str | None = None) -> dict:
    if issued_at is None:
        issued_at = datetime.now(timezone.utc).isoformat()
    return {
        "certificate_type": "NAIL_LOCAL_LIVE_AGENT",
        "version": "1.0",
        "issued_at": issued_at,
        "issued_by": "test",
        "judge_model": "nail-guard:v4",
        "target_agent": {"model": model, "provider": "ollama",
                         "deployment_scope": scope},
        "scorecard": {"composite": composite, "pass_rate": 0.9,
                      "total_attacks": 10, "total_passed": 9,
                      "total_failed": 1, "critical_failures": 0},
        "policy": {"rating": rating, "tier": "Professional"},
    }


def _write(tmp_path: Path, cert: dict, name="cert.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(cert, default=str))
    return p


def _run(args) -> int:
    return nd.main(args)


# ── happy path ───────────────────────────────────────────────────────
def test_push_unsigned_passes_at_correct_tier(tmp_path):
    p = _write(tmp_path, _good_cert(composite=0.85))
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AA",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 0


def test_push_aaa_tier_requires_higher_composite(tmp_path):
    p = _write(tmp_path, _good_cert(composite=0.85, rating="AA"))
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AAA",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 2


def test_push_a_tier_accepts_lower_composite(tmp_path):
    p = _write(tmp_path, _good_cert(composite=0.72, rating="A"))
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "A",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 0


# ── failure modes ───────────────────────────────────────────────────
def test_push_blocks_fail_rating_even_if_composite_high(tmp_path):
    # crafted inconsistency: composite 0.95 but rating FAIL
    cert = _good_cert(composite=0.95, rating="FAIL")
    p = _write(tmp_path, cert)
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AAA",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 2


def test_push_blocks_too_old(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    p = _write(tmp_path, _good_cert(issued_at=old))
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AA",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct",
                 "--max-age-days", "30"]) == 2


def test_push_blocks_future_issued_at(tmp_path):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    p = _write(tmp_path, _good_cert(issued_at=future))
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AA", "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 2


def test_push_blocks_scope_mismatch(tmp_path):
    p = _write(tmp_path, _good_cert(scope="finance"))
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AA",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 2


def test_push_blocks_model_mismatch(tmp_path):
    p = _write(tmp_path, _good_cert(model="other:7b"))
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AA",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 2


def test_push_missing_field_blocks(tmp_path):
    cert = _good_cert()
    del cert["scorecard"]
    p = _write(tmp_path, cert)
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AA",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 2


def test_push_missing_file_blocks(tmp_path):
    assert _run(["push", "--agent", "a",
                 "--cert", str(tmp_path / "nope.json"),
                 "--tier", "AA",
                 "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 2


def test_push_invalid_json_blocks(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AA", "--scope", "general",
                 "--model", "mistral:7b-instruct"]) == 2


def test_push_require_signature_blocks_unsigned(tmp_path, monkeypatch):
    monkeypatch.setenv("NAIL_ARSENAL_KEYS", str(tmp_path / "keys"))
    p = _write(tmp_path, _good_cert())
    assert _run(["push", "--agent", "a", "--cert", str(p),
                 "--tier", "AA", "--scope", "general",
                 "--model", "mistral:7b-instruct",
                 "--require-signature"]) == 2


# ── sign + verify roundtrip ─────────────────────────────────────────
def test_sign_then_push_with_require_signature(tmp_path, monkeypatch):
    keys_dir = tmp_path / "keys"
    monkeypatch.setenv("NAIL_ARSENAL_KEYS", str(keys_dir))
    cert_path = _write(tmp_path, _good_cert())
    out_path = tmp_path / "cert.signed.json"

    rc = _run(["sign", "--cert", str(cert_path), "--out", str(out_path)])
    assert rc == 0
    signed = json.loads(out_path.read_text())
    assert "signature" in signed and "." in signed["signature"]

    rc = _run(["push", "--agent", "a", "--cert", str(out_path),
               "--tier", "AA", "--scope", "general",
               "--model", "mistral:7b-instruct",
               "--require-signature"])
    assert rc == 0


def test_verify_rejects_tampered_signed_cert(tmp_path, monkeypatch):
    keys_dir = tmp_path / "keys"
    monkeypatch.setenv("NAIL_ARSENAL_KEYS", str(keys_dir))
    cert_path = _write(tmp_path, _good_cert())
    out_path = tmp_path / "cert.signed.json"
    _run(["sign", "--cert", str(cert_path), "--out", str(out_path)])

    # tamper composite after signing
    signed = json.loads(out_path.read_text())
    signed["scorecard"]["composite"] = 0.99
    out_path.write_text(json.dumps(signed, default=str))

    rc = _run(["verify", "--cert", str(out_path)])
    assert rc == 2


def test_verify_unsigned_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("NAIL_ARSENAL_KEYS", str(tmp_path / "keys"))
    p = _write(tmp_path, _good_cert())
    # Need an issuer key to even attempt verify
    generate_keypair(directory=tmp_path / "keys")
    assert _run(["verify", "--cert", str(p)]) == 2


def test_signature_rejected_with_wrong_key(tmp_path, monkeypatch):
    # Sign with key A, verify-via-push with require_signature against key B
    keys_a = tmp_path / "ka"
    keys_b = tmp_path / "kb"
    monkeypatch.setenv("NAIL_ARSENAL_KEYS", str(keys_a))
    cert_path = _write(tmp_path, _good_cert())
    out_path = tmp_path / "cert.signed.json"
    _run(["sign", "--cert", str(cert_path), "--out", str(out_path)])
    # Switch trust anchor to a brand-new keypair
    generate_keypair(directory=keys_b)
    monkeypatch.setenv("NAIL_ARSENAL_KEYS", str(keys_b))
    rc = _run(["push", "--agent", "a", "--cert", str(out_path),
               "--tier", "AA", "--scope", "general",
               "--model", "mistral:7b-instruct",
               "--require-signature"])
    assert rc == 2
