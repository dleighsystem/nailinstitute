# NAIL Foresight

> Pre-flight planner. The fifth and last package of the NAIL **BEFORE**
> stack (after `diagnostic/`, `shield/`, `arsenal/`, `rehearsal/`).

## Why

`shield/` cleans inputs. `arsenal/` constrains capabilities. `rehearsal/`
shadows individual calls. **Foresight asks the higher-level question**:
*"viewed as a whole, is this multi-step plan a good idea?"*

Concretely: before the agent executes any step, we hand the entire
plan + the current world snapshot to **`nail-reason`** (our locally-trained
critic LLM) and ask it to enumerate failure modes. If the plan scores
above a configurable risk threshold, we abort or escalate.

```
agent generates plan ──▶  ┌────────────────────┐
  step 1: read tickets    │ Foresight Planner  │
  step 2: refund £180     │  ┌──────────────┐  │
  step 3: notify customer │  │ nail-reason  │  │ ← LLM critic (local Ollama)
                          │  │     v3.1     │  │
                          │  └──────┬───────┘  │
                          │         ▼          │
                          │  ┌──────────────┐  │
                          │  │ Critique     │  │ risk: 0.0–1.0
                          │  │  - risks[]   │  │ verdict: ALLOW/HOLD/REJECT
                          │  │  - mitigations  │
                          │  └──────────────┘  │
                          └─────────┬──────────┘
                                    │
              ┌─────────────────────┴─────────────┐
              ▼                                   ▼
     plan executes                      orchestrator revises
       (low risk)                        (or asks human)
```

## Quick start

```python
from foresight import Plan, Step, OllamaCritic

plan = Plan(goal="Refund customer C-42 for damaged item",
            steps=[
                Step(tool="tickets.read",   args={"id": "T-9001"}),
                Step(tool="refunds.issue",  args={"customer_id": "C-42",
                                                  "amount_gbp": 180}),
                Step(tool="email.send",     args={"to": "c-42@example.com",
                                                  "template": "refund_done"}),
            ])

critic = OllamaCritic(model="nail-reason:v3.1")
result = critic.critique(plan, world={"customer_balance_gbp": 0,
                                       "today_refund_total_gbp": 320})

if result.risk >= 0.7:
    raise SystemExit(f"plan rejected: {result.summary}")
elif result.risk >= 0.4:
    request_human_review(result)
else:
    execute(plan)
```

CLI:

```bash
nail-foresight critique --plan plan.json
nail-foresight critique --plan plan.json --model nail-reason:v3.1 --threshold-hold 0.4
```

## Status

v0.1.0 — Plan / Step datamodel, OllamaCritic (HTTP via stdlib `urllib`),
heuristic JSON extraction, CLI, mock-driven tests. Ollama is optional at
import time — the pure-Python `HeuristicCritic` works with no LLM at all
(slower to develop but useful for tests / CI).
