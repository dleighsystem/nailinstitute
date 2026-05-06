# NAIL Model Passport v1

**Status:** v1 draft · **Owner:** NAIL Institute · **Consumer:** Neuravant Insurance  
**Purpose:** replace informal trust in `MODEL_STATUS.md` with a signed, machine-verifiable handoff from the Institute to Insurance.

---

## Boundary

- **NAIL Institute issues passports** after local DGX certification of `nail-reason`, `nail-guard`, or successor models.
- **Neuravant Insurance verifies passports** before using a model in customer-facing certification, cognitive routing, or underwriting evidence generation.
- The two repositories **do not import each other**. They share only this schema and canonical JSON signing rule.

---

## Canonical Signing Rule

1. Remove the top-level `signature` object.
2. Serialize the remaining object as UTF-8 JSON with:
   - sorted keys
   - compact separators: `,` and `:`
   - no ASCII escaping
3. Sign those bytes with HMAC-SHA256.
4. Store the hex digest in `signature.value`.

Verifier must reject passports when:

- signature is absent or invalid
- `schema_version` is not `nail.model_passport.v1`
- `certification.certified` is not `true`
- `expires_at` is in the past
- `passport_id` appears in a revocation list
- `subject.model` is not the expected model tag

---

## Schema

```json
{
  "schema_version": "nail.model_passport.v1",
  "passport_id": "MP-20260425-...",
  "issued_at": "2026-04-25T08:25:04.381645+00:00",
  "expires_at": "2026-07-24T08:25:04.381645+00:00",
  "issuer": {
    "name": "NAIL Institute",
    "environment": "local-dgx-spark"
  },
  "subject": {
    "model": "nail-reason:v5.1",
    "role": "reason",
    "artifact_sha256": "optional-model-or-export-hash",
    "ollama_tag": "nail-reason:v5.1"
  },
  "certification": {
    "certified": true,
    "certificate_sha256": "sha256-of-source-cert-json",
    "certified_at": "2026-04-25T08:25:04.381645+00:00",
    "authority": "NAIL Institute — In-House (Local DGX Spark)",
    "checks": [
      {
        "check": "classification_accuracy",
        "actual": 1.0,
        "threshold": 0.5,
        "operator": "≥",
        "passed": true
      }
    ]
  },
  "policy": {
    "requires_certified": true,
    "revocation_status": "active",
    "allowed_uses": ["research-cert", "production-cert", "cognitive-system2"]
  },
  "signature": {
    "alg": "HMAC-SHA256",
    "key_id": "nail-institute-local-2026q2",
    "value": "hex-hmac"
  }
}
```

---

## Issuing

```bash
export NAIL_MODEL_PASSPORT_HMAC_KEY="replace-with-shared-secret"
python scripts/local_llm/issue_model_passport.py \
  --cert scripts/local_llm/certifications/cert_reason_v5.1_20260425_092504.json \
  --out scripts/local_llm/passports/nail-reason-v5.1.passport.json \
  --key-id nail-institute-local-2026q2 \
  --expires-days 90
```

The output passport is copied to Neuravant through normal release operations. Neuravant stores only the passport and verification secret; it does not import Institute code.
