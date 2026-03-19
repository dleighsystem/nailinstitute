# Contributing to the AVE Database

Thank you for helping make agentic AI safer. The AVE (Agentic Vulnerabilities & Exposures) Database is the world's first structured catalogue of AI agent failure modes, modelled after the CVE system but purpose-built for autonomous agents.

**Anyone can contribute.** Security researchers, AI engineers, academics, red teamers, and practitioners who encounter unexpected agent behaviour — your field observations are exactly what makes this database valuable.

---

## Table of Contents

- [What Belongs in the AVE Database](#what-belongs-in-the-ave-database)
- [What Does NOT Belong](#what-does-not-belong)
- [How to Submit](#how-to-submit)
- [AVE Card Schema](#ave-card-schema)
- [Evidence Standards](#evidence-standards)
- [Review Process](#review-process)
- [AVE ID Assignment](#ave-id-assignment)
- [Severity Guidelines](#severity-guidelines)
- [Category Taxonomy](#category-taxonomy)
- [Licensing](#licensing)
- [Recognition](#recognition)

---

## What Belongs in the AVE Database

An AVE card documents a **repeatable failure mode, vulnerability, or emergent pathology** in AI agent systems. Good submissions include:

| Type | Example |
|------|---------|
| **Behavioural failure** | Agents deadlock in consensus loops (AVE-2025-0002) |
| **Attack vector** | Injecting false facts into shared memory (AVE-2025-0001) |
| **Resource exploitation** | Token embezzlement / EDoS attacks (AVE-2025-0003) |
| **Alignment failure** | Sycophantic collapse under pressure (AVE-2025-0012) |
| **Tool-chain exploit** | MCP tool registration poisoning (AVE-2025-0014) |
| **Emergent behaviour** | Novel pathologies not fitting existing categories |

### Key Criteria

1. **Agentic** — The vulnerability specifically affects autonomous AI agents (single or multi-agent), not traditional ML model accuracy issues.
2. **Repeatable** — Can be reproduced by others with access to similar infrastructure.
3. **Documented** — Has at minimum a clear description of the mechanism, even if a full PoC isn't available yet.

---

## What Does NOT Belong

- **Traditional ML attacks** (adversarial examples on image classifiers, model inversion)
- **General software bugs** (a framework has a Python crash — that's a GitHub Issue for that framework)
- **Prompt injection against single-turn chatbots** (unless it specifically exploits agentic capabilities like tool use, memory, or delegation)
- **Purely theoretical speculation** with no mechanism described (philosophical concerns about AGI without actionable details)

---

## How to Submit

### Option 1: GitHub Issue (Easiest)

1. Go to [**New Issue → AVE Card Submission**](https://github.com/dleighsystem/nailinstitute/issues/new?template=ave-submission.yml)
2. Fill in the structured form
3. The NAIL team will triage, assign an AVE ID, and create the formal card

### Option 2: Pull Request (For Experienced Contributors)

1. Fork the repository
2. Generate a card skeleton:
   ```bash
   python -m ave submit --name "Your Vulnerability Name" --category memory --severity high
   ```
   This creates `ave-database/cards/AVE-DRAFT-XXXX.json` and `.md` files.
3. Fill in the generated files with your data
4. Validate:
   ```bash
   python -m ave validate ave-database/cards/AVE-DRAFT-XXXX.json
   ```
5. Submit a PR using the [pull request template](/.github/PULL_REQUEST_TEMPLATE.md)

### Option 3: Private Disclosure (For Severe Findings)

If your finding could be directly weaponized against production systems:

1. Use the [**Private Disclosure**](https://github.com/dleighsystem/nailinstitute/issues/new?template=private-disclosure.yml) issue template, OR
2. Email **security@nailinstitute.org** directly

See [SECURITY.md](./SECURITY.md) for our responsible disclosure policy.

---

## AVE Card Schema

Every AVE card has the following structure. Fields marked with `*` are required.

### Identity

| Field | Type | Description |
|-------|------|-------------|
| `ave_id` * | string | Assigned by NAIL (e.g., `AVE-2025-0037`). Use `AVE-DRAFT-XXXX` in PRs. |
| `name` * | string | Descriptive vulnerability name |
| `aliases` | string[] | Other names in literature or community |

### Classification

| Field | Type | Description |
|-------|------|-------------|
| `category` * | enum | Attack surface — see [Category Taxonomy](#category-taxonomy) |
| `severity` * | enum | `critical`, `high`, `medium`, `low`, `info` |
| `status` * | enum | `theoretical`, `proven`, `proven_mitigated`, `not_proven`, `in_progress` |

### Description

| Field | Type | Description |
|-------|------|-------------|
| `summary` * | string | One-paragraph description |
| `mechanism` * | string | Step-by-step explanation of how it works |
| `blast_radius` * | string | What breaks when this fires |
| `prerequisite` * | string | Conditions required to trigger |

### Environment Vector

| Field | Type | Description |
|-------|------|-------------|
| `frameworks` | string[] | e.g., `["LangGraph", "CrewAI", "AutoGen"]` |
| `models_tested` | string[] | e.g., `["nemotron:70b", "gpt-4o"]` |
| `multi_agent` | bool | Requires multi-agent setup? |
| `tools_required` | bool | Requires tool/function calling? |
| `memory_required` | bool | Requires shared/persistent memory? |

### Evidence

| Field | Type | Description |
|-------|------|-------------|
| `experiment_id` | string | Identifier for the reproduction experiment |
| `data_file` | string | Path to raw data (JSON logs, etc.) |
| `key_metric` | string | What was measured |
| `key_value` | string | The result |
| `p_value` | float | Statistical significance (if applicable) |
| `sample_size` | int | Number of trials |
| `cross_model` | bool | Validated across multiple models? |

### Defences

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Defence technique name |
| `layer` | string | Which architectural layer |
| `effectiveness` | string | Measured reduction in impact |
| `notes` | string | Additional context |

### Metadata

| Field | Type | Description |
|-------|------|-------------|
| `date_discovered` | string | When first observed (YYYY-MM) |
| `cwe_mapping` | string | Nearest traditional CWE |
| `mitre_mapping` | string | Nearest MITRE ATT&CK technique |
| `references` | string[] | URLs, paper citations |
| `related_aves` | string[] | Cross-referenced AVE IDs |

---

## Evidence Standards

We use a tiered evidence system:

| Status | Required Evidence | Example |
|--------|-------------------|---------|
| `theoretical` | Mechanism description + plausible attack path | "If an agent stores user input without sanitisation..." |
| `in_progress` | Initial reproduction attempt in progress | Partial logs, preliminary results |
| `proven` | Reproducible PoC with logs/scripts | Python script + JSON log showing the failure |
| `proven_mitigated` | Proven + documented defence that reduces impact | PoC + mitigation code + before/after metrics |
| `not_proven` | Tested but could not reproduce | Negative result with methodology documented |

**Minimum for acceptance:** `theoretical` with a clear, actionable mechanism description.

**Gold standard:** A self-contained reproduction script, JSON log output, and tested defence.

---

## Review Process

1. **Triage (48h)** — NAIL team confirms the submission is in scope and assigns a reviewer
2. **Validation (1–2 weeks)** — Reviewer attempts reproduction or evaluates the mechanism
3. **Assignment** — Valid submissions receive a permanent `AVE-YYYY-NNNN` identifier
4. **Publication** — Card is merged into `ave-database/cards/` with full attribution

### What Reviewers Check

- [ ] Is this an agentic vulnerability (not a traditional software bug)?
- [ ] Is the mechanism clearly described?
- [ ] Can this be reproduced or is the theoretical path plausible?
- [ ] Does the category assignment make sense?
- [ ] Is the severity rating appropriate?
- [ ] Are there any related existing AVE cards?

---

## AVE ID Assignment

- **Draft IDs** (`AVE-DRAFT-XXXX`) — Used in PRs before review
- **Permanent IDs** (`AVE-YYYY-NNNN`) — Assigned by NAIL team after validation
  - `YYYY` = year of discovery
  - `NNNN` = sequential number within that year
- IDs are **never reused** once assigned, even if a card is later marked `not_proven`

---

## Severity Guidelines

| Severity | Criteria | Production Impact |
|----------|----------|-------------------|
| 🔴 **critical** | Immediate data loss, exfiltration, safety failure, or system compromise | Requires emergency response |
| 🟠 **high** | Significant operational impact, reliably exploitable | Affects availability, integrity, or confidentiality |
| 🟡 **medium** | Degrades performance or requires specific conditions | Noticeable but not catastrophic |
| 🟢 **low** | Minor impact, edge case, or mitigated by default | Negligible in most deployments |
| ℹ️ **info** | Theoretical or observational, not yet validated | Research interest only |

---

## Category Taxonomy

| Category | Code | Scope |
|----------|------|-------|
| Memory | `memory` | Memory pollution, laundering, poisoning, RAG corruption |
| Consensus | `consensus` | Deadlock, paralysis, voting manipulation |
| Injection | `injection` | Prompt injection, indirect injection, cross-context |
| Resource | `resource` | Token embezzlement, EDoS, compute exhaustion |
| Drift | `drift` | Persona drift, language drift, goal drift |
| Alignment | `alignment` | Sycophancy, deceptive alignment, reward hacking |
| Social | `social` | Collusion, bystander effect, social loafing |
| Tool | `tool` | Confused deputy, tool chain exploit, MCP poisoning |
| Temporal | `temporal` | Time bombs, sleeper agents, chronological desync |
| Structural | `structural` | Cascade failure, routing deadlock, livelock |
| Credential | `credential` | Secret exfiltration, key harvesting |
| Delegation | `delegation` | Shadow delegation, privilege escalation |
| Fabrication | `fabrication` | Hallucination weaponisation, data fabrication |
| Emergent | `emergent` | Novel behaviours not fitting above categories |

**Proposing a new category?** Open a [Discussion](https://github.com/dleighsystem/nailinstitute/discussions) with your rationale. Categories are added when 3+ cards justify a new cluster.

---

## Licensing

All AVE Database content is licensed under [**CC-BY-SA-4.0**](https://creativecommons.org/licenses/by-sa/4.0/).

This means:
- ✅ Anyone can use, share, and adapt the vulnerability data
- ✅ Commercial use is permitted
- 📎 Attribution to the AVE Database and original contributor is required
- 🔄 Derivative works must use the same license

The NAIL platform **source code** (Python packages) is separately licensed — see the root LICENSE file.

---

## 🏆 Recognition & Gamification

We believe contributions to agentic AI safety should be **visible, rewarding, and fun**.
Every accepted card earns you XP, unlocks badges, and climbs the leaderboard.

### ⚡ Experience Points (XP)

Every AVE card earns XP based on severity, evidence quality, and impact:

| Severity | Base XP | | Bonus | XP |
|----------|--------:|-|-------|---:|
| 🔴 Critical | 500 | | First card ever | +200 |
| 🟠 High | 300 | | Evidence with data | +50 (each) |
| 🟡 Medium | 150 | | Proof of Concept | +100 |
| 🟢 Low | 75 | | Defence/mitigation | +75 |
| ℹ️ Info | 50 | | Cross-references | +25 |
|  |  | | Novel discovery | +150 |
|  |  | | First in new category | +300 |

Cards with `proven_mitigated` status earn a **1.2× multiplier** — you found it AND helped fix it.

### 🎖️ Tier System

| Icon | Tier | XP Required | Perks |
|------|------|-------------|-------|
| 👁️ | **WATCHER** | 0+ | Joined the hunt |
| 🏹 | **HUNTER** | 500+ | Proven contributor — listed in Hall of Fame |
| 🛡️ | **SENTINEL** | 1,500+ | Trusted researcher — fast-track review |
| 🏗️ | **ARCHITECT** | 4,000+ | Shaping the taxonomy — invited to review PRs |
| ⭐ | **FELLOW** | 8,000+ | NAIL Research Fellow — named in publications |

### 🏅 Badges

Unlock achievements for specific milestones:

| Badge | How to Earn | Rarity |
|-------|-------------|--------|
| 🩸 First Blood | Submit your first AVE card | Common |
| 🖐️ Five Alive | 5 accepted cards | Uncommon |
| 🎯 Ten Ring | 10 accepted cards | Rare |
| 🔴 Critical Finder | Find a CRITICAL vulnerability | Uncommon |
| 💀 Critical Hunter | Find 3+ CRITICAL vulnerabilities | Rare |
| 📊 Show Your Work | Submit with empirical evidence | Common |
| 🛡️ Shield Bearer | Submit with a known defence | Common |
| 🗺️ Category Pioneer | First card in a new category | Rare |
| 🎓 Polymath | Cards across 5+ categories | Rare |
| 💡 Novel Discovery | Report an undocumented vulnerability | Uncommon |
| 🎩 Hat Trick | 3 months consecutive submissions | Uncommon |
| 🏆 Year of Living Dangerously | 12 months consecutive | Legendary |
| ⭐ NAIL Research Fellow | Achieve Fellow tier | Legendary |

See the full catalog: `python -m ave badges`

### 📊 Track Your Progress

```bash
python -m ave leaderboard           # See the rankings
python -m ave profile "Your Handle"  # View your full profile
python -m ave badges                 # Browse all earnable badges
python -m ave hall-of-fame           # Generate HALL_OF_FAME.md
```

See the live [**Hall of Fame**](./HALL_OF_FAME.md) for current standings.

---

*Questions? Open a [Discussion](https://github.com/dleighsystem/nailinstitute/discussions) or email contribute@nailinstitute.org.*
