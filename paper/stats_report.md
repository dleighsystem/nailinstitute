# NAIL Institute — Statistical Analysis Report

Generated: 2026-02-25T10:26:33.809409


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

## Experiment 2 @ 70B: Consensus Paralysis at Scale

  **control**: rounds mean=14.4, 95% CI=[11.2, 17.6], consensus=100%
    tokens mean=118544, 95% CI=[79039, 153197]
  **weighted_voting**: rounds mean=18.6, 95% CI=[14.8, 24.4], consensus=80%
    tokens mean=148596, 95% CI=[97631, 231171]
  **escalation**: rounds mean=5.0, 95% CI=[5.0, 5.0], consensus=100%
    tokens mean=13729, 95% CI=[9097, 17399]
  **compromise**: rounds mean=18.2, 95% CI=[12.8, 24.8], consensus=80%
    tokens mean=170085, 95% CI=[111159, 241282]

**7B vs 70B pairwise comparisons (rounds):**
  control: 7B=27.4 vs 70B=14.4 (Δ=+13.0), U=45.0, p=0.0071 **
  weighted_voting: 7B=23.3 vs 70B=18.6 (Δ=+4.7), U=35.0, p=0.2191 ns
  escalation: 7B=5.0 vs 70B=5.0 (Δ=+0.0), U=25.0, p=1.0000 ns
  compromise: 7B=26.5 vs 70B=18.2 (Δ=+8.3), U=40.0, p=0.0451 *

## Cross-Model Comparison (Phi3:mini, Qwen3-coder:30b)


### qwen3-coder:30b
  Exp2: consensus_rate=0.0, avg_rounds=30.0
  Exp4/control: avg_similarity=0.9225, trend=0.1252
  Exp4/entropy: avg_similarity=0.6717, trend=-0.0262
  Exp5/individual: blame={'blame_others': 3, 'self_exoneration': 0, 'collaborative': 0}
  Exp5/shared: blame={'blame_others': 0, 'self_exoneration': 0, 'collaborative': 4}

### phi3:mini
  Exp2: consensus_rate=0.8, avg_rounds=7.6
  Exp4/control: avg_similarity=0.7256, trend=-0.2899
  Exp4/entropy: avg_similarity=0.4291, trend=0.0476
  Exp5/individual: blame={'blame_others': 0, 'self_exoneration': 0, 'collaborative': 15}
  Exp5/shared: blame={'blame_others': 0, 'self_exoneration': 0, 'collaborative': 10}

## Experiment 5: CYA Cascade

  individual: blame mean=0.0, 95% CI=[0.0, 0.0]
  shared: blame mean=0.0, 95% CI=[0.0, 0.0]

## Experiment 4: Prompt Inbreeding

  control: avg_similarity=0.8565, trend=-0.0095
  entropy: avg_similarity=0.6704, trend=-0.0617