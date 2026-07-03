#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# run_all_tests.sh — Full regression suite for NAIL Institute
#
# Runs each package's tests from its own directory to avoid
# Python namespace package collisions.
# ═══════════════════════════════════════════════════════════════════

set -e

BASE="$(cd "$(dirname "$0")" && pwd)"
TOTAL=0
FAILED=0

LOCAL_PACKAGE_PATHS=(
    "$BASE"
    "$BASE/rmap"
    "$BASE/ave"
    "$BASE/canary"
    "$BASE/arena"
    "$BASE/ctf"
    "$BASE/diagnostic"
    "$BASE/horizon"
    "$BASE/integration"
    "$BASE/threatfeed"
    "$BASE/nail_monitor"
    "$BASE/fleet"
    "$BASE/shield"
    "$BASE/nail_harness"
    "$BASE/compliance"
)
LOCAL_PYTHONPATH="$(IFS=:; echo "${LOCAL_PACKAGE_PATHS[*]}")"
export PYTHONPATH="${LOCAL_PYTHONPATH}${PYTHONPATH:+:$PYTHONPATH}"

run_suite() {
    local pkg=$1
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Testing: $pkg"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if cd "$BASE/$pkg" && python -m pytest tests/ --tb=short -q 2>&1; then
        echo "  ✅ $pkg: PASSED"
    else
        echo "  ❌ $pkg: FAILED"
        FAILED=$((FAILED + 1))
    fi
    TOTAL=$((TOTAL + 1))
    echo
}

echo "═══════════════════════════════════════════════════════════════"
echo "  NAIL Institute — Full Regression Suite"
echo "═══════════════════════════════════════════════════════════════"
echo

run_suite "rmap"
run_suite "ave"
run_suite "canary"
run_suite "arena"
run_suite "ctf"
run_suite "diagnostic"
run_suite "horizon"
run_suite "integration"
run_suite "threatfeed"
run_suite "nail_monitor"
run_suite "fleet"
run_suite "shield"
run_suite "nail_security"
run_suite "nail_harness"
run_suite "compliance"
run_suite "scripts"

echo "═══════════════════════════════════════════════════════════════"
if [ $FAILED -eq 0 ]; then
    echo "  ALL $TOTAL SUITES PASSED ✅"
else
    echo "  $FAILED of $TOTAL SUITES FAILED ❌"
fi
echo "═══════════════════════════════════════════════════════════════"

exit $FAILED
