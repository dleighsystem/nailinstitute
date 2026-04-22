#!/usr/bin/env bash
# R3 finish-line pipeline. Waits for guard --all to finish, then runs:
#   - reason DPO (from existing sft/final checkpoint)
#   - export guard:v3 (Q4_K_M)
#   - export reason:v3 (Q8_0)
#   - certify guard:v3
#   - certify reason:v3
# All output goes to scripts/local_llm/logs/r3_finish.log
set -u

WS="/home/dleighsystems/Desktop/NAIL institute"
cd "$WS" || exit 1

LOG="scripts/local_llm/logs/r3_finish_$(date +%Y%m%d_%H%M%S).log"
exec >> "$LOG" 2>&1

step() { echo; echo "════════ $* ════════"; date -u +"%Y-%m-%dT%H:%M:%SZ"; }

step "WAIT for guard --all (train.py) to finish"
while pgrep -f "train.py --model guard --all" > /dev/null; do
    sleep 30
done
echo "guard training complete."

# Verify guard DPO checkpoint exists
if [ ! -d "scripts/local_llm/checkpoints/guard/dpo/final" ]; then
    echo "ERROR: guard DPO checkpoint missing — aborting."
    exit 1
fi

step "EXPORT guard:v3 (Q4_K_M)"
# Force a fresh merge: remove stale merged_16bit so v3 weights are used
rm -rf "scripts/local_llm/exports/guard/merged_16bit" \
       "scripts/local_llm/exports/guard/nail-guard-f16.gguf" \
       "scripts/local_llm/exports/guard/nail-guard-Q4_K_M.gguf"
python scripts/local_llm/export_ollama.py --model guard --tag v3
EXP_GUARD=$?

step "TRAIN reason DPO (from sft/final + redteam pairs)"
# train_dpo loads from sft/final by convention; we leave grpo/final intact
python scripts/local_llm/train.py --model reason --stage dpo
TRAIN_REASON=$?

if [ $TRAIN_REASON -ne 0 ]; then
    echo "ERROR: reason DPO failed — skipping reason export/cert."
else
    step "EXPORT reason:v3 (Q8_0 for latency)"
    rm -rf "scripts/local_llm/exports/reason/merged_16bit" \
           "scripts/local_llm/exports/reason/nail-reason-f16.gguf" \
           "scripts/local_llm/exports/reason/nail-reason-Q4_K_M.gguf" \
           "scripts/local_llm/exports/reason/nail-reason-Q8_0.gguf"
    python scripts/local_llm/export_ollama.py --model reason --tag v3 --quant Q8_0
    EXP_REASON=$?
fi

step "CERTIFY guard:v3"
python scripts/local_llm/certify_ollama.py --model guard --tag v3
CERT_GUARD=$?

if [ "${EXP_REASON:-1}" -eq 0 ]; then
    step "CERTIFY reason:v3"
    python scripts/local_llm/certify_ollama.py --model reason --tag v3
    CERT_REASON=$?
fi

step "DONE"
echo "guard cert exit:  ${CERT_GUARD:-skipped}"
echo "reason cert exit: ${CERT_REASON:-skipped}"
echo "Latest certificates:"
ls -lt scripts/local_llm/certifications/cert_*v3*.json 2>/dev/null | head -2
