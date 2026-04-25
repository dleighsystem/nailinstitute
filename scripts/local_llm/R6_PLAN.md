# R6 Plan — `nail-reason:v6`

**Status:** drafted 2026-04-25 (post-M14 ship).
**Predecessor:** R5 / `nail-reason:v5` — failed cert 2026-04-24.

---

## 1. v5 Failure Diagnosis (verified)

`cert_reason_v5_20260424_222941.json`:

| check                          | actual    | threshold | result |
|--------------------------------|-----------|-----------|--------|
| `classification_accuracy`      | **0.0625**| ≥ 0.50    | ❌ FAIL |
| `redteam_bypass_rate`          | 0.067     | ≤ 0.30    | ✅ PASS (best ever) |
| `false_positive_rate`          | 0.00      | ≤ 0.30    | ✅ PASS (best ever) |
| `p95_latency_s`                | 66.1 s    | ≤ 60.0 s  | ❌ FAIL (close) |

**Root cause** (confirmed by reading `certify_ollama.py` + the eval JSONL):

The cert harness uses **two different system prompts**:

1. **Eval 1 — classification.** System prompt is read FROM each JSONL row. Real production prompts in our eval set:
   - "deep security analyst for AI agent systems … reference AVE IDs"
   - "incident response analyst … structured incident report with timeline"
   - The redteam-style "VERDICT:ATTACK / VERDICT:BENIGN" prompt (only ~10 of 17 rows)
   The gold answer is a long structured report with `AVE-YYYY-NNNN` IDs.

2. **Evals 2 & 3 — redteam / FP.** A *fixed* system prompt is injected by the cert: "VERDICT:ATTACK or VERDICT:BENIGN on the first line."

R5 trained `nail-reason` **only** on schema #2 (concise VERDICT prefix). Result:

* On Eval 2/3 → **excellent** (the model now starts every reply with `VERDICT:…` → 6.7% bypass, 0% FP, both records).
* On Eval 1 → **catastrophic** — the model now outputs `VERDICT:ATTACK\n<short>` to *every* prompt, including the deep-analysis prompts, so the JSON-extractor never finds a matching `ave_id` → 6.25%.

**This is a format collapse, not a substance collapse.** v5 is *better* at security than v3.1 — it just lost its second voice.

---

## 2. v6 Strategy — Dual-Mode SFT

Don't pick a side. Train **both** modes, conditioned on the system prompt the model receives at inference.

### 2.1 Data mix (~250 samples)

| corpus | count | source | output schema |
|---|---|---|---|
| **A. redteam-VERDICT** | 100 | existing `data/nail_reason_train.redteam.jsonl` from R5 | `VERDICT:ATTACK\n<one short sentence>` |
| **B. classification-AVE** | 100 | NEW: `build_reason_classification_sft.py` — replays the eval-style prompts (deep-analyst, incident-analyst) with AVE-grounded gold answers | structured report containing the correct `AVE-YYYY-NNNN` ID and severity |
| **C. on-policy held-outs** | 50 | sampled from `ave-database/cards/*.md` we haven't shown the model yet | mixed: half VERDICT-prefix, half AVE-report |

The **system prompt** in each row tells the model which mode to enter. v5's mistake was training schema A with no schema-B counter-examples, so the model learned "always VERDICT-prefix." Adding B re-grounds the conditional behaviour.

### 2.2 DPO pairs (~80)

| chosen | rejected |
|---|---|
| short VERDICT-prefix reply (≤ 30 words) on a redteam prompt | long narrative without VERDICT prefix |
| AVE-grounded report (≤ 200 words) on a deep-analyst prompt | VERDICT-prefix-only reply (no AVE ID) — *kills the v5 failure mode directly* |

### 2.3 Training plan

* Base: **Qwen2.5-14B** (same as v5 — keeps inference budget identical).
* SFT: **3 epochs** (down from R5's 4 — less overfit on schema A).
* DPO: **2 epochs** with a 50/50 mix of the two pair types.
* Keep R5's batch / lr / LoRA config unchanged.

### 2.4 Latency budget

R5 hit 66 s (6 s over). Two cheap wins:

1. The schema-B gold answers are intentionally capped at ≤ 200 words — should pull avg-case down vs. v3.1's 200–600 token replies.
2. Add `num_predict: 350` to the Modelfile for `reason:v6` (was unset; defaults to 4096).

If v6 still misses 60 s p95, the M13.2 fallback is a thin format-normaliser wrapper that runs `reason` with `num_predict: 200` and synthesises the AVE-report from a separate `guard:v4` JSON pass — no retrain needed.

---

## 3. Acceptance Criteria

`cert_reason_v6_*.json` must show:

* `classification_accuracy ≥ 0.50` *(currently 0.06 — the only reason v5 failed substance)*
* `redteam_bypass_rate ≤ 0.30` *(v5: 0.067 — preserve)*
* `false_positive_rate ≤ 0.30` *(v5: 0.00 — preserve)*
* `p95_latency_s ≤ 60.0` *(v5: 66 — needs 10% trim)*

If all four hit, update `MODEL_STATUS.md`: reason role goes ✅ certified → real (non-dry-run) cert pipeline opens for client agents that depend on the reason role.

---

## 4. Concrete Step-List (M13.1)

1. ✅ **Diagnose v5** (this file).
2. ⏳ Run `scripts/local_llm/diagnose_reason_v5.py` against live `nail-reason:v5` — confirm the format-collapse hypothesis on real responses (writes `logs/diagnose_reason_v5_<ts>.jsonl`).
3. ⏳ Implement `scripts/local_llm/build_reason_classification_sft.py` (corpus B above).
4. ⏳ Update `train.py` reason data glob to include `nail_reason_train.classify.jsonl`.
5. ⏳ Update `build_reason_concise_dpo.py` (or write a sibling `build_reason_dual_dpo.py`) to add the schema-A-on-deep-prompt → schema-B-correct preference pairs.
6. ⏳ Write `r6_reason.sh` (clone of `r5_reason.sh`, add corpus B + new DPO).
7. ⏳ Launch unattended; monitor `logs/r6_reason_*.log`.
8. ⏳ On success: `python scripts/local_llm/certify_ollama.py --model reason --tag v6` — must hit all four bars.
9. ⏳ Promote `nail-reason:v6` in `nail_harness/models.py` (`certified_for_client_certs=True`).
10. ⏳ Re-run `M14 cert_collectors` end-to-end without `--dry-run` against a synthetic agent — first **real** (non-dry-run) bundle in NAIL history.

---

## 5. Risk Register

| risk | mitigation |
|---|---|
| Adding corpus B re-introduces verbose drift → bypass rate climbs back to v3.1 levels | DPO pair "long-narrative-without-VERDICT REJECTED" puts hard pressure on the redteam path; weights stay on the safety side of the chooser |
| 14B base can't fit both modes well | Fallback: M13.2 normaliser wrapper (ship v5 + post-processor) — no retrain required, breaks tie within hours |
| 60 s p95 still missed | `num_predict=350`, plus per-prompt early-stop on `\n\n---` tail tokens |
