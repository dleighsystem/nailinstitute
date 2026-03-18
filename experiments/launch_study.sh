#!/bin/bash
# NAIL Institute — Cross-Model Validation Launcher
# Run this from the terminal where API keys are set

set -e

cd "/home/dleighsystems/Desktop/NAIL institute/experiments"

echo ""
echo "  ╔═══════════════════════════════════════════════════════════╗"
echo "  ║  NAIL CROSS-MODEL VALIDATION — KEY CHECK                ║"
echo "  ╚═══════════════════════════════════════════════════════════╝"
echo ""

# Check keys
READY=true
for KEY in ANTHROPIC_API_KEY GOOGLE_API_KEY KIMI_API_KEY; do
    VAL=$(eval echo \$$KEY)
    if [ -z "$VAL" ]; then
        echo "  ❌ $KEY is NOT SET"
        READY=false
    else
        echo "  ✅ $KEY is set (${#VAL} chars)"
    fi
done

echo ""

if [ "$READY" = false ]; then
    echo "  ⚠️  Some keys are missing. Set them with:"
    echo '    export ANTHROPIC_API_KEY="your-key"'
    echo '    export GOOGLE_API_KEY="your-key"'
    echo '    export KIMI_API_KEY="your-key"'
    exit 1
fi

# Run mode
MODE="${1:-pilot}"

if [ "$MODE" = "pilot" ]; then
    echo "  🔬 PILOT MODE — 3 trials per model (quick connectivity test)"
    echo "  Models: Ollama (nemotron:70b), Anthropic, Google, Kimi"
    echo ""
    python3 -m cross_model_study.run --pilot --models ollama,anthropic,google,kimi 2>&1 | tee "/home/dleighsystems/Desktop/NAIL institute/experiments/data/cross_model_pilot_log.txt"
elif [ "$MODE" = "full" ]; then
    echo "  🧬 FULL STUDY — 30 trials per model (publication-grade)"
    echo "  Models: Ollama (nemotron:70b), Anthropic, Google, Kimi"
    echo ""
    nohup python3 -m cross_model_study.run --models ollama,anthropic,google,kimi > "/home/dleighsystems/Desktop/NAIL institute/experiments/data/cross_model_full_log.txt" 2>&1 &
    echo "  📡 Running in background (PID: $!)"
    echo "  📄 Log: /home/dleighsystems/Desktop/NAIL institute/experiments/data/cross_model_full_log.txt"
    echo "  Check progress: tail -f '/home/dleighsystems/Desktop/NAIL institute/experiments/data/cross_model_full_log.txt'"
else
    echo "  Usage: bash launch_study.sh [pilot|full]"
fi
