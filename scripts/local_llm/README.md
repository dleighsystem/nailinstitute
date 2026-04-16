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
