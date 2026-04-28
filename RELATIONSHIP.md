# RELATIONSHIP.md — NAIL Institute ↔ Neuravant Insurance

> **Read this first** if you're trying to understand why there are *two*
> repositories that both talk about "certifying AI agents."
> Last updated: 2026-04-28.

---

## The one-line answer

**NAIL Institute is the research arm. Neuravant Insurance is the
commercial product.** They are two halves of the same company —
*Neuravant AI Limited* — with deliberately different jobs, cadences,
and audiences. Neither is a duplicate of the other; they are
**upstream and downstream** of each other.

---

## Who does what

|                          | NAIL Institute (this repo)                    | Neuravant Insurance (`/Neuravant Insurance/`)        |
|--------------------------|-----------------------------------------------|------------------------------------------------------|
| **Mission**              | Discover *how agents fail* and prove it       | Certify, price, and insure agents in market          |
| **Output**               | Papers, AVE entries, model weights, threat taxonomies, reference implementations | Cert PDFs/JSON, premiums, claims, monitoring telemetry, regulatory submissions |
| **Audience**             | Researchers, peer reviewers, OSS, regulators reading papers | Customers, brokers, carriers (Hiscox), regulators (FCA, EU AI Act) |
| **Hardware**             | NVIDIA DGX Spark — 24/7 experiments, model training | Cloud Run / FastAPI — customer-facing portal         |
| **Cadence**              | Slow, exploratory, multi-experiment arcs      | Fast, contractual, SLAs and 90-day re-cert clocks    |
| **Failure mode**         | "We didn't catch a new attack class"          | "We mispriced a policy / missed a runtime breach"    |
| **Repo posture**         | Open-ish, citable, IP source                  | Commercial, audited, customer-private                |
| **Revenue**              | None directly (it is the moat)                | All of it — SaaS + insurance premium                 |

---

## The architectural picture

```
       NAIL INSTITUTE  (R&D — this repo)             NEURAVANT INSURANCE  (commercial)
     ┌─────────────────────────────────┐           ┌──────────────────────────────────┐
     │ DGX Spark experiments           │           │ nail_server.py (FastAPI portal)  │
     │ Arena (24/7 self-play)          │           │ Diagnostic engine (7 dimensions) │
     │ AVE database (threat catalogue) │  ────▶    │ Cert generator + public registry │
     │ apex (System 1/2 brain)         │  AVE      │ Policy engine + premium calc     │
     │ foresight (pre-flight critic)   │           │ NAIL SDK (runtime monitor)       │
     │ nail-reason / nail-guard models │  ────▶    │ Stripe + claims + bordereaux     │
     │ Guardian-7B (planned)           │  models   │ Hiscox / FCA / EU AI Act packs   │
     │ Papers, theory, threat taxa     │           │ Brokers + carriers + customers   │
     │ nail_harness (cert reference impl) │        │                                  │
     └────────────────┬────────────────┘           └────────────────┬─────────────────┘
                      │                                             │
                      │       ◀── runtime telemetry ──              │
                      │     (real-world failures from               │
                      │      SDK-deployed customers)                │
                      └─────────────────────────────────────────────┘
                                  THE DATA FLYWHEEL
```

That bottom arrow is the moat. Insurance's deployed SDK produces
real-world failure telemetry → the Institute uses it to invent
next-generation defences → Insurance sells them. Each side
strengthens the other; neither side competes with the other.

---

## Why `apex/` lives here, not there

`apex/` (the Kahneman-style System 1 / System 2 cognitive front-end,
formerly drafted as "apex_matrix") was added to the Institute
deliberately, not by accident. The reason is **cost**:

- Cloud-hosted certification of even a few thousand customer agents
  per month would burn API budget that no early-stage MGA can absorb.
- The DGX Spark is already paid for, idle most nights, and can run
  Ollama-served models at zero marginal token cost.
- `apex/` + `arena/` + `foresight/` + `nail_harness/` is
  a **complete local certification pipeline** that doesn't touch a
  paid API endpoint — so the Institute can dry-run the same workload
  Insurance would otherwise have to bill for.

In short: `apex/` is here so the Institute can act as a **local
load-bearing rehearsal floor** for Insurance — running thousands of
candidate cert workloads against research models before Insurance
commits to running the real, signed, billable cert against a customer.

This is also why `arena.run_for_cert()` and `foresight.run_for_cert()`
shims exist (commit `(b)`): they give the local pipeline the same
shape the production pipeline expects, so a workload that runs on the
DGX runs unchanged when Insurance later wants to lift it into
production.

**Cost moat, not feature duplication.**

---

## What lives where (canonical map)

### Lives in NAIL Institute (this repo)

