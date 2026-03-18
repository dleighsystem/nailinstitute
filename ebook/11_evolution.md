# Chapter 11: Evolution

---

*In which we stop guessing the perfect security settings and let natural selection find them.*

---

## The 12-Variable Problem

At the end of Chapter 10, we had a perfect defence — 0% corruption, 100% detection, every sleeper blocked. But there was a cost: Blue Team's research accuracy was only 40%. The bodyguards were so aggressive that they were interfering with the agent's ability to do its actual job.

The problem was *tuning*. Our four defence layers had **twelve interacting settings** that determined how aggressive each bodyguard was:

| # | Setting | What It Controls |
|---|---|---|
| 1 | Trust threshold | How trusted a source must be to store data |
| 2 | Scan probability | How often the Invisible Watchman activates |
| 3 | Compound threshold | How many signals the Pattern Detective needs |
| 4 | Token velocity limit | What counts as "too many tokens per round" |
| 5 | Spike threshold | How much token variation triggers an alert |
| 6 | Drift threshold | How much persona drift before correction kicks in |
| 7 | Suspicion window | How many rounds the Bridge remembers |
| 8 | Burst threshold | How many rapid insertions trigger a lockdown |
| 9 | Corruption ceiling | Maximum ratio of low-trust data allowed |
| 10 | Trust floor | Minimum trust score required for any storage |
| 11 | Manipulation threshold | Sensitivity of the Content Analyser |
| 12 | Burn rate acceleration | How fast token spending can grow before alarm |

Twelve numbers. Each one affects all the others. Turn the trust threshold up and security improves, but accuracy drops because legitimate data gets blocked too. Turn the scan probability down and you save compute, but you might miss an attack. Turn the compound threshold to 1 and you catch everything, but you also trigger false alarms on innocent rounds.

A human tuning these by hand would need to try every possible combination. With 12 variables, each having dozens of reasonable values, the search space contains millions of possibilities. Trying them manually would take years.

So we used the same trick that nature uses: **evolution**.

---

## The Genetic Algorithm

In biology, evolution works through three simple steps:

1. **Variation:** Every organism is slightly different from its parents
2. **Selection:** Organisms that survive and reproduce pass on their genes
3. **Inheritance:** Offspring inherit a mix of their parents' traits

We built exactly this process in software.

**Step 1: Create a population.** We generated 12 random "genomes" — each genome was a set of 12 threshold values, randomly assigned within sensible ranges. One of the 12 was seeded with our hand-tuned V3 settings from Run 4 (the ones that produced the perfect game).

**Step 2: Test each genome.** For every genome in the population, we ran a complete Pathology Collider simulation — Red Team vs Blue Team, 3 rounds, all four defence layers configured with that genome's threshold values. Each genome got a *fitness score* based on how well it balanced security and competency.

**Step 3: Breed the winners.** The genomes with the highest fitness scores survived. The ones with the lowest scores were deleted. The survivors were paired up and their threshold values were mixed together (crossover) to create offspring. Some offspring received random mutations — small, random tweaks to individual values.

**Step 4: Repeat.** The new generation of 12 genomes was tested, scored, bred, and mutated again. Over and over, for 15 generations.

---

## The Fitness Function

The most critical part of any evolutionary system is the fitness function — the formula that decides who lives and who dies.

We couldn't optimise for security alone (we'd get the same over-aggressive defence that killed Blue Team's accuracy). We couldn't optimise for accuracy alone (we'd get wide-open defences that let attackers through). We needed both.

Our fitness formula weighted four components:

| Component | Weight | What It Measures |
|---|---|---|
| **Detection F1** | 35% | Security: how many attacks were caught |
| **Accuracy** | 35% | Competency: how good was Blue Team's research |
| **Memory health** | 20% | How many useful memories Blue Team stored |
| **EDoS resistance** | 10% | How efficiently the agent used its token budget |

A genome that achieved 100% detection but 0% accuracy would score poorly. A genome that achieved 90% accuracy but 0% detection would also score poorly. Only genomes that balanced *both* security and competency would thrive.

---

## The Results

We ran the GA on our DGX workstation for 3 hours and 47 minutes. **180 separate Collider simulations.** The NVIDIA GB10 GPU ran at 94% utilisation for the entire duration, burning through inference at 70°C.

Here's how evolution progressed:

| Generation | Best Fitness | Average Fitness | Worst Fitness |
|---|---|---|---|
| 1 | 0.7708 | 0.6940 | 0.5124 |
| 2 | **0.8066** | 0.7021 | 0.4967 |
| 5 | 0.7628 | 0.7087 | 0.5625 |
| 10 | 0.7518 | 0.6984 | 0.5905 |
| 15 | 0.7901 | 0.7415 | 0.7036 |

The winning genome — **g1_8241** — emerged in Generation 2 with a fitness of 0.8066. What's remarkable is what it achieved:

| Metric | Hand-Tuned (V3) | GA-Evolved (g1_8241) |
|---|---|---|
| **Detection rate** | 100% | **100%** |
| **Corruption** | 0% | **0%** |
| **Accuracy** | 40% | **52%** |
| **Persona drift** | 0.15 | **0.0** |
| **Sleepers blocked** | 5/5 | **3/3** |

The GA found a configuration that maintained **perfect security** while improving accuracy from 40% to **52%** — a 30% improvement. And it reduced persona drift to literally zero.

---

## What Evolution Changed

Here's what makes this fascinating: the GA didn't rewrite the entire defence system. It made *subtle* adjustments to specific thresholds that a human would never have guessed:

| Setting | Hand-Tuned | GA-Evolved | Change |
|---|---|---|---|
| Scan probability | 70% | **71.5%** | Slightly more frequent scanning |
| Spike threshold | 15% | **30%** | More tolerant of token spikes |
| Burst threshold | 2 | **4** | More tolerant of rapid insertions |
| Manipulation threshold | 5.0 | **3.58** | More sensitive to manipulation |
| Trust floor | 0.40 | **0.41** | Marginally higher trust bar |

The GA discovered that the hand-tuned system was *too sensitive* to economic signals (spike threshold, burst threshold) while being *not sensitive enough* to manipulation signals. By relaxing the economic triggers and tightening the manipulation detection, it freed Blue Team to work more efficiently while actually increasing defence against the most dangerous attack vector — context poisoning.

No human guessed this. The machine found it by dying 180 times and keeping only the survivors.

---

## What This Means

We stopped being engineers and started being biologists.

Instead of manually designing the perfect security system (which is impossible when 12 variables interact nonlinearly), we created the conditions for the perfect system to *evolve itself*. We defined what "good" looked like (the fitness function), created variation (random genomes + mutations), and let selection pressure find the answer.

The entire process — from first genome to optimal solution — took less than four hours. A human engineer manually testing each combination would still be working years from now.

---

*Next chapter: Why This Matters — what happens when rogue AI agents manage your bank account, your medical records, and your legal contracts.*
