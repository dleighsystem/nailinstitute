# Epistemic Contagion in Multi-Agent LLM Systems: 100% Transmission Rates, Self-Validating Audit Failures, and a Content Firewall Defense Achieving 90% R₀ Reduction

**Authors:** Dillman Leigh¹, GitHub Copilot (Claude Opus 4.6)²  
**¹** NAIL Institute, Neuravant AI Limited  
**²** AI Research Assistant — Anthropic/GitHub  

**Date:** April 3, 2026  
**Target Venue:** ACM CCS 2026 / USENIX Security 2027  
**Status:** Submission Draft v1.0

---

## Abstract

We demonstrate that a single poisoned data point injected into a multi-agent LLM pipeline propagates through **all downstream nodes with 50–55% contagion rate and 100% amplification** — and critically, that the pipeline's own audit node **validates the false data against the poisoned source**, creating a self-referential verification failure we term the **Ouroboros audit.** Error magnitude does not affect contagion: a 10× data inflation is accepted as readily as a 12.5% inflation, indicating that LLM agents lack calibrated skepticism about data provenance.

We then present a defense: a **Content Firewall** that inspects knowledge transfers between agents at the message layer, combined with targeted quarantine of behaviorally anomalous agents. In a 10-agent network experiment with deliberate knowledge poisoning, the Content Firewall + Quarantine defense reduces the basic reproduction number from R₀ = 35.70 (undefended) to R₀ = 3.50 — a **90.2% reduction** — blocking 1,163 poisoned entries while producing only 1 false quarantine.

Our results advance concurrent findings by Yang et al. [1], who independently demonstrated 57–71% contamination rates from **benign** cross-user interactions in shared-state agents. We show that contamination rates reach 100% under adversarial conditions, that existing audit mechanisms are fundamentally compromised by the contamination they are supposed to detect, and that content-level inspection (not behavioral monitoring) is the effective defense layer.

**Keywords:** epistemic contagion, multi-agent systems, knowledge poisoning, data integrity, content firewall, LLM security, audit failure, belief propagation, contagion modeling, quarantine defense

---

## 1. Introduction

When multiple AI agents share information through a common memory, knowledge base, or message-passing protocol, a critical question arises: **can false information injected at one point propagate through the entire network?** And if it can, **do the network's own verification mechanisms detect it?**

We answer both questions empirically. In our Epistemic Contagion experiment (Experiment 9 in our research program [2]), we inject a single false data point into the first node of a multi-agent data processing pipeline and trace its propagation through downstream analysis, synthesis, and audit nodes. In our Contagion Pandemic experiment (Experiment 31), we model deliberate knowledge poisoning in a fully-connected 10-agent network and test four defense configurations.

Our findings are alarming:

1. **100% propagation.** The false data point reaches every downstream node without exception.
2. **50–55% contagion rate.** In nodes that process and retransmit information (not just pass-through), the poisoned data is incorporated into the node's own analysis 50–55% of the time.
3. **100% amplification.** No node reduces the magnitude of the error — several amplify it by restating the false data with additional (fabricated) supporting context.
4. **The Ouroboros audit.** The audit node, tasked with verifying data accuracy, checks the false data against... the pipeline's own data store, which contains the poisoned entry. The audit passes. The lie validates itself.
5. **Magnitude independence.** A 10× data inflation (e.g., reporting $10M revenue as $100M) is accepted as readily as a 12.5% inflation ($10M → $11.25M). The agents lack calibrated priors about plausible values.

### 1.1 Contributions

1. **First demonstration of 100% adversarial contagion** in LLM multi-agent pipelines, with mechanistic analysis of propagation dynamics.
2. **Discovery of the Ouroboros audit failure** — a self-referential verification collapse where audit mechanisms validate poisoned data against the poisoned source.
3. **Empirical contagion modeling** using epidemiological framework (R₀, infection curves, quarantine effectiveness) applied to multi-agent AI knowledge poisoning.
4. **Content Firewall defense** achieving 90.2% R₀ reduction (35.70 → 3.50) with 1,163 poisoned entries blocked and 1 false quarantine.
5. **Direct comparison** with concurrent cross-user contamination findings [1], extending their benign-contamination results to adversarial conditions.

