# M17 — Cert Lifecycle Spec (revocation · expiry · public verify)

**Status:** DRAFT (spec only — no implementation yet).
**Predecessors:** M13 (model registry), M15 (cert pipeline), M16 (thresholds), M13.1 (first real cert).
**Owner:** NAIL Institute.
**Audience:** anyone who needs to *trust* a NAIL cert weeks or months after it was issued.

---

## 0 · Why M17 exists

M15 emits a **CertBundle**: a JSON document signed by its own SHA-256 fingerprint
(`bundle_sha256`), rooted at a specific `nail_commit` and `thresholds_version`.
That gives us **integrity** (the bytes haven't changed) and **provenance**
(we know which code produced it). It does *not* yet give us:

| Property | Question it answers | M17 mechanism |
|---|---|---|
| **Freshness** | Is this cert still in-date? | Expiry (`expiry_utc`) |
| **Revocability** | Did NAIL pull this cert after issuing it? | Revocation list |
| **Third-party trust** | Can a customer of *our* customer verify a cert without running our toolchain? | Public verify endpoint |

Without these three, a 6-month-old cert is indistinguishable from a fresh one,
and a cert that NAIL has internally repudiated still verifies as `PASS`.
M17 closes that gap.

---

## 1 · Bundle additions (backwards-compatible)

The CertBundle gains **two optional top-level fields**. Old bundles without
them are still verifiable; new bundles must populate both.

```json
{
  "...": "(existing M15 fields)",
  "lifetime_days": 90,
  "expiry_utc": "2026-07-24T09:25:04Z"
}
```

Rules:

- `expiry_utc = issued_utc + lifetime_days` (UTC, ISO-8601, second precision).
- `lifetime_days` defaults per axis profile:
  - **AAA / AA**: 90 days
  - **A**: 60 days
  - **B**: 30 days
  - **DENIED**: bundles still produced for audit but `expiry_utc == issued_utc` (instantly stale).
- `bundle_sha256` is computed *with* the new fields included — see §4.

---

## 2 · Revocation list

A **single signed JSON document** distributed via the public repo
(`public-repo/certs/revocations.json`) — append-only, monotonic by
`revocation_index`.

### 2.1 Shape

```json
{
  "schema": "nail.revocations/v1",
  "issuer": "NAIL Institute",
  "generated_utc": "2026-04-30T12:00:00Z",
  "revocation_index": 17,
  "entries": [
    {
      "bundle_sha256": "f4180095ee8e9bc6fc5e33d91c649584460f4cc733d9ad3e303e3c24a1af61bd",
      "agent_id": "acme-bot-prod-001",
      "revoked_utc": "2026-04-29T18:20:00Z",
      "reason_code": "MODEL_DEMOTED",
      "reason_text": "nail-reason:v5.1 demoted; re-cert required.",
      "supersedes": null
    }
  ],
  "signature_sha256": "<sha256 of the document with this field removed>"
}
```

### 2.2 Reason codes (closed set)

| Code | Meaning |
|---|---|
| `MODEL_DEMOTED` | A model named in the bundle's runtime block was demoted (M13). |
| `THRESHOLD_BUMP` | `thresholds_version` was bumped and old certs no longer meet the new floor (M16). |
| `EVIDENCE_INVALIDATED` | Underlying eval/probe set was found to be miscalibrated (cf. M13.1 story). |
| `AGENT_RECONFIGURED` | Customer changed the agent under the same `agent_id`; cert no longer applies. |
| `OPERATIONAL_INCIDENT` | Live incident proved a metric was over-stated. |
| `ADMIN_RECALL` | Manual recall, reason in `reason_text`. |

### 2.3 Append-only invariant

- New entries get appended; existing entries are never deleted or edited.
- `revocation_index` is monotonically increasing.
- `signature_sha256` is recomputed on every append.
- The whole file is committed to `public-repo/`; git history *is* the audit log.

### 2.4 Verifier semantics

A bundle is **valid** iff:
1. `bundle_sha256` matches the recomputed canonical fingerprint (M15 rule), AND
2. `now_utc < expiry_utc`, AND
3. `bundle_sha256` does **not** appear in the revocation list.

Any failure → `verdict_effective = REVOKED` regardless of the bundle's own
`verdict` field.

---

## 3 · Public verify endpoint

A small read-only HTTP service that lets anyone — not just holders of the
NAIL toolchain — verify a cert.

### 3.1 Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness probe. |
| `GET` | `/v1/revocations` | Latest revocation list (entire JSON). |
| `GET` | `/v1/revocations/index` | `{ "revocation_index": 17, "generated_utc": "..." }` (cheap freshness check). |
| `POST` | `/v1/verify` | Body: a CertBundle JSON. Response: see §3.2. |
| `GET` | `/v1/cert/{bundle_sha256}` | Returns the public summary for a known cert (agent_id, verdict, grade, issued, expiry, revocation status). Does **not** return the full bundle (agent owns that). |

### 3.2 `/v1/verify` response shape

```json
{
  "bundle_sha256":         "f4180095…",
  "fingerprint_ok":        true,
  "expired":               false,
  "expiry_utc":            "2026-07-24T09:25:04Z",
  "revoked":               false,
  "revocation":            null,
  "verdict_declared":      "PASS",
  "verdict_effective":     "PASS",
  "thresholds_version":    "1.0",
  "nail_commit":           "df00034451f54f236b1270090ea0fad580e6a3c7",
  "checked_utc":           "2026-04-30T13:01:22Z"
}
```

`verdict_effective` is the **only** field a verifier should trust to make a
"is this cert good *right now*" decision.

### 3.3 Non-goals

- The endpoint never **issues** certs; that's M15's job.
- The endpoint never **modifies** the revocation list; that's a NAIL-internal
  operation that goes through git.
- The endpoint stores **no agent data**; bundles are processed in-memory only.

---

## 4 · Canonical fingerprint (updated rule)

The M15 fingerprint rule remains, with the lifetime fields included:

```python
def fingerprint(bundle: dict) -> str:
    canon = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    blob  = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()
```

This is **already** what `cert_pipeline.CertBundle.fingerprint()` does;
adding new top-level keys does not change the algorithm.

---

## 5 · CLI surface (planned)

```bash
# Inspect (M17 extends scripts/inspect_cert.py)
inspect_cert.py BUNDLE --verify --check-expiry --check-revocation \
    [--revocations-path public-repo/certs/revocations.json] \
    [--revocations-url  https://verify.nail.institute/v1/revocations]

# Revoke (NAIL-internal)
nail_harness/cli_revoke.py BUNDLE_SHA256 \
    --reason-code MODEL_DEMOTED \
    --reason-text "nail-reason:v5.1 demoted" \
    --signoff "L. Dean (NAIL Institute)"

# Serve (the public endpoint)
nail_harness/cli_verify_server.py \
    --revocations-path public-repo/certs/revocations.json \
    --bind 0.0.0.0:8443 \
    [--tls-cert ... --tls-key ...]
```

---

## 6 · Threat model (sketch)

| Attack | Mitigation |
|---|---|
| Replay an expired cert | `/v1/verify` checks `expiry_utc`. |
| Strip `bundle_sha256` and re-add a forged one | Fingerprint recompute over the rest of the bundle catches it. |
| Edit the revocation list to remove an entry | Append-only invariant + git history; `signature_sha256` change is visible. |
| Stand up a fake verify endpoint | Public endpoint lives at a single, signed-DNS hostname; verifier libraries pin it. |
| Issue a cert and then reload `nail_commit` to a malicious commit | `nail_commit` is a hash, not a tag — pinning is automatic. |

What M17 does **not** defend against (out of scope, deferred to M18+):

- Compromise of NAIL's signing key for the revocation list (key rotation TBD).
- Customer collusion (a customer who deliberately runs a non-certified model under a certified `agent_id`).
- Side-channel leaks of evidence files on the issuer side.

---

## 7 · Acceptance criteria (when M17 is implementable)

- [ ] CertBundle gains `lifetime_days` + `expiry_utc`; existing tests stay green.
- [ ] `cert_pipeline` populates both fields on issue.
- [ ] `revocations.json` schema validator + append-only test.
- [ ] `cli_revoke` adds entries, recomputes signature, fails on tamper.
- [ ] `cli_verify_server` serves all 5 routes; integration test against a
      synthetic bundle + revocation list.
- [ ] `inspect_cert --check-expiry --check-revocation` exits non-zero on either failure.
- [ ] M14 `cert_collectors` unchanged (M17 is post-issuance only).
- [ ] Round-trip integration test: issue → expire → verify-fails;
      issue → revoke → verify-fails; issue → verify-passes.

---

## 8 · Open questions

1. **Lifetime per-axis vs per-bundle?** Current proposal: per-bundle, derived
   from the *worst* axis grade. Alternative: shortest of `min(axis_lifetimes)`.
2. **Should expired certs be auto-added to the revocation list?** Probably no —
   expiry is a function of time, revocation is a function of an event. Keeping
   them separate keeps the revocation list small.
3. **Distributed verify endpoint?** v1 is single-host. If we hit the AWS S3
   pattern of a static-served revocation list with edge caching, the endpoint
   becomes a thin shim and fingerprint check moves to the client library.
4. **Customer-side revocation?** Should a customer be able to voluntarily
   revoke their own cert (e.g. before redeploying)? Likely yes, with a
   `CUSTOMER_REQUESTED` reason code — defer to M17.1.

---

*M17 is intentionally a paper spec. The implementation work is sized at ~3
focused commits (bundle fields + revocation list + endpoint), and should
not begin until at least one customer asks for cert re-verification — which
is the actual signal that the freshness/revocation question matters in
practice.*
