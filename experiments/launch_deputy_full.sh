#!/bin/bash
# NAIL Institute — Full Confused Deputy Study Launcher
# Run this from the terminal where API keys are set

set -e
cd "/home/dleighsystems/Desktop/NAIL institute/experiments"

echo ""
echo "  ╔═══════════════════════════════════════════════════════════╗"
echo "  ║  CONFUSED DEPUTY — FULL 30-TRIAL STUDY                  ║"
echo "  ╚═══════════════════════════════════════════════════════════╝"
echo ""

# Check keys
for KEY in ANTHROPIC_API_KEY GOOGLE_API_KEY KIMI_API_KEY; do
    VAL=$(eval echo \$$KEY)
    if [ -z "$VAL" ]; then
        echo "  ⚠️  $KEY is NOT SET (will skip this model)"
    else
        echo "  ✅ $KEY is set"
    fi
done

echo ""
echo "  Estimated time: ~60–90 minutes"
echo "  Results will be saved to: data/deputy_full_results.json"
echo ""

# Clear pycache to ensure latest code
find . -name "__pycache__" -path "*/cross_model_study/*" -exec rm -rf {} + 2>/dev/null
find . -name "__pycache__" -path "*/shared/*" -exec rm -rf {} + 2>/dev/null

nohup python3 -m cross_model_study.deputy_full > data/deputy_full_log.txt 2>&1 &
echo "  📡 Running in background (PID: $!)"
echo "  📄 Log: data/deputy_full_log.txt"
echo ""
echo "  Monitor: tail -f data/deputy_full_log.txt"
echo "  Check:   grep 'exploited' data/deputy_full_log.txt | tail"