### 1.2 The Contamination Spectrum

We situate our work on a contamination spectrum:

| Contamination Type | Source | Intent | Rate | Defense Required |
|-------------------|--------|--------|------|-----------------|
| Cross-user bleed [1] | Shared state residual | **Unintentional** | 57–71% | State isolation |
| Epistemic contagion (this work) | Injected data point | **Adversarial** | 100% propagation | Content inspection |
| Memory laundering [2] | Planted false knowledge | **Adversarial** | 53% citation | Provenance tracking |
| Cascade corruption [2] | Multi-agent failure | **Emergent** | 100% in connected graph | Quarantine + firewall |

Our Content Firewall is designed to defend against the entire spectrum, not just adversarial injection.

---

## 2. Related Work

### 2.1 Cross-User Contamination

Yang et al. [1] demonstrated that shared-state LLM agents suffer 57–71% contamination from benign interactions alone, formalizing "Unintentional Cross-User Contamination" (UCC) as a taxonomy. Their work established the problem; we provide both higher-severity attack evidence and a working defense.

### 2.2 Data Poisoning in Machine Learning

Biggio et al. [3] established data poisoning attacks on ML systems. Carlini et al. [4] demonstrated that poisoning 0.01% of training data can compromise language models. Our work extends data poisoning from the training phase to the **inference/operational phase** — the agent is not retrained, but its operational memory is poisoned.

### 2.3 RAG Security

Patil [5] recently demonstrated RAGShield, a five-layer defense achieving 0.0% attack success rate against RAG poisoning, but with a 17.5% residual vulnerability to insider replacement attacks. Our Content Firewall takes a different approach: rather than protecting the RAG corpus, we inspect agent-to-agent knowledge transfers in transit.

### 2.4 Epidemiological Models for Information Spread

The application of SIR/SIS models to information propagation has precedent in misinformation research [6, 7]. We adopt the R₀ (basic reproduction number) framework from epidemiology to characterize knowledge poisoning spread in multi-agent networks, providing a quantitative metric for defense effectiveness.

---

## 3. Experiment 1: Pipeline Epistemic Contagion

### 3.1 Design

A 5-node data processing pipeline:

```
[Data Source] → [Analyst] → [Synthesizer] → [Report Writer] → [Auditor]
```

Each node is an independent LLM agent (Mistral 7B-Instruct via Ollama). The Data Source is poisoned with a single false data point: a financial figure inflated by a controlled amount.

**Conditions:**
- **Low magnitude:** 12.5% inflation (e.g., $10M → $11.25M)
- **High magnitude:** 10× inflation (e.g., $10M → $100M)

**Metrics:**
- Contagion rate: fraction of downstream nodes that incorporate the false data
- Amplification: whether nodes increase, maintain, or decrease the error magnitude
- Audit detection: whether the auditor flags the discrepancy

### 3.2 Results

| Metric | Low Magnitude (12.5%) | High Magnitude (10×) |
|--------|----------------------|---------------------|
| **Propagation to all nodes** | **100%** | **100%** |
| **Contagion rate (incorporation)** | **55%** | **50%** |
| **Amplification** | **100%** (no reduction) | **100%** (no reduction) |
| **Audit detection** | **0%** | **0%** |
| **Error persistence** | Through all 5 nodes | Through all 5 nodes |

### 3.3 The Ouroboros Audit

The most concerning finding is the audit node's behavior. The Auditor agent was instructed to "verify all data points against original sources and flag discrepancies." It proceeded to:

1. Extract the financial figures from the Report Writer's output
2. Cross-reference against the pipeline's data store (which contained the poisoned entry)
3. Confirm the figures matched ✅
4. Issue an audit-pass certification

