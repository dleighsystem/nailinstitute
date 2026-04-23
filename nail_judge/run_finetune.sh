#!/usr/bin/env bash
# ── nail_judge/run_finetune.sh ──────────────────────────────────────
# Correct wrapper for running the NAIL Judge LoRA fine-tune on the DGX Spark
# (GB10, sm_121). The original failure came from invoking the script with
# `miniconda3/bin/python` (torch 2.10.0+cu130 — caps at sm_120), which caused
# cpp extensions to be skipped and training to stall at step 0.
#
# Fix: use the NAIL institute .venv (torch 2.11.0+cu130 — supports sm_121).
# Do not run while another training job (e.g. scripts/local_llm/train.py) is
# holding the GPU — GPU RAM will be contended.

set -euo pipefail

cd "$(dirname "$0")/.."   # => /home/dleighsystems/Desktop/NAIL institute

VENV_PY=".venv/bin/python"
BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-Coder-7B-Instruct}"
EPOCHS="${EPOCHS:-3}"
OUT="${OUT:-nail_judge/models/nail-judge-v1}"
LOG="${LOG:-/tmp/nail_judge_finetune.log}"

if [[ ! -x "$VENV_PY" ]]; then
  echo "❌ Missing $VENV_PY — activate/install the NAIL institute .venv first." >&2
  exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  NAIL Judge fine-tune launcher"
echo "  Python:     $VENV_PY"
"$VENV_PY" - <<'PY'
import torch
print(f"  Torch:      {torch.__version__} (cuda {torch.version.cuda})")
try:
    cap = torch.cuda.get_device_capability(0)
    print(f"  GPU capability: sm_{cap[0]}{cap[1]}")
except Exception as e:
    print(f"  GPU capability: unknown ({e})")
PY
echo "  Base model: $BASE_MODEL"
echo "  Epochs:     $EPOCHS"
echo "  Output:     $OUT"
echo "  Log:        $LOG"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Guard against concurrent GPU jobs
if pgrep -af 'scripts/local_llm/train.py' > /dev/null; then
  echo "⚠ scripts/local_llm/train.py is running — that will contend for GPU." >&2
  echo "  Either stop it first, or re-run this script after it completes." >&2
  exit 2
fi

exec "$VENV_PY" -m nail_judge.finetune \
    --base-model "$BASE_MODEL" \
    --train-data nail_judge/data/train.jsonl \
    --eval-data  nail_judge/data/eval.jsonl \
    --output     "$OUT" \
    --epochs     "$EPOCHS" 2>&1 | tee "$LOG"
