# NAIL Model Status

**Effective:** 2026-04-24 · **Source of truth:** `nail_harness/models.py`
**Authority:** ratified by `CERTIFICATION_THRESHOLDS.md` v1.0

> [!IMPORTANT]
> This file declares which locally-trained models are **certified for
> use inside the NAIL cert pipeline**. The cert pipeline must refuse
> to issue a client certificate while any required role is uncertified.
> Drift between this file and `nail_harness/models.py` is checked by
> `tests/test_thresholds_sync.py`.

---

## 1. Certified roles (production)

| Role | Model | Cert verdict | Cert evidence | Notes |
|------|-------|--------------|---------------|-------|
| **guard** | `nail-guard:v4` | ✅ certified 2026-04-23 | `cert_guard_v4_20260423_011847.json` | acc 0.80 · bypass 0.00 · fp 0.00 · p95 5.4 s |

## 2. Uncertified / failed roles

| Role | Best candidate | Verdict | Why it failed | Action |
|------|----------------|---------|---------------|--------|
| **reason** | `nail-reason:v5` | ❌ failed 2026-04-24 | `partial_accuracy=0.31` (need ≥ 0.50 exact), `p95=66 s` (need ≤ 60 s) — but `bypass_rate=0.067` and `fp=0.00` are **excellent** | re-train v6 (M13.1) OR ship a thin format-normaliser wrapper around v5 (M13.2) |

### Reason role — root-cause notes (for the next training pass)

`v5` regressed on the *format* axis, not the *substance* axis:

* DPO concise pass made answers too terse to match the judge's exact
  `VERDICT:LABEL` regex. Partial accuracy is 5× exact accuracy ⇒ the
  model is right, just laconic.
* p95 = 66 s is dragged above 60 s by **one** read-timeout on a long
  AVE-2025-0021 prompt; p50 = 2.8 s is excellent.
* Bypass rate 6.7 % is the **best of any reason version** (v1–v3
  sit at 40–45 %).

→ Retraining should add a format-anchor preference pair set
(prefer "VERDICT:LABEL\\n…" prefix, reject answers that omit it),
keep the concise-DPO weight, and add at least one long-context
example to surface the timeout class.

## 3. Historical certifications (full audit trail)

| Model | Date | Verdict | Headline metric |
|-------|------|---------|-----------------|
| `nail-guard:v1` | 2026-04-21 | ❌ | acc 0.0 |
| `nail-guard:v2` | 2026-04-22 | ❌ | acc 0.0 |
| `nail-guard:v3` | 2026-04-22 | ❌ | bypass 0.75 |
| `nail-guard:v4` | 2026-04-23 | ✅ | acc 0.80 · bypass 0.00 |
| `nail-reason:v1` | 2026-04-21 | ❌ | bypass 0.45 |
| `nail-reason:v2` | 2026-04-22 | ❌ | bypass 0.45 |
| `nail-reason:v3` | 2026-04-22 | ❌ | bypass 0.40 · p95 121 s |
| `nail-reason:v3.1` | 2026-04-22 | ❌ | bypass 0.45 · p95 111 s |
| `nail-reason:v5` | 2026-04-24 | ❌ | bypass 0.07 (best) · acc 0.06 (worst) |

## 4. Client-cert gate

```
required_roles = {"guard", "reason"}
certified_roles = {role for role, model in MODELS.items() if model.certified}
client_cert_allowed = required_roles.issubset(certified_roles)
```

**As of 2026-04-24: `client_cert_allowed = False`** because `reason`
has no certified model. The cert pipeline will refuse to emit a
signed bundle (M15) until this changes.

This is enforced in code by `nail_harness.models.assert_client_cert_allowed()`,
exercised by `tests/test_model_status.py`.

---

*Update this file in lockstep with `nail_harness/models.py`. The
sync test will fail the build if they drift.*