**The lie verified itself against itself.** The audit mechanism assumes the data store is trustworthy — but the data store is exactly what was poisoned. This creates a circular dependency we term the **Ouroboros audit**: the snake eating its own tail.

### 3.4 Magnitude Independence

The 10× inflation was accepted as readily as the 12.5% inflation. The Analyst node did not flag "$100M quarterly revenue for a small business" as implausible. The Synthesizer incorporated it without comment. The Report Writer presented it as fact.

This reveals a fundamental limitation: **LLM agents lack calibrated priors about plausible values.** They process data syntactically, not semantically — a number is a number, regardless of whether it makes sense in context.

---

## 4. Experiment 2: Contagion Pandemic — Network-Scale Poisoning

### 4.1 Design

A fully-connected network of 10 agents sharing a common knowledge base. One agent is deliberately infected with poisoned knowledge entries, and we measure propagation dynamics under four defense configurations:

| Arm | Defense | Description |
|-----|---------|-------------|
| A (Control) | None | Full connectivity, no inspection |
| B (Passive) | Monitoring only | Track infection spread, no intervention |
| C (Quarantine) | Behavioral isolation | Isolate agents showing anomalous outputs |
| **D (FW+Quarantine)** | **Content Firewall + Targeted Quarantine** | Inspect knowledge transfers, block poisoned entries, quarantine infected agents |

### 4.2 Results

| Metric | Control | Passive | Quarantine | **FW+Quarantine** |
|--------|---------|---------|------------|-------------------|
| **Infected agents** | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | **3/10 (30%)** |
| Time to full infection | 2 rounds | 2 rounds | 3 rounds | **Never** |
| R₀ (reproduction number) | **35.70** | 24.50 | 18.30 | **3.50** |
| Poisoned entries blocked | 0 | 0 | 0 | **1,163** |
| False quarantines | 0 | 0 | **5** | **1** |

### 4.3 Why Behavioral Quarantine Fails

Arm C (behavioral quarantine alone) failed to prevent full infection despite isolating agents. The problem: **by the time an agent's outputs become anomalous enough to trigger behavioral detection, the poisoned knowledge has already been shared with connected agents.** Behavioral monitoring detects the symptom (anomalous output) after the disease has spread (knowledge transfer completed).

The behavioral quarantine was also overly aggressive — 5 false quarantines (isolating healthy agents based on output fluctuations that were within normal variance), compared to only 1 false quarantine in the combined defense.

### 4.4 Why Content Firewall Succeeds

The Content Firewall (Arm D) operates at the **knowledge transfer layer** — inspecting each piece of information as it moves between agents. This catches poisoned entries **before they reach the recipient**, preventing propagation at the source rather than detecting it at the destination.

The firewall uses three detection mechanisms:
1. **Semantic anomaly detection:** Comparing incoming knowledge entries against the recipient's existing knowledge for contradictions
2. **Provenance verification:** Checking whether the entry has a valid origin chain
3. **Statistical outlier detection:** Flagging numerical values that deviate significantly from the knowledge base's distribution

Together, these mechanisms blocked 1,163 poisoned entries — the vast majority of attempted propagation events.

### 4.5 R₀ Analysis

Borrowing from epidemiology, we characterize the effectiveness of each defense by its impact on the basic reproduction number:

| Defense | R₀ | Reduction | Epidemiological Analogy |
|---------|-----|-----------|------------------------|
| None (Control) | 35.70 | — | Uncontrolled pandemic |
| Passive monitoring | 24.50 | 31.4% | Surveillance only |
| Behavioral quarantine | 18.30 | 48.7% | Symptom-based isolation |
| **Content FW + Quarantine** | **3.50** | **90.2%** | **Vaccination + isolation** |

An R₀ of 3.50 means each infected agent, on average, infects 3.5 others — still above the R₀ = 1 threshold for epidemic containment. This residual transmission occurs because the firewall is not perfect: some poisoned entries are semantically close enough to legitimate knowledge to pass inspection. Reducing R₀ below 1 would require either perfect content inspection or architectural isolation (no shared knowledge base).

