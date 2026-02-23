#!/bin/bash
# NAIL Institute — Experiment Auto-Chain
# ========================================
# Waits for Exp5 to finish, then runs remaining experiments sequentially.
# Usage: nohup bash run_chain.sh > logs/chain_console.log 2>&1 &

set -e
PYTHON="/home/dleighsystems/miniconda3/envs/nail_experiments/bin/python"
EXPDIR="/home/dleighsystems/Desktop/NAIL institute/experiments"
cd "$EXPDIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Wait for Exp5 (PID 1517951) to finish
EXP5_PID=1517951
if kill -0 $EXP5_PID 2>/dev/null; then
    log "⏳ Waiting for Exp5 (PID $EXP5_PID) to finish..."
    while kill -0 $EXP5_PID 2>/dev/null; do
        sleep 30
    done
    log "✅ Exp5 finished!"
else
    log "✅ Exp5 already finished."
fi

# Run remaining 7B experiments in order (fastest first)
EXPERIMENTS=(8 2 3 1 6)
NAMES=("Learned Helplessness" "Consensus Paralysis" "Token Embezzlement" "Memory Pollution" "Language Drift")

for i in "${!EXPERIMENTS[@]}"; do
    exp=${EXPERIMENTS[$i]}
    name=${NAMES[$i]}
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "▶ Starting Experiment $exp: $name"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    $PYTHON run_all.py --exp $exp --skip-prereq 2>&1 | tee "logs/exp${exp}_console.log"
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        log "✅ Experiment $exp completed successfully!"
    else
        log "❌ Experiment $exp failed with exit code $EXIT_CODE"
        log "   Continuing to next experiment..."
    fi

    # Brief cooldown between experiments
    log "⏳ 30s cooldown..."
    sleep 30
done

# Now run 70B versions of Exp4 and Exp7
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "▶ Starting 70B model comparison runs"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

export NAIL_FAST_MODEL="nemotron:70b"

log "▶ Exp4 (Prompt Inbreeding) — 70B"
$PYTHON run_all.py --exp 4 --skip-prereq 2>&1 | tee logs/exp4_70b_console.log
log "✅ Exp4 70B complete!"
sleep 30

log "▶ Exp7 (Goodhart's Cartel) — 70B"
$PYTHON run_all.py --exp 7 --skip-prereq 2>&1 | tee logs/exp7_70b_console.log
log "✅ Exp7 70B complete!"
sleep 30

# Reset model back to 7B for CrewAI runs
export NAIL_FAST_MODEL="mistral:7b-instruct"

log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "▶ Starting CrewAI framework comparison runs"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

log "▶ CrewAI Exp4 (Prompt Inbreeding)"
$PYTHON -m crewai_versions.crewai_exp4_inbreeding 2>&1 | tee logs/crewai_exp4_console.log
log "✅ CrewAI Exp4 complete!"
sleep 30

log "▶ CrewAI Exp7 (Goodhart's Cartel)"
$PYTHON -m crewai_versions.crewai_exp7_cartel 2>&1 | tee logs/crewai_exp7_console.log
log "✅ CrewAI Exp7 complete!"
sleep 30

log "▶ CrewAI Exp5 (CYA Cascade)"
$PYTHON -m crewai_versions.crewai_exp5_cya 2>&1 | tee logs/crewai_exp5_console.log
log "✅ CrewAI Exp5 complete!"

log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "🎉 ALL EXPERIMENTS COMPLETE!"
log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Results in: $EXPDIR/data/"
log "Logs in:    $EXPDIR/logs/"
