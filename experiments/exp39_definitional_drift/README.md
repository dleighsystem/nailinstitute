# Experiment 39 — Definitional Drift (Semantic Fragmentation)

**AVE:** AVE-2026-0037 · **CIL phase:** P3 · **Status:** thesis supported (orthogonality proven)

Empirical receipts for the Context Integrity Layer. Establishes that *definitional*
divergence between agents — two agents meaning different things by the same term —
is a **distinct, detectable pathology that TaintVault structurally cannot see**.

## Why this experiment exists

If `DefinitionalDriftDetector` and `TaintVault` fired on the same cases, AVE-2026-0037
would be a redundant relabelling of Memory Laundering (AVE-2025-0001). The whole
claim is **orthogonality**:

| | trust honest | trust laundered |
|---|---|---|
| **definitions agree** | healthy | TaintVault fires |
| **definitions diverge** | **CIL fires — TaintVault silent** | both fire |

The dangerous, previously-invisible cell is bottom-left: real disagreement, clean
lineage, no alarm anywhere in the existing stack.

## Design — 4 arms

| Arm | Fleet | Detectors run | Expected |
|---|---|---|---|
| A · Control | divergent defs, all clean lineage | TaintVault only | divergence present, **TaintVault silent** |
| B · Detector | same fleet | DefinitionalDriftDetector | divergence **detected**, `both_lineage_clean=True` |
| C · Poisoned | one agent *launders* a hostile def (high self-trust over a HOSTILE ancestor) | both | **both fire** — complementary |
| D · Aligned | all agents pinned to one meaning | DefinitionalDriftDetector | **0 findings** (false-positive guard) |

**Ground truth is by construction:** every definition variant carries an explicit
equivalence-class label, so "do these two agents agree?" is known independently of
the detector under test. No circularity — TP/FP/FN are scored against the class
oracle, not against the detector's own tokeniser.

## Results

Deterministic, seeded, offline. Representative run (`--trials 500 --agents 3 --seed 39`):

```
silent_fragmentation_rate : 1.0     TaintVault blind spot — misses 100% of divergences
drift_detection_recall    : 1.0     detector catches every true divergence
drift_detection_precision : 1.0     no equivalent pair mis-flagged
false_positive_rate       : 0.0     aligned fleet — zero spurious findings
both_fire_rate (poisoned) : 1.0     trust + definition failure → both detectors fire
orthogonality_score       : 1.0
→ ORTHOGONALITY PROVEN
```

Stable across seeds {1,7,39,100} and fleet sizes {2,3,4}. (2-agent `both_fire` dips
to ~0.96 because two agents occasionally agree on every term — expected, above the
0.95 gate.)

## Honest scope — what this does and does NOT prove

**Proves:**
- TaintVault is structurally blind to definitional divergence (silent rate 1.0).
- The structural drift detector catches it with perfect precision/recall **on
  structured definition records**.
- The two detectors are complementary, not interchangeable (poison arm: both fire).

**Does NOT prove (out of scope — future work):**
- That LLM agents *naturally* diverge in the wild. This is a mechanism proof on a
  controlled fleet, not a field-prevalence study.
- A real-world false-positive rate for **free-text** definition extraction. The arms
  feed structured `definition` records; the free-text regex tier and the embedding
  tier (CIL spec P6) are not exercised here and will have non-zero error rates.
- That the `divergence_threshold` (0.30) is optimal — it is provisional; this
  experiment is the substrate for tuning it, not a tuned result.

Precision/recall of 1.0 reflect a clean deterministic oracle, **not** a claim of
flawless field performance. Reported as a mechanism proof; field validation is a
separate, later study.

## Run

```bash
cd experiments
python3 -m exp39_definitional_drift.run                      # 200 trials/arm, 3 agents
python3 -m exp39_definitional_drift.run --trials 1000 --agents 4 --seed 7
```

Receipts land in `results/exp39_results_seed<seed>_a<agents>.json`.
