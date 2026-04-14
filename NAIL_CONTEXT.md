# NAIL Institute — Persistent Context

> This file is automatically loaded by NailAgentClient.
> Equivalent to Anthropic's CLAUDE.md for persistent agent memory.
> Last updated: 2026-03-29

---

## Infrastructure

- **Hardware**: NVIDIA DGX Spark, ARM64, 128GB unified memory, cuQuantum 26.01.0
- **Python**: 3.12 (venv at `/home/dleighsystems/Desktop/NAIL institute/.venv`)
- **Quantum**: PennyLane 0.44.1, pennylane-lightning 0.44.0, lightning.qubit backend
- **ML**: scikit-learn 1.8.0, numpy, scipy
- **LLM**: Ollama local — nemotron:70b (PRIMARY), mistral:7b-instruct (FAST), deepseek-coder:6.7b-instruct (CODE)
- **Ollama URL**: http://localhost:11434

---

## Experiment Results (Round 2)

### VQC v3 (phase2_vqc_v3.py) — 🏆 TARGET HIT
- **Binary**: 100% accuracy, 100% Sleeper recall, 100% Normal recall (65.2s, early stop E55)
- **Multiclass**: 92.2% overall accuracy, 100% Sleeper recall (199.4s)
- **Per-class**: Normal 93.3%, Goal Drift 60.0%, Memory Corruption 100%, EDoS 100%, Prompt Injection 100%, Sleeper 100%
- **Weights**: `quantum-research/experiments/models/vqc_binary_weights_20260329_171206.json`
- **Architecture**: 8 qubits, 4 layers StronglyEntanglingLayers, angle encoding, LR=0.02, batch=32

### Ship of Theseus (exp30) — 10K Run
- Control: 61.7% accuracy → Treatment (Active Forgetting): 84.5% accuracy (+22.8%)
- Active Forgetting pruned 24,381 stale memory entries
- Proves memory management is critical for agent integrity

### Contagion Pandemic (exp31) — v2
- 4 arms: Control, Passive, Behavioral Quarantine, Firewall+Quarantine
- Firewall + Quarantine: 70% infection reduction (best arm)
- Content-inspection firewall before memory writes is essential

### QAOA Staging (staging_deploy.py)
- 5-round QAOA vs GA validation — QAOA did not beat GA
- Decision: HOLD on production deployment until extended run

### Quantum Kernel (phase2_enhanced_kernel.py)
- 66.7% overall accuracy, 66.7% Sleeper recall
- VQC v3 decisively outperforms quantum kernel approach

---

## Defense Thresholds (QAOA-Optimized)

```
trust_floor:              0.7378
semantic_drift_ceiling:   0.4995
memory_corruption_ceiling: 0.30
burn_rate_ceiling:        0.80
```

---

## Pathology Types

| ID | Name | Description | VQC Recall |
|----|------|-------------|------------|
| 0 | Normal | Healthy agent behavior | 93.3% |
| 1 | Goal Drift | Gradual objective shift | 60.0% |
| 2 | Memory Corruption | Poisoned memory entries | 100% |
| 3 | EDoS | Token budget drain | 100% |
| 4 | Prompt Injection | Safety bypass attempts | 100% |
| 5 | Sleeper Agent | Dormant activation | 100% |

---

## Defense Architecture

### Layer 5 (Quantum Anomaly Detection) — 4 Tiers
- **Tier 0**: VQC binary classifier (100% Sleeper recall) — NEW
- **Tier 1**: Quantum Reservoir temporal patterns
- **Tier 2**: Quantum Kernel SVM / Heuristic
- **Tier 3**: Simple threshold heuristic (fallback)

### Pathology Collider Defense Stack
- Layer 1: Content Analysis (manipulation detection)
- Layer 2: Semantic Drift Monitor (persona anchor comparison)
- Layer 3: Memory Integrity (cross-referencing stored facts)
- Layer 4: Economic Monitor (token budget tracking)
- Layer 5: Quantum Anomaly Detection (VQC + Reservoir + SVM)

---

## Key File Paths

```
nail_harness/                        # Agent harness framework
  util.py                            # Ollama wrapper (llm_call equivalent)
  agent_client.py                    # NailAgentClient (query loop)
  memory.py                          # Active Forgetting memory manager
  hooks.py                           # Pre/Post tool-use hooks
  mcp_server.py                      # Quantum detection MCP tools
  evaluator_optimizer.py             # Red/Blue team loop

.nail/agents/                        # Agent role definitions
  red_team.md                        # Adversarial attack generator
  blue_team.md                       # Defense evaluator
  quantum_researcher.md              # Experiment coordinator

experiments/shared/                   # Shared infrastructure
  ollama_llm.py                      # Ollama LLM wrapper
  config.py                          # Model names, paths
  agent_base.py                      # Base agent class

experiments/exp20_pathology_collider/ # Live Red vs Blue
  vqc_adapter.py                     # VQC → Layer 5 bridge
  quantum_anomaly_layer.py           # Layer 5 detector
  collider.py                        # Main orchestrator

quantum-research/experiments/        # Quantum experiments
  phase2_vqc_v3.py                   # VQC training
  phase2_enhanced_kernel.py          # Quantum kernel
  phase4_qaoa_coordinator.py         # QAOA optimization
```
