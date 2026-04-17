#!/usr/bin/env python3
"""
NAIL Train — Fine-tune nail-guard and nail-reason using Unsloth + TRL.

Runs entirely on the local DGX Spark. Supports:
  - SFT (Supervised Fine-Tuning)
  - DPO (Direct Preference Optimization) — guard model
  - GRPO (Group Relative Policy Optimization) — reason model

Usage:
    python scripts/local_llm/train.py --model guard --stage sft
    python scripts/local_llm/train.py --model guard --stage dpo
    python scripts/local_llm/train.py --model reason --stage sft
    python scripts/local_llm/train.py --model reason --stage grpo
    python scripts/local_llm/train.py --model guard --all   # SFT then DPO
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

WORKSPACE = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = WORKSPACE / "scripts" / "local_llm" / "config.yaml"
DATA_DIR = WORKSPACE / "scripts" / "local_llm" / "data"
OUTPUT_BASE = WORKSPACE / "scripts" / "local_llm" / "checkpoints"


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def get_model_config(config: dict, model_name: str) -> dict:
    models = config["models"]
    if model_name not in models:
        print(f"✗ Unknown model '{model_name}'. Choose: {list(models.keys())}")
        sys.exit(1)
    return models[model_name]


def train_sft(model_name: str, cfg: dict, hardware: dict):
    """Supervised Fine-Tuning with Unsloth + TRL SFTTrainer."""
    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments
    from datasets import load_dataset

    training = cfg["training"]
    lora = training["lora"]
    base_model = cfg["base_model"]
    max_seq = training.get("max_seq_length", 4096)

    print(f"\n{'═' * 60}")
    print(f"  SFT Training: {model_name}")
    print(f"  Base model: {base_model}")
    print(f"  LoRA: r={lora['r']}, α={lora['alpha']}")
    print(f"{'═' * 60}\n")

    # Load model with Unsloth 4-bit
    # On DGX Spark unified memory, explicitly tell transformers
    # that GPU has enough memory to avoid false CPU offload detection
    import torch
    free_mem = torch.cuda.mem_get_info()[0]
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq,
        dtype=None,  # auto-detect
        load_in_4bit=True,
        device_map={"": 0},  # force all to GPU 0
    )

    # Apply LoRA
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora["r"],
        lora_alpha=lora["alpha"],
        lora_dropout=lora.get("dropout", 0.05),
        target_modules=lora.get("target_modules", [
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ]),
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    # Load dataset
    train_path = DATA_DIR / f"nail_{model_name}_train.jsonl"
    eval_path = DATA_DIR / f"nail_{model_name}_eval.jsonl"

    if not train_path.exists():
        print(f"✗ Training data not found: {train_path}")
        print("  Run generate_dataset.py first.")
        sys.exit(1)

    dataset = load_dataset("json", data_files={
        "train": str(train_path),
        "eval": str(eval_path) if eval_path.exists() else str(train_path),
    })

    # Format for chat template
    def format_chat(example):
        text = tokenizer.apply_chat_template(
            example["messages"], tokenize=False, add_generation_prompt=False
        )
        return {"text": text}

    dataset = dataset.map(format_chat)

    # Output directory
    output_dir = OUTPUT_BASE / model_name / "sft"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Training arguments
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=training.get("batch_size", 4),
        gradient_accumulation_steps=training.get("gradient_accumulation", 4),
        num_train_epochs=training.get("epochs", 3),
        learning_rate=float(training.get("learning_rate", 2e-4)),
        lr_scheduler_type=training.get("scheduler", "cosine"),
        warmup_ratio=training.get("warmup_ratio", 0.1),
        fp16=not training.get("bf16", True),
        bf16=training.get("bf16", True),
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch",
        report_to="none",
        seed=42,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset["eval"],
        args=training_args,
        dataset_text_field="text",
        max_seq_length=max_seq,
    )

    print("Starting SFT training...")
    trainer.train()

    # Save
    model.save_pretrained(str(output_dir / "final"))
    tokenizer.save_pretrained(str(output_dir / "final"))

    # Save training metadata
    meta = {
        "model": model_name,
        "stage": "sft",
        "base": base_model,
        "lora_r": lora["r"],
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir / "final"),
    }
    (output_dir / "training_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    print(f"\n✓ SFT complete. Model saved to {output_dir / 'final'}")
    return output_dir / "final"


def train_dpo(model_name: str, cfg: dict, hardware: dict):
    """DPO alignment (for nail-guard)."""
    from unsloth import FastLanguageModel, PatchDPOTrainer
    # Fix: llm_blender incompatible with transformers 5.x (TRANSFORMERS_CACHE removed)
    import transformers.utils.hub as _hub
    if not hasattr(_hub, "TRANSFORMERS_CACHE"):
        import os
        _hub.TRANSFORMERS_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    from trl import DPOTrainer, DPOConfig
    from datasets import load_dataset

    PatchDPOTrainer()

    dpo = cfg.get("alignment", {})

    sft_path = OUTPUT_BASE / model_name / "sft" / "final"
    if not sft_path.exists():
        print(f"✗ SFT checkpoint not found: {sft_path}")
        print("  Run SFT first: --model guard --stage sft")
        sys.exit(1)

    max_seq = cfg.get("training", {}).get("max_seq_length", 4096)

    print(f"\n{'═' * 60}")
    print(f"  DPO Training: {model_name}")
    print(f"  From SFT checkpoint: {sft_path}")
    print(f"{'═' * 60}\n")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(sft_path),
        max_seq_length=max_seq,
        dtype=None,
        load_in_4bit=True,
    )

    # DPO needs preference pairs — load or generate
    dpo_data_path = DATA_DIR / f"nail_{model_name}_dpo.jsonl"
    if not dpo_data_path.exists():
        print(f"⚠ DPO preference data not found: {dpo_data_path}")
        print("  Generating basic preference pairs from SFT data...")
        _generate_dpo_pairs(model_name, tokenizer, model)

    dataset = load_dataset("json", data_files=str(dpo_data_path))["train"]

    output_dir = OUTPUT_BASE / model_name / "dpo"
    output_dir.mkdir(parents=True, exist_ok=True)

    dpo_config = DPOConfig(
        output_dir=str(output_dir),
        per_device_train_batch_size=dpo.get("batch_size", 2),
        gradient_accumulation_steps=dpo.get("gradient_accumulation", 8),
        num_train_epochs=dpo.get("epochs", 1),
        learning_rate=float(dpo.get("learning_rate", 5e-5)),
        beta=dpo.get("beta", 0.1),
        fp16=not cfg.get("training", {}).get("bf16", True),
        bf16=cfg.get("training", {}).get("bf16", True),
        logging_steps=10,
        save_strategy="epoch",
        report_to="none",
    )

    trainer = DPOTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=dpo_config,
    )

    print("Starting DPO training...")
    trainer.train()

    model.save_pretrained(str(output_dir / "final"))
    tokenizer.save_pretrained(str(output_dir / "final"))
    print(f"\n✓ DPO complete. Model saved to {output_dir / 'final'}")
    return output_dir / "final"


def train_grpo(model_name: str, cfg: dict, hardware: dict):
    """GRPO alignment (for nail-reason)."""
    from unsloth import FastLanguageModel
    import transformers.utils.hub as _hub
    if not hasattr(_hub, "TRANSFORMERS_CACHE"):
        import os
        _hub.TRANSFORMERS_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    from trl import GRPOTrainer, GRPOConfig

    grpo = cfg.get("alignment", {})

    sft_path = OUTPUT_BASE / model_name / "sft" / "final"
    if not sft_path.exists():
        print(f"✗ SFT checkpoint not found: {sft_path}")
        sys.exit(1)

    max_seq = cfg.get("training", {}).get("max_seq_length", 4096)

    print(f"\n{'═' * 60}")
    print(f"  GRPO Training: {model_name}")
    print(f"  From SFT checkpoint: {sft_path}")
    print(f"{'═' * 60}\n")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(sft_path),
        max_seq_length=max_seq,
        dtype=None,
        load_in_4bit=True,
    )

    # Load prompts for GRPO (extract just the prompt portion from training data)
    from datasets import Dataset
    train_path = DATA_DIR / f"nail_{model_name}_train.jsonl"
    prompts = []
    with open(train_path) as f:
        for line in f:
            row = json.loads(line)
            # Data may be in "messages" or "text" format
            if "messages" in row:
                msgs = row["messages"]
                # Build prompt from system + user messages
                prompt_parts = []
                for m in msgs:
                    if m["role"] in ("system", "user"):
                        prompt_parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>")
                if prompt_parts:
                    prompt = "\n".join(prompt_parts) + "\n<|im_start|>assistant\n"
                    prompts.append({"prompt": prompt[:2048]})  # truncate for GRPO
            elif "text" in row:
                text = row["text"]
                if "<|im_start|>assistant" in text:
                    prompt = text.split("<|im_start|>assistant")[0] + "<|im_start|>assistant\n"
                    prompts.append({"prompt": prompt[:2048]})
    dataset = Dataset.from_list(prompts) if prompts else None
    if not dataset or len(dataset) == 0:
        print("⚠ No GRPO prompts extracted. Skipping GRPO.")
        return None
    print(f"  GRPO prompts: {len(dataset)}")

    output_dir = OUTPUT_BASE / model_name / "grpo"
    output_dir.mkdir(parents=True, exist_ok=True)

    # GRPO reward function — scores reasoning quality
    def reward_fn(completions: list[str], **kwargs) -> list[float]:
        rewards = []
        for c in completions:
            score = 0.0
            # Reward structured output
            if "##" in c:
                score += 0.3
            if "AVE-" in c:
                score += 0.2
            if any(w in c.lower() for w in ["blast radius", "attack vector", "defense", "mitigation"]):
                score += 0.3
            if len(c) > 200:
                score += 0.1
            if len(c) > 500:
                score += 0.1
            rewards.append(min(score, 1.0))
        return rewards

    grpo_config = GRPOConfig(
        output_dir=str(output_dir),
        per_device_train_batch_size=grpo.get("batch_size", 1),
        gradient_accumulation_steps=grpo.get("gradient_accumulation", 16),
        num_train_epochs=grpo.get("epochs", 1),
        learning_rate=float(grpo.get("learning_rate", 1e-5)),
        num_generations=grpo.get("num_generations", 4),
        fp16=not cfg.get("training", {}).get("bf16", True),
        bf16=cfg.get("training", {}).get("bf16", True),
        logging_steps=10,
        report_to="none",
    )

    trainer = GRPOTrainer(
        model=model,
        tokenizer=tokenizer,
        reward_funcs=[reward_fn],
        train_dataset=dataset,
        args=grpo_config,
    )

    print("Starting GRPO training...")
    trainer.train()

    model.save_pretrained(str(output_dir / "final"))
    tokenizer.save_pretrained(str(output_dir / "final"))
    print(f"\n✓ GRPO complete. Model saved to {output_dir / 'final'}")
    return output_dir / "final"


def _generate_dpo_pairs(model_name: str, tokenizer, model):
    """Generate basic DPO preference pairs from SFT training data."""
    import random

    train_path = DATA_DIR / f"nail_{model_name}_train.jsonl"
    dpo_path = DATA_DIR / f"nail_{model_name}_dpo.jsonl"

    pairs = []
    with open(train_path) as f:
        samples = [json.loads(line) for line in f if line.strip()]

    for s in samples[:200]:
        msgs = s["messages"]
        user_msg = next((m["content"] for m in msgs if m["role"] == "user"), "")
        chosen = next((m["content"] for m in msgs if m["role"] == "assistant"), "")

        # Create a "rejected" response (deliberately worse)
        rejected = "I'm not sure about that. Could you provide more details?"

        pairs.append({
            "prompt": user_msg,
            "chosen": chosen,
            "rejected": rejected,
        })

    random.shuffle(pairs)
    with open(dpo_path, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")

    print(f"  Generated {len(pairs)} DPO preference pairs → {dpo_path}")


def main():
    parser = argparse.ArgumentParser(description="NAIL LLM Trainer (Unsloth + TRL)")
    parser.add_argument("--model", required=True, choices=["guard", "reason"],
                        help="Which model to train")
    parser.add_argument("--stage", choices=["sft", "dpo", "grpo"],
                        help="Training stage")
    parser.add_argument("--all", action="store_true",
                        help="Run all stages for the model")
    args = parser.parse_args()

    config = load_config()
    model_cfg = get_model_config(config, args.model)
    hardware = config.get("hardware", {})

    if args.all:
        train_sft(args.model, model_cfg, hardware)
        if args.model == "guard":
            train_dpo(args.model, model_cfg, hardware)
        else:
            train_grpo(args.model, model_cfg, hardware)
    elif args.stage == "sft":
        train_sft(args.model, model_cfg, hardware)
    elif args.stage == "dpo":
        train_dpo(args.model, model_cfg, hardware)
    elif args.stage == "grpo":
        train_grpo(args.model, model_cfg, hardware)
    else:
        parser.error("Specify --stage or --all")


if __name__ == "__main__":
    main()
