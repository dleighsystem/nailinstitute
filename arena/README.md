# DGX Arena — Continuous Red/Blue Adversarial Evolution

**Phase 3 of the Agent-CVE programme.**

The Arena operationalises the Pathology Collider as a 24/7 Red-vs-Blue
self-play engine.  A **Red Swarm** of GA-evolved attack vectors battles a
**Blue Bridge** of configurable defences.  Both sides evolve every
generation.  Novel breakthroughs are auto-published as draft AVE
vulnerability cards.

## Architecture

```
┌───────────────────────────────────────────┐
│               Arena Director               │
│  (orchestrates rounds, seasons, reports)   │
└────────┬──────────────────────┬───────────┘
         │                      │
┌────────▼──────────┐  ┌───────▼──────────┐
│   Red Swarm        │  │   Blue Bridge     │
│  (AttackVector GA) │  │  (DefenceConfig   │
│  evolves attacks   │◄─►  evolves defs)   │
└────────┬──────────┘  └───────┬──────────┘
         │                      │
         └──────────┬───────────┘
                    ▼
         ┌─────────────────────┐
         │    Battle Log        │
         │  (forensic record)   │
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐
         │  AVE Auto-Publish    │
         │  breakthrough → card │
         └─────────────────────┘
```

## Installation

```bash
cd arena
pip install -e ".[dev]"
```

## Quick Start

```python
from arena import Arena

# Run a quick 10-round season
arena = Arena.quick()
result = arena.run_season(rounds=10)

print(result.summary())
# {'season_id': 'season-0001-a1b2c3', 'rounds_played': 10,
#  'red_wins': 42, 'blue_wins': 53, 'breach_rate': 0.42, ...}

# Auto-generate draft AVE cards for any breakthroughs
for card in result.draft_ave_cards():
    print(card["ave_id"], card["title"])
```

## Modules

| Module | Classes | Purpose |
|--------|---------|---------|
| `vectors.py` | `AttackType`, `AttackVector`, `AttackPayload` | GA-evolvable adversarial payloads (13 attack categories, 8 tunable genes) |
| `defences.py` | `DefenceConfig`, `DetectionResult`, `BlueBridge` | Configurable detector bank (17 detectors, 10 defence categories) |
| `swarm.py` | `RedSwarm`, `SwarmStats` | GA population manager — tournament selection, crossover, mutation |
| `battle.py` | `BattleOutcome`, `BattleLog`, `Verdict` | Single engagement execution and forensic logging |
| `arena.py` | `Arena`, `SeasonResult`, `Breakthrough` | Top-level orchestrator with coevolution and AVE auto-publish |

## Attack Types (Red)

| Type | Description |
|------|-------------|
| `prompt_injection` | Direct instruction override |
| `indirect_injection` | Injection via document/context |
| `jailbreak` | Safety constraint bypass |
| `credential_harvest` | API key / password extraction |
| `pii_extraction` | Personal data exfiltration |
| `token_edos` | Economic denial of service via token burn |
| `sleeper_payload` | Delayed-activation hidden instructions |
| `memory_poisoning` | False fact injection into context |
| `tool_poisoning` | Tool chain parameter manipulation |
| `social_engineering` | Authority / urgency exploitation |
| `collusion_split` | Multi-agent coordinated attack |
| `persona_override` | Identity / role hijacking |
| `chain_attack` | Multi-step compound attack |

## Attack Genes (GA Parameters)

Each attack vector has 8 continuously-tunable genes (0.0–1.0):

| Gene | Low (0.0) | High (1.0) |
|------|-----------|------------|
| `intensity` | Subtle probe | Maximum force |
| `stealth` | Obvious | Heavily obfuscated |
| `complexity` | Single step | Multi-hop chain |
| `persistence` | Single shot | Sustained campaign |
| `social_pressure` | Neutral | Maximum authority/urgency |
| `encoding` | Plain text | Heavy encoding |
| `multi_vector` | Single type | Compound multi-type |
| `timing` | Immediate | Delayed/sleeper |

## Defence Detectors (Blue)

The Blue Bridge deploys 17 detectors across 10 categories:

- **Injection filters** — prompt injection, indirect injection, jailbreak
- **Exfiltration guards** — credential leak, PII leak
- **Resource limiters** — token budget, repetition
- **Social detectors** — social pressure, authority claims
- **Persona monitors** — persona override, role consistency
- **Tool chain guards** — tool chain validation
- **Collusion detectors** — multi-agent coordination
- **Memory integrity** — memory poisoning, sleeper patterns
- **Behaviour baseline** — anomaly detection
- **Canary tripwires** — honeypot token detection

## Factory Configs

```python
Arena.quick()       # 10 Red vectors, 5 Blue configs — fast testing
Arena.standard()    # 50 Red vectors, 20 Blue configs — meaningful evolution
Arena.maximum()     # 200 Red vectors, 50 Blue configs — production 24/7
```

## Multi-Season Evolution

```python
arena = Arena.standard()

# Run multiple seasons — populations carry over
for season in range(10):
    result = arena.run_season(rounds=50)
    print(f"Season {season}: {result.breach_rate:.2%} breach rate, "
          f"{len(result.breakthroughs)} breakthroughs")
```

## Integration with AVE

Breakthroughs are automatically formatted as draft AVE cards:

```python
result = arena.run_season(rounds=100)
for card in result.draft_ave_cards():
    # card = {
    #     "ave_id": "AVE-ARENA-a1b2c3d4",
    #     "title": "Arena Breakthrough: jailbreak",
    #     "description": "GA-evolved jailbreak attack bypassed ...",
    #     "category": "arena_discovery",
    #     "severity": "high",
    #     "attack_genes": {...},
    # }
    pass
```

## Tests

```bash
cd arena
pytest -v
```
