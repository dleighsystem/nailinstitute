# 🛡️ AVE Database — Agentic Vulnerabilities & Exposures

[![Cards](https://img.shields.io/badge/AVE_Cards-36-blue)](./cards/)
[![License](https://img.shields.io/badge/License-CC--BY--SA--4.0-green)](https://creativecommons.org/licenses/by-sa/4.0/)
[![Validate](https://img.shields.io/badge/CI-Validated-brightgreen)](../.github/workflows/ave-validate.yml)
[![Contribute](https://img.shields.io/badge/PRs-Welcome-orange)](../CONTRIBUTING.md)

> **The MITRE ATT&CK of the Agentic Era.**
>
> The world's first structured catalogue of AI agent failure modes — behavioural
> vulnerabilities, attack vectors, and emergent pathologies affecting autonomous
> AI systems. Open to contributions from the global security research community.

---

## 🚀 Quick Start

### Browse Vulnerabilities

Every card is available as **JSON** (machine-readable) and **Markdown** (human-readable):

```
ave-database/
├── cards/
│   ├── AVE-2025-0001.json    ← Machine-readable card
│   ├── AVE-2025-0001.md      ← Human-readable companion
│   ├── AVE-2025-0002.json
│   ├── AVE-2025-0002.md
│   └── ...
├── index.json                ← Full database index
├── severity_index.json       ← Cards grouped by severity
└── README.md                 ← You are here
```

### Query via CLI

```bash
pip install -e ave/            # Install the AVE toolkit
python -m ave list             # List all cards
python -m ave show AVE-2025-0001   # Detailed view
python -m ave search -k "injection"  # Search by keyword
python -m ave stats            # Database statistics
python -m ave validate ave-database/cards/  # Validate all cards
python -m ave submit --interactive  # Generate a draft card
```

---

## 📊 Database Summary

### 36 Documented Vulnerabilities

| AVE-ID | Severity | Name | Category | Status |
|--------|----------|------|----------|--------|
| [AVE-2025-0001](./cards/AVE-2025-0001.md) | 🔴 critical | Sleeper Payload Injection | `memory` | `proven_mitigated` |
| [AVE-2025-0002](./cards/AVE-2025-0002.md) | 🟠 high | Consensus Paralysis | `consensus` | `proven_mitigated` |
| [AVE-2025-0003](./cards/AVE-2025-0003.md) | 🔴 critical | Token Embezzlement (EDoS) | `resource` | `proven_mitigated` |
| [AVE-2025-0004](./cards/AVE-2025-0004.md) | 🟡 medium | Prompt Inbreeding | `drift` | `proven_mitigated` |
| [AVE-2025-0005](./cards/AVE-2025-0005.md) | 🟡 medium | CYA Cascade | `social` | `proven` |
| [AVE-2025-0006](./cards/AVE-2025-0006.md) | 🟡 medium | Language Drift | `drift` | `proven` |
| [AVE-2025-0007](./cards/AVE-2025-0007.md) | 🟠 high | Goodhart's Cartel | `alignment` | `proven` |
| [AVE-2025-0008](./cards/AVE-2025-0008.md) | 🟡 medium | Learned Helplessness | `alignment` | `proven` |
| [AVE-2025-0009](./cards/AVE-2025-0009.md) | 🔴 critical | Epistemic Contagion | `memory` | `proven` |
| [AVE-2025-0010](./cards/AVE-2025-0010.md) | 🟡 medium | Clever Hans Effect | `alignment` | `proven` |
| [AVE-2025-0011](./cards/AVE-2025-0011.md) | 🟡 medium | Prompt Satiation | `structural` | `proven` |
| [AVE-2025-0012](./cards/AVE-2025-0012.md) | 🟠 high | Sycophantic Collapse | `alignment` | `proven` |
| [AVE-2025-0013](./cards/AVE-2025-0013.md) | 🟡 medium | Chronological Desync | `temporal` | `proven` |
| [AVE-2025-0014](./cards/AVE-2025-0014.md) | 🟠 high | MCP Tool Registration Poisoning | `tool` | `proven` |
| [AVE-2025-0015](./cards/AVE-2025-0015.md) | 🟡 medium | Observer Effect | `alignment` | `proven` |
| [AVE-2025-0016](./cards/AVE-2025-0016.md) | 🟡 medium | Upgrade Regression | `structural` | `proven` |
| [AVE-2025-0017](./cards/AVE-2025-0017.md) | 🟠 high | Container Isolation Bleed | `structural` | `proven` |
| [AVE-2025-0018](./cards/AVE-2025-0018.md) | 🟡 medium | Somatic Blindness | `structural` | `proven_mitigated` |
| [AVE-2025-0019](./cards/AVE-2025-0019.md) | 🟠 high | Pydantic Schema Exploitation | `injection` | `proven` |
| [AVE-2025-0020](./cards/AVE-2025-0020.md) | 🔴 critical | Multi-Pathology Compound Attack | `structural` | `proven_mitigated` |
| [AVE-2025-0021](./cards/AVE-2025-0021.md) | 🟠 high | Algorithmic Bystander Effect | `social` | `proven_mitigated` |
| [AVE-2025-0022](./cards/AVE-2025-0022.md) | 🟠 high | Memory Laundering | `memory` | `proven` |
| [AVE-2025-0023](./cards/AVE-2025-0023.md) | 🟡 medium | Static Topology Fragility | `structural` | `proven_mitigated` |
| [AVE-2025-0024](./cards/AVE-2025-0024.md) | 🔴 critical | Deceptive Alignment | `alignment` | `not_proven` |
| [AVE-2025-0025](./cards/AVE-2025-0025.md) | 🟠 high | Agent Collusion | `social` | `proven` |
| [AVE-2025-0026](./cards/AVE-2025-0026.md) | 🔴 critical | Confused Deputy Attack | `tool` | `proven` |
| [AVE-2025-0027](./cards/AVE-2025-0027.md) | 🟠 high | Shadow Delegation | `delegation` | `proven` |
| [AVE-2025-0028](./cards/AVE-2025-0028.md) | 🔴 critical | Credential Harvesting | `credential` | `proven` |
| [AVE-2025-0029](./cards/AVE-2025-0029.md) | 🔴 critical | Temporal Sleeper Agent | `temporal` | `proven` |
| [AVE-2025-0030](./cards/AVE-2025-0030.md) | 🟠 high | Semantic Trojan Horse | `injection` | `theoretical` |
| [AVE-2025-0031](./cards/AVE-2025-0031.md) | 🟠 high | Temporal Persona Shift | `drift` | `theoretical` |
| [AVE-2025-0032](./cards/AVE-2025-0032.md) | 🔴 critical | Multi-Hop Tool Chain Exploitation | `tool` | `proven` |
| [AVE-2025-0033](./cards/AVE-2025-0033.md) | 🔴 critical | Jailbreak Chaining for Capability Escalation | `injection` | `theoretical` |
| [AVE-2025-0034](./cards/AVE-2025-0034.md) | 🔴 critical | Federated Poisoning in Multi-Tenant Systems | `memory` | `theoretical` |
| [AVE-2025-0035](./cards/AVE-2025-0035.md) | 🟡 medium | Attention Smoothing | `resource` | `proven` |
| [AVE-2025-0036](./cards/AVE-2025-0036.md) | 🟡 medium | Errors of Omission | `alignment` | `proven` |

### Statistics

| Severity | Count | |
|----------|------:|-|
| 🔴 CRITICAL | 11 | ████████████ |
| 🟠 HIGH | 12 | █████████████ |
| 🟡 MEDIUM | 13 | ██████████████ |

| Category | Count |
|----------|------:|
| `alignment` | 7 |
| `structural` | 6 |
| `memory` | 4 |
| `drift` | 3 |
| `social` | 3 |
| `tool` | 3 |
| `injection` | 3 |
| `resource` | 2 |
| `temporal` | 2 |
| `consensus` | 1 |
| `delegation` | 1 |
| `credential` | 1 |

---

## 🤝 How to Contribute

**Anyone can submit vulnerabilities.** We welcome security researchers, AI engineers,
academics, red teamers, and practitioners.

### Three Ways to Submit

| Method | Difficulty | Best For |
|--------|-----------|----------|
| [**GitHub Issue**](https://github.com/dleighsystem/nailinstitute/issues/new?template=ave-submission.yml) | Easy | First-time contributors — fill in a structured form |
| [**Pull Request**](../CONTRIBUTING.md#option-2-pull-request-for-experienced-contributors) | Moderate | Experienced contributors — submit JSON + Markdown directly |
| [**Private Disclosure**](../SECURITY.md) | Any | Severe/weaponizable findings — responsible disclosure process |

### Generate a Card Skeleton

```bash
# Quick mode
python -m ave submit --name "My Vulnerability" --category memory --severity high

# Interactive mode
python -m ave submit --interactive

# Validate before submitting
python -m ave validate ave-database/cards/AVE-DRAFT-0001.json
```

### What We're Looking For

- ✅ Repeatable agent failure modes (deadlocks, drift, resource exhaustion)
- ✅ Novel attack vectors against agentic systems (tool chain exploits, memory poisoning)
- ✅ Emergent behaviours in multi-agent deployments
- ✅ Framework-specific vulnerabilities (LangChain, CrewAI, AutoGen, etc.)
- ✅ Defences and mitigations for existing cards

### Severity Guide

| Icon | Level | Description |
|------|-------|-------------|
| 🔴 | **CRITICAL** | Immediate data loss, exfiltration, or safety failure |
| 🟠 | **HIGH** | Significant operational impact, exploitable in production |
| 🟡 | **MEDIUM** | Degrades performance, requires specific conditions |
| 🟢 | **LOW** | Minor impact, edge case |
| ℹ️ | **INFO** | Theoretical or not yet validated |

---

## 📐 AVE Card Schema

Every card follows a structured schema modelled after CVE/CWE.
See [CONTRIBUTING.md](../CONTRIBUTING.md#ave-card-schema) for the full specification.

**Key fields:**

```json
{
  "ave_id": "AVE-2025-0001",
  "name": "Sleeper Payload Injection",
  "category": "memory",
  "severity": "critical",
  "status": "proven_mitigated",
  "summary": "...",
  "mechanism": "...",
  "blast_radius": "...",
  "prerequisite": "...",
  "environment": { "frameworks": ["..."], "models_tested": ["..."] },
  "evidence": [{ "experiment_id": "...", "key_metric": "...", "key_value": "..." }],
  "defences": [{ "name": "...", "effectiveness": "..." }],
  "avss_score": { "overall_score": 10.0, "vector_string": "AVSS:1.0/..." }
}
```

---

## 📖 Citation

If you use this database in your research, please cite:

```bibtex
@dataset{leigh2026ave,
  author    = {Leigh, Dillman},
  title     = {{AVE Database}: Agentic Vulnerabilities \& Exposures},
  year      = {2026},
  publisher = {NAIL Institute, Neuravant AI Limited},
  url       = {https://github.com/NAIL-INSTITUTE-FOR-AGENTIC-SECURITY/ave-database},
  version   = {1.0.0},
  note      = {36 documented AI agent vulnerability cards}
}
```

A `CITATION.cff` file is included for automatic citation tooling (GitHub "Cite this repository" button).

---

## 📜 Licensing

All AVE Database content is licensed under
[**CC-BY-SA-4.0**](https://creativecommons.org/licenses/by-sa/4.0/).

You are free to use, share, and adapt this data for any purpose, including
commercial use, with attribution.

---

## 🔗 Related Resources

- [CONTRIBUTING.md](../CONTRIBUTING.md) — Full contributor guide
- [SECURITY.md](../SECURITY.md) — Responsible disclosure policy
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) — Community conduct standards
- [NAIL Institute](https://github.com/dleighsystem/nailinstitute) — The parent platform

---

*Maintained by the [NAIL Institute](https://github.com/dleighsystem/nailinstitute) — Building the safety infrastructure for agentic AI.*