- **DGX-bound research:** `experiments/`, `paper/`, `quantum_*`, `MI-theories.md`, `theory5.md`
- **Threat catalogue & adversary research:** `ave/`, `ave-database/`, `arena/`, `ctf/`, `horizon/`, `threatfeed/`, `Agent-CVE.md`
- **Model R&D & gating:** `nail_harness/models.py`, `MODEL_STATUS.md`, `scripts/local_llm/`, `nail-reason` / `nail-guard` Modelfiles
- **Local cognitive stack:** `apex/`, `foresight/`, `dese/`, `nail_monitor/`, `shield/`, `rmap/`
- **Cert *reference implementation*:** `nail_harness/cert_pipeline.py`, `cli_certify.py`, `cli_collect.py`, `cert_collectors.py`, `thresholds.json`, `CERTIFICATION_THRESHOLDS.md`, `scripts/inspect_cert.py`
- **Operator demonstrators:** `CLIENT_INTAKE.md`, `CLIENT_ONBOARDING.md`, `scripts/demo_certify.sh`, `nail_harness/client_config.example.yaml`
- **Post-mortems & specs:** `POST_MORTEM_M9_M13_1.md`, `M17_SPEC.md`
- **Public-facing research artefacts:** `public-repo/`, `ebook/`, `press/`

### Lives in Neuravant Insurance (separate workspace)

- **Customer portal:** `nail_server.py`, `website/` (multi-language en/de/es/fr)
- **Production cert engine:** `nail/cert_generator.py`, `nail/registry.py`, `nail/judge.py`
- **7-dimension diagnostic:** SSR + OSR + CRR + AHR + ECR + TSR + SLR
- **Insurance product:** `nail/policy_engine.py`, `nail/claims.py`, `nail/payments.py`, `nail/compliance.py`, `nail/bordereaux.py`
- **Runtime SDK:** `packaging/neuravant-enforce/`, `nail-sdk-js/`
- **Commercial onboarding:** broker pack, FCA submission, Hiscox NDA, GTM playbook
- **Brand & legal:** trademark filing, badge, terms, DPA, SOC2 readiness

---

## How the two sides hand off

There is exactly **one** load-bearing handoff today, and it is informal:

> **Institute certifies a model → Insurance trusts the model is safe to use.**

Specifically: when `MODEL_STATUS.md` in this repo says
`nail-reason:v5.1` is `certified=True`, Insurance is implicitly
trusting that. Today this trust is by convention. As soon as there is
a paying customer and a real claim event, that boundary will need to
be **formal** — a signed model passport that Insurance reads before
each cert run.

That formalisation is *not yet built* and is the most important piece
of plumbing you don't have. It belongs in Insurance, but the *spec*
for the passport belongs here.

---

## What does *not* cross the boundary

To prevent a slow drift into one big tangled stack:

- **Customer data never touches the Institute.** Every customer agent,
  endpoint, signed cert, and premium calculation lives in Insurance.
  The Institute sees only anonymised aggregate telemetry (the data
  flywheel arrow above).
- **Production cert decisions never come from the Institute.**
  `nail_harness/cli_certify` exists to *demonstrate* the cert format
  and to run *research-grade* certs internally. It is **not** what
  Insurance hands to a customer. Insurance has its own
  `cert_generator.py` for that.
- **Insurance does not import from the Institute** as a Python
  dependency today, and probably should not. The right coupling is
  **spec compliance**, not code coupling: both sides implement the
  same canonical-JSON-plus-sha256 cert format, but each side owns its
  own implementation.

---

## When confusion strikes, ask these three questions

1. **Who is the audience?** A customer / broker / carrier → it's an
   Insurance concern. A researcher / paper reviewer / OSS user → it's
   an Institute concern.
2. **Is money or a contract attached?** If yes, it lives in Insurance.
   If no, it can live in either, but defaults to the Institute.
3. **Does it need to be reproducible on the DGX with no API spend?**
   If yes, it lives in the Institute (that's the whole point of
   `apex/` + the local cognitive stack).

---

## Things that do *not* need to happen

To save anyone's reflex urge to "tidy this up":

- ❌ Do **not** merge the two repos.
- ❌ Do **not** move `nail_harness` into Insurance. It is the open
  reference implementation that gives the cert format its
  "anyone-can-verify" property; that's a research/IP asset.
- ❌ Do **not** delete the production cert engine in Insurance to
  "use the Institute's instead." They serve different audiences with
  different SLAs. Two implementations of one spec is the *right*
  number for a rating-agency play.
- ❌ Do **not** move `CLIENT_INTAKE.md` / `CLIENT_ONBOARDING.md` to
  Insurance. They're useful here as a research-grade demonstrator of
  what an operator-mediated cert workflow looks like. Insurance
  already has its own commercial onboarding.

---

## TL;DR for any future contributor

> *NAIL Institute = the lab.*
> *Neuravant Insurance = the shop.*
> *The lab invents what the shop sells.*
> *The shop's customers tell the lab what to invent next.*
>
> If you're not sure where something belongs, default to the lab —
> and only promote it to the shop when a customer is paying for it.

---

*Owner: NAIL Institute (Neuravant AI Limited).*
*If this document and the code disagree, the code wins, and this doc
needs updating.*
