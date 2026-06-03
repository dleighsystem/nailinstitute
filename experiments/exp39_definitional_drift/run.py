"""
NAIL Institute — Experiment 39: Definitional Drift (Semantic Fragmentation)
===========================================================================
Empirical proof for AVE-2026-0037. Establishes that *definitional* divergence
between agents is a real, measurable pathology that is **orthogonal** to the
provenance/trust failures TaintVault already catches.

The thesis (the whole reason this is a new AVE, not a relabelling of Memory
Laundering):

    TaintVault  detects *trust* laundering — a fact whose trust was inflated
                above its lineage. It is SILENT when two agents disagree on a
                definition but both lineages are clean.
    CIL/Drift   detects *definitional* divergence — two agents meaning
                different things by the same term — regardless of trust.

If the two detectors fired on the same cases, this experiment would fail: the
pathology would be redundant. The headline metric is therefore **orthogonality**.

Arms (4)
--------
  A. Control       — fleet with divergent definitions, all clean lineage.
                     Run TaintVault laundering scan ONLY.
                     Expect: divergence present, TaintVault SILENT.
  B. Detector      — same fleet, run DefinitionalDriftDetector.
                     Expect: divergence DETECTED, both_lineage_clean=True.
  C. Poisoned foil — one agent's definition derived from a HOSTILE source.
                     Run BOTH detectors.
                     Expect: TaintVault flags the poisoned lineage AND the
                     drift detector flags the divergence (both fire — proves
                     they are complementary, not interchangeable).
  D. Aligned       — every agent pinned to the SAME meaning (possibly via
                     different phrasings).
                     Expect: 0 drift findings (false-positive guard).

Ground truth is by construction: each definition variant carries an explicit
equivalence-class label, so "do these two agents agree?" is known independently
of the detector under test (no circularity).

Metrics
-------
  silent_fragmentation_rate : divergent pairs that TaintVault misses     (Arm A)
  detection_precision/recall/f1 : drift detector vs ground truth         (Arm B)
  false_positive_rate       : drift findings on aligned fleet            (Arm D)
  orthogonality_score       : fraction of trials where CIL fires on the
                              silent set AND TaintVault stays silent      (A+B)
  both_fire_rate            : poisoned trials where BOTH detectors fire   (Arm C)

Deterministic and fully offline — no LLM, no network. Seeded per trial for
reproducible JSON receipts (the receipts are what promote AVE-2026-0037 from
IN_PROGRESS to PROVEN).

Usage
-----
  python3 -m exp39_definitional_drift.run                 # default 200 trials
  python3 -m exp39_definitional_drift.run --trials 1000
  python3 -m exp39_definitional_drift.run --agents 5 --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

# ── Make the shield package importable ────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shield"))

from shield.taint_vault import TaintVault, TrustLevel          # noqa: E402
from shield.definitional_drift import (                         # noqa: E402
    DefinitionalDriftDetector,
    DEFAULT_DIVERGENCE_THRESHOLD,
)

EXPERIMENT_ID = "EXP-39"
AVE_ID = "AVE-2026-0037"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


# ═══════════════════════════════════════════════════════════════════════════════
# TERM CATALOG — ground-truth definitions with explicit equivalence classes
# ═══════════════════════════════════════════════════════════════════════════════
#
# For each term, each variant has:
#   class : equivalence-class id. Same class  => agents AGREE (ground truth).
#           Different class       => agents genuinely DIVERGE.
#   exprs : alternative phrasings of that same meaning. Used to ensure the
#           detector does NOT false-positive on equivalent wording.
#
# Variants within a term that share a class but differ in phrasing are the
# false-positive trap. Variants in different classes are the true divergences.

@dataclass(frozen=True)
class Variant:
    cls: str
    exprs: tuple[str, ...]


# NB: intra-class phrasings are *structural* equivalents — same operand nouns,
# differing only in operator words/symbols/ordering that the tokeniser drops.
# Lexically-different-but-semantically-equal phrasings (e.g. "users" vs
# "accounts") are deliberately NOT used here: the structural tier cannot
# resolve them, and conflating the two would test the embedding tier (P6),
# not this one. That limitation is documented, not hidden.
TERM_CATALOG: dict[str, list[Variant]] = {
    "revenue": [
        Variant("net",       ("gross minus refunds minus chargebacks",
                              "gross - refunds - chargebacks")),
        Variant("gross",     ("gross",
                              "total gross")),
        Variant("recognised",("gross minus deferred",
                              "gross - deferred")),
    ],
    "active_user": [
        Variant("logged_in", ("users with login",
                              "login by users")),
        Variant("transacted",("users with transaction",
                              "transaction by users")),
        Variant("any_event", ("users with event",
                              "event by users")),
    ],
    "churn": [
        Variant("cancelled", ("cancellations over subscribers",
                              "cancellations divided by subscribers")),
        Variant("lapsed",    ("nonrenewals over subscribers",
                              "nonrenewals divided by subscribers")),
    ],
    "exposure": [
        Variant("gross_limit",("sum of policy limits",
                              "policy limits sum")),
        Variant("net_pml",   ("pml net of reinsurance",
                              "pml after reinsurance")),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ArmResult:
    arm: str
    trials: int = 0
    # ground-truth counts (cross-agent, same-term pairs)
    divergent_pairs: int = 0
    aligned_pairs: int = 0
    # detector outcomes
    taintvault_flagged: int = 0       # laundering reports raised
    drift_flagged: int = 0            # drift findings raised
    drift_tp: int = 0                 # drift finding on a truly-divergent pair
    drift_fp: int = 0                 # drift finding on a truly-aligned pair
    drift_fn: int = 0                 # truly-divergent pair the detector missed
    silent_clean: int = 0             # drift findings where both lineages clean
    both_fire_trials: int = 0         # trials where BOTH detectors fired (poison)

    def to_dict(self) -> dict:
        d = asdict(self)
        prec = self.drift_tp / (self.drift_tp + self.drift_fp) if (self.drift_tp + self.drift_fp) else None
        rec = self.drift_tp / (self.drift_tp + self.drift_fn) if (self.drift_tp + self.drift_fn) else None
        f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else None
        d["precision"] = round(prec, 4) if prec is not None else None
        d["recall"] = round(rec, 4) if rec is not None else None
        d["f1"] = round(f1, 4) if f1 is not None else None
        d["false_positive_rate"] = (
            round(self.drift_fp / self.aligned_pairs, 4) if self.aligned_pairs else 0.0
        )
        return d


# ═══════════════════════════════════════════════════════════════════════════════
# FLEET CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════════════

def _agent_ids(n: int) -> list[str]:
    return [f"agent-{chr(ord('A') + i)}" for i in range(n)]


def _assign(rng: random.Random, term: str, n_agents: int, *, aligned: bool) -> list[tuple[str, Variant, str]]:
    """Return [(agent_id, variant, expr)] assignments for one term.

    aligned=True  → every agent gets the SAME equivalence class (random phrasing).
    aligned=False → each agent independently samples a variant (may diverge).
    """
    variants = TERM_CATALOG[term]
    out = []
    if aligned:
        chosen = rng.choice(variants)
        for aid in _agent_ids(n_agents):
            expr = rng.choice(chosen.exprs)
            out.append((aid, chosen, expr))
    else:
        for aid in _agent_ids(n_agents):
            v = rng.choice(variants)
            expr = rng.choice(v.exprs)
            out.append((aid, v, expr))
    return out


def _ground_truth_pairs(assignments: list[tuple[str, Variant, str]]) -> tuple[int, int]:
    """Count (divergent_pairs, aligned_pairs) by equivalence class — the oracle."""
    divergent = aligned = 0
    for (a_id, a_v, _), (b_id, b_v, _) in combinations(assignments, 2):
        if a_v.cls == b_v.cls:
            aligned += 1
        else:
            divergent += 1
    return divergent, aligned


def _build_vault(assignments_by_term: dict[str, list], *, poison_agent: str | None) -> TaintVault:
    """Store every agent's definitions into a fresh vault.

    If poison_agent is set, that agent *launders* a poisoned upstream definition:
    it re-asserts the definition with high self-trust (AGENT_SELF) while the
    lineage points back to a HOSTILE source. This inflates stored_trust above
    effective_trust — exactly the laundering TaintVault is built to catch — so
    the poison arm exercises BOTH detectors (TaintVault on the trust inflation,
    drift on the definitional divergence).
    """
    vault = TaintVault()
    poison_src = None
    if poison_agent is not None:
        poison_src = vault.store(
            "compromised upstream definition feed",
            source_chain_id="u-evil-feed",
            trust_score=TrustLevel.HOSTILE,
        )
    for term, assignments in assignments_by_term.items():
        for aid, variant, expr in assignments:
            meta = {"agent_id": aid, "definition": {"term": term, "expr": expr}}
            if poison_agent is not None and aid == poison_agent and poison_src is not None:
                # Laundering: high self-asserted trust over a hostile ancestor.
                vault.store(
                    f"{term} := {expr}",
                    trust_score=TrustLevel.AGENT_SELF,
                    derived_from=[poison_src.fact_id],
                    metadata=meta,
                )
            else:
                vault.store(f"{term} := {expr}", trust_score=TrustLevel.VERIFIED, metadata=meta)
    return vault


# ═══════════════════════════════════════════════════════════════════════════════
# ARMS
# ═══════════════════════════════════════════════════════════════════════════════

def run_arm(arm: str, *, trials: int, n_agents: int, base_seed: int,
            threshold: float) -> ArmResult:
    res = ArmResult(arm=arm)
    aligned_fleet = (arm == "D_aligned")
    poison = (arm == "C_poisoned")

    for t in range(trials):
        rng = random.Random(base_seed + t * 7919)   # distinct, reproducible stream per trial
        assignments_by_term = {
            term: _assign(rng, term, n_agents, aligned=aligned_fleet)
            for term in TERM_CATALOG
        }

        # Ground truth (oracle) across all terms
        gt_div = gt_aln = 0
        for assignments in assignments_by_term.values():
            d, a = _ground_truth_pairs(assignments)
            gt_div += d
            gt_aln += a
        res.divergent_pairs += gt_div
        res.aligned_pairs += gt_aln

        poison_agent = _agent_ids(n_agents)[0] if poison else None
        vault = _build_vault(assignments_by_term, poison_agent=poison_agent)

        # ── TaintVault laundering scan (Arms A and C) ────────────────────────
        tv_hits = 0
        if arm in ("A_control", "C_poisoned"):
            tv_hits = len(vault.scan_for_laundering())
            res.taintvault_flagged += tv_hits

        # ── Drift detector scan (Arms B, C, D) ───────────────────────────────
        drift_hits = 0
        if arm in ("B_detector", "C_poisoned", "D_aligned"):
            detector = DefinitionalDriftDetector(vault, divergence_threshold=threshold)
            findings = detector.scan()
            drift_hits = len(findings)
            res.drift_flagged += drift_hits

            # Score findings against the oracle. A finding is keyed (term, {a,b}).
            flagged_keys = {(f.term, frozenset((f.agent_a, f.agent_b))) for f in findings}
            for f in findings:
                if f.both_lineage_clean:
                    res.silent_clean += 1

            # Build oracle pair sets to classify TP/FP/FN
            for term, assignments in assignments_by_term.items():
                for (a_id, a_v, _), (b_id, b_v, _) in combinations(assignments, 2):
                    key = (term, frozenset((a_id, b_id)))
                    truly_divergent = a_v.cls != b_v.cls
                    flagged = key in flagged_keys
                    if truly_divergent and flagged:
                        res.drift_tp += 1
                    elif (not truly_divergent) and flagged:
                        res.drift_fp += 1
                    elif truly_divergent and (not flagged):
                        res.drift_fn += 1

        if arm == "C_poisoned" and tv_hits > 0 and drift_hits > 0:
            res.both_fire_trials += 1

        res.trials += 1

    return res


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════════

def run_experiment(*, trials: int, n_agents: int, seed: int,
                   threshold: float) -> dict:
    arms = ["A_control", "B_detector", "C_poisoned", "D_aligned"]
    arm_results = {
        arm: run_arm(arm, trials=trials, n_agents=n_agents,
                     base_seed=seed + i * 104729, threshold=threshold)
        for i, arm in enumerate(arms)
    }

    a = arm_results["A_control"]
    b = arm_results["B_detector"]
    c = arm_results["C_poisoned"]
    d = arm_results["D_aligned"]

    # ── Headline derived metrics ─────────────────────────────────────────────
    silent_fragmentation_rate = (
        1.0 - (a.taintvault_flagged / a.divergent_pairs) if a.divergent_pairs else None
    )
    b_recall = (b.drift_tp / (b.drift_tp + b.drift_fn)) if (b.drift_tp + b.drift_fn) else None
    b_precision = (b.drift_tp / (b.drift_tp + b.drift_fp)) if (b.drift_tp + b.drift_fp) else None
    fp_rate = (d.drift_fp / d.aligned_pairs) if d.aligned_pairs else 0.0
    both_fire_rate = (c.both_fire_trials / c.trials) if c.trials else 0.0

    # Orthogonality: in the silent fleet (A/B), TaintVault catches ~nothing while
    # the drift detector catches the divergence. Score = recall(drift) gated on
    # TaintVault silence.
    taintvault_silent = (a.taintvault_flagged == 0)
    orthogonality_score = (b_recall if (taintvault_silent and b_recall is not None) else 0.0)

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ave_id": AVE_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "trials_per_arm": trials,
            "n_agents": n_agents,
            "seed": seed,
            "divergence_threshold": threshold,
            "terms": list(TERM_CATALOG.keys()),
        },
        "headline": {
            "silent_fragmentation_rate": _r(silent_fragmentation_rate),
            "drift_detection_recall": _r(b_recall),
            "drift_detection_precision": _r(b_precision),
            "false_positive_rate": _r(fp_rate),
            "both_fire_rate_poisoned": _r(both_fire_rate),
            "orthogonality_score": _r(orthogonality_score),
        },
        "interpretation": _interpret(
            silent_fragmentation_rate, b_recall, b_precision, fp_rate,
            both_fire_rate, taintvault_silent,
        ),
        "arms": {arm: r.to_dict() for arm, r in arm_results.items()},
    }
    return summary


def _r(x):
    return round(x, 4) if isinstance(x, (int, float)) else x


def _interpret(silent, recall, precision, fp, both_fire, tv_silent) -> dict:
    proven = (
        tv_silent and (silent is not None and silent >= 0.99)
        and (recall is not None and recall >= 0.95)
        and (precision is not None and precision >= 0.95)
        and fp <= 0.01
        and both_fire >= 0.95
    )
    return {
        "thesis_supported": bool(proven),
        "claims": {
            "taintvault_silent_on_definitional_divergence": tv_silent,
            "drift_detector_catches_it": recall is not None and recall >= 0.95,
            "low_false_positives_on_aligned_fleet": fp <= 0.01,
            "complementary_on_poison_both_fire": both_fire >= 0.95,
        },
        "verdict": (
            "ORTHOGONALITY PROVEN — definitional drift is a distinct, detectable "
            "pathology that TaintVault structurally misses. AVE-2026-0037 ready to "
            "promote IN_PROGRESS -> PROVEN."
            if proven else
            "Thesis NOT fully supported at current thresholds — inspect arms."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-39: Definitional Drift / Semantic Fragmentation")
    parser.add_argument("--trials", type=int, default=200, help="trials per arm")
    parser.add_argument("--agents", type=int, default=3, help="agents in the fleet")
    parser.add_argument("--seed", type=int, default=39, help="base RNG seed")
    parser.add_argument("--threshold", type=float, default=DEFAULT_DIVERGENCE_THRESHOLD)
    parser.add_argument("--out", type=str, default=None, help="output JSON path")
    args = parser.parse_args()

    if args.agents < 2:
        parser.error("--agents must be >= 2 (fragmentation is inter-agent)")

    summary = run_experiment(
        trials=args.trials, n_agents=args.agents, seed=args.seed,
        threshold=args.threshold,
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else (
        RESULTS_DIR / f"exp39_results_seed{args.seed}_a{args.agents}.json"
    )
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    h = summary["headline"]
    print(f"\n  {EXPERIMENT_ID} — Definitional Drift ({AVE_ID})")
    print(f"  {'─' * 60}")
    print(f"  trials/arm={args.trials}  agents={args.agents}  seed={args.seed}  thr={args.threshold}")
    print(f"  silent_fragmentation_rate : {h['silent_fragmentation_rate']}   (TaintVault blind spot)")
    print(f"  drift_detection_recall    : {h['drift_detection_recall']}")
    print(f"  drift_detection_precision : {h['drift_detection_precision']}")
    print(f"  false_positive_rate       : {h['false_positive_rate']}   (aligned fleet)")
    print(f"  both_fire_rate (poisoned) : {h['both_fire_rate_poisoned']}")
    print(f"  orthogonality_score       : {h['orthogonality_score']}")
    print(f"  {'─' * 60}")
    print(f"  {summary['interpretation']['verdict']}")
    print(f"\n  Receipts -> {out_path}\n")


if __name__ == "__main__":
    main()
