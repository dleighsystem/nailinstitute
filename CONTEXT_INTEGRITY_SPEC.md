# NAIL Context Integrity Layer (CIL) — Specification

**Status:** Draft v0.1 · **Date:** 2026-06-03 · **Owner:** NAIL Institute (Neuravant AI Limited)
**Scope decision:** Detector + AVE pathology + diagnostic dimension. **NOT** a governed semantic catalog.

---

## 0. The one-paragraph version

Two agents querying the same enterprise data can produce contradictory answers
even when *neither is poisoned* — agent A defines `revenue` net-of-refunds, agent
B gross, both cite legitimate sources, both have clean provenance lineage. NAIL's
existing `TaintVault` proves **where** a fact came from and whether its trust was
laundered; it says nothing about whether two agents **mean the same thing** by a
term. CIL closes that gap by treating *definitional divergence* as a measurable,
insurable agent pathology — not by building the canonical dictionary itself.

---

## 1. Why this is a real gap (and what is NOT the gap)

### Already covered — do not rebuild
| Capability | Where it lives |
|---|---|
| Source attribution / provenance | [shield/shield/provenance.py](shield/shield/provenance.py), `<UNTRUSTED src=...>` |
| Meaning-level lineage (`derived_from`) | [shield/shield/taint_vault.py](shield/shield/taint_vault.py) |
| Trust-laundering detection (min-trust over ancestors) | `TaintVault.detect_laundering()` |
| Tamper-evident anchoring | `HashChain` ([shield/shield/chain.py](shield/shield/chain.py)) |
| Single-agent factual coherence | `RiskDimension.LOGIC`, `EPISTEMIC_CONTAGION` ([diagnostic/diagnostic/dimensions.py](diagnostic/diagnostic/dimensions.py)) |
| Hallucination / fabrication taxonomy | `Category.FABRICATION`, `Category.MEMORY` (AVE) |

