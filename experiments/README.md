# NAIL Institute — Agentic Framework Pathology Experiments

## 🧬 Overview

Four controlled experiments studying structural pathologies in multi-agent AI frameworks, using **100% local LLM inference** via Ollama. No API costs. No rate limits. Full control.

**Thesis:** A dumb model in a well-designed framework will outperform a brilliant model in a structurally flawed framework.

---

## 🏗️ Architecture

```
experiments/
├── shared/                      # Shared utilities
│   ├── config.py                # Central configuration (models, paths)
│   ├── ollama_llm.py            # Local Ollama LLM wrapper with token tracking
│   ├── agent_base.py            # Base Agent class
│   └── logger.py                # Structured JSON experiment logger
│
├── exp1_memory_pollution/       # Experiment 1: Tragedy of the Commons
│   └── run.py                   # Shared memory degradation test
│
├── exp2_consensus_paralysis/    # Experiment 2: Algorithmic Filibustering
│   └── run.py                   # Consensus deadlock + escape hatches
│
├── exp3_token_embezzlement/     # Experiment 3: Token Embezzlement
│   └── run.py                   # Resource-driven goal displacement
│
├── exp4_prompt_inbreeding/      # Experiment 4: Prompt Inbreeding
│   └── run.py                   # Lineage degradation + entropy injection
│
├── docker/                      # Docker sandbox for safe execution
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── logs/                        # Structured experiment logs (JSONL)
├── data/                        # Generated data, results, caches
├── run_all.py                   # Master runner script
└── requirements.txt             # Python dependencies
```

---

## 🚀 Quick Start

### 1. Activate the environment
```bash
conda activate nail_experiments
```

### 2. Verify Ollama is running
```bash
ollama list   # Should show your models
```

### 3. Run smoke test
```bash
cd "/home/dleighsystems/Desktop/NAIL institute/experiments"
python run_all.py --smoke-test
```

### 4. Run experiments
```bash
# Run ALL experiments:
python run_all.py

# Run a specific experiment:
python run_all.py --exp 1   # Memory Pollution
python run_all.py --exp 2   # Consensus Paralysis  
python run_all.py --exp 3   # Token Embezzlement
python run_all.py --exp 4   # Prompt Inbreeding
```

---

## 📊 The Experiments

### Experiment 1: Tragedy of the Commons (Memory Pollution)
**Question:** Does a shared multi-agent memory space degrade over time?

| Condition | Description |
|-----------|-------------|
| Control | 3 Research Agents dump summaries into shared ChromaDB — no curation |
| Variable | An **Archivist Agent** continuously monitors, compresses, and prunes irrelevant content |

**Metrics:** Decision Agent accuracy, retrieval precision, DB size over time

---

### Experiment 2: Algorithmic Filibustering (Consensus Paralysis)
**Question:** What breaks infinite debate loops in multi-agent councils?

| Condition | Description |
|-----------|-------------|
| Control | 3 agents (Creative, Logic, Compliance) must reach unanimous consensus |
| Weighted Voting | Creative + Logic can override Compliance |
| Escalation | CEO Agent steps in after 5 failed rounds |
| Compromise | Compliance must rewrite (not just reject) proposals |

**Metrics:** Rounds to consensus, max-limit hit rate, output quality

---

### Experiment 3: Token Embezzlement (Goal Displacement)
**Question:** Do token budgets cause agents to write band-aid fixes?

| Condition | Description |
|-----------|-------------|
| Control | Worker penalized for exceeding token budget |
| Variable | Worker rewarded for root-cause analysis even if over budget |

**Metrics:** Unit test pass rate, band-aid detection (AST analysis), root-cause fix rate

---

### Experiment 4: Prompt Inbreeding (Lineage Degradation)  
**Question:** Does an agent generating agents lose cognitive diversity over time?

| Condition | Description |
|-----------|-------------|
| Control | Meta-Agent freely evolves Sub-Agent prompts over 20 generations |
| Entropy | Structural entropy injected every 3rd generation (lateral-thinking metaphors) |

**Metrics:** Cosine similarity between generations, lexical diversity, success rate

---

## 🔧 Models Used (Local via Ollama)

| Role | Model | Purpose |
|------|-------|---------|
| Primary | `nemotron:70b` | Heavy reasoning tasks |
| Fast | `mistral:7b-instruct` | Agent interactions (speed) |
| Code | `deepseek-coder:6.7b-instruct` | Code generation/fixing |

Models can be changed in `shared/config.py` or via environment variables:
```bash
export NAIL_PRIMARY_MODEL=nemotron:70b
export NAIL_FAST_MODEL=mistral:7b-instruct
export NAIL_CODE_MODEL=deepseek-coder:6.7b-instruct
```

---

## 📁 Output

All experiment outputs are saved as structured JSON:
- **Logs:** `logs/<experiment>/run_<id>.jsonl` — line-delimited JSON events
- **Results:** `data/exp<N>_results.json` — aggregated metrics + raw data

Load logs in Python for analysis:
```python
import pandas as pd
df = pd.read_json("logs/exp1_memory_pollution/run_control.jsonl", lines=True)
```

---

## 🐳 Docker (Optional)

For sandboxed execution (recommended when agents generate/run code):
```bash
cd docker
docker compose up --build
```

---

## 📝 Lab Notebook Checklist

For each experiment, record:
- [ ] Framework architecture diagram (who talks to whom)
- [ ] Exact system prompts used
- [ ] Raw logs of catastrophic failures
- [ ] Quantitative metrics (accuracy, rounds, tokens, similarity)
- [ ] Qualitative observations
- [ ] Screenshots of interesting agent behaviors