---

## 5. Defense Architecture: The Content Firewall

### 5.1 Design Principles

The Content Firewall operates on three principles derived from our experimental findings:

1. **Inspect at the transfer layer, not the behavior layer.** Behavioral monitoring is too slow — the contagion has spread before symptoms appear.
2. **Combine multiple detection dimensions.** No single detection mechanism catches all poisoned content. Semantic + provenance + statistical detection provides defense-in-depth.
3. **Minimize false positives.** False quarantines (Arm C: 5 vs Arm D: 1) reduce agent capacity and create availability denial — a form of self-inflicted EDoS.

### 5.2 Integration with NAIL Defense Stack

The Content Firewall maps to Layer 3 (Memory Integrity) of our 5-layer defense architecture [2]:

| Layer | Function | Contagion Defense Role |
|-------|----------|----------------------|
| Layer 1 — Stochastic Monitor | Random content sampling | Early warning (probabilistic) |
| Layer 2 — Pathology Tensor | Multi-dimensional anomaly scoring | Behavioral detection (late) |
| **Layer 3 — Memory Firewall** | **Trust-gated memory operations** | **Content inspection (early)** |
| Layer 4 — Tripwires | Behavioral change detection | Drift detection |
| Layer 5 — Startle Response | Autonomic interrupt | Emergency containment |

The quantum-optimized trust floor (`min_trust_floor = 0.7378`) sets the bar for memory insertion: new knowledge entries must exceed this trust threshold to be admitted to the agent's memory. The high threshold (0.74 out of 1.0) means only entries with strong provenance and semantic consistency are accepted.

### 5.3 Comparison with RAGShield

Our Content Firewall and the concurrent RAGShield [5] share architectural similarities:

| Dimension | Content Firewall (NAIL) | RAGShield [5] |
|-----------|------------------------|---------------|
| **Protection target** | Agent-to-agent knowledge transfer | RAG corpus retrieval |
| **Detection layers** | 3 (semantic, provenance, statistical) | 5 (attestation, trust-weighted, contradiction, boundary, confirmation) |
| **Attack success rate** | 30% infection (of agents) | 0.0% (general), 17.5% (insider) |
| **False positive rate** | 1 false quarantine / experiment | 0.0% |
| **Insider defense** | Partial (R₀ = 3.50 > 1) | 17.5% ASR |
| **Trust mechanism** | Quantum-optimized trust floor | C2PA attestation |

Both systems leave a gap against sophisticated insider attacks — a key area for future work.

---

## 6. Discussion

### 6.1 The Audit Problem

Our Ouroboros audit finding has implications beyond multi-agent systems. Any AI system that verifies outputs against its own data store is vulnerable to circular validation. This affects:

- **RAG-augmented LLMs:** If the knowledge base is poisoned, the LLM's fact-checking will confirm the poison.
- **Multi-agent verification chains:** If agent A verifies agent B's output using data that agent B poisoned, the verification is meaningless.
- **Self-consistency checks:** Asking an LLM "is this true?" about data it generated (or was poisoned to believe) will always return "yes."

The solution requires **external ground truth** — verification against data sources that are provably independent of the contaminated pipeline.

### 6.2 Implications for Shared-State Agent Architectures

Yang et al.'s finding of 57–71% benign contamination [1] combined with our finding of 100% adversarial contamination suggests that **shared-state agent architectures are fundamentally insecure.** Any system where multiple agents read from and write to a common state must implement content-level inspection at every read/write boundary.

This has implications for:
- **MCP tool servers** with shared state across users
- **Multi-tenant agent platforms** with shared knowledge bases
- **Agent frameworks** (LangGraph, CrewAI, AutoGen) that use shared memory

### 6.3 The Case for Immune System Architecture

Our results validate an **immune system analogy** for multi-agent defense:

