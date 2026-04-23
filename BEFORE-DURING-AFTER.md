# Stopping Bad Actions BEFORE They Occur — NAIL's Proprietary Pre-Action Defence

> Deep-research strategy doc for closing the **BEFORE** layer of the NAIL
> protection lifecycle, benchmarked against and designed to surpass
> [Execlave](https://www.execlave.com/) (v.2026.04).
>
> Companion docs: `lifecycle-defense.md` (Day-2/post-deployment),
> `container-isolation.md` (compute–cognition entanglement),
> `Agent_Threat_Landscape.md`, `Agent-CVE.md`, `MCP1.md`, `horizon.md`.

---

## §0  TL;DR

| Lifecycle phase | What it does | NAIL today | Execlave |
|---|---|---|---|
| **BEFORE** — block bad actions before they form | Pre-deployment certification, prompt-time neutralisation, intent forecasting, capability provisioning, blast-radius simulation, threat-feed precompilation | Partial (`DiagnosticPipeline` cert only) | **None** — they start at runtime gate |
| **DURING** — block bad actions as they execute | Inline guard, runtime monitor, kill-switch | `nail-guard:v4` + `nail_monitor` + `nail_harness` | Their entire product (~20 ms gate) |
| **AFTER** — investigate, claim, learn | Forensics, claims, AVE database, retraining feedback | `ave/` + `ave-database/` + `arena/` + `canary/` + insurance underwriting | Audit logs only |

**The Execlave gap:** they intercept the agent's **already-formed action** at the
last possible moment ("agent decided to call `db.query('DROP TABLE...')` →
deny"). By that point, the model has *already been compromised*; they only
prevent the resulting damage. They have **no proactive defence** — no
pre-deployment hardening, no prompt-time injection neutralisation, no agent-side
training, no risk transfer. They are an enforcement firewall, not a
protection system.

**NAIL's proprietary BEFORE layer** attacks the problem **four steps earlier**:

1. **Pre-deployment** — issue or refuse the AAA/AA/A certificate based on
   `DiagnosticPipeline` results. No cert, no production. (We have this; needs
   extension into a deployment gate.)
2. **Prompt-arrival** — `nail-shield` neutralises injection at the
   token/structure level *before* the model sees it.
3. **Intent-forecasting** — `nail-foresight` reads the agent's planning
   chain-of-thought and predicts the next action's risk class **before** the
   action token is emitted.
4. **Capability-provisioning** — `nail-arsenal` issues short-lived,
   attribute-attested tool tokens so the agent literally *cannot* call a
   tool it wasn't pre-authorised for in this session.
5. **Blast-radius simulation** — `nail-rehearsal` dry-runs every novel action
   in a containerised twin before it touches production, and replays
   threatfeed CVE-of-the-day patterns daily.

Combined with the existing DURING (`nail-guard:v4`) and AFTER
(`ave/` + insurance) layers, this gives us the only end-to-end
**before / during / after / underwrite** stack on the market.

---

## §1  Strip-down of Execlave

Sources: their landing page, `/about`, `/security`, `/blog` (April 2026).

### 1.1 What they actually are

> "Execlave is the enforcement infrastructure that sits between your AI agents
> and the real world — making sure they cannot do anything your company hasn't
> explicitly allowed."

Architecturally:

```
agent.run()
   │
   ▼
   intent (e.g. "tool_call: db.query, args=…")
   │
   ▼   [Execlave ~3–25 ms]
   ┌──────────────────────────────────┐
   │  semantic check · policy eval     │ → PASS / HOLD / DENY
   │  audit log (SHA-256 chained)      │
   └──────────────────────────────────┘
   │
   ▼ if PASS
   real-world call
```

### 1.2 Their capability inventory (verbatim from the site)

- Runtime policy engine, **p50 < 20 ms**
- **11** built-in policy types (cost limit, model restriction, content filter,
  prompt-injection guard, PII block, etc.)
- **3-line SDK** (`@trace` decorator, Python + TS)
- Kill switch < 15 ms
- Append-only Postgres logs with SHA-256 hash chain + RSA-SHA256 signed exports
- Tenant isolation via Postgres RLS, AES-256 at rest, TLS 1.2+ in transit
- 3 outcomes: PASS / HOLD (human review) / DENY
- Compliance alignment with **7** frameworks (SOC 2 / HIPAA / GDPR / ISO 27001 /
  EU AI Act / PCI DSS / NIST AI RMF)
- Cloud-managed *or* self-hosted (Docker Compose / k8s, air-gap compatible)
- Dashboard with traces, costs per agent, kill button

### 1.3 Their stated principles (from `/about`)

1. **"Enforcement over observation"** — block, don't just log
2. **"Compliance by architecture"** — audit evidence as a byproduct
3. **"Speed is non-negotiable"** — < 20 ms or it gets bypassed

These are good principles. They also bound their entire product: it is a
*runtime gate with a beautiful audit trail*. Nothing more.

### 1.4 Structural weaknesses (where NAIL must be better)

| # | Weakness | Why it matters |
|---|---|---|
| **W1** | **Reactive, not proactive.** Sees the agent's *already-formed* tool call. By then the model is compromised. | A clever injection that phrases exfiltration as a legitimate-looking query passes their static policy engine. They block obvious bad calls; they do not detect *intent shift*. |
| **W2** | **Static policy DSL** (regex / JSON Schema / cost limits). | Cannot reason semantically about *combinations* of allowed actions that compose into a forbidden outcome (e.g. read row + send email = exfil). |
| **W3** | **No pre-deployment certification.** Assumes the agent is already in production. | Customers ship untested agents; Execlave catches issues only when they fire. NAIL refuses the certificate and the agent never ships. |
| **W4** | **No model-side defence.** They do not harden the agent itself. | A locally-fine-tuned, attack-resistant agent (which is what `nail-guard` enables) is structurally safer than a vulnerable agent behind a gate. Defence-in-depth requires both. |
| **W5** | **No risk transfer.** They sell governance, not insurance. | When their gate misses something (it will — it's <20 ms semantic checks against a clever attacker), the customer eats the loss. NAIL's PolicyDraft underwrites the residual risk. |
| **W6** | **No adversarial feedback loop.** Logs are forensic, not training data. | Every blocked attempt is a free, real-world adversarial sample. Execlave throws it into Postgres and never closes the loop. NAIL's `arena/` + AVE pipeline retrains on every miss. |
| **W7** | **No threat-feed integration.** They ship 11 generic policy types. | Yesterday's CVE-of-the-day is tomorrow's silent breach. NAIL's `threatfeed/` package can pre-compile defences for novel patterns within hours. |
| **W8** | **No blast-radius simulation.** The first time a novel action runs, it runs against production. | NAIL `nail-rehearsal` (proposed) executes the action in a sandboxed twin first; if the simulation breaches policy, the production call is denied without ever firing. |
| **W9** | **Single-agent perspective.** Their dashboard tracks individual agents. | Agentic risks are increasingly emergent across *fleets* (cf. `lifecycle-defense.md` Frontier 2 — "Multi-Tenant Contagion"). NAIL must monitor R₀ of malicious logic across an agent population. |
| **W10** | **Compliance-as-marketing.** "Designed to align with" SOC 2/ISO/EU AI Act — they explicitly note they hold **no formal certifications**. | NAIL's certificate is itself the compliance artefact (model_id, deployment_scope, dimension_summary, premium = signed evidence package). |

These ten gaps are the entire opportunity space.

---

## §2  NAIL inventory — what we already have

```
BEFORE   ┌─ DiagnosticPipeline (diagnostic/)        — pre-deployment scoring, AAA/AA/A
         │  PolicyDraft (diagnostic/rating.py)     — premium + coverage limit
         │  threatfeed/                              — feed scaffold (mostly empty)
         └─ ATTACK_LIBRARY (21 scenarios, 6 dims)

DURING   ┌─ nail-guard:v4 (CERTIFIED, 80% acc, 0% bypass, 5.4s p95)
         │  nail-reason:v3.1 (verbose narrative judge; v5 in training)
         │  nail_harness/ — guard/judge orchestration, certify_ollama, judge_loop
         │  nail_monitor/ — runtime monitor scaffold
         │  canary/       — pre-deploy red-team agents
         └─ container-isolation theory (theory not yet code)

AFTER    ┌─ ave/  + ave-database/ — AVE schema, severity index, signed cards
         │  arena/    — adversarial sparring of guard vs attacker
         │  ctf/      — capture-the-flag forensics
         │  rmap/     — remediation mapping
         │  PolicyDraft.to_dict() → certificate JSON
         └─ scripts/run_local_certification.py — live agent → cert → premium
```

**Strengths**: `nail-guard:v4` is the model-side defence Execlave doesn't have.
The AVE database + insurance underwriting is the risk transfer Execlave can't
offer. The DiagnosticPipeline is a working pre-deployment gate.

**Gaps to close** (the BEFORE layer, in priority order):

1. **Prompt-arrival neutralisation** — no `nail-shield` package yet
2. **Intent forecasting** — no `nail-foresight` package yet
3. **Capability provisioning** — no `nail-arsenal` package yet
4. **Blast-radius simulation** — no `nail-rehearsal` package yet
5. **Threatfeed → policy compiler** — `threatfeed/` is scaffold only
6. **Cert as deployment gate** — runner exists; needs CI/CD plug-in
7. **Fleet-level R₀ monitor** — extends `nail_monitor` to populations

---

## §3  Designing the proprietary BEFORE layer

> Five components. Each one is something Execlave structurally cannot do.

### 3.1  `nail-shield` — prompt-arrival neutralisation

**Problem.** The single biggest agentic vulnerability is prompt injection
embedded in *agent inputs* — emails, tickets, scraped pages, RAG chunks, tool
return values. Execlave catches the *consequence* (the malicious tool call);
NAIL must neutralise the *cause* (the injection text) before it ever reaches
the model.

**Mechanism.**

```
untrusted_input ──▶ nail-shield ──▶ sanitised_input ──▶ agent
                       │
                       ├── 1. Structural canonicalisation
                       │     • strip zero-width chars, RLO/LRO bidi
                       │     • normalise unicode (NFKC), collapse whitespace
                       │     • detect & quote nested control sequences
                       │
                       ├── 2. Provenance wrapping
                       │     • every untrusted span is wrapped:
                       │       <UNTRUSTED src="email:abc@x.com" id="u-7f3">
                       │         …content…
                       │       </UNTRUSTED>
                       │     • the agent system prompt is trained to *never*
                       │       follow instructions from inside <UNTRUSTED> tags
                       │
                       ├── 3. Injection classifier
                       │     • nail-guard:v4 in "input mode" — classifies
                       │       each span; high-confidence injections → quoted
                       │       AND flagged to nail-foresight
                       │
                       ├── 4. Secret scrub
                       │     • PII / API keys / credentials redacted with
                       │       reversible tokens (so legitimate workflows
                       │       still work via post-hoc rehydration)
                       │
                       └── 5. Hash + chain
                             • sha256(input_canonical) appended to AVE
                               evidence chain — every later action can be
                               cryptographically tied back to its source
```

**Why this beats Execlave.** Their `prompt_injection_guard` is a runtime
content filter on outputs. `nail-shield` is a structural sanitiser at the
input boundary, with provenance preservation that Execlave's three-line SDK
cannot provide because they never see the inputs — only the resulting tool
calls.

**Implementation.** New top-level package `shield/`, modelled on `diagnostic/`:

```
shield/
  pyproject.toml
  shield/
    __init__.py
    canonicaliser.py     — unicode/bidi/zero-width
    provenance.py        — UNTRUSTED tag wrapper + parser
    classifier.py        — wraps GuardClient(nail-guard:v4) for input mode
    secret_scrub.py      — regex + entropy + reversible tokenisation
    chain.py             — append-only hash chain (compatible with AVE)
    cli.py               — `nail-shield process --input email.txt`
  tests/
```

**Latency budget.** < 50 ms per input span (canonicaliser ~1ms, classifier
~30ms via local guard, scrub ~5ms, chain ~1ms).

---

### 3.2  `nail-foresight` — intent forecasting

**Problem.** Even with sanitised inputs, an agent's *planning trace* (the CoT
or scratchpad) reveals intent **before** the final action token is generated.
A 7B model planning to exfiltrate data emits diagnostic tokens (e.g. "I should
encode this as base64", "let me bypass the…") that are never observed by
Execlave because Execlave only sees the final tool call.

**Mechanism.**

```
agent.scratchpad += new_tokens
        │
        ▼  (every K tokens, async)
   nail-foresight (small classifier head, 1B params, distilled
   from nail-guard:v4 on AVE planning traces)
        │
        ├── predict P(next_action_class) ∈
        │     {benign, exfil, privilege_escalation, deletion,
        │      cost_runaway, manipulation, recursion_bomb, …}
        │
        ├── if max_p > 0.85 on a forbidden class:
        │     → emit pre-emptive HOLD signal to the agent runtime
        │     → preserve scratchpad to AVE
        │     → notify nail_monitor (fleet view)
        │
        └── if 0.5 < max_p < 0.85:
              → escalate to full nail-guard:v4 on the partial trace
              → optionally inject "self-correction" steering prompt
                 ("Reconsider: does this action align with your role?")
```

**Why this beats Execlave.** Their gate is at the *action* boundary; ours is
at the *thought* boundary. We can stop the agent **before it commits to the
intent**, not just before it executes it. The "self-correction" steering arm
is also unique — it lets a marginal-risk plan be redirected without a hard
stop, which Execlave cannot do because they don't see the planning chain.

**Training data.** Already partially captured: `experiments/database.json`
contains thousands of traces from Round-1 and Round-2 experiments where agents
were observed planning malicious actions. Distil into a 1B classifier
(Qwen2.5-1.5B-Instruct → LoRA → INT4 GGUF, ~600 MB on disk, 5 ms/inference on
the DGX).

**Implementation.** New package `foresight/`, ships as `nail-foresight:v1`
Ollama tag. Hooks into `nail_monitor` via async callback.

---

### 3.3  `nail-arsenal` — capability provisioning

**Problem.** Execlave's policies are *negative* ("agent X cannot call tool Y").
This is unmaintainable: the universe of forbidden combinations is infinite.
NAIL inverts this — agents start with **zero capabilities**; tools must be
issued per-session as short-lived attested tokens.

**Mechanism.**

```
At session start:
   ┌─────────────────────────────────────────────────┐
   │  Session Manifest                                │
   │   agent_id:    customer-support-v2               │
   │   user_id:     u-123 (verified via OIDC)         │
   │   scope:       refund_processing                 │
   │   tools_requested: [tickets.read, refunds.issue] │
   └─────────────────────────────────────────────────┘
        │
        ▼  nail-arsenal (policy compiler)
   ┌─────────────────────────────────────────────────┐
   │  Issued Capability Tokens (each ed25519-signed)  │
   │   t1: tickets.read    — 30 min, max 50 calls     │
   │   t2: refunds.issue   — 30 min, max £200 cumul.  │
   │                          requires HOLD ≥ £50     │
   └─────────────────────────────────────────────────┘
        │
        ▼  agent runtime
   any tool call WITHOUT a valid token → DENY at the SDK level,
   never reaches the network. The agent is structurally incapable of
   calling refunds.delete because no token for it was ever minted.
```

**Why this beats Execlave.** Their default is "everything allowed unless
policy says no". Ours is "nothing allowed unless explicitly minted". This is
the same shift that gave us containers vs. bare-metal: a categorically smaller
attack surface. Plus, capability tokens carry their own audit context, so the
AVE chain has cryptographic proof of *who authorised this session to do this*.

**Implementation.** New package `arsenal/`. Token format: JWT-like with
ed25519, `aud=<tool>`, `sub=<agent_session>`, `exp`, `cnf` (proof-of-possession),
plus NAIL-specific claims:

```json
{
  "tool": "refunds.issue",
  "limits": {"calls": 5, "cumulative_gbp": 200},
  "conditions": [{"op": "hold_above_gbp", "value": 50}],
  "issuer": "nail-arsenal:1",
  "ave_chain_id": "..."
}
```

SDK shim wraps existing tool functions and rejects without a valid token.

---

### 3.4  `nail-rehearsal` — blast-radius simulation

**Problem.** The first time a novel action runs in production, it runs in
production. If it's destructive, you find out by losing data. Execlave can
DENY it, but they don't know it's destructive without a policy that already
covers it — and zero-day actions never have a pre-existing policy.

**Mechanism.**

```
agent emits action A
        │
        ▼  nail-arsenal validates token  ✓
        ▼  nail-rehearsal asks: have we seen this action shape before?
        │
        ├── if YES (cached, low-risk) → forward to production
        │
        └── if NO (novel) → fork into rehearsal twin:
               1. clone the relevant subset of state into ephemeral container
                  (using container-isolation primitives from existing doc)
               2. execute A against the twin
               3. measure side-effects:
                    • rows changed     • secrets touched
                    • external calls   • cost incurred
                    • file writes      • permission changes
               4. score blast radius vs. policy budget
               5. if within budget → forward to production
                  if exceeds       → DENY + write AVE incident card
```

**Why this beats Execlave.** They have no notion of *what an action will do*
before it runs. They have a *policy* about what it's *allowed* to do. Those
are different things. A `db.query("UPDATE users SET email=?, ...")` looks
identical regardless of whether it touches 1 row or 10 million. NAIL
rehearses; Execlave assumes.

**Implementation.** New package `rehearsal/`. Heavy lift: requires generic
container twinning. v1 scope: the 6 most common destructive action classes
(SQL writes, file deletes, API POSTs, email sends, payment flows, IAM
changes). Use existing `container-isolation.md` thinking + Docker Compose
fixtures.

---

### 3.5  Threatfeed → policy compiler

**Problem.** The `threatfeed/` package is a scaffold. Real threat feeds
(MITRE ATLAS, AIID, AIAAIC, Huntr) ship daily disclosures. Execlave has no
mechanism to ingest these into runtime policies. NAIL must close that loop in
hours, not quarters.

**Mechanism.**

```
daily cron:
   ┌── pull MITRE ATLAS, Huntr LLM bugs, AIID new entries
   ├── pull internal arena/ logs for new attack patterns observed last 24 h
   ├── for each new pattern:
   │     1. AVE-classify → severity index
   │     2. synthesise an attack scenario (auto-write a probe like
   │        ATTACK_LIBRARY entry)
   │     3. run against current production agents in canary/ fleet
   │     4. if any agent fails → emit shield/foresight rule update
   │     5. open a Pull Request against shield/rules/ with the new pattern
   └── publish to ave-database/cards/ for AVE consumers
```

**Why this beats Execlave.** They have no public mechanism to update their 11
policy types. They are static; we are continuously self-updating. By the time
a CVE is publicly disclosed, NAIL agents already have a defence shipped.

**Implementation.** Extend `threatfeed/threatfeed/`:

```
threatfeed/
  ingestors/
    mitre_atlas.py
    huntr.py
    aiid.py
    arena_internal.py
  synthesiser.py        — pattern → AttackScenario
  compiler.py           — AttackScenario → shield/foresight/arsenal rules
  publisher.py          — push to ave-database + git PR
```

---

### 3.6  Pre-deployment cert as a hard gate

**Problem.** `scripts/run_local_certification.py` produces a certificate but
nothing enforces its presence at deployment time. An ungraded agent can ship.

**Mechanism.**

- Ship a `nail-deploy` CLI: `nail-deploy push --agent my-agent --cert ./cert.json`
- The CLI validates: cert is signed, scope matches, composite ≥ minimum for
  the tier requested, cert age ≤ 30 days, model digest matches.
- Without a passing cert → deployment refused.
- GitHub Action / GitLab CI templates that wrap this — drops into existing
  agent CI/CD with one workflow file.

**Why this beats Execlave.** They onboard agents post-hoc with a `@trace`
decorator. Anything not decorated is invisible. NAIL refuses deployment of
uncertified agents at the orchestration layer — the gap is structurally
impossible.

**Implementation.** Add `scripts/nail_deploy.py` + GitHub Action template
under `.github/workflows/templates/nail-cert-gate.yml`.

---

### 3.7  Fleet-level R₀ monitor

**Problem.** From `lifecycle-defense.md` Frontier 2 — agents in a fleet can
infect each other. Execlave's dashboard is per-agent. They cannot see
contagion.

**Mechanism.** Extend `nail_monitor/` with a population-level layer:

- Embed every agent action (sanitised) into a 384-dim space (existing local
  embedder)
- Maintain a rolling 24-h centroid per agent
- When two agents' centroids drift toward each other AND a contagion-pattern
  classifier fires → quarantine signal
- R₀ = average number of agents an "infected" agent transmits a malicious
  pattern to within a 24-h window. Target: R₀ < 0.3.

**Implementation.** `nail_monitor/fleet.py` + a Grafana panel / simple
dashboard.

---

## §4  Engineering plan

### 4.1  Package map (target end-state)

```
NAIL Institute monorepo
├─ shield/         🆕  BEFORE — prompt-arrival neutralisation
├─ foresight/      🆕  BEFORE — intent forecasting (1B distilled model)
├─ arsenal/        🆕  BEFORE — capability provisioning
├─ rehearsal/      🆕  BEFORE — blast-radius simulation
├─ threatfeed/     🟡  BEFORE — extend ingestors + compiler
├─ diagnostic/     ✅  BEFORE — already does cert + premium
├─ nail_harness/   ✅  DURING — guard/reason orchestration
├─ nail_monitor/   🟡  DURING — extend with fleet/R₀
├─ canary/         ✅  DURING — pre-deploy red-team
├─ ave/ + ave-database/  ✅  AFTER — schema + signed cards
├─ arena/          ✅  AFTER — adversarial sparring
├─ ctf/            ✅  AFTER — forensics
├─ rmap/           ✅  AFTER — remediation mapping
└─ integration/    ✅  ALL — agent connector + pipeline
```

### 4.2  Milestones

| # | Milestone | Output | Effort | Unblocks |
|---|---|---|---|---|
| **M0** | Finish R5 reason DPO+export (already in flight) | `nail-reason:v5` | resume from saved SFT ckpt, ~1 h | — |
| **M1** | Run real-agent certs (trading-expert, uk-legal-llm-v3, code-analyzer) | 3 cert JSONs + premium table | 30 min after R5 | Demo material |
| **M2** | `shield/` v0 — canonicaliser + provenance + classifier wrapper | new package, 4 modules, tests | 1 day | All BEFORE work depends on this |
| **M3** | `foresight/` v0 — distil 1B classifier from AVE planning traces | `nail-foresight:v1` Ollama tag | 1–2 days (training run) | Pre-emptive HOLD |
| **M4** | `arsenal/` v0 — capability tokens + SDK shim | ed25519 minter + verifier + Python SDK shim | 2 days | Eliminates W1 |
| **M5** | `rehearsal/` v0 — twin-execute SQL writes + API POSTs (2 of 6 classes) | container twin runner | 3 days | Eliminates W8 |
| **M6** | `threatfeed/` ingestors live (MITRE ATLAS + arena internal) | daily cron + PR-emitting compiler | 2 days | Auto-defence |
| **M7** | `nail-deploy` cert-gate CLI + GitHub Action template | `scripts/nail_deploy.py` + workflow YAML | 1 day | Closes the deployment hole |
| **M8** | `nail_monitor/fleet.py` + R₀ dashboard | population-level monitor | 2 days | Eliminates W9 |
| **M9** | Marketing page comparing NAIL stack vs. Execlave | `press/nail_vs_execlave.md` + chart | 0.5 day | Sales |

Total: ~2 working weeks to a complete, demonstrably-superior pre-action
defence layer.

### 4.3  First commit (after this doc)

Create `shield/` skeleton. The very first piece of working code:

```
shield/shield/canonicaliser.py
    sanitise(text, *, source_id=None) -> CanonicalisedSpan
        - NFKC normalise
        - strip zero-width / bidi controls
        - collapse whitespace
        - return wrapped <UNTRUSTED src=...>...</UNTRUSTED>
```

This single function is more proactive defence than Execlave ships.

---

## §5  Positioning

When asked **"how is NAIL different from Execlave?"** the answer is:

> Execlave is a runtime gate. NAIL is the entire lifecycle.
>
> They protect you for the **3–25 ms window** when an agent's bad action
> reaches their gate. We protect you:
>
> - **Before** — the agent can't ship without our certificate, the prompts
>   it sees are sanitised at arrival, its plans are forecasted before
>   actions form, and its tools are minted per-session with cryptographic
>   limits.
> - **During** — our `nail-guard` runs *inside* the agent's reasoning, not
>   at its output boundary, so we catch attacks the gate cannot see.
> - **After** — every incident becomes an AVE record that retrains tomorrow's
>   guard, and the residual risk that any stack misses is **underwritten**
>   by our policy. They sell governance; we sell governance + risk transfer.
>
> Execlave's customers buy a firewall. NAIL's customers buy a closed loop.

---

## §6  Next action (immediate)

After R5 finishes and the three real-agent certifications complete, the very
next engineering work is **M2 — `shield/` v0**. It is the smallest piece of
the BEFORE layer with the largest immediate effect: every prompt entering
every agent gets a structurally hostile environment for injections, regardless
of which model the agent uses.

That single package alone makes us strictly better than Execlave on their
flagship value proposition (prompt-injection guard).

— *NAIL Institute, April 2026*
