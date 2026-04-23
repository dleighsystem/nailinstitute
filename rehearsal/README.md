# NAIL Rehearsal

> Sandbox dry-run. The fourth package of the NAIL **BEFORE** stack
> (after `diagnostic/`, `shield/`, `arsenal/`).

## Why

`arsenal/` answers *"is the agent allowed to call this tool with these args?"*
**Rehearsal answers a stricter question first**: *"if we let this call run,
what would actually happen — and is the resulting world acceptable?"*

The pattern is borrowed from chaos engineering and database migrations:
**execute against a shadow environment, diff the side effects, decide.**

```
agent.tool("refunds.issue", amount_gbp=180, customer_id="C-42")
                │
                ▼
        ┌───────────────┐
        │  Rehearsal    │   1. snapshot world state
        │   sandbox     │   2. run shadow impl
        └──────┬────────┘   3. compute diff
               │
        ┌──────▼────────┐
        │  Verdict      │   ALLOW    →  proceed to real call
        │  policy       │   HOLD     →  flag for human review
        └──────┬────────┘   DENY     →  reject + emit event
               │
        ┌──────▼────────┐
        │ real impl     │   only runs on ALLOW (or HOLD-with-confirm)
        └───────────────┘
```

## Quick start

```python
from rehearsal import Sandbox, requires_rehearsal, Verdict

sandbox = Sandbox()

@sandbox.shadow("refunds.issue")
def shadow_issue(*, amount_gbp, customer_id, **_):
    # cheap pure-Python model of the side-effect; NO real I/O.
    return {"refund_id": "shadow-rfnd", "delta_gbp": -amount_gbp,
            "customer_balance_after": -amount_gbp}

@sandbox.policy("refunds.issue")
def refund_policy(args, shadow_result, world):
    if shadow_result["delta_gbp"] < -200:
        return Verdict.deny("over single-call cap of £200")
    if shadow_result["delta_gbp"] < -50:
        return Verdict.hold("over warning threshold £50")
    return Verdict.allow()

@requires_rehearsal("refunds.issue", sandbox=sandbox)
def issue_refund(amount_gbp, customer_id):
    # only runs when verdict is ALLOW (or HOLD passed with --force-confirm)
    return real_call(...)
```

CLI:

```bash
nail-rehearsal replay recordings/run-42.jsonl     # dry-replay a captured trace
nail-rehearsal verdict-table                       # show recent verdicts
```

## Status

v0.1.0 — sandbox, world-state snapshots, recorder, policy registry, replayer,
in-memory ledger, CLI. Pure stdlib.
