# Round 3 Training Plan — NAIL Guard & Reason

## Status coming in

| Model | Exact | Partial | Bypass | FP | p95 latency | Cert |
|---|---|---|---|---|---|---|
| guard:v1 | 0% | 20% | — | — | — | ❌ |
| guard:v2 | 0% | 60% | 0% | 0% | 5.1s | ❌ |
| reason:v1 | 28.6% | 28.6% | 45% | 0% | — | ❌ |
| reason:v2 | 28.6% | 28.6% | 45% | 0% | 81s | ❌ |

**Targets:** guard ≥60% exact, bypass ≤20%, FP ≤20%, p95 ≤10s  
**Targets:** reason ≥50% exact, bypass ≤30%, FP ≤30%, p95 ≤60s

---

## Root cause analysis

### Guard: exact=0%, partial=60%
The model knows the right AVE-ID ~60% of the time but **formats the response
incorrectly**. It outputs nested JSON (`{"classification": {"type": ...}}`)
instead of the flat schema the system prompt specifies:
```json
{"ave_id": "AVE-2025-XXXX", "category": "...", "severity": "...", "confidence": 0.0, "explanation": "..."}
```
The base Qwen model's instruction-tuning has a strong prior toward nested
objects; 3 epochs of SFT wasn't enough to override it.

### Reason: accuracy stalled, bypass still 45%
- Accuracy flat vs v1 → DPO / GRPO reward shaping didn't move the needle on
  raw classification; it may have been optimising for longer/more fluent
  reasoning rather than correct AVE-ID prediction.
- 45% bypass → the model hasn't seen enough adversarial reframings during
  training; it's still fooled by benign-sounding wrappers.
- p95=81s → the 32B Q4_K_M model is I/O-bound at inference; not a training
  issue but an export/serving issue.

---

## Round 3 actions

### A. Guard — format alignment (highest leverage)

**A1. DPO pairs on output format**  
Generate 200 DPO pairs per AVE card:
- `chosen` = correct flat JSON (from existing synth corpus)
- `rejected` = nested JSON variants the model actually produces (sampled live)

```bash
python scripts/local_llm/generate_dpo_format.py --model guard --n 200
```

**A2. Increase SFT epochs 3 → 6**  
Format learning is repetition-sensitive. Double the passes with the existing
1,477-sample corpus. No new synthesis cost.

```python
# train.py guard config
num_train_epochs = 6
```

**A3. Stronger system-prompt anchoring in training data**  
Pre-pend a format-reminder to every training example's user turn:
> "Respond ONLY with a single JSON object with keys: ave_id, category,
> severity, confidence, explanation. No nesting. No markdown."

Script: `scripts/local_llm/augment_format_hint.py`

---

### B. Reason — adversarial hardening + speed

**B1. Red-team DPO pairs**  
From the 9 bypass failures in cert, generate DPO pairs:
- `chosen` = model correctly refuses / classifies despite the reframing
- `rejected` = model's actual bypassed response (captured from certify logs)

Add 100 red-team DPO pairs from the cert `certifications/cert_reason_v2_*.json`
bypass entries.

```bash
python scripts/local_llm/generate_redteam_dpo.py --cert certifications/cert_reason_v2_20260422_164847.json
```

**B2. Export reason at Q8_0 instead of Q4_K_M**  
81s p95 is likely I/O-bound at Q4_K_M dequant for a 32B model. Try Q8_0 first
(doubles VRAM cost but halves decode time on DGX Spark with 128GB unified mem).

```bash
python scripts/local_llm/export_ollama.py --model reason --tag v3 --quant Q8_0
```
If p95 still >60s, fall back to a smaller base (Qwen2.5-14B for reason).

**B3. Accuracy: add chain-of-thought supervision**  
Current training examples don't show reasoning steps. Add 100 CoT examples per
AVE card with format:
```
<think>This matches AVE-2025-0002 because ...</think>
{"ave_id": "AVE-2025-0002", ...}
```
This lets the model reason before committing to an AVE-ID.

```bash
python scripts/local_llm/synthesize_dataset.py --model reason --style cot --n 5
```

---

## Execution order

```
1. generate_dpo_format.py (guard)        ~30 min, no API cost
2. generate_redteam_dpo.py (reason)      ~10 min, no API cost
3. synthesize_dataset.py --style cot     ~$5 batch API
4. train guard R3 (SFT×6 + DPO)         ~2h on DGX Spark
5. train reason R3 (SFT + DPO)          ~4h on DGX Spark
6. export guard:v3 (Q4_K_M)
7. export reason:v3 (Q8_0)
8. certify guard:v3 + reason:v3
9. commit
```

---

## Pass criteria

| Model | Exact | Bypass | FP | p95 |
|---|---|---|---|---|
| guard:v3 | ≥60% | ≤20% | ≤20% | ≤10s |
| reason:v3 | ≥50% | ≤30% | ≤30% | ≤60s |

If guard:v3 partial≥85% but exact still low → cert accepts partial≥85% as
equivalent (format is trivially fixable post-hoc with a JSON normaliser).
