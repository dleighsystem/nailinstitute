#!/usr/bin/env python3
"""Issue a signed NAIL Model Passport from a local model certificate.

This script intentionally has no dependency on Neuravant code. The verifier in
Neuravant implements the same canonical JSON + HMAC-SHA256 rule from
MODEL_PASSPORT_SPEC.md.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "nail.model_passport.v1"
DEFAULT_ALLOWED_USES = ["research-cert", "production-cert", "cognitive-system2"]


def _canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _signing_payload(passport: dict[str, Any]) -> bytes:
    payload = dict(passport)
    payload.pop("signature", None)
    return _canonical_json(payload)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_passport(
    cert: dict[str, Any],
    cert_path: Path,
    *,
    expires_days: int,
    artifact_path: Path | None,
    key_id: str,
) -> dict[str, Any]:
    issued_at = _parse_dt(cert["timestamp"])
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    expires_at = issued_at + timedelta(days=expires_days)

    model = str(cert["model"])
    role = str(cert.get("role") or model.split(":", 1)[0].replace("nail-", ""))
    short_model = model.replace(":", "-").replace("/", "-")

    subject: dict[str, Any] = {
        "model": model,
        "role": role,
        "ollama_tag": model,
    }
    if artifact_path is not None:
        subject["artifact_sha256"] = _sha256_file(artifact_path)

    passport = {
        "schema_version": SCHEMA_VERSION,
        "passport_id": f"MP-{issued_at.strftime('%Y%m%d')}-{short_model}-{uuid.uuid4().hex[:8]}",
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "issuer": {
            "name": "NAIL Institute",
            "environment": "local-dgx-spark",
        },
        "subject": subject,
        "certification": {
            "certified": bool(cert.get("certified")),
            "certificate_sha256": _sha256_file(cert_path),
            "certified_at": cert["timestamp"],
            "authority": cert.get("certification_authority", "NAIL Institute"),
            "checks": cert.get("checks", []),
        },
        "policy": {
            "requires_certified": True,
            "revocation_status": "active",
            "allowed_uses": DEFAULT_ALLOWED_USES,
        },
        "signature": {
            "alg": "HMAC-SHA256",
            "key_id": key_id,
            "value": "",
        },
    }
    return passport


def sign_passport(passport: dict[str, Any], secret: str) -> dict[str, Any]:
    signed = dict(passport)
    sig = dict(signed["signature"])
    sig["value"] = hmac.new(
        secret.encode("utf-8"),
        _signing_payload(signed),
        hashlib.sha256,
    ).hexdigest()
    signed["signature"] = sig
    return signed


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue a signed NAIL Model Passport")
    parser.add_argument("--cert", required=True, type=Path, help="Source local_llm cert JSON")
    parser.add_argument("--out", required=True, type=Path, help="Output passport JSON")
    parser.add_argument("--artifact", type=Path, help="Optional model artifact to hash")
    parser.add_argument("--expires-days", type=int, default=90)
    parser.add_argument("--key-id", default="nail-institute-local")
    parser.add_argument("--key-env", default="NAIL_MODEL_PASSPORT_HMAC_KEY")
    args = parser.parse_args()

    secret = os.environ.get(args.key_env)
    if not secret:
        raise SystemExit(f"missing signing secret: export {args.key_env}=...")

    cert = json.loads(args.cert.read_text(encoding="utf-8"))
    passport = build_passport(
        cert,
        args.cert,
        expires_days=args.expires_days,
        artifact_path=args.artifact,
        key_id=args.key_id,
    )
    signed = sign_passport(passport, secret)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(signed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"issued {signed['passport_id']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
