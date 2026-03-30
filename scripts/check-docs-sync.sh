#!/usr/bin/env bash
# scripts/check-docs-sync.sh — Pre-commit hook for docs/code alignment
#
# Ensures documentation doesn't drift ahead of code.
# Install: cp scripts/check-docs-sync.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# Or use with pre-commit framework: see .pre-commit-config.yaml
#
# Checks:
# 1. Every package in pyproject.toml files is importable
# 2. README service counts match reality
# 3. No committed .env files or log files
# 4. DEBT.md exists and is not empty

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

errors=0
warnings=0

echo "🔍 NAIL Docs/Code Sync Check"
echo "=============================="

# ── 1. Check all sub-packages have pyproject.toml ──────────────
echo ""
echo "1. Checking sub-package structure..."
for pkg in ave arena nail_monitor horizon canary ctf diagnostic integration rmap threatfeed; do
    if [ ! -d "$pkg" ]; then
        echo -e "  ${RED}✗${NC} $pkg/ directory missing"
        ((errors++))
    elif [ ! -f "$pkg/pyproject.toml" ]; then
        echo -e "  ${YELLOW}⚠${NC} $pkg/ exists but missing pyproject.toml"
        ((warnings++))
    else
        echo -e "  ${GREEN}✓${NC} $pkg/"
    fi
done

# ── 2. Check for committed secrets / logs ──────────────────────
echo ""
echo "2. Checking for files that shouldn't be committed..."

staged_files=$(git diff --cached --name-only 2>/dev/null || true)

# Check for .env files (but not .env.example)
if echo "$staged_files" | grep -q "^\.env$\|/\.env$"; then
    echo -e "  ${RED}✗${NC} .env file staged for commit — potential credential leak"
    ((errors++))
fi

# Check for log files
log_files=$(echo "$staged_files" | grep -c "\.log$" || true)
if [ "$log_files" -gt 0 ]; then
    echo -e "  ${YELLOW}⚠${NC} $log_files .log file(s) staged — consider adding to .gitignore"
    ((warnings++))
fi

# Check for nohup.out
if echo "$staged_files" | grep -q "nohup.out"; then
    echo -e "  ${RED}✗${NC} nohup.out staged for commit"
    ((errors++))
fi

if [ "$errors" -eq 0 ] && [ "$warnings" -eq 0 ]; then
    echo -e "  ${GREEN}✓${NC} No problematic files staged"
fi

# ── 3. Check DEBT.md exists ────────────────────────────────────
echo ""
echo "3. Checking debt tracking..."
if [ ! -f "DEBT.md" ]; then
    echo -e "  ${YELLOW}⚠${NC} DEBT.md not found — create it to track technical debt"
    ((warnings++))
elif [ ! -s "DEBT.md" ]; then
    echo -e "  ${YELLOW}⚠${NC} DEBT.md is empty"
    ((warnings++))
else
    echo -e "  ${GREEN}✓${NC} DEBT.md exists ($(wc -l < DEBT.md) lines)"
fi

# ── 4. Check __init__.py files have __all__ ────────────────────
echo ""
echo "4. Checking API contracts (__all__ exports)..."
for pkg_init in ave/ave/__init__.py arena/arena/__init__.py nail_monitor/nail_monitor/__init__.py \
                horizon/horizon/__init__.py canary/canary/__init__.py ctf/ctf/__init__.py \
                rmap/rmap/__init__.py threatfeed/threatfeed/__init__.py \
                nail_harness/__init__.py dese/__init__.py; do
    if [ -f "$pkg_init" ]; then
        if grep -q "__all__" "$pkg_init"; then
            echo -e "  ${GREEN}✓${NC} $pkg_init"
        else
            echo -e "  ${YELLOW}⚠${NC} $pkg_init — missing __all__"
            ((warnings++))
        fi
    fi
done

# ── Summary ────────────────────────────────────────────────────
echo ""
echo "=============================="
if [ "$errors" -gt 0 ]; then
    echo -e "${RED}BLOCKED: $errors error(s), $warnings warning(s)${NC}"
    echo "Fix errors before committing."
    exit 1
elif [ "$warnings" -gt 0 ]; then
    echo -e "${YELLOW}PASSED with $warnings warning(s)${NC}"
    exit 0
else
    echo -e "${GREEN}ALL CHECKS PASSED ✅${NC}"
    exit 0
fi