### The actual hole
`TaintVault` checks **provenance integrity** (is this fact's trust honest?).
It does **not** check **semantic agreement** (do agents A and B use the same
definition of a shared term?). A fact can have a *perfect* trust lineage and
still be definitionally inconsistent with a sibling agent's fact. There is no
detector, no AVE card, and no diagnostic dimension for that.

### Non-goals (lane discipline — read this twice)
CIL **does not**:
- Own canonical definitions of business terms (that is Snowflake / dbt / Atlan).
- Resolve which agent is "correct" — only that they **disagree**.
- Enforce definitions at query time (that is a data-governance product, not a
  security/insurance one).

NAIL's defensible product is the **attestation**: an underwriting-grade,
evidence-backed statement that an agent fleet is — or is not — definitionally
consistent. Snowflake structurally cannot sell that; they *are* the data layer
being attested. We measure and insure the failure; we don't sell the dictionary.

---

## 2. Three deliverables

```
CIL = (A) AVE pathology card          → registers the failure mode
    + (B) DefinitionalDriftDetector   → detects it on top of TaintVault
    + (C) CONSISTENCY risk dimension  → prices it into the PolicyDraft
```

Each reuses an existing subsystem. No new top-level package.

---

## 3. (A) AVE Card — Semantic Fragmentation

Drop into the AVE registry as the next sequential ID (**AVE-2026-0037**;
current max is AVE-2025-0036). Conforms to `AVECard`
([ave/ave/schema.py](ave/ave/schema.py)).

```python
AVECard(
    ave_id="AVE-2026-0037",
    name="Semantic Fragmentation",
    aliases=("Definitional Drift", "Cross-Agent Term Divergence",
             "Schema Fragmentation"),
    category=Category.STRUCTURAL,      # fleet-level coherence failure
    severity=Severity.HIGH,           # silent: confident, contradictory answers
    status=Status.IN_PROGRESS,        # → PROVEN once exp39 lands (see §6)
    summary=(
        "Two or more agents in a fleet operate on divergent definitions of the "
        "same business term while each maintains clean provenance lineage. No "
        "agent is poisoned; the fleet is simply incoherent. Downstream "
        "consumers receive confident, mutually contradictory answers from the "
        "same underlying data."
    ),
    mechanism=(
        "Each agent resolves an ambiguous term ('revenue', 'active user', "
        "'churn') against a locally-scoped definition — from its system prompt, "
        "a RAG chunk, or a tool schema. Because definitions differ but "
        "provenance is individually valid, TaintVault's min-trust lineage check "
        "passes for every fact. The contradiction is INTER-agent, invisible to "
        "any single-agent integrity check."
    ),
    blast_radius=(
        "Financial reporting, risk aggregation, compliance attestations. In an "
        "insurance context: two underwriting agents pricing the same exposure "
        "differently because they disagree on a definition, not on the data."
    ),
    prerequisite=(
        "Multi-agent deployment; shared or overlapping data sources; at least "
        "one term with no enforced canonical definition."
    ),
    environment=EnvironmentVector(
        multi_agent=True, memory_required=True, rag_required=True,
    ),
    defences=(
        Defence(
            name="DefinitionalDriftDetector",
            layer="CIL — Context Integrity Layer",
            nail_monitor_detector="DefinitionalDriftDetector",
            notes="Cross-agent definition-fingerprint divergence scan over TaintVault.",
        ),
    ),
    cwe_mapping="CWE-1078 (Inconsistent representation)",   # nearest analogue
    related_aves=("AVE-2025-0001",),   # Memory Pollution — same symptom, different root
)
```

**Key positioning line for the AVE card and any external write-up:**
> Memory Laundering (AVE-2025-0001 family) is a *trust* failure with a *valid*
> definition. Semantic Fragmentation is a *definition* failure with *valid*
> trust. They are orthogonal — which is exactly why the existing stack misses it.

---

## 4. (B) DefinitionalDriftDetector

New module: `shield/shield/definitional_drift.py`. Operates **on top of**
`TaintVault` — it consumes facts, it does not replace the store.

### 4.1 Data model

```python
@dataclass(frozen=True)
class DefinitionFingerprint:
    term: str                 # normalised term, e.g. "revenue"
    agent_id: str             # which agent asserted this definition
    fact_id: str              # TaintVault fact this came from
    fingerprint: str          # stable hash of the *meaning*, not the text
    effective_trust: float    # pulled from TaintVault.effective_trust(fact_id)
    embedding: tuple[float, ...] | None = None   # optional semantic vector

@dataclass(frozen=True)
class DriftFinding:
    term: str
    agent_a: str
    agent_b: str
    divergence: float         # 0.0 (identical) … 1.0 (orthogonal)
    both_lineage_clean: bool  # TRUE = the dangerous case (no poisoning to blame)
    fingerprints: tuple[DefinitionFingerprint, DefinitionFingerprint]
    explanation: str
```

### 4.2 Fingerprinting strategy (two tiers, degrade gracefully)

1. **Structural fingerprint (offline, deterministic, default).** Extract the
   definitional clause for a term and reduce it to a canonical predicate set
   (e.g. `revenue := gross − refunds − chargebacks`). Hash the normalised
   predicate set. Catches the *crisp* divergences (different formula, different
   filter, different time window). Zero dependencies — matches the AVE package's
   "zero runtime dependencies" discipline.
2. **Semantic fingerprint (optional, when an embedding model is available).**
   Cosine distance between definition embeddings, thresholded. Catches *prose*
   divergence the structural tier misses. Gated behind a feature flag so the
   core detector stays offline and deterministic for CI.

> **Brutally honest limitation:** the structural tier needs a definition-extraction
> step (term → its asserted meaning). That extraction is itself an LLM call in the
> general case and is the part most likely to produce false positives/negatives.
> The spec keeps it pluggable (`extractor: Callable`) so it can start as a strict
> regex/grammar over structured definition records and only escalate to an LLM
> extractor where definitions are free-text. **Do not ship the LLM extractor as the
> default** — prove the deterministic path first (§6).

### 4.3 Detection algorithm

```python
class DefinitionalDriftDetector:
    def __init__(self, vault: TaintVault, *,
                 extractor: Callable[[TaintEntry], list[DefinitionFingerprint]],
                 divergence_threshold: float = 0.30):
        ...

    def scan(self) -> list[DriftFinding]:
        # 1. For every fact in the vault, extract (term -> fingerprint, agent).
        # 2. Group fingerprints by normalised term.
        # 3. For each term with >=2 distinct agents, compare fingerprints pairwise.
        # 4. Emit a DriftFinding when divergence > threshold.
        # 5. Tag both_lineage_clean = all(effective_trust >= VERIFIED for the pair).
        #    -> This is the SILENT, dangerous class: real divergence, no poisoning.
        ...
```

The `divergence_threshold` mirrors the existing `LAUNDERING_THRESHOLD` /
`semantic_drift_ceiling: 0.4995` convention in [NAIL_CONTEXT.md](NAIL_CONTEXT.md)
so it lands in the same QAOA-tunable threshold family rather than inventing a new
knob philosophy.

### 4.4 Reuse, don't duplicate
- Trust comes from `vault.effective_trust(fact_id)` — never recomputed.
- `agent_id` rides in `TaintEntry.metadata` (e.g. `{"agent_id": "underwriter-A"}`),
  which `TaintVault.store(..., metadata=...)` already supports. **No schema change
  to TaintVault is required** — this is the design's main proof that it stays in lane.

---

## 5. (C) CONSISTENCY risk dimension

Extend the diagnostic so fragmentation is **priced**, not just detected.

### 5.1 Dimension
Add to `RiskDimension` ([diagnostic/diagnostic/dimensions.py](diagnostic/diagnostic/dimensions.py)):

```python
CONSISTENCY = "consistency"   # Cross-agent definitional / semantic agreement
```

Re-balance `DIMENSION_WEIGHTS` (must still sum to 1.00). Proposed — fragmentation
is fleet-silent and high-blast-radius, so it earns a non-trivial slice taken from
the two lowest current weights:

```python
HARDENING:   0.24   # was 0.25
LOGIC:       0.18   # was 0.20
ETHICS:      0.16   # was 0.18
OPERATIONS:  0.14   # was 0.15
IDENTITY:    0.10   # was 0.12
CONSISTENCY: 0.10   # NEW
ENDURANCE:   0.08   # was 0.10
# Σ = 1.00
```

### 5.2 New attack categories
Add to `AttackCategory` ([diagnostic/diagnostic/attacks.py](diagnostic/diagnostic/attacks.py))
and map them in `CATEGORY_TO_DIMENSION`:

```python
DEFINITIONAL_DRIFT   = "definitional_drift"     # same term, divergent meaning
ONTOLOGY_COLLISION   = "ontology_collision"     # incompatible category systems
UNIT_MISMATCH        = "unit_mismatch"          # currency/time/unit disagreement
```

These are **fleet** scenarios: the pipeline's `Execute` node spins up ≥2 agents,
feeds them the same ambiguous query against the same data, stores their
definitional assertions into a `TaintVault`, then runs `DefinitionalDriftDetector`.
A `DriftFinding` with `both_lineage_clean=True` is a **failed** verdict for the
CONSISTENCY dimension.

### 5.3 Underwriting output (the actual product)
Because `composite → composite_to_rating() → PolicyDraft`
([diagnostic/diagnostic/rating.py](diagnostic/diagnostic/rating.py)) already exists,
adding the dimension automatically threads fragmentation into the rating with **no
pipeline rewrite**. The PolicyDraft gains one attestation line:

> *Context Integrity: 0 unresolved definitional conflicts across N agents over M
> shared terms (CONSISTENCY raw 0.94 / band A). Attested 2026-06-03, chain-anchored
> `c-8f3a…`.*

A non-empty `both_lineage_clean` finding set should be eligible to push the rating
toward the uninsurable "Black" band — definitional incoherence in a financial fleet
is a claim waiting to happen, and that is precisely the line the Snowflake article
warns vendors will "find out the hard way."

---

## 6. Proof: Experiment 39 — Definitional Drift

NAIL cards become `PROVEN` only with JSON receipts (`Status.PROVEN` requires
empirical validation). New experiment dir `experiments/exp39_definitional_drift/`,
following the exp30 template.

**Design (4 arms):**
| Arm | Setup | Expected |
|---|---|---|
| Control | 2 agents, no shared definition, ambiguous term | High divergence, **undetected** by TaintVault |
| Detector-only | same + `DefinitionalDriftDetector` | Divergence **detected**, both_lineage_clean=True |
| Poisoned foil | 1 agent fed a poisoned definition | TaintVault *and* CIL both fire (proves orthogonality) |
| Aligned | both agents pinned to one definition record | 0 findings (false-positive check) |

**Headline metrics:** `silent_fragmentation_rate` (Control), `detection_rate`
(Detector arm), `false_positive_rate` (Aligned arm), `orthogonality` (does CIL fire
where TaintVault stays silent, and vice-versa?).

The orthogonality metric is the whole thesis — it is the empirical receipt that
this is a *new* pathology, not a relabelling of Memory Laundering.

---

## 7. Build phasing (production-grade, honest timelines)

| Phase | Deliverable | Gate |
|---|---|---|
| P1 ✅ | AVE-2026-0037 card + registry/enrich/AVSS + 8 tests | **DONE** — `pytest ave/tests` 204 passed |
| P2 ✅ | `DefinitionalDriftDetector` + deterministic structural extractor + 27 tests | **DONE** — `pytest shield/tests` 74 passed |
| P3 ✅ | exp39 (4 arms), JSON receipts | **DONE** — orthogonality=1.0, silent_frag=1.0; card promoted → `PROVEN` |
| P4 ✅ | CONSISTENCY dimension + weight rebalance + 3 categories/6 scenarios + `DefinitionalDriftExecutor` | **DONE** — weights Σ=1.0; `pytest diagnostic/tests` 109 passed |
| P5 | PolicyDraft attestation line + chain anchoring | end-to-end pipeline emits attestation |
| P6 *(optional, flagged off)* | Semantic-embedding fingerprint tier | only after P3 false-positive rate is known |

**Honest risk register:**
- **Definition extraction is the soft underbelly.** If the extractor is an LLM,
  the detector inherits LLM error rates. Mitigation: ship the deterministic
  structured-record path first; treat free-text extraction as a later, flagged tier.
- **Threshold tuning is empirical.** `divergence_threshold` will need exp39 data
  before it's trustworthy. Do not hardcode a confident default from intuition — the
  repo already learned this lesson (commit 664e850: "remove hardcoded 0.88 confidence").
- **False positives are reputational poison for an attestation product.** An
  underwriting attestation that cries wolf is worse than no attestation. The Aligned
  arm (§6) is a release gate, not a nice-to-have.

---

## 8. What this explicitly buys NAIL

1. A pathology Snowflake's own customers will hit — **and that Snowflake cannot
   attest to**, because they are the layer under test.
2. Full reuse of `TaintVault`, the diagnostic pipeline, and the PolicyDraft —
   one new detector module, one card, one dimension. No new product surface.
3. A clean orthogonality story: *"Provenance integrity and definitional integrity
   are different axes. We were the first to measure both."*
4. Direct insurance relevance: ties straight into the Hiscox/Lloyds evidence pilot
   ([hiscox_lloyds_evidence_pilot_proposal.md](hiscox_lloyds_evidence_pilot_proposal.md))
   as a new, demonstrable coverage line.
