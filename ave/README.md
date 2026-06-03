# AVE — Agentic Vulnerabilities & Exposures

**The CVE database for AI agent failures.**

Every vulnerability that can affect an autonomous AI agent — from prompt injection to consensus paralysis to memory laundering — gets a unique **AVE-ID**, a severity score, empirical evidence, and a mapping to known defences.

This is the **MITRE ATT&CK of the Agentic Era**, built on 29 empirical experiments and 50,000+ adversarial simulations at the NAIL Institute (Neuravant AI Limited).

---

## Quick Start

```python
import ave

# Look up a specific vulnerability
card = ave.lookup("AVE-2025-0026")
print(card)
# ╔══ AVE-2025-0026: Confused Deputy Attack ══╗
#   Category:  tool
#   Severity:  critical
#   Status:    proven
#   Summary:   LLMs blindly trust their own tool descriptions...

# Search by category
memory_vulns = ave.search(category=ave.Category.MEMORY)
print(f"{len(memory_vulns)} memory-related vulnerabilities")

# Filter by severity
critical = ave.cards_by_severity(ave.Severity.CRITICAL)
for c in critical:
    print(c.short())

# Get summary statistics
stats = ave.card_count()
print(f"Total: {stats['total']} cards")
print(f"Critical: {stats['by_severity'].get('critical', 0)}")
```

## Installation

```bash
pip install -e ".[dev]"
```

## Card Structure

Every AVE card contains:

| Field | Type | Description |
|-------|------|-------------|
| `ave_id` | `str` | Unique identifier (e.g. `AVE-2025-0001`) |
| `name` | `str` | Human-readable name |
| `aliases` | `tuple[str]` | Alternative names in literature |
| `category` | `Category` | Attack surface / failure domain |
| `severity` | `Severity` | CRITICAL / HIGH / MEDIUM / LOW / INFO |
| `status` | `Status` | PROVEN / PROVEN_MITIGATED / THEORETICAL / NOT_PROVEN / IN_PROGRESS |
| `summary` | `str` | One-paragraph description |
| `mechanism` | `str` | How the attack or failure works |
| `blast_radius` | `str` | What breaks when this fires |
| `prerequisite` | `str` | Conditions required to trigger |
| `environment` | `EnvironmentVector` | Frameworks, models, and features required |
| `evidence` | `tuple[Evidence]` | Pointers to empirical experiments |
| `defences` | `tuple[Defence]` | Known mitigations (RMAP modules, nail_monitor detectors) |
| `cwe_mapping` | `str` | Nearest CWE if applicable |
| `mitre_mapping` | `str` | Nearest MITRE ATT&CK technique |

## Categories (14)

| Category | Description |
|----------|-------------|
| `MEMORY` | Memory pollution, laundering, poisoning |
| `CONSENSUS` | Deadlock, paralysis, bystander effect |
| `INJECTION` | Prompt injection, indirect injection |
| `RESOURCE` | Token embezzlement, EDoS, cost anomaly |
| `DRIFT` | Persona drift, language drift, goal drift |
| `ALIGNMENT` | Sycophancy, deceptive alignment, RLHF exploits |
| `SOCIAL` | Collusion, bystander, social loafing |
| `TOOL` | Confused deputy, tool chain, MCP poisoning |
| `TEMPORAL` | Chronological desync, sleeper payloads |
| `STRUCTURAL` | Cascade corruption, routing deadlock |
| `CREDENTIAL` | Credential harvesting, secret exfiltration |
| `DELEGATION` | Shadow delegation, privilege escalation |
| `FABRICATION` | Hallucination, data fabrication |
| `EMERGENT` | Novel behaviours not fitting other categories |

## Registry at a Glance

| Stat | Count |
|------|-------|
| **Total Cards** | 37 |
| **Lab-Proven** (Experiments 1–29) | 29 |
| **Theoretical** (Threat Landscape) | 4 |
| **Proven & Mitigated** | 5 |
| **Not Proven** | 1 (Deceptive Alignment) |
| **In Progress** | 1 (AVE-2026-0037 Semantic Fragmentation — CIL) |

### Severity Distribution

| Severity | Count |
|----------|-------|
| CRITICAL | 9 |
| HIGH | 14 |
| MEDIUM | 14 |

## API Reference

### `ave.lookup(ave_id: str) -> AVECard | None`
Look up a single card by its AVE-ID.

### `ave.search(*, category, severity, status, keyword) -> list[AVECard]`
Search with optional filters (AND-combined).

### `ave.all_cards() -> list[AVECard]`
Return all cards in registry order.

### `ave.cards_by_severity(severity) -> list[AVECard]`
Filter by severity level.

### `ave.cards_by_category(category) -> list[AVECard]`
Filter by attack category.

### `ave.cards_by_status(status) -> list[AVECard]`
Filter by research status.

### `ave.card_count() -> dict`
Summary counts by severity, category, and status.

### `AVECard.to_dict() -> dict`
JSON-serialisable dictionary representation.

### `AVECard.short() -> str`
One-line summary: `[AVE-2025-0001] [CRITICAL] Sleeper Payload Injection (proven_mitigated)`

## Defence Integration

AVE cards map directly to two defence systems:

- **RMAP** (Resilient Multi-Agent Protocol): `Defence.rmap_module` points to `rmap.graph`, `rmap.immune`, `rmap.somatic`, or `rmap.crucible`
- **nail_monitor**: `Defence.nail_monitor_detector` names the specific detector class (e.g. `ConsensusParalysisDetector`)

## JSON Export

```python
import json, ave

# Export single card
card = ave.lookup("AVE-2025-0001")
print(json.dumps(card.to_dict(), indent=2))

# Export entire database
db = [c.to_dict() for c in ave.all_cards()]
with open("ave_database.json", "w") as f:
    json.dump(db, f, indent=2)
```

## Tests

```bash
cd ave && pytest tests/ -v
# 63 passed in 0.05s
```

## Relationship to Agent-CVE.md

This package implements **Phase 1** of the 4-phase Agent-CVE programme:

1. ✅ **AVE Database** — This package (structured vulnerability cards)
2. 🔲 **Canary Fleet** — Honeypot agents that detect novel attacks
3. 🔲 **DGX Arena** — Red/blue continuous evolution on DGX Spark
4. 🔲 **CTF Events** — Community red-teaming competitions

---

**Built at the NAIL Institute on DGX Spark • Python 3.12 • Zero runtime dependencies**
