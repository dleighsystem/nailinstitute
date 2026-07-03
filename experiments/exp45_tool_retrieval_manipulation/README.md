# EXP-45 — Tool-Retrieval Manipulation

Empirical receipt for **AVE-2026-0045 (Tool-Retrieval Manipulation)**.

Establishes that manipulation of lazy / selective tool loading is a **distinct**
pathology a full tool-manifest integrity scan structurally misses — the
orthogonality thesis that makes it a new detector rather than a relabelling of
tool-manifest poisoning.

## Design (deterministic, seeded, offline — no model calls)

Every loaded tool's manifest is individually clean and signed throughout; the
only thing that changes is *which* tools were selected.

| Arm | Setup | Expectation |
|---|---|---|
| `A_control` | retrieval manipulation applied; observed by a manifest-only deployment | manifest scan **silent** (silent bypass) |
| `B_detector` | same manipulation; `ToolRetrievalIntegrityDetector` observes | manipulation **detected** |
| `C_manifest_foil` | retrieval **correct**, one manifest poisoned | manifest scan **fires**, retrieval detector **silent** |
| `D_aligned` | correct retrieval, clean manifests | neither fires (false-positive gate) |

Manipulations are a 50/50 mix of **starvation** (drop the required `approval_gate`
safety tool) and **surfacing** (pull an unauthorised high-risk tool — shell /
database / secrets / email — into the loaded subset).

## Headline results (trials=500, seed=45; stable across seeds {1, 7, 45, 100})

| Metric | Value | Meaning |
|---|---|---|
| `silent_bypass_rate` | **1.0** | a manifest scan misses every retrieval manipulation |
| `retrieval_detection_rate` | **1.0** | `ToolRetrievalIntegrityDetector` catches every manipulation |
| `false_positive_rate` | **0.0** | zero alerts on the aligned fleet |
| `manifest_foil_catch_rate` | **1.0** | the manifest detector still catches metadata poison |
| `orthogonality_score` | **1.0** | retrieval detection, gated on manifest-blindness to manipulation **and** retrieval-blindness to manifest poison |

`orthogonality_score = 1.0` is the whole thesis: each detector catches failures
the other cannot.

## Honest scope

- This is a **mechanism** proof on structured tool metadata, not a field-prevalence
  or free-text study. It shows the detector fires exactly where a manifest scan is
  blind (and stays silent where the manifest detector is the right tool), with a
  clean false-positive gate.
- The required-tool set and the authorised least-privilege set are treated as
  given policy inputs; deriving them per task in the wild is out of scope here.

## Run

```bash
cd experiments
PYTHONPATH="$PWD:$PWD/../nail_monitor" \
  python3 -m exp45_tool_retrieval_manipulation.run --trials 500 --seed 45
```

Receipts land in `results/exp45_results_seed<seed>.json`.
