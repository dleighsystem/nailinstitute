# Experiment 32: Deep Defense Strategy Laboratory

## Objective

Systematically evaluate **6 novel defensive strategies** against undesirable agent task execution, beyond the existing 5-layer defence stack.

## Gap Analysis — What our current defenses DON'T cover

| Gap | Description | Current Blind Spot |
|-----|-------------|-------------------|
| **Pre-execution intent** | All 5 layers are *reactive* — they detect AFTER an action | No prevention before tool/task execution |
| **Tool capability scoping** | Agents have full tool access once running | No least-privilege per-task |
| **Semantic goal verification** | We detect drift but don't verify the TASK itself is valid | Agent could execute a valid-looking but unauthorized task |
| **Multi-turn chain attacks** | Each turn is evaluated independently | A benign T1 → benign T2 → malicious T3 chain passes all layers |
| **Output weaponization** | We scan for injection markers but not semantic harm | An agent could produce harmful outputs that pass all pattern checks |
| **Consensus without collusion** | Startle response forces binary choice on ONE agent | No independent verification from multiple agents |

## The 6 New Strategies

1. **Intent Classifier (Pre-Execution Gate)** — Quantum-enhanced task classification BEFORE execution
2. **Least-Privilege Tool Scoping** — Dynamic tool permission narrowing based on task context  
3. **Semantic Goal Anchoring** — Embedding-distance verification that the task matches the authorized goal
4. **Chain-of-Thought Audit Trail** — Multi-turn reasoning chain analysis for escalation detection
5. **Constitutional Output Validator** — LLM-as-judge output validation against a constitution
6. **Consensus Verification Tribunal** — N-of-M independent agent agreement before high-risk actions

## How to Run

```bash
cd "/home/dleighsystems/Desktop/NAIL institute"
source .venv/bin/activate
python -m experiments.exp32_defense_strategies.run              # All 6 strategies
python -m experiments.exp32_defense_strategies.run --strategy 1  # Single strategy
python -m experiments.exp32_defense_strategies.run --full         # Extended with VQC
```
