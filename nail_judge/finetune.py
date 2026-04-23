"""
NAIL Judge — LoRA Fine-Tuning Script.

Fine-tunes Llama 3.1 8B Instruct (or Mistral 7B) on NAIL certification
verdict data using QLoRA (4-bit quantisation + LoRA adapters).

Requirements:
    pip install torch transformers peft bitsandbytes trl datasets accelerate

Usage:
    python -m nail_judge.finetune \
        --base-model meta-llama/Llama-3.1-8B-Instruct \
        --train-data nail_judge/data/train.jsonl \
        --eval-data nail_judge/data/eval.jsonl \
        --output nail_judge/models/nail-judge-v1 \
        --epochs 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ════════════════════════════════════════════════════════════════════
# Config
# ════════════════════════════════════════════════════════════════════

DEFAULT_BASE_MODEL = "meta-llama/Llama-3.1-8B-Instruct"
DEFAULT_OUTPUT = "nail_judge/models/nail-judge-v1"

LORA_CONFIG = {
    "r": 64,              # LoRA rank
    "lora_alpha": 128,    # Scaling factor
    "lora_dropout": 0.05,
    "target_modules": [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    "bias": "none",
    "task_type": "CAUSAL_LM",
}

TRAINING_ARGS = {
    "num_train_epochs": 3,
    "per_device_train_batch_size": 4,
    "per_device_eval_batch_size": 4,
    "gradient_accumulation_steps": 4,
    "learning_rate": 2e-4,
    "weight_decay": 0.01,
    "warmup_ratio": 0.03,
    "lr_scheduler_type": "cosine",
    "logging_steps": 10,
    "eval_strategy": "steps",
    "eval_steps": 50,
    "save_strategy": "steps",
    "save_steps": 100,
    "save_total_limit": 3,
    "bf16": True,
    "gradient_checkpointing": True,
    "max_grad_norm": 0.3,
    "optim": "paged_adamw_8bit",
    "report_to": "none",
    "max_seq_length": 2048,
}


# ════════════════════════════════════════════════════════════════════
# Dataset
# ════════════════════════════════════════════════════════════════════

def load_dataset_from_jsonl(path: str | Path) -> list[dict]:
    """Load ChatML JSONL dataset."""
    samples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def format_chatml(sample: dict, tokenizer) -> str:
    """Format a sample using the tokenizer's chat template."""
    messages = sample["messages"]
    try:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
    except Exception:
        # Fallback: manual ChatML
        text = ""
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            text += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        return text


# ════════════════════════════════════════════════════════════════════
# Fine-Tuning
# ════════════════════════════════════════════════════════════════════

