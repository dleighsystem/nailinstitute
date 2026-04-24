# nail-apex — Cognitive Front-End

Kahneman-style **dual-system** orchestrator for NAIL agents:

* **System 1** — fast intuitive reflex. Single small Ollama model
  (default `llama3.1:8b-instruct-q8_0`). Returns in <1s for chat,
  formatting, simple recall.
* **System 2** — deliberate test-time-compute (TTC). Wraps a larger
  reasoning model (default `nail-reason:v5`) with a forced
  `<thought>` / `<answer>` template, parses the trace, returns only
  the answer. Used for math, code, multi-step logic.

A **router** in front decides which system to use. Two routers ship:

* `CosineRouter` — pure Python; sentence-transformer cosine vs anchors.
  Zero LLM calls. Fast, cheap, deterministic. (Optional: needs
  `sentence-transformers`.)
* `GuardRouter` — calls `nail-guard:v4` (Ollama) for classification.
  Drop-in once Ollama is available; falls back to `CosineRouter` on
  failure.

Every step (route, sys1, sys2) is auto-emitted into `fleet/` if fleet
is importable, mirroring the `_telemetry` pattern from the other
NAIL packages. Every input passes through `shield.process(...)` first
when shield is available.

## Architecture

```
   user query
       │
       ▼
  ┌────────────────────┐    apex.brain
  │ shield.process()   │    optional, on-by-default if shield installed
  └─────────┬──────────┘
            ▼
  ┌────────────────────┐
  │ Router.classify()  │    SYSTEM_1 | SYSTEM_2
  └─────────┬──────────┘
            ▼
   ┌────────┴────────┐
   ▼                 ▼
 System1           System2
 (fast)            (TTC <thought>/<answer>)
   └────────┬────────┘
            ▼
       fleet.safe_emit()
            │
            ▼
       answer to caller
```

## Quick start

```python
from apex import ApexBrain

brain = ApexBrain()                         # uses defaults; shield/fleet auto-detected
print(brain.process("hi, how are you?"))   # → SYSTEM_1, llama3.1
print(brain.process("Prove √2 is irrational."))  # → SYSTEM_2, nail-reason:v5 with <thought>
```

Override pieces:

```python
from apex import ApexBrain, CosineRouter, System1, System2

brain = ApexBrain(
    router=CosineRouter(),
    system1=System1(model="qwen2.5:7b-instruct"),
    system2=System2(model="nail-reason:v5"),
    enable_shield=True,
)
```

## Tests

```bash
cd apex && python3 -m pytest tests/ -q
```

All tests stub the Ollama HTTP layer, so the suite runs offline.