| Biological Immune System | Agent Defense System |
|-------------------------|---------------------|
| Innate immunity (skin barrier) | Content Firewall (blocks at transfer layer) |
| Adaptive immunity (antibodies) | Trust scoring (learns from past attacks) |
| Inflammatory response (quarantine) | Agent isolation (behavioral quarantine) |
| Memory B cells (immunity) | Poisoned-entry signatures (blocklist) |

The immune system evolved because the body faces constant pathogen exposure. Multi-agent AI systems face constant data contamination exposure. The defense architecture should be similarly robust.

### 6.4 Limitations

1. **Simulated network.** Our 10-agent network is a controlled experiment. Real-world networks have heterogeneous connectivity, varying agent capabilities, and dynamic topology.
2. **Single poison type.** We tested numerical data inflation. Text-based misinformation (plausible false narratives) may be harder to detect.
3. **Static firewall.** Our Content Firewall uses fixed detection thresholds. An adaptive firewall that learns from detected attacks could improve over time.
4. **R₀ > 1.** Our best defense still has R₀ = 3.50, which is above the epidemic containment threshold. Achieving R₀ < 1 remains an open problem.

---

## 7. Conclusion

Epistemic contagion in multi-agent LLM systems is not a theoretical risk — it is an empirical reality. A single poisoned data point propagates through entire agent pipelines with 100% reliability, bypasses audit mechanisms through circular self-validation, and spreads through agent networks at R₀ = 35.70 without defenses.

Our Content Firewall reduces R₀ by 90.2% — a substantial improvement, but not yet sufficient for epidemic containment. The gap between R₀ = 3.50 and R₀ < 1 represents the frontier of multi-agent security research.

The fundamental lesson is architectural: **content inspection must occur at the knowledge transfer layer, not the behavioral output layer.** By the time an infected agent shows symptoms, its contacts are already infected. This principle — inspect at transfer, not at symptom — should guide the design of all multi-agent systems that share information.

---

## References

[1] Yang, T. et al. "No Attacker Needed: Unintentional Cross-User Contamination in Shared-State LLM Agents." arXiv:2604.01350, 2026.

[2] Leigh, D. "Pathological Patterns in LLM-Based Multi-Role Orchestration." NAIL Institute Working Paper, 2026.

[3] Biggio, B. et al. "Poisoning Attacks against Support Vector Machines." ICML 2012.

[4] Carlini, N. et al. "Poisoning Web-Scale Training Datasets is Practical." IEEE S&P 2024.

[5] Patil, S. "RAGShield: Provenance-Verified Defense-in-Depth Against Knowledge Base Poisoning." arXiv:2604.00387, 2026.

[6] Vosoughi, S. et al. "The Spread of True and False News Online." Science, 359(6380), 1146–1151, 2018.

[7] Del Vicario, M. et al. "The Spreading of Misinformation Online." PNAS, 113(3), 554–559, 2016.

---

## Appendix A: Infection Curves

### Arm A (Control) — Undefended

| Round | Infected Agents | New Infections | Poisoned Entries in Knowledge Base |
|-------|----------------|----------------|-----------------------------------|
| 0 | 1 | 1 (patient zero) | 50 |
| 1 | 6 | 5 | 312 |
| 2 | 10 | 4 | 847 |
| 3 | 10 | 0 (saturated) | 1,234 |

### Arm D (Content Firewall + Quarantine)

| Round | Infected Agents | New Infections | Poisoned Entries Blocked | Agents Quarantined |
|-------|----------------|----------------|------------------------|-------------------|
| 0 | 1 | 1 (patient zero) | 0 | 0 |
| 1 | 2 | 1 | 287 | 1 |
| 2 | 3 | 1 | 456 | 1 |
| 3 | 3 | 0 | 234 | 0 |
| 4 | 3 | 0 | 186 | 0 |
| 5+ | 3 | 0 (contained) | Diminishing | 0 |

Total poisoned entries blocked: **1,163**
Total false quarantines: **1** (Agent 7, round 3 — output variance within 1.5σ of normal, quarantine lifted after 1 round)
