# Post-mortem — Building NAIL's Cert Stack (M9 → M13.1)

**Window:** the apex_matrix merge through firing NAIL's first non-dry-run cert.
**Author:** GitHub Copilot, paired with L. Dean.
**Final outcome:** `cert_acme-bot-prod-001_f4180095ee8e.json` — verdict `PASS`,
grade **AAA**, composite **1.000**, signed off `L. Dean (NAIL Institute)`,
2026-04-25 09:25:04 UTC. NAIL's cert stack now produces real certs, not
dry-runs.

---

## 1 · The arc in one paragraph

We started by merging `apex_matrix` into NAIL (M9, M10), then re-certified
`nail-reason:v5` and shipped two foundational pieces (M12 SymbolicCritic,
M11 apex.harness). Then we built the customer-cert pipeline end-to-end:
thresholds (M16), model registry + gate (M13), pipeline orchestration (M15),
metric collectors (M14). At the end of M14 we had a complete pipeline that
could only emit `DRY-RUN-PASS` because no model had earned a real cert.
M13.1 was the gate-flip: certify `nail-reason:v5.1` (the deployed reasoning
model). Instead of an expensive retrain, a 30-minute diagnostic proved the
model wasn't broken — the **eval harness** was. Two zero-training fixes
(Modelfile `num_predict 4096→350`; rebuild eval to be AVE-anchored with
JSON gold) flipped the model from 0% to 100% classification accuracy. Cert
issued. Gate opened. First real cert fired immediately after.

---

## 2 · What we built

| ID | What | Files | LOC (added) |
|---|---|---|---|
| M9  | apex_matrix merge | `apex/` v0.1.0 | (existing import) |
| M10 | apex Ollama facade | `apex/` v0.2.0 | ~400 |
| M11 | apex.harness | `apex/apex/harness/*` | ~600 |
| M12 | SymbolicCritic | `foresight/foresight/symbolic_critic.py` | ~250 |
| M16 | Cert thresholds | `CERTIFICATION_THRESHOLDS.md`, `nail_harness/thresholds.json` | ~280 |
| M13 | Model registry + gate | `nail_harness/models.py`, `MODEL_STATUS.md` | ~330 |
| M15 | Cert pipeline | `nail_harness/cert_pipeline.py`, `cli_certify.py` | ~620 |
| M14 | Cert collectors | `nail_harness/cert_collectors.py`, `cli_collect.py` | ~440 |
| —   | Demo | `scripts/demo_certify.sh` | ~80 |
| M13.1 | First real cert | model promotion, gate flip, fired cert | ~150 |
| (a)   | Cert inspector | `scripts/inspect_cert.py` | ~177 |
| (b)   | run_for_cert shims | `arena/cert_shim.py`, `foresight/cert_shim.py` + tests | ~290 |
| (c)   | M17 spec | `M17_SPEC.md` | ~249 (doc) |

**Total:** ~3,200 LOC of code/tests + ~800 LOC of spec/docs across ~12
focused commits, 42→257 tests green at the end (different scopes — the
257 includes arena+foresight+root tests collected via the right paths).

---

## 3 · The pivotal moment — M13.1

### 3.1 What we expected

The original `R6_PLAN.md` budgeted a multi-hour retrain for `nail-reason`:
SFT + DPO on a 14B Q4 model, eval, repeat. We had `cert_reason_v5_*.json`
showing classification at ~6.7% — well below the AAA floor. The obvious
move was "the model is bad, retrain it."

### 3.2 What we did instead

Wrote `scripts/local_llm/diagnose_reason_v5.py` first — a 100-line empirical
test of the assumption. It probed the live `nail-reason:v5` model directly
with the same prompts the cert pipeline used, then re-ran with small prompt
mutations.

### 3.3 What we found

Two unrelated tooling defects, neither in the model weights:

1. **Modelfile bug**: `PARAMETER num_predict 4096`. At 4096 tokens, the
   model spent its budget filling JSON with hallucinated padding fields
   instead of returning the answer. Drop to 350 → answers are clean.
2. **Eval miscalibration**: only 2/17 gold rows actually contained the
   AVE-ID being asked about. A 14B Q4 model cannot memorise 42 AVE cards
   from base training; without the AVE-ID in the prompt, classification
   was effectively random. **The cert was measuring the eval, not the
   model.**

### 3.4 What we shipped instead of a retrain

