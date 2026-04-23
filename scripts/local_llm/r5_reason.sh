#!/usr/bin/env bash
# R5 pipeline (reason-focused).
#
# Goal: produce nail-reason:v5 that passes all four cert checks
# (cert_reason_v3.1 missed: classification 28.6% < 50%, bypass 45% > 30%,
#  latency 111s > 60s; only false-positive 0% passed).
#
# Strategy:
#   1. Build VERDICT-schema SFT (~100 short samples) — same trick that
#      fixed guard in R4 (75% bypass → 0%).
#   2. Build concise-DPO pairs (chosen ≤30 words, rejected ≥120 words).
#   3. Train SFT (4 epochs) then DPO (2 epochs) on Qwen2.5-14B base.
#   4. Export Q4_K_M GGUF, register as nail-reason:v5.
#   5. Cert v5 against the same 4 thresholds.
#
# Runs unattended; output → scripts/local_llm/logs/r5_reason_<ts>.log
set -u

WS="/home/dleighsystems/Desktop/NAIL institute"
cd "$WS" || exit 1
mkdir -p scripts/local_llm/logs
LOG="scripts/local_llm/logs/r5_reason_$(date +%Y%m%d_%H%M%S).log"
exec >> "$LOG" 2>&1
step() { echo; echo "════════ $* ════════"; date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# ── 0. Build datasets ─────────────────────────────────────────────────
step "BUILD reason redteam SFT (VERDICT schema, ~100 samples)"
python scripts/local_llm/build_reason_redteam_sft.py || exit 1

step "BUILD reason concise-DPO pairs"
python scripts/local_llm/build_reason_concise_dpo.py || exit 1

# ── 1. Wipe stale 32B checkpoints (we're switching base to 14B) ──────
step "WIPE stale reason checkpoints"
rm -rf scripts/local_llm/checkpoints/reason/sft \
       scripts/local_llm/checkpoints/reason/dpo \
       scripts/local_llm/checkpoints/reason/grpo \
       scripts/local_llm/exports/reason/merged_16bit \
       scripts/local_llm/exports/reason/nail-reason-f16.gguf \
       scripts/local_llm/exports/reason/nail-reason-Q4_K_M.gguf
echo "  cleared."

# ── 2. SFT (4 epochs on Qwen2.5-14B) ─────────────────────────────────
step "SFT reason (Qwen2.5-14B base, 4 epochs)"
python scripts/local_llm/train.py --model reason --stage sft || exit 1

if [ ! -d "scripts/local_llm/checkpoints/reason/sft/final" ]; then
    echo "ERROR: reason SFT final missing"; exit 1
fi

# ── 3. DPO (concise verdict preference, 2 epochs) ────────────────────
step "DPO reason (concise + correct verdict, 2 epochs)"
python scripts/local_llm/train.py --model reason --stage dpo || exit 1

if [ ! -d "scripts/local_llm/checkpoints/reason/dpo/final" ]; then
    echo "ERROR: reason DPO final missing"; exit 1
fi

# ── 4. Export reason:v5 (Q4_K_M) ─────────────────────────────────────
step "EXPORT reason:v5 (Q4_K_M)"
python scripts/local_llm/export_ollama.py --model reason --tag v5 || exit 1

# ── 5. Certify ───────────────────────────────────────────────────────
step "CERTIFY reason:v5"
python scripts/local_llm/certify_ollama.py --model reason --tag v5 || true

step "DONE — latest reason cert"
ls -lt scripts/local_llm/certifications/cert_reason_v5_*.json 2>/dev/null | head -1
echo "── tail of log ──"
ls -lt scripts/local_llm/certifications/cert_reason_v5_*.json 2>/dev/null | head -1 | awk '{print $NF}' \
    | xargs -I{} python3 -c "import json; d=json.load(open('{}')); print('certified=', d.get('certified')); [print(c['check'], c['actual'], c['operator'], c['threshold'], 'PASS' if c['passed'] else 'FAIL') for c in d.get('checks', [])]"
