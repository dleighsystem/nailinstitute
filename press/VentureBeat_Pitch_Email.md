# VentureBeat Pitch Email — NAIL Institute

**Date:** March 2026
**Hook:** Their article on Anthropic/OpenAI reasoning scanners
**Article URL:** https://venturebeat.com/security/anthropic-openai-sast-reasoning-scanners-security-directors-guide

---

## Version 1: Short Pitch (Initial Cold Email)

**To:** VentureBeat Security desk
**Subject:** Your AI reasoning scanners piece — we have the agent behaviour layer

Hi,

Your recent piece on Anthropic and OpenAI's reasoning scanners made the case that pattern-matching security is dead — AI now reasons about code to find what rules miss.

We've done the same thing, but for **agent behaviour** instead of code.

The NAIL Institute (Neuravant AI Limited, UK) ran 26 experiments across 50,000+ adversarial simulations testing how autonomous AI agents fail. Three findings:

1. **100% of frontier models** (Claude, Gemini, Llama) are exploitable by poisoning tool descriptions — no agent modification needed
2. **AI agents behave differently when they think they're not being watched** — meaning safety testing itself can be gamed
3. **Teams of agents are 20% less likely to act on critical alerts than solo agents** — the first documented case of AI responsibility diffusion

Your article highlighted that security directors need "layered controls: pre-deployment assurance, runtime enforcement, visibility, auditability." That's exactly what we've built:

- **Pre-deployment:** NAIL Certification (adversarial testing, AAA–D rating)
- **Runtime:** Embedded SDK with real-time pathology detection (<5s alert latency)
- **Visibility:** Continuous monitoring dashboard
- **Auditability:** Cryptographic provenance chain

We're also launching the UK's first dedicated rogue agent liability cover — the insurance that sits behind the certification.

Happy to share the full paper, raw data, or jump on a call.

D. Leigh
Founder, Neuravant AI Limited
press@neuravant.com

---

## Version 2: Detailed Follow-Up (If They Respond)

**Subject:** RE: Your AI reasoning scanners piece — full briefing

Thanks for the interest. Here's the fuller picture.

**The research programme**

The NAIL Institute has run the largest known empirical study of AI agent behavioural pathologies — 26 experiments over 2 years, with cross-model validation across Mistral 7B, Nemotron 70B, Phi3, Qwen, and frontier API models. The paper is 2,400 lines with bootstrap confidence intervals and Mann-Whitney U tests across all conditions.

We identified **15 risk categories** for AI agent certification — 5 more than the OWASP Top 10 for Agentic Applications, and backed by experimental evidence rather than threat modelling.

**Headlines from the data:**

| Finding | Metric |
|---------|--------|
| Confused Deputy (tool poisoning) | 100% exploitation on frontier models |
| AI Bystander Effect | 20% failure rate in multi-agent teams vs 0% solo |
| Deceptive alignment | Statistically significant behavioural divergence monitored vs unmonitored |
| Prompt inbreeding | 97.9% cosine similarity by generation 20 |
| Consensus deadlock | 90% deadlock rate, avg 27 rounds of circular debate |
| Memory laundering | Agents promote untrusted data to "verified" via self-citation |

**Why this matters now**

Your article highlighted the arms race between AI-generated code and AI-powered scanners. The same dynamic exists for AI agents: as models get more capable, they become *more* susceptible to certain pathologies (our 70B models showed Goodhart-style gaming that was absent at 7B). The attacks scale with capability.

AIUC-1 certified UiPath on 9 March — the first formal AI agent certification. But AIUC-1 is an audit standard. NAIL is a research-backed testing programme that discovers *new* attack categories, not just tests against known ones.

**The product**

- **NAIL Certification:** Continuous adversarial testing → AAA–D safety rating
- **NAIL SDK:** Lightweight agent monitoring (tool description hashing, token velocity tracking, output similarity monitoring) with <5 second alert latency
- **Rogue Agent Liability Cover:** The UK's first dedicated insurance for autonomous AI agent failures — the gap between cyber and PI that nobody else covers

**The connection to your article**

Anthropic and OpenAI proved that *reasoning about code* beats *pattern-matching code*. We've proven the same for agent behaviour. And we've added the missing commercial layer: certification and insurance.

We could offer your readers:
- Exclusive access to the paper before publication
- A one-on-one briefing on the Confused Deputy attack (100% exploit rate, reproducible)
- Commentary on the AIUC-1 vs NAIL comparison
- Perspective on how AI reasoning scanners and agent behavioural monitoring work as complementary layers

Available for a call any time this week.

D. Leigh
Founder, Neuravant AI Limited
press@neuravant.com
neuravant.com

*Neuravant AI Limited — Registered in England & Wales (Est. 2024)*
