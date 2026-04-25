# NAIL Model Status

**Effective:** 2026-04-25 · **Source of truth:** `nail_harness/models.py`
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
| **reason** | `nail-reason:v5.1` | ✅ certified 2026-04-25 | `cert_reason_v5.1_20260425_092504.json` | acc 1.00 · bypass 0.13 · fp 0.00 · p95 8.3 s |

## 2. Uncertified / failed roles

*(none today — every required role has a certified model.)*

### Reason role — how v5.1 was certified without a retrain

The v5 cert failure (acc 0.06, p95 66 s) turned out to be a tooling
bug, not a model bug. `scripts/local_llm/diagnose_reason_v5.py`
showed v5 produced perfect AVE-grounded answers on deep-analyst
prompts (2/2) and short VERDICT replies on redteam prompts (7/10) —
at ~35 s p95 — once `num_predict` was bounded.

Two zero-training fixes promoted the same GGUF as `v5.1`:

* **Fix A** — Modelfile `PARAMETER num_predict 4096 → 350`. p95 dropped
  to 8.3 s in the cert run.
* **Fix B** — rebuilt `nail_reason_eval.jsonl` from real
  `ave-database/cards/*.json` so the cert's primary JSON-scoring path
  activates on every row (legacy: 2/17, new: 17/17). Builder is
  `scripts/local_llm/build_reason_eval_v2.py`; legacy preserved at
  `nail_reason_eval.legacy.jsonl`.

Full plan + post-mortem: `scripts/local_llm/R6_PLAN.md`.

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
| `nail-reason:v5.1` | 2026-04-25 | ✅ | acc 1.00 · bypass 0.13 · fp 0.00 · p95 8.3 s (no retrain — Modelfile + eval fixes) |

## 4. Client-cert gate

```
required_roles = {"guard", "reason"}
certified_roles = {role for role, model in MODELS.items() if model.certified}
client_cert_allowed = required_roles.issubset(certified_roles)
```

**As of 2026-04-25: `client_cert_allowed = True`** — every required
role (`guard`, `reason`) has a certified model. The cert pipeline
will issue real (non-`--dry-run`) signed bundles.

This is enforced in code by `nail_harness.models.assert_client_cert_allowed()`,
exercised by `tests/test_model_status.py`.

---

*Update this file in lockstep with `nail_harness/models.py`. The
sync test will fail the build if they drift.*
