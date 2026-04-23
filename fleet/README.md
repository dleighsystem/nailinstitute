# NAIL Fleet (R0)

> Telemetry roll-up across deployed agents.
> Sister-package to `shield/`, `arsenal/`, `foresight/`, `rehearsal/`,
> `threatfeed/`. Lives **outside** the agent loop — agents *push*
> events, fleet *aggregates* and *queries*.

## Why

Each NAIL package emits structured signals:

| package      | signal                                |
|--------------|---------------------------------------|
| `shield/`    | sanitisations, blocks                 |
| `arsenal/`   | token mints, denials                  |
| `foresight/` | plan critiques (verdict + risk)       |
| `rehearsal/` | sandbox verdicts (allow/hold/deny)    |
| `threatfeed/`| advisories observed                   |
| harness      | step latencies, errors                |

A single agent's signals are useful. A **fleet's** signals are diagnostic
gold: which agent class trips arsenal denials most? Which tool pattern
gets HOLD'd by foresight? Are advisory rollouts correlated with cert-fail
spikes?

```
agent A ┐
agent B ├─► fleet.Ingest ─► sqlite events ─► fleet.RollUp ─► query / CLI / dashboard
agent C ┘
```

## R0 scope

* `Event` dataclass: agent_id, kind (str), severity, ts, attrs (json).
* `Store` (SQLite, file-backed; in-memory for tests).
* `Ingest.record(event)` — append-only.
* `RollUp` — `by_agent`, `by_kind`, `by_severity`, `top_tools`,
  `time_window`, `verdict_distribution`.
* `Heartbeat` — agent registers + last-seen tracking.
* `nail-fleet` CLI: `ingest`, `roll-up`, `agents`, `tail`, `export`.

## Quick start

```python
from fleet import Store, Ingest, RollUp, Event

store = Store(":memory:")
ingest = Ingest(store)
ingest.record(Event(agent_id="refund-bot-1", kind="foresight.verdict",
                    severity="info", attrs={"verdict": "hold", "risk": 0.65}))

rollup = RollUp(store)
print(rollup.verdict_distribution(kind="foresight.verdict"))
# {'hold': 1}
```

CLI:

```bash
nail-fleet ingest --event '{"agent_id":"a","kind":"shield.block","severity":"warn"}'
nail-fleet roll-up --by agent
nail-fleet agents
nail-fleet tail --kind foresight.verdict --limit 20
```

## Status

R0 — single-process SQLite store, push API, basic queries, CLI. R1 will
add HTTP ingest, retention policies, and signed events (via
`arsenal.signing`).
