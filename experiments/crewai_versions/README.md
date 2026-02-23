# CrewAI Agent Framework Versions

These are **true agent framework** implementations of the same experiments,
using CrewAI 1.9.3 with autonomous agent planning and delegation.

The purpose is to compare **prompt-orchestrated** (our custom Python code
controlling turn-taking) vs **agent-framework** (CrewAI managing the agents
autonomously) to see if framework overhead amplifies or dampens pathologies.

## Experiments
- `crewai_exp4_inbreeding.py` — Prompt Inbreeding via CrewAI hierarchical process
- `crewai_exp7_cartel.py` — Goodhart's Cartel via CrewAI sequential process
- `crewai_exp5_cya.py` — CYA Cascade via CrewAI hierarchical process

## Running
```bash
conda activate nail_experiments
cd experiments
python -m crewai_versions.crewai_exp4_inbreeding
python -m crewai_versions.crewai_exp7_cartel
python -m crewai_versions.crewai_exp5_cya
```
