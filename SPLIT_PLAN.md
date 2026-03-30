# 🔀 SPLIT_PLAN.md — Monorepo → 3 Repositories

> Plan for extracting the NAIL Institute monorepo into three focused
> repositories, as recommended by external code review (2026-03-30).
>
> Status: **PLANNING** — not yet executed.

---

## Why Split?

1. **Cognitive load** — New contributors face 120+ directories. Three focused
   repos are each understandable in an afternoon.
2. **Composability** — If we consume our own public API, it will be polished
   when others try to use it.
3. **CI speed** — Running all tests takes too long. Scoped repos get fast,
   focused CI.
4. **Versioning** — AVE schema changes shouldn't require a new release of
   the detection engine.

---

## The Three Repos

### Repo 1: `ave-database` (The Catalogue)

> The MITRE ATT&CK equivalent — vulnerability data, schema, scoring, CLI.

| Current Location | Goes Here |
|------------------|-----------|
| `ave/` | `ave/` (core package) |
| `ave-database/` | `ave-database/` (card data) |
| `dese/` | `dese/` (entropy engine, used in AVE scoring) |
| `public-repo/ave/` | Merge into `ave/` |
| `public-repo/ave-database/` | Merge into `ave-database/` |
| `public-repo/schema-v2/` | `schema/v2/` |
| `public-repo/schema-v3/` | `schema/v3/` |
| `.github/workflows/ave-validate.yml` | `.github/workflows/validate.yml` |
| `.github/workflows/update-hall-of-fame.yml` | Keep |
| `HALL_OF_FAME.md` | Keep |
| `CONTRIBUTING.md` | Keep |
| `CODE_OF_CONDUCT.md` | Keep |
| `SECURITY.md` | Keep |

**Public API contract:**
```python
# What other repos import:
from ave import AVECard, Category, Severity, lookup, search, all_cards
from ave.scoring import compute_avss, AVSSVector
from ave.export import export_database
```

**PyPI package:** `nail-ave`
**License:** CC-BY-SA-4.0 (data) + Apache 2.0 (code)

---

### Repo 2: `nail-security-platform` (The Engine)

> Testing, detection, red-teaming, monitoring — the offensive + defensive
> security infrastructure.

| Current Location | Goes Here |
|------------------|-----------|
| `nail_harness/` | `harness/` (core test harness) |
| `nail_monitor/` | `monitor/` (20 pathology detectors) |
| `arena/` | `arena/` (adversarial battle arena) |
| `horizon/` | `horizon/` (scanning + campaigns) |
| `canary/` | `canary/` (deployment + smoke) |
| `ctf/` | `ctf/` (capture-the-flag) |
| `threatfeed/` | `threatfeed/` (threat intelligence) |
| `rmap/` | `rmap/` (regulatory mapping) |
| `diagnostic/` | `diagnostic/` (system diagnostics) |
| `integration/` | `integration/` (cross-package) |
| `experiments/` | `experiments/` (research data) |
| `harness-reference/` | `reference/` (Anthropic patterns) |
| `conftest.py` | Keep |
| `run_all_tests.sh` | Keep |
| `docker-compose.yml` | Keep |
| `docker-compose.canary.yml` | Keep |
| `Dockerfile` | Keep |

**Public API contract:**
```python
# What the SaaS product imports:
from nail_monitor import PathologyMonitor
from nail_monitor.detectors_v6 import (
    TokenVelocityDetector, ToolDescriptionDriftDetector, ...
)
from nail_arena import Arena
from nail_harness import NailAgentClient, MemoryManager
```

**PyPI package:** `nail-security`
**Dependency:** `nail-ave` (for AVE card references in detectors)
**License:** Apache 2.0

---

### Repo 3: `nail-publications` (The Voice)

> Research papers, ebook, press materials, public-facing scaffolds,
> academic curriculum — everything that communicates the work.

| Current Location | Goes Here |
|------------------|-----------|
| `paper/` | `paper/` |
| `ebook/` | `ebook/` (13 chapters) |
| `press/` | `press/` |
| `public-repo/academic/` | `academic/` |
| `public-repo/annual-report/` | `annual-report/` |
| `public-repo/chapters/` | `chapters/` (regional) |
| `public-repo/conference/` | `conference/` |
| `public-repo/publications/` | `publications/` |
| `public-repo/training/` | `training/` |
| `public-repo/docs/` | `docs/` (GitHub Pages) |
| All 117 service blueprints | `blueprints/` (the single-file FastAPI prototypes) |
| `public-repo/ROADMAP.md` | Keep |
| `public-repo/AWESOME.md` | Keep |

**No public API contract** — this repo is consumed by humans, not code.

**License:** CC-BY-SA-4.0

---

## Shared Dependencies

| Dependency | Used By | Strategy |
|-----------|---------|----------|
| `pydantic>=2.0` | All three | Each repo declares independently |
| `fastapi>=0.115` | Platform + Blueprints | Independent |
| `ave` package | Platform imports AVE cards | Platform declares `nail-ave` as pip dependency |
| `numpy` | Monitor detectors | Platform only |
| `pennylane` | Harness (quantum VQC) | Platform only, optional dep |

---

## Migration Steps

### Phase 1: Prepare (do before splitting)
- [x] Honest README (done 2026-03-30)
- [x] DEBT.md created (done 2026-03-30)
- [x] CI import check (done 2026-03-30)
- [x] `__all__` on all packages (done 2026-03-30)
- [ ] Ensure all cross-package imports use public API only (not internal modules)
- [ ] Remove committed `.env`, `*.log`, `nohup.out` from history
- [ ] Add `.gitignore` rules for the above

### Phase 2: Extract
- [ ] Use `git filter-repo` to extract `ave/` + `ave-database/` + `dese/` → `ave-database` repo
- [ ] Use `git filter-repo` to extract security packages → `nail-security-platform` repo
- [ ] Move publications to `nail-publications` repo
- [ ] Set up cross-repo CI (platform CI installs `nail-ave` from PyPI)

### Phase 3: Wire
- [ ] Publish `nail-ave` to PyPI
- [ ] Publish `nail-security` to PyPI
- [ ] Update Neuravant Insurance SaaS to install from PyPI instead of bundling
- [ ] Archive the monorepo with a pointer to the three new repos

---

## Decision Record

| Decision | Rationale |
|----------|-----------|
| AVE database is its own repo | It's the public face — CC-BY-SA licensed, community-contributed. Must be easy to clone and browse without the security engine. |
| Security platform is one repo (not per-package) | The 10 packages are tightly coupled through `integration/` and `conftest.py`. Splitting further would create circular deps. |
| Publications are separate | They don't need CI, don't need Python deps, and bloat the main repos. |
| Blueprints go with Publications | They're design documents, not running code. When promoted to production, they move to the Platform repo. |

---

*This plan was created 2026-03-30. Execute when bandwidth allows.*
*Estimated effort: 2-3 days for a clean extraction with history preservation.*
