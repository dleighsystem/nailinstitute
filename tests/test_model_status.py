"""Tests for the NAIL model registry and its sync with MODEL_STATUS.md."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_models():
    """Load nail_harness.models directly from file so we don't depend
    on the workspace being on sys.path (the root conftest strips it
    on purpose for the editable-package fix)."""
    import sys
    spec = importlib.util.spec_from_file_location(
        "nail_harness_models_under_test",
        ROOT / "nail_harness" / "models.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclass introspection needs the module registered before exec
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_m = _load_models()
MODELS = _m.MODELS
REQUIRED_ROLES_FOR_CLIENT_CERT = _m.REQUIRED_ROLES_FOR_CLIENT_CERT
CertGateError = _m.CertGateError
certified_model_for = _m.certified_model_for
best_candidate_for = _m.best_candidate_for
client_cert_allowed = _m.client_cert_allowed
assert_client_cert_allowed = _m.assert_client_cert_allowed


# ── registry shape ───────────────────────────────────────────────
def test_required_roles_all_have_an_entry():
    for r in REQUIRED_ROLES_FOR_CLIENT_CERT:
        assert r in MODELS, f"required role {r!r} missing from MODELS"


def test_unknown_role_raises():
    with pytest.raises(CertGateError):
        certified_model_for("does-not-exist")


# ── current truth (April 2026) ───────────────────────────────────
def test_guard_is_certified_today():
    rec = MODELS["guard"]
    assert rec.certified
    assert rec.name == "nail-guard:v4"
    assert certified_model_for("guard") == "nail-guard:v4"


def test_reason_is_certified_today():
    rec = MODELS["reason"]
    assert rec.certified
    assert rec.name == "nail-reason:v5.1"
    assert certified_model_for("reason") == "nail-reason:v5.1"


def test_best_candidate_returns_certified_record():
    rec = best_candidate_for("reason")
    assert rec.name == "nail-reason:v5.1"
    assert rec.certified


# ── client-cert gate ────────────────────────────────
def test_client_cert_allowed_today():
    assert client_cert_allowed() is True
    # must not raise
    assert_client_cert_allowed()


# ── doc/code sync ────────────────────────────────────────────────
def test_model_status_md_present_and_lists_each_role():
    md = (ROOT / "MODEL_STATUS.md").read_text()
    for role, rec in MODELS.items():
        assert rec.name in md, f"model {rec.name} not mentioned in MODEL_STATUS.md"
        assert role in md, f"role {role} not mentioned in MODEL_STATUS.md"


def test_model_status_md_states_client_cert_open():
    """Now that all roles are certified, the doc must say so."""
    md = (ROOT / "MODEL_STATUS.md").read_text()
    if client_cert_allowed():
        assert "client_cert_allowed = True" in md, \
               "MODEL_STATUS.md must explicitly state the gate is open"