def finetune(
    base_model: str = DEFAULT_BASE_MODEL,
    train_data: str = "nail_judge/data/train.jsonl",
    eval_data: str = "nail_judge/data/eval.jsonl",
    output_dir: str = DEFAULT_OUTPUT,
    epochs: int = 3,
    use_4bit: bool = True,
):
    """Run QLoRA fine-tuning."""

    # ── Imports (heavy, so deferred) ───────────────────────────
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments,
        )
        from trl import SFTTrainer
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Install with:")
        print("  pip install torch transformers peft bitsandbytes trl datasets accelerate")
        sys.exit(1)

    print("━" * 60)
    print("  NAIL Judge — LoRA Fine-Tuning")
    print(f"  Base Model: {base_model}")
    print(f"  Train Data: {train_data}")
    print(f"  Output:     {output_dir}")
    print(f"  Epochs:     {epochs}")
    print(f"  4-bit:      {use_4bit}")
    print("━" * 60)

    # ── Load tokenizer ─────────────────────────────────────────
    print("\n📦 Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(
        base_model,
        trust_remote_code=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ── Load model (quantised) ─────────────────────────────────
    print("📦 Loading model...")
    if use_4bit:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
        )
        model = prepare_model_for_kbit_training(model)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
        )

    # ── Apply LoRA ─────────────────────────────────────────────
    print("🔧 Applying LoRA adapters...")
    lora_config = LoraConfig(**LORA_CONFIG)
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Load data ──────────────────────────────────────────────
    print("📊 Loading training data...")
    train_samples = load_dataset_from_jsonl(train_data)
    eval_samples = load_dataset_from_jsonl(eval_data)

    # Format with chat template
    train_texts = [format_chatml(s, tokenizer) for s in train_samples]
    eval_texts = [format_chatml(s, tokenizer) for s in eval_samples]

    train_dataset = Dataset.from_dict({"text": train_texts})
    eval_dataset = Dataset.from_dict({"text": eval_texts})

    print(f"   Train: {len(train_dataset)} samples")
    print(f"   Eval:  {len(eval_dataset)} samples")

    # ── Training args ──────────────────────────────────────────
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=TRAINING_ARGS["per_device_train_batch_size"],
        per_device_eval_batch_size=TRAINING_ARGS["per_device_eval_batch_size"],
        gradient_accumulation_steps=TRAINING_ARGS["gradient_accumulation_steps"],
        learning_rate=TRAINING_ARGS["learning_rate"],
        weight_decay=TRAINING_ARGS["weight_decay"],
        warmup_ratio=TRAINING_ARGS["warmup_ratio"],
        lr_scheduler_type=TRAINING_ARGS["lr_scheduler_type"],
        logging_steps=TRAINING_ARGS["logging_steps"],
        eval_strategy=TRAINING_ARGS["eval_strategy"],
        eval_steps=TRAINING_ARGS["eval_steps"],
        save_strategy=TRAINING_ARGS["save_strategy"],
        save_steps=TRAINING_ARGS["save_steps"],
        save_total_limit=TRAINING_ARGS["save_total_limit"],
        bf16=TRAINING_ARGS["bf16"],
        gradient_checkpointing=TRAINING_ARGS["gradient_checkpointing"],
        max_grad_norm=TRAINING_ARGS["max_grad_norm"],
        optim=TRAINING_ARGS["optim"],
        report_to=TRAINING_ARGS["report_to"],
    )

    # ── Trainer ────────────────────────────────────────────────
    print("🚀 Starting training...")
    trainer = SFTTrainer(
        model=model,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        args=training_args,
        processing_class=tokenizer,
        max_seq_length=TRAINING_ARGS["max_seq_length"],
    )

    trainer.train()

    # ── Save ───────────────────────────────────────────────────
    print(f"\n💾 Saving model to {output_dir}...")
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)

    # Save config for inference
    config = {
        "base_model": base_model,
        "lora_config": LORA_CONFIG,
        "training_args": {k: str(v) for k, v in TRAINING_ARGS.items()},
        "train_samples": len(train_dataset),
        "eval_samples": len(eval_dataset),
        "epochs": epochs,
    }
    with open(Path(output_dir) / "nail_judge_config.json", "w") as f:
        json.dump(config, f, indent=2)

    print("✅ Fine-tuning complete!")
    print(f"   Model: {output_dir}")
    print(f"   Merge with: python -m nail_judge.merge --adapter {output_dir}")

    return output_dir


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="NAIL Judge — LoRA Fine-Tuning")
    parser.add_argument(
        "--base-model", default=DEFAULT_BASE_MODEL,
        help=f"HuggingFace model ID (default: {DEFAULT_BASE_MODEL})",
    )
    parser.add_argument(
        "--train-data", default="nail_judge/data/train.jsonl",
        help="Path to training JSONL",
    )
    parser.add_argument(
        "--eval-data", default="nail_judge/data/eval.jsonl",
        help="Path to evaluation JSONL",
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--epochs", type=int, default=3,
        help="Number of training epochs (default: 3)",
    )
    parser.add_argument(
        "--no-4bit", action="store_true",
        help="Disable 4-bit quantisation (requires more VRAM)",
    )
    args = parser.parse_args()

    finetune(
        base_model=args.base_model,
        train_data=args.train_data,
        eval_data=args.eval_data,
        output_dir=args.output,
        epochs=args.epochs,
        use_4bit=not args.no_4bit,
    )


if __name__ == "__main__":
    main()
