# 📋 DEBT.md — Technical Debt Tracker

> Honest ledger of every known gap between what the project claims and
> what's actually working. Created 2026-03-30 in response to external
> code review. Updated as items are resolved.

---

## Status Key

| Emoji | Meaning |
|-------|---------|
| 🔴 | Not started — claim exists, code doesn't |
| 🟡 | Partial — code exists but untested / not wired |
| 🟢 | Resolved — code matches docs |

---

## 1. Documentation ↔ Code Drift

### public-repo/ README.md (FIXED 2026-03-30)

| Item | Was | Now | Status |
|------|-----|-----|--------|
| "155 services" badge | Claimed 155 production services | 12 production + 117 blueprints | 🟢 |
| "31/31 phases complete" | Implied all phases running | "31 designed · 10 production-tested" | 🟢 |
| At a Glance table | No distinction scaffold vs real | Separate rows for packages vs blueprints | 🟢 |
| Platform section | "155 Services" heading | Split into Production Packages + Blueprints | 🟢 |

### Remaining README Drift

| Item | File | Issue | Status |
|------|------|-------|--------|
| "All 50 vulnerability cards" | public-repo/README.md Quick Start | Says 50 but index claims 100 | 🔴 |
| Docker Compose phase files | README | Claims all phases have compose files; needs verification each service actually starts | 🟡 |
| Vendor integration SDKs | vendor-integrations/ | Has code but no tests | 🟡 |
| Academic courses content | academic/courses/ | Markdown outlines exist, no actual course materials (slides, labs) | 🟡 |

---

## 2. Service Blueprints (117 single-file services)

These are the 108 single-file + 9 multi-file services in `public-repo/` that
have **no tests and no pyproject.toml**. They contain real FastAPI endpoint
logic but have never been integration-tested.

**Action items:**

| Priority | Task | Status |
|----------|------|--------|
| P1 | Add `pyproject.toml` to each multi-file service (9 total) | 🔴 |
| P2 | Write smoke test for each: start → health check → shutdown | 🔴 |
| P2 | Verify all Docker Compose files actually boot cleanly | 🔴 |
| P3 | Add type hints to all single-file services | 🔴 |
| P3 | Lint all services with ruff / mypy | 🔴 |

---

## 3. Production Packages — Missing Coverage

| Package | Lines | Tests | Gap | Status |
|---------|------:|:-----:|-----|--------|
| **ave** | 8,040 | 4 | Needs scoring edge-case tests, export round-trip | 🟡 |
| **nail_monitor** | 4,701 | 1 | Only 1 test file for 20 detectors — needs per-detector tests | 🔴 |
| **integration** | 6,019 | 7 | Reasonable, but needs cross-package integration tests | 🟡 |
| **canary** | 4,424 | 3 | Missing deployment smoke tests | 🟡 |
| **arena** | 4,268 | 3 | Missing swarm + collider tests | 🟡 |
| **ctf** | 3,482 | 2 | Missing multi-player scenario tests | 🟡 |
| **threatfeed** | 2,857 | 2 | Missing feed ingestion tests | 🟡 |
| **rmap** | 2,506 | 5 | Best coverage — model for others | 🟢 |
| **horizon** | 2,086 | 1 | Missing campaign orchestration tests | 🔴 |
| **dese** | 1,950 | 1 | Missing entropy validation (NIST SP 800-22) tests | 🔴 |
| **diagnostic** | 1,950 | 1 | Missing extractor tests | 🔴 |
| **nail_harness** | ~500 | 0 | No tests at all; no `__all__` export | 🔴 |

---

## 4. Infrastructure Gaps

| Item | Status | Notes |
|------|--------|-------|
| CI only covers AVE card validation | 🔴 | No import check, no package tests in CI |
| No pre-commit hooks | 🔴 | Docs can outpace code without guard |
| nail_harness missing `__all__` | 🔴 | Only package without explicit exports |
| No type stubs for cross-package boundaries | 🔴 | Implicit contracts only |
| Monorepo → 3-repo split not planned | 🟡 | Plan documented, not executed |

---

## 5. Cross-Cutting Issues

| Issue | Impact | Priority |
|-------|--------|----------|
| 108 single-file services have no import guards | Services crash on missing deps instead of graceful degradation | P2 |
| No dependency lockfile (no `poetry.lock` / `pip freeze`) | Builds not reproducible | P2 |
| Log files committed to repo (exp*.log) | Bloats clone, leaks experiment data | P1 |
| `.env` file committed | Potential credential leak | P1 |
| `nohup.out` in experiments/ | Leftover process output | P3 |

---

## Resolution Log

| Date | Item | Resolution |
|------|------|------------|
| 2026-03-30 | README "155 services" overclaim | Split into 12 production + 117 blueprints |
| 2026-03-30 | README "31/31 complete" overclaim | Changed to "31 designed · 10 production-tested" |
| 2026-03-30 | DEBT.md created | This file |
| 2026-03-30 | CI import check workflow | Added `.github/workflows/import-check.yml` |
| 2026-03-30 | Pre-commit hook | Added `scripts/check-docs-sync.sh` |
| 2026-03-30 | nail_harness `__all__` | Added to `__init__.py` |
| 2026-03-30 | 3-repo split plan | Documented in SPLIT_PLAN.md |
