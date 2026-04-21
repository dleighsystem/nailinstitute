# NAIL Local LLM Training Pipeline

## Architecture: Two-Model Split

```
┌─────────────────────────────────────────────────────────────┐
│                    NAIL INFERENCE STACK                       │
│                                                              │
│  ┌──────────────────────┐    ┌────────────────────────────┐ │
│  │   SMALL MODEL (≤8B)  │    │    LARGE MODEL (32B+)      │ │
│  │   "nail-guard"       │    │    "nail-reason"           │ │
│  │                      │    │                            │ │
│  │  • Route/classify    │    │  • Deep reasoning          │ │
│  │  • Guardrail judge   │    │  • Attack analysis         │ │
│  │  • Tool selection    │    │  • Report generation       │ │
│  │  • Drift detection   │    │  • Vulnerability research  │ │
│  │  • AVE classification│    │  • Code review / audit     │ │
│  │                      │    │                            │ │
│  │  Base: Qwen2.5 7B    │    │  Base: Qwen2.5 32B        │ │
│  │  VRAM: ~5GB (Q4)     │    │  VRAM: ~19GB (Q4)         │ │
│  │  Latency: <50ms      │    │  Latency: <2s             │ │
│  └──────────┬───────────┘    └────────────┬───────────────┘ │
│             │                              │                 │
│             └──────────┬───────────────────┘                 │
│                        ▼                                     │
│              ┌─────────────────┐                            │
│              │  ContainmentStack│  (Paper 8 primitives)     │
│              │  BEE │ SDF │ CIA│  Running on nail-guard     │
│              └─────────────────┘                            │
└─────────────────────────────────────────────────────────────┘
         Total VRAM: ~24GB of 128GB unified memory
```

## Pipeline Components

| Script | Purpose |
|---|---|
| `generate_dataset.py` | Synthesize training data from AVE cards, experiments, attacks |
| `train.py` | Fine-tune with Unsloth (SFT + DPO/GRPO) |
| `certify.py` | In-house evaluation via lm-evaluation-harness + custom NAIL benchmarks |
| `export_ollama.py` | Export to GGUF and register with Ollama |
| `config.yaml` | All hyperparameters and model specifications |

## Quick Start

```bash
# 1. Generate training dataset
python scripts/local_llm/generate_dataset.py

# 2. Train small model (nail-guard)
python scripts/local_llm/train.py --model guard

# 3. Train large model (nail-reason)
python scripts/local_llm/train.py --model reason

# 4. Certify both models (100% local, no data leaves DGX)
python scripts/local_llm/certify.py --model guard
python scripts/local_llm/certify.py --model reason

# 5. Export to Ollama
python scripts/local_llm/export_ollama.py --model guard
python scripts/local_llm/export_ollama.py --model reason
```

## In-House Certification

All certification runs locally — no data, weights, or eval results ever leave the DGX.

- **Standard benchmarks**: MMLU, HellaSwag, ARC, TruthfulQA (via lm-eval-harness)
- **NAIL Security Suite**: Custom eval tasks testing AVE detection, attack classification, guardrail enforcement
- **Regression tests**: Compare against base model and previous fine-tune iterations
- **Red-team probing**: Automated adversarial probing using diagnostic attack library

## Cost Controls (Round-2 Training Loop)

The round-2 pipeline calls Claude Opus 4.7 for grounded synthesis and DPO
judging. Three orthogonal mechanisms keep that bill small and visible:

### 1. Spend accounting (`judge.py`)

Every Claude or Ollama call is logged to
`scripts/local_llm/data/judge_spend.jsonl` with model, token counts, USD
cost, and a caller tag from the `NAIL_JUDGE_CALLER` env var. Inspect with:

```bash
python scripts/local_llm/judge.py spend          # human table
python scripts/local_llm/judge.py spend --json   # machine-readable
```

Output includes `saved vs full-price real-time` so cache + batch wins are
attributed automatically.

### 2. Batch API (50% off, up to 24h wall time)

For offline workloads (synthesis, judge passes), the Anthropic Messages
Batches API costs half as much as real-time. Submit, poll, and fetch via
`batch_client.py`:

```bash
# One-shot: submit, wait, fetch (blocks until complete)
NAIL_JUDGE_CALLER=synthesize python scripts/local_llm/synthesize_dataset.py \
    --target both --per-ave 15 --batch

# Two-step: submit now, fetch later
python scripts/local_llm/synthesize_dataset.py \
    --target both --per-ave 15 --batch --submit-only
# ... wait 1-4h ...
python scripts/local_llm/batch_client.py status <batch_id>
python scripts/local_llm/synthesize_dataset.py --fetch <batch_id> --per-ave 15

# List all batches submitted from this machine
python scripts/local_llm/batch_client.py list
```

Batch state (id, custom_id manifest, submission timestamp, caller) is
persisted to `data/batches/<batch_id>.json` so a crashed `--fetch` can be
re-run without re-submitting.

### 3. Prompt caching (90% off repeated prefixes)

Pass `cache_system=True` to `JudgeClient.chat()` or `--cache-system` to
`synthesize_dataset.py`. The system prompt is sent with a `cache_control`
breakpoint so the second-and-later calls pay 0.10× input tokens for the
cached portion (vs 1.25× on the first write). Caches are ephemeral
(~5 minutes) and only kick in for blocks above ~1024 tokens for Opus/Sonnet
or 2048 for Haiku — below that the flag is a no-op.

### Reference: full round-2 synthesis cost

Measured on a 4-request canary (Opus 4.7, batch, no cache):
- 2083 input + 5317 output tokens
- Real-time would have cost: **\$0.428**
- Batched cost (what we paid): **\$0.214**
- Per sample: ~\$0.027

Extrapolated to a full 42-card × 15-sample × 2-target run (1260 calls):
- Real-time: ~**\$33**
- Batch alone: ~**\$17**
- Batch + cache (if system prompt grows past 1024 tokens): ~**\$12**

Always prefer `--batch` unless you need a single result fast.
