# RMAP — Resilient Multi-Agent Protocol

> **Production framework for self-healing, self-aware agentic systems.**

Built from empirical research: 29 experiments, 50,000+ adversarial simulations at the NAIL Institute (Neuravant AI Limited).

## The Problem

Every agentic system in production today will eventually:
- **Deadlock** — agents argue forever, burning tokens, reaching no consensus
- **Converge** — agents copy each other's outputs until the system produces identical slop
- **Fabricate** — agents invent statistics, citations, and financial data with total confidence
- **Drift** — agent personas erode over long contexts until they break character
- **Crash** — infrastructure failures (OOM, GPU throttle, network timeout) cause cascading collapse

RMAP solves all five. Not with guardrails. With an immune system.

## Installation

```bash
pip install rmap
```

With optional extras:
```bash
pip install rmap[full]     # All optional dependencies
pip install rmap[ollama]   # Ollama integration
pip install rmap[monitor]  # nail-monitor integration
pip install rmap[dev]      # pytest, coverage
```

## The Four Pillars

### Phase 1 — Metamorphic Graph Engine

Dynamic agent topologies that reshape at runtime. Agents don't just traverse the graph — they redraw it.

```python
from rmap import MetamorphicGraph

graph = MetamorphicGraph()
graph.create_agent("planner", "coordinator", "You orchestrate tasks.")
graph.create_agent("coder", "developer", "You write Python code.")
graph.create_agent("reviewer", "critic", "You review code for bugs.")

graph.connect("planner", "coder")
graph.connect("coder", "reviewer")
graph.connect("reviewer", "planner")  # Feedback loop

# At runtime, the orchestrator can reshape:
graph.create_agent("security", "auditor", "You check for vulnerabilities.")
graph.connect("reviewer", "security")

# Fork a subgraph for isolated sub-tasks:
sg_id = graph.fork_subgraph(["coder", "reviewer"], task="Fix the auth bug")
# ... work happens in isolation ...
graph.collapse_subgraph(sg_id)

# Every mutation is recorded:
print(graph.get_metrics())
```

### Phase 2 — Digital Homeostasis (Immune System)

Macrophage agents, apoptosis protocols, antibody quarantine. Software doesn't crash; it heals around the wound.

```python
from rmap import ImmuneDaemon

daemon = ImmuneDaemon(
    deadlock_warn=6,       # Warn after 6 rounds without consensus
    deadlock_critical=10,  # Escalate after 10
)

# Wire intervention callbacks:
daemon.register_macrophage(lambda target, rnd: kill_and_respawn(target))
daemon.register_antibody(lambda output, info: sanitize(output))

# In your agent loop:
interventions = daemon.observe_consensus_round(
    round_num=round_num,
    votes={"agent_a": True, "agent_b": False, "agent_c": True},
)

interventions = daemon.observe_output(
    agent_name="analyst",
    output=agent_response,
    round_num=round_num,
)

print(daemon.summary())
```

### Phase 3 — Somatic Awareness

Real-time infrastructure telemetry injected into agent context. Agents know they're inside computers.

```python
from rmap import SomaticHeader

# One-shot:
header = SomaticHeader.collect()
# → "[SOMATIC CPU:45% | RAM:60%(48.0/80.0GB) | DISK:200GB | GPU:90%(VRAM:60.0/80.0GB)@72°C | LOAD:2.5/2.0/1.5]"

system_prompt = f"{header}\n\nYou are a coding agent. If tools are slow, check the somatic header first."

# Continuous monitoring:
somatic = SomaticHeader(poll_interval=5.0)
for round in rounds:
    prompt = f"{somatic}\n\n{task}"
    # Agent now sees infrastructure state in every prompt
```

### Phase 4 — Evolutionary Crucible

Stop engineering configurations. Start evolving them.

```python
from rmap import Crucible, GeneDef, Genome

# Define the search space:
gene_defs = [
    GeneDef("threshold", 0.1, 0.9),
    GeneDef("window_size", 2, 10, is_int=True),
    GeneDef("learning_rate", 0.001, 0.1),
    GeneDef("temperature", 0.0, 2.0),
]

# Define your fitness function:
def evaluate(genome: Genome) -> float:
    config = genome.genes
    # Run your system with these parameters...
    accuracy = run_experiment(config)
    return accuracy

# Evolve:
crucible = Crucible(gene_defs, evaluate, elitism=2, mutation_rate=0.2)
best = crucible.evolve(generations=20, population_size=12)

print(f"Best fitness: {best.fitness}")
print(f"Best config: {best.genes}")
print(f"Trajectory: {crucible.fitness_trajectory()}")
```

## Framework Agnostic

RMAP doesn't care what LLM backend you use. The `AgentNode` takes any `Callable[[str], str]`:

```python
# Ollama
import requests
def ollama_invoke(prompt):
    r = requests.post("http://localhost:11434/api/generate",
                      json={"model": "llama3", "prompt": prompt, "stream": False})
    return r.json()["response"]

# OpenAI
from openai import OpenAI
client = OpenAI()
def openai_invoke(prompt):
    return client.chat.completions.create(
        model="gpt-4", messages=[{"role": "user", "content": prompt}]
    ).choices[0].message.content

# Wire it in:
graph = MetamorphicGraph()
graph.create_agent("coder", "dev", "Write code.", invoke=ollama_invoke)
graph.create_agent("reviewer", "critic", "Review code.", invoke=openai_invoke)
```

## API Reference

| Module | Key Classes | Purpose |
|--------|------------|---------|
| `rmap.graph` | `MetamorphicGraph`, `AgentNode`, `SubGraph` | Dynamic topology |
| `rmap.immune` | `ImmuneDaemon`, `DeadlockDetector`, `FabricationDetector` | Automated healing |
| `rmap.somatic` | `SomaticHeader`, `SomaticSnapshot`, `collect_telemetry` | Infrastructure awareness |
| `rmap.crucible` | `Crucible`, `Genome`, `GeneDef` | Evolutionary optimization |

## Research

This library is the production distillation of:

**"Twenty-Nine Empirical Experiments on LLM Agentic System Failure Modes"**
NAIL Institute (Neuravant AI Limited), 2025

The paper documents 29 experiments across 50,000+ adversarial simulations proving that multi-agent LLM systems exhibit predictable, reproducible failure modes — and that biological metaphors (immune systems, somatic awareness, metamorphic topology, evolution) provide effective cures.

## License

MIT

## Citation

```bibtex
@article{nail2025rmap,
  title={Resilient Multi-Agent Protocol: Production Framework for Self-Healing Agentic Systems},
  author={NAIL Institute},
  year={2025},
  note={Based on 29 empirical experiments on LLM agentic system failure modes}
}
```
