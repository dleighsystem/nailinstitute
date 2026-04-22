#!/usr/bin/env bash
# R4 pipeline (guard-focused).
# 1. Wait for guard --all (SFT 6e + DPO 2e) to finish
# 2. Export guard:v4 (Q4_K_M)
# 3. Cert guard:v4 with the augmented eval (5 redteam + 5 benign held-out
#    samples appended to the standalone probe sets)
set -u

WS="/home/dleighsystems/Desktop/NAIL institute"
cd "$WS" || exit 1
LOG="scripts/local_llm/logs/r4_finish_$(date +%Y%m%d_%H%M%S).log"
exec >> "$LOG" 2>&1
step() { echo; echo "════════ $* ════════"; date -u +"%Y-%m-%dT%H:%M:%SZ"; }

step "WAIT for guard --all"
while pgrep -f "train.py --model guard --all" > /dev/null; do sleep 30; done

if [ ! -d "scripts/local_llm/checkpoints/guard/dpo/final" ]; then
    echo "ERROR: guard DPO final missing"; exit 1
fi

step "EXPORT guard:v4 (Q4_K_M)"
rm -rf scripts/local_llm/exports/guard/merged_16bit \
       scripts/local_llm/exports/guard/nail-guard-f16.gguf \
       scripts/local_llm/exports/guard/nail-guard-Q4_K_M.gguf
python scripts/local_llm/export_ollama.py --model guard --tag v4

step "CERTIFY guard:v4"
python scripts/local_llm/certify_ollama.py --model guard --tag v4

step "DONE"
ls -lt scripts/local_llm/certifications/cert_guard_v4_*.json | head -1
