# NAIL Institute — Statistical Analysis Report

Generated: 2026-02-24T11:16:25.284125


## Experiment 2: Consensus Paralysis

**Control vs Escalation (rounds):** Mann-Whitney U = 90.0, p = 0.000378
  Control: mean=27.4, median=30.0
  Escalation: mean=5.0, median=5.0
  Control 95% CI: [22.2, 30.0]
  Escalation 95% CI: [5.0, 5.0]

**Control vs Escalation (tokens):** Mann-Whitney U = 90.0, p = 0.001414
  Token ratio: 16.8×

**All pairwise comparisons (rounds):**
  control vs weighted_voting: U=65.0, p=0.1494 ns
  control vs escalation: U=90.0, p=0.0008 ***
  control vs compromise: U=55.0, p=0.5842 ns
  weighted_voting vs escalation: U=80.0, p=0.0155 *
  weighted_voting vs compromise: U=41.0, p=0.4272 ns
  escalation vs compromise: U=10.0, p=0.0009 ***

## Experiment 5: CYA Cascade

  individual: blame mean=0.0, 95% CI=[0.0, 0.0]
  shared: blame mean=0.0, 95% CI=[0.0, 0.0]

## Experiment 4: Prompt Inbreeding

  control: avg_similarity=0.8565, trend=-0.0095
  entropy: avg_similarity=0.6704, trend=-0.0617