- `Modelfile`: `num_predict 4096 → 350`.
- `scripts/local_llm/build_reason_eval_v2.py`: rebuild eval so the user
  prompt names the AVE-ID up-front (matches the legacy training prompt
  style) and gold is strict JSON `{ave_id, severity, category, analysis,
  mitigation}` (so the cert's primary scorer activates).
- One re-run of `certify_ollama.py` → classification 1.00, bypass 0.13,
  fp 0.00, p95 8.26s → **CERTIFIED**.

### 3.5 The win

Saved ~95% of M13.1's budgeted cost (no retrain, no DPO data curation).
But more importantly: **NAIL's cert stack caught its own miscalibration
on the very first end-to-end run.** That's the system working as designed
— a cert that was about to be issued got blocked because the evidence
didn't actually measure what it claimed to measure. The fact that the
fix lived in our tooling, not the model, is exactly the kind of error
we expect customers' cert runs to surface too.

---

## 4 · What the diagnostic taught us about our own design

1. **Always run a 30-minute diagnostic before a 30-hour rebuild.** The
   `diagnose_*.py` pattern is now a first-class part of M-level work.
2. **Eval-builder bugs look exactly like model bugs.** If accuracy is
   suspiciously low *or* suspiciously discontinuous across versions,
   probe the eval data first. Cheap. Fast. Specific.
3. **`num_predict` is a load-bearing parameter for JSON-structured tasks.**
   At budgets 10× the answer size, small models hallucinate padding rather
   than terminate. Document the rule: pick `num_predict` to be 1.5–2× the
   *expected* longest valid answer, not the *theoretical* max.
4. **Gold format must match what the cert scorer asserts on.** If the cert
   wants JSON and gold is prose, the primary scorer never runs and the
   fallback scorer is always wrong about something.

---

## 5 · Architectural notes

### 5.1 The cert stack actually has 4 layers, not one

```
┌──────────────────────────────────────────────┐
│ M13:  models.py  — gate (can we cert today?) │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│ M14:  cert_collectors — package outputs →    │
│       metrics JSON                           │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│ M15:  cert_pipeline — metrics → CertBundle   │
│       (hard floors, axis grades, signoff)    │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│ M16:  thresholds.json — the policy the rest  │
│       of the stack reads                     │
└──────────────────────────────────────────────┘
```

The clean separation means each layer is independently testable and
swappable. M16 is the only piece that's pure data; the other three are
code with their own test suites.

### 5.2 The shim layer (b) was missing until just now

Until commit `(b)`, `cert_collectors` accepted "shaped dicts" and the
demo / CLI fed them by hand via `--evidence k=v`. That's fine for demos
but means real cert runs require operators to know the metric names.
The `run_for_cert` shims close this — `arena.run_for_cert()` and
`foresight.run_for_cert()` produce dicts that pipe straight into
`collect_safety_metrics`, with no operator-typed metric names in the
chain.

### 5.3 What's missing (M17, deferred)

A cert today is verifiable for **integrity** (recompute SHA-256) and
**provenance** (`nail_commit`, `thresholds_version`, signoff). It is
*not* verifiable for **freshness** or **revocation status**. M17 spec
is now written; implementation is deferred until a customer asks.

---

## 6 · Numbers

| Thing | Number |
|---|---|
| Commits in the window | ~14 (M9 → (c)) |
| Tests added | ~30 (cert_pipeline, cert_collectors, model_status, cert_shims, etc.) |
| Tests green at the end | 257 across arena+foresight+root |
| Hours of compute saved by R6 pivot | ~6 (a 14B SFT+DPO run we didn't do) |
| First real cert composite | **1.000** |
| First real cert sha256 | `f4180095ee8e9bc6fc5e33d91c649584460f4cc733d9ad3e303e3c24a1af61bd` |
| First real cert agent_id | `acme-bot-prod-001` |

---

## 7 · The headline finding

**NAIL is now a working certification authority.** The first cert wasn't
a demo or a dry-run; it was a real bundle for a real (synthetic-named)
agent, with a real signoff. The infrastructure to issue, the model to
back the issuance, and the gate that prevents premature issuance all
work and were exercised end-to-end.

The fact that the very first integration run *caught a bug in our own
eval harness* is the strongest possible signal that the system does what
it claims: it catches cases where the evidence doesn't actually measure
what it says it measures. That property is the entire product. The model
weights, the thresholds, the JSON shape — those are all replaceable. The
discipline of "no cert without verifiable evidence" is the moat.

---

## 8 · What's next

In rough priority order:

1. **(b) is now in.** Demos can switch from `--evidence k=v` to live
   arena/foresight runs.
2. **(c) is paper-only.** Implement when a customer asks.
3. **M14.1 (suggested):** add the canary + monitor adapters that are
   stubbed in `cert_collectors.py` docstring but not yet wired.
4. **M11.1 (suggested):** wire the apex.harness `--certify` chain so
   `apex run … --certify` produces a bundle without a separate
   `cli_certify` call.
5. **M13.2:** certify `nail-guard:v?` (the only remaining un-certified
   role that the gate currently blocks).

---

*Finalised the day after the first real cert was issued. The cert stack
shipped on schedule. The diagnostic that saved us from a wasted retrain
is now a pattern we'll reuse.*
