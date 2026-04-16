# NAIL Judge — Local Certification Evaluator

A fine-tuned 8B LLM that evaluates AI agent responses to adversarial attacks.
Replaces frontier API calls for the pass/fail evaluation step of NAIL certification.

## Architecture

```
Attack (frontier LLM) → Agent Under Test → Response → NAIL Judge (local) → Verdict
```

## Training Data Sources

| Source | Records | Type |
|--------|---------|------|
| Diagnostic attack library (21 scenarios) | Synthetic expansions | Attack → expected verdict |
| Arena battle logs | GA-evolved attacks | Attack → breach/defend outcome |
| Experiment results (exp1–exp38) | Research findings | Pathology → classification |

## Usage

```bash
# 1. Extract & label training data
python -m nail_judge.extract_training_data

# 2. Fine-tune (LoRA on Llama 3 8B or Mistral 7B)
python -m nail_judge.finetune --base-model meta-llama/Llama-3.1-8B-Instruct

# 3. Run inference
python -m nail_judge.judge --response "I can't help with that."
```
