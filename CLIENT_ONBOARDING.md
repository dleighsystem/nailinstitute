# NAIL Cert — Client Onboarding Runbook

**Audience:** the NAIL operator running an engagement.
**Goal:** signed `CertBundle` in the client's hands within 3 business days
of intake.

> The discipline that matters: **no cert without verifiable evidence.**
> If at any step the evidence doesn't measure what we claim it measures,
> stop and fix the eval. (See `POST_MORTEM_M9_M13_1.md` §3 for why.)

---

## Step 0 — Pre-engagement checklist (NAIL side)

Before we send the intake form, confirm:

- [ ] Cert gate is open: `python -c "from nail_harness.models import assert_client_cert_allowed; assert_client_cert_allowed()"` exits 0.
- [ ] Tests are green: `python -m pytest tests/ arena/tests/ foresight/tests/ -q` reports 0 failures.
- [ ] `nail-reason` is the certified tag in `MODEL_STATUS.md` (currently `nail-reason:v5.1`).
- [ ] `thresholds.json` version matches what we'll claim on the cert (currently `1.0`).

If any of those are red, do **not** start an engagement.

---

## Step 1 — Send intake form

1. Send the client `CLIENT_INTAKE.md`.
2. They fill it in and return.
3. NDA signed before any traffic.

**Expected back:** all of §§1-6. §7 (special asks) is optional but always
worth reading.

---

## Step 2 — Generate `client_config.yaml`

From the returned intake, derive a config:

```bash
cp nail_harness/client_config.example.yaml \
   engagements/<client>/client_config.yaml
$EDITOR engagements/<client>/client_config.yaml
```

Fill in `agent_id`, `signoff_by`, `output_dir`, `vendor`, `contact`, and
the `notes` block (probe window, side-effecting-tools opt-in).

`metrics_json` will be filled in after Step 4.

---

## Step 3 — Rehearsal (dry-run)

Always do at least one dry-run before the real probe window. Catches
config typos and gate issues without burning the client's signoff.

```bash
# Use a synthetic AAA metrics file from the demo
bash scripts/demo_certify.sh aaa
# Confirm DRY-RUN-PASS, AAA, 5/5 hard floors green
```

If the demo passes but the gate is closed for any reason, abort and
escalate.

---

## Step 4 — Probe window

During the agreed window:

```bash
# A. Run the live probes against the client endpoint
python -m nail_harness.cli_collect \
    --agent-id <agent_id> \
    --endpoint <client_endpoint> \
    --output engagements/<client>/runs/<date>/metrics.json
```

`cli_collect` drives `apex.harness` for capability + ops, and uses the
`run_for_cert` shims (commit `(b)`) for safety:

- `arena.run_for_cert(rounds=10)` → adversarial bypass + benign FP
- `foresight.run_for_cert(safe_corpus)` → plan-critique reject rate

If a metric source is unavailable for this client (e.g. no canary in
their stack), supply it via `--evidence k=v` on the same invocation.
Document the substitution in `notes:`.

---

## Step 5 — Issue the cert

```bash
# Update the config to point at the produced metrics
sed -i "s|^metrics_json:.*|metrics_json: \"engagements/<client>/runs/<date>/metrics.json\"|" \
    engagements/<client>/client_config.yaml

# Issue
python -m nail_harness.cli_certify --config engagements/<client>/client_config.yaml
```

Expected output:

```
agent     : <agent_id>
composite : 1.0  (AAA)
verdict   : PASS
bundle    : engagements/<client>/certs/cert_<agent_id>_<sha>.json
sha256    : <fingerprint>
```

**If verdict ≠ PASS**: do **not** rerun until you understand why. The
denial reasons are the product. Show them to the client. Decide together
whether to fix the agent or accept a lower grade.

---

## Step 6 — Hand-off

Bundle the following into a single `cert_handoff_<client>_<date>.tar.gz`:

1. The signed `cert_<agent_id>_<sha>.json` bundle.
2. `scripts/inspect_cert.py` (so they can re-verify independently).
3. A copy of the filled-in `CLIENT_INTAKE.md`.
4. The `client_config.yaml` used (with `signoff_by` intact — auditable).
5. The `metrics.json` that produced the bundle (full evidence trail).
6. A one-page cover letter naming the cert sha256 and what it certifies.

The client can then run, with no NAIL toolchain required:

```bash
python inspect_cert.py cert_<agent_id>_<sha>.json --verify
# exit 0 = bundle integrity confirmed
```

---

## Step 7 — Calendar the re-cert

Today there is no machine-checked expiry (M17, deferred). So the operator
adds a calendar reminder per the cadence in §6 of the intake (default 90
days). Send a reminder 14 days before.

Re-cert is a fresh run from Step 3.

---

## Failure modes to watch for

| Symptom | Likely cause | Fix |
|---|---|---|
| `cli_certify` returns rc=2, "agent_id required" | typo in config key | YAML keys are snake_case |
| `verdict: DENIED`, denial mentions H5 | `signoff_by` empty or `--dry-run` flag not removed | fill `signoff_by`, drop `--dry-run` |
| Bypass rate suspiciously low (e.g. 0.0) on first try | arena rounds too low | bump `--arena-rounds` to ≥10 in `cli_collect` |
| Classification 0.00 with high latency | look at `num_predict` in the model's Modelfile (M13.1 lesson) | confirm model serves complete answers |
| Composite drops a band on re-cert with no model change | thresholds bumped in `thresholds.json` | check `thresholds_version` field; communicate to client |

---

## What NOT to do

- ❌ Issue a cert without running Step 3 first.
- ❌ Reuse an `agent_id` across deployments (breaks the audit trail).
- ❌ Edit a metrics.json by hand to make a DENIED bundle pass. The whole
  product collapses if we do this once.
- ❌ Skip the hand-off `inspect_cert.py` — independent verification is
  the *point*.
- ❌ Promise revocation today. M17 is paper-only; say "manual recall on
  request" and mean it.
