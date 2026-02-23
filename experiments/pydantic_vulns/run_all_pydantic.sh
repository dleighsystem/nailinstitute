#!/usr/bin/env bash
# Run all 5 Pydantic vulnerability tests
# These are SEQUENTIAL (they share Ollama), not truly parallel processes.
# But V1 and V5 are fast (few LLM calls), V2 is medium, V3 and V4 are longer.

set +e   # Don't exit on error — we handle failures per-test
cd "$(dirname "$0")/.."

PYTHON="/home/dleighsystems/miniconda3/envs/nail_experiments/bin/python"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo "========================================="
echo "  PYDANTIC VULNERABILITY TEST SUITE"
echo "  $(date)"
echo "========================================="
echo ""

TESTS=(
    "pydantic_vulns/v1_procrustean_bed.py|V1: Procrustean Bed (Schema Coercion)"
    "pydantic_vulns/v5_type_coercion.py|V5: Type Coercion Masking"
    "pydantic_vulns/v2_pydantic_purgatory.py|V2: Pydantic Purgatory (Validation Loop)"
    "pydantic_vulns/v4_conditional_deadlock.py|V4: Conditional Edge Deadlock"
    "pydantic_vulns/v3_state_asphyxiation.py|V3: State Asphyxiation"
)

PASS=0
FAIL=0

for entry in "${TESTS[@]}"; do
    IFS='|' read -r script name <<< "$entry"
    echo "▶ Running $name"
    echo "  Script: $script"
    
    logfile="$LOG_DIR/pydantic_$(basename "$script" .py).log"
    
    if $PYTHON "$script" 2>&1 | tee "$logfile"; then
        echo "  ✅ $name COMPLETE"
        PASS=$((PASS + 1))
    else
        echo "  ❌ $name FAILED"
        FAIL=$((FAIL + 1))
    fi
    echo ""
done

echo "========================================="
echo "  PYDANTIC SUITE COMPLETE"
echo "  Passed: $PASS  Failed: $FAIL"
echo "  $(date)"
echo "========================================="
