"""NAIL model registry — single source of truth for which locally-trained
models are certified for use inside the cert pipeline.

Mirrors ``MODEL_STATUS.md`` (drift checked by tests). Read this from
the cert pipeline; **do not** hard-code model names elsewhere.

Usage:

    from nail_harness.models import MODELS, certified_model_for, \\
        assert_client_cert_allowed

    guard_model = certified_model_for("guard")     # -> "nail-guard:v4"
    assert_client_cert_allowed()                    # raises CertGateError
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class CertGateError(RuntimeError):
    """Raised when the cert pipeline is asked to do something it isn't
    allowed to do — e.g. issue a client cert while a required role
    has no certified model."""


@dataclass(frozen=True)
class ModelRecord:
    role: str
    name: str
    certified: bool
    cert_date: Optional[str] = None
    cert_evidence: Optional[str] = None  # filename under scripts/local_llm/certifications/
    notes: str = ""


# Required roles for issuing a client certificate. If any of these
# don't have a certified model, the pipeline must refuse to emit a
# signed bundle.
REQUIRED_ROLES_FOR_CLIENT_CERT: frozenset[str] = frozenset({"guard", "reason"})


# Best-current model per role. Keep in lockstep with MODEL_STATUS.md.
MODELS: dict[str, ModelRecord] = {
    "guard": ModelRecord(
        role="guard",
        name="nail-guard:v4",
        certified=True,
        cert_date="2026-04-23",
        cert_evidence="cert_guard_v4_20260423_011847.json",
        notes="acc 0.80 · bypass 0.00 · fp 0.00 · p95 5.4s",
    ),
    "reason": ModelRecord(
        role="reason",
        name="nail-reason:v5",
        certified=False,
        cert_date="2026-04-24",
        cert_evidence="cert_reason_v5_20260424_222941.json",
        notes=(
            "BEST safety on record (bypass 0.067, fp 0.00) but failed "
            "format strictness (partial_acc 0.31, exact_acc 0.06) and "
            "p95 latency 66s (dragged by single long-context timeout). "
            "Needs M13 retrain with format-anchor preference pairs."
        ),
    ),
}


def certified_model_for(role: str) -> str:
    """Return the certified model name for a role.

    Raises ``CertGateError`` if the role has no certified model.
    """
    rec = MODELS.get(role)
    if rec is None:
        raise CertGateError(f"unknown role: {role!r}")
    if not rec.certified:
        raise CertGateError(
            f"role {role!r} has no certified model "
            f"(best candidate {rec.name!r} failed cert on "
            f"{rec.cert_date}; see {rec.cert_evidence})"
        )
    return rec.name


def best_candidate_for(role: str) -> ModelRecord:
    """Return the best current candidate (certified or not). Useful
    for tooling that wants to *attempt* a run with degraded
    expectations, e.g. development or recertification jobs."""
    rec = MODELS.get(role)
    if rec is None:
        raise CertGateError(f"unknown role: {role!r}")
    return rec


def client_cert_allowed() -> bool:
    """True iff every role in REQUIRED_ROLES_FOR_CLIENT_CERT has a
    certified model."""
    return all(
        MODELS.get(r) is not None and MODELS[r].certified
        for r in REQUIRED_ROLES_FOR_CLIENT_CERT
    )


def assert_client_cert_allowed() -> None:
    """Raise CertGateError if the pipeline is not allowed to issue a
    client certificate. Call this at the top of any code path that
    produces a signed cert bundle (M15)."""
    if client_cert_allowed():
        return
    missing = sorted(
        r for r in REQUIRED_ROLES_FOR_CLIENT_CERT
        if not (MODELS.get(r) and MODELS[r].certified)
    )
    msg_lines = [
        "Cannot issue client certificate — required role(s) uncertified:",
    ]
    for r in missing:
        rec = MODELS.get(r)
        if rec is None:
            msg_lines.append(f"  • {r}: NO MODEL REGISTERED")
        else:
            msg_lines.append(
                f"  • {r}: best candidate {rec.name!r} failed "
                f"({rec.cert_date}); see {rec.cert_evidence}"
            )
    msg_lines.append("See MODEL_STATUS.md for remediation plan.")
    raise CertGateError("\n".join(msg_lines))
