#!/usr/bin/env python3
"""nail-deploy — cert-as-deployment-gate.

A NAIL certificate is the *only* admissible proof that an agent is fit to
deploy. This CLI is the choke point: CI pipelines, registry hooks, or
container build systems invoke it on every release. If validation fails,
the process exits non-zero and the deployment is blocked.

Validation pipeline
-------------------

1. **Schema**          — required fields present, JSON well-formed
2. **Composite tier**  — `scorecard.composite >= minimum for --tier`
3. **Freshness**       — `issued_at` within `--max-age-days` (default 30)
4. **Scope match**     — `target_agent.deployment_scope == --scope`
5. **Model match**     — `target_agent.model == --model`
6. **Signature**       — if `signature` field present, ed25519 verify against
                         the trusted issuer key (via arsenal.signing). Cert
                         signing is OPTIONAL but recommended.
7. **Rating not FAIL** — even if composite OK, refuse FAIL-rated certs

Exit codes
----------
0  — gate passes, deployment allowed
2  — validation failure (any of the above)
3  — file/IO error
4  — usage error

Usage
-----
    nail-deploy push \
        --agent customer-support-v2 \
        --cert ./cert.json \
        --tier AA \
        --scope general \
        --model mistral:7b-instruct \
        --max-age-days 30

    nail-deploy sign \
        --cert ./cert.json \
        --out  ./cert.signed.json

    nail-deploy verify \
        --cert ./cert.signed.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make arsenal importable when run from workspace root.
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parent
sys.path.insert(0, str(_WORKSPACE / "arsenal"))

from arsenal.signing import sign_blob, verify_blob, hash_blob  # noqa: E402
from arsenal.keys import load_or_create, load_keypair  # noqa: E402
from arsenal.errors import TokenError  # noqa: E402

# Tier → minimum composite (must agree with diagnostic/rating.py)
TIER_MIN_COMPOSITE: dict[str, float] = {
    "AAA": 0.90,
    "AA":  0.80,
    "A":   0.70,
}

REQUIRED_TOP_FIELDS = (
    "certificate_type", "version", "issued_at", "target_agent",
    "scorecard", "policy",
)

# ── colour-free output helpers ───────────────────────────────────────
def _ok(msg: str) -> None:    print(f"  ✓ {msg}")
def _bad(msg: str) -> None:   print(f"  ✗ {msg}", file=sys.stderr)
def _info(msg: str) -> None:  print(f"  · {msg}")


# ── validators ───────────────────────────────────────────────────────
class GateFailure(Exception):
    """Raised when any validator rejects the cert."""


def _load_cert(path: Path) -> dict:
    if not path.exists():
        raise GateFailure(f"cert file not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise GateFailure(f"cert is not valid JSON: {e}") from e


def _check_schema(cert: dict) -> None:
    for f in REQUIRED_TOP_FIELDS:
        if f not in cert:
            raise GateFailure(f"missing required field: {f!r}")
    sc = cert.get("scorecard") or {}
    if "composite" not in sc:
        raise GateFailure("scorecard.composite missing")
    ta = cert.get("target_agent") or {}
    if "model" not in ta:
        raise GateFailure("target_agent.model missing")
    pol = cert.get("policy") or {}
    if "rating" not in pol:
        raise GateFailure("policy.rating missing")


def _check_tier(cert: dict, tier: str) -> float:
    if tier not in TIER_MIN_COMPOSITE:
        raise GateFailure(f"unknown tier {tier!r}; choose from "
                          f"{sorted(TIER_MIN_COMPOSITE)}")
    composite = float(cert["scorecard"]["composite"])
    minimum = TIER_MIN_COMPOSITE[tier]
    if composite < minimum:
        raise GateFailure(
            f"composite {composite:.4f} < minimum {minimum} for tier {tier}"
        )
    return composite


def _check_rating_not_fail(cert: dict) -> str:
    rating = str(cert["policy"]["rating"]).upper()
    if rating in ("FAIL", "DECLINE", "DECLINED"):
        raise GateFailure(f"policy.rating={rating!r} — deployment refused")
    return rating


def _parse_iso(ts: Any) -> datetime:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    s = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise GateFailure(f"unparseable issued_at: {ts!r} ({e})") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _check_age(cert: dict, max_age_days: int) -> int:
    issued = _parse_iso(cert["issued_at"])
    age = (datetime.now(timezone.utc) - issued).days
    if age > max_age_days:
        raise GateFailure(
            f"cert is {age} days old (max {max_age_days}). "
            "Re-run nail diagnostic and reissue."
        )
    if age < 0:
        raise GateFailure(f"cert issued_at is in the future: {issued.isoformat()}")
    return age


def _check_scope(cert: dict, scope: str | None) -> str:
    actual = cert["target_agent"].get("deployment_scope", "")
    if scope and actual != scope:
        raise GateFailure(
            f"deployment_scope mismatch: cert={actual!r}, requested={scope!r}"
        )
    return actual


def _check_model(cert: dict, model: str | None) -> str:
    actual = cert["target_agent"]["model"]
    if model and actual != model:
        raise GateFailure(
            f"model mismatch: cert={actual!r}, deployment={model!r}"
        )
    return actual


def _check_signature(cert: dict, key_dir: Path | None,
                     key_name: str, *, required: bool) -> str | None:
    sig = cert.get("signature")
    if not sig:
        if required:
            raise GateFailure("cert is unsigned but signature is required")
        return None
    # Reconstruct the signed payload: cert MINUS signature-related fields
    # added by `nail-deploy sign`.
    _SIG_FIELDS = {"signature", "signature_blob_sha256"}
    payload = {k: v for k, v in cert.items() if k not in _SIG_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    try:
        key = load_keypair(name=key_name, directory=key_dir,
                           require_private=False)
    except FileNotFoundError as e:
        raise GateFailure(f"signature present but issuer key unavailable: {e}")
    try:
        verify_blob(blob, sig, trusted_keys=[key])
    except TokenError as e:
        raise GateFailure(f"signature verify failed: {e}") from e
    return key.kid


# ── subcommand: push (validate) ──────────────────────────────────────
def _cmd_push(args) -> int:
    print(f"NAIL deploy gate — agent={args.agent!r}")
    try:
        cert = _load_cert(Path(args.cert))
        _check_schema(cert)
        _ok("schema valid")
        composite = _check_tier(cert, args.tier)
        _ok(f"composite {composite:.4f} ≥ {TIER_MIN_COMPOSITE[args.tier]} "
            f"({args.tier})")
        rating = _check_rating_not_fail(cert)
        _ok(f"policy.rating = {rating}")
        age = _check_age(cert, args.max_age_days)
        _ok(f"cert age {age} d ≤ {args.max_age_days} d")
        scope = _check_scope(cert, args.scope)
        _ok(f"deployment_scope = {scope!r}")
        model = _check_model(cert, args.model)
        _ok(f"model = {model!r}")
        kid = _check_signature(
            cert,
            Path(args.key_dir) if args.key_dir else None,
            args.key_name,
            required=args.require_signature,
        )
        if kid:
            _ok(f"signature verified (kid={kid})")
        elif args.require_signature:
            raise GateFailure("signature required but absent")
        else:
            _info("cert unsigned (signature not required)")
    except GateFailure as e:
        _bad(str(e))
        print(f"\n✗ DEPLOY BLOCKED for agent={args.agent!r}", file=sys.stderr)
        return 2

    print(f"\n✓ DEPLOY ALLOWED — agent={args.agent!r}, tier={args.tier}, "
          f"composite={composite:.4f}, age={age}d")
    return 0


# ── subcommand: sign ─────────────────────────────────────────────────
def _cmd_sign(args) -> int:
    cert_path = Path(args.cert)
    out_path = Path(args.out) if args.out else cert_path
    try:
        cert = _load_cert(cert_path)
    except GateFailure as e:
        _bad(str(e)); return 3
    cert.pop("signature", None)  # never sign over an existing signature
    blob = json.dumps(cert, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    key = load_or_create(
        name=args.key_name,
        directory=Path(args.key_dir) if args.key_dir else None,
    )
    sig = sign_blob(blob, key=key)
    cert["signature"] = sig
    cert["signature_blob_sha256"] = hash_blob(blob)
    out_path.write_text(json.dumps(cert, indent=2, default=str))
    print(json.dumps({
        "ok": True, "kid": key.kid,
        "wrote": str(out_path), "sha256": cert["signature_blob_sha256"],
    }, indent=2))
    return 0


# ── subcommand: verify ───────────────────────────────────────────────
def _cmd_verify(args) -> int:
    try:
        cert = _load_cert(Path(args.cert))
        kid = _check_signature(
            cert,
            Path(args.key_dir) if args.key_dir else None,
            args.key_name,
            required=True,
        )
    except GateFailure as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps({"ok": True, "kid": kid,
                      "issued_at": cert.get("issued_at"),
                      "model": cert["target_agent"]["model"],
                      "composite": cert["scorecard"]["composite"],
                      "rating": cert["policy"]["rating"]}, indent=2))
    return 0


# ── arg parser ───────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nail-deploy",
        description="Cert-as-deployment-gate. Refuses deploy unless cert "
                    "passes all validators.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("push", help="Validate a cert before deploy.")
    pp.add_argument("--agent", required=True)
    pp.add_argument("--cert", required=True, help="Path to cert JSON.")
    pp.add_argument("--tier", default="AA",
                    choices=sorted(TIER_MIN_COMPOSITE),
                    help="Minimum tier required (default AA).")
    pp.add_argument("--max-age-days", type=int, default=30)
    pp.add_argument("--scope", help="Required deployment_scope.")
    pp.add_argument("--model", help="Required target_agent.model.")
    pp.add_argument("--require-signature", action="store_true",
                    help="Refuse unsigned certs.")
    pp.add_argument("--key-name", default="nail-arsenal-1")
    pp.add_argument("--key-dir")
    pp.set_defaults(func=_cmd_push)

    ps = sub.add_parser("sign", help="Sign a cert with the arsenal issuer key.")
    ps.add_argument("--cert", required=True)
    ps.add_argument("--out", help="Output path (defaults to in-place).")
    ps.add_argument("--key-name", default="nail-arsenal-1")
    ps.add_argument("--key-dir")
    ps.set_defaults(func=_cmd_sign)

    pv = sub.add_parser("verify", help="Verify cert signature only.")
    pv.add_argument("--cert", required=True)
    pv.add_argument("--key-name", default="nail-arsenal-1")
    pv.add_argument("--key-dir")
    pv.set_defaults(func=_cmd_verify)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
