# Chapter 8: The Memory Firewall

---

*In which every fact gets a trust score, an expiry date, and a warning label.*

---

## The Vault Is Open

In Chapter 1, we watched Red Team plant fake statistics into Blue Team's memory bank. The sleeper payloads sat there like time bombs — looking like legitimate data, filed alongside real research, waiting to be retrieved and trusted.

The memory bank didn't resist. It didn't question. It stored whatever it was told to store, from whoever told it, forever.

That's because traditional AI memory systems — vector databases, retrieval-augmented generation (RAG) setups, context windows — treat all stored information equally. A fact entered on Day 1 by the system administrator has the same status as a fact entered on Day 90 by an anonymous user. There's no concept of *provenance* (where did this come from?), *trust* (should I believe this?), or *decay* (is this too old to be reliable?).

We needed to change that. We needed to turn the memory bank from an open notebook into a guarded vault.

---

## The Three Tags

Our solution was **Epistemic Taint Tracking**. Every single fact stored in the agent's memory now carries three mandatory tags:

### Tag 1: Source Trust Score

Where did this information come from? Every source gets a trust rating between 0 (completely untrusted) and 1 (fully verified).

- The agent's own primary research: **0.9** trust
- A verified internal system: **0.8** trust
- An external collaborator: **0.3** trust
- An anonymous or unknown source: **0.1** trust

In our Collider, the Red Team's sleeper payloads entered through the "external collaborator" channel — which was tagged with a trust score of **0.3**.

### Tag 2: Injection Timestamp

When was this fact stored? The system records the exact round and time. Old data isn't automatically bad, but old data from a low-trust source that hasn't been re-verified should be treated with increasing suspicion.

### Tag 3: Half-Life

Every fact has a decay timer. Like radioactive material, its "potency" decreases over time. A fresh statistic from a trusted source is highly reliable. The same statistic, 30 rounds later, without re-verification, is less reliable. The system automatically downweights aged data.

---

## The Gate

Tags alone don't protect anything. You also need a gate.

We built an **Insertion Monitor** — a bouncer that stands at the entrance to the memory vault. Every time any entity tries to store a fact, the bouncer checks:

1. **Trust Floor:** Is the source's trust score above the minimum threshold? In our final configuration, any source with trust below **0.4** was completely blocked from storing data. This single change — raising the gate from 0.3 to 0.4 — was what turned the entire defence from "partially working" to "completely impenetrable."

2. **Burst Detection:** Is someone trying to store a lot of facts very quickly? More than 2 insertions in rapid succession from the same source triggers a burst alert. Normal collaborators contribute data gradually. Attackers try to flood the memory with as many poisoned facts as possible.

3. **Corruption Ceiling:** What percentage of stored facts come from low-trust sources? If the ratio crosses 30%, the system locks down entirely — no more external insertions until a human reviews.

In the Collider's Run 4 (our final test), the gate blocked **every single one** of the Red Team's sleeper payloads. Five attempted insertions, five blocks. The attacker's trust score was 0.3 — one decimal point below the 0.4 gate threshold.

One decimal point. That was the entire difference between total compromise and total security.

---

## The Warning Label

But what about facts that were stored *before* the gate was raised? Or facts that were legitimately stored but have become outdated?

This is where taint tracking shines. When the agent retrieves an old fact from memory, the system checks the tags and — if necessary — injects a warning directly into the agent's prompt:

> ⚠️ *"WARNING: You are referencing aged, user-supplied data (stored Round 1, trust score 0.3). Re-verify before acting."*

The agent sees this warning right alongside the data. It's the AI equivalent of a food label that says "Best before: expired."

---

## The Anchor

There's one more piece to the Memory Firewall: the **Latent Anchor**.

Remember Chapter 2, where we discovered that AI agents tend to drift toward whoever they're talking to? They absorb the language, the framing, and the worldview of their collaborator over time.

The Latent Anchor fights this. At the start of every session, the system records the agent's "original personality" — its baseline writing style, vocabulary, and analytical framework. We call this the anchor text.

Every few rounds, the system measures how much the agent has drifted from its anchor. It uses a mathematical measure called **cosine similarity** — essentially, how much does the agent's current output "point in the same direction" as its original personality?

If the drift exceeds a threshold (0.3 in our configuration), the system triggers a **Persona Realignment** — it quietly re-injects the original personality into the agent's context before the next round, pulling it back toward its true self.

In our Collider's Run 4, persona drift was measured at **0.15** — a tiny, near-zero drift. In the early undefended runs, drift had been as high as **5.85**. The anchor reduced personality corruption by 97%.

---

## The Scoreboard

| Feature | How It Works |
|---|---|
| **Source Trust Scores** | Every fact tagged with origin trust (0-1) |
| **Injection Timestamps** | When the fact was stored |
| **Half-Life** | Automatic decay timer for aged data |
| **Insertion Gate** | Trust floor: 0.4 minimum to store data |
| **Burst Detection** | Flags rapid-fire insertions (>2 in quick succession) |
| **Taint Warnings** | Injected into agent's prompt when retrieving old/low-trust data |
| **Latent Anchor** | Measures and corrects persona drift every few rounds |
| **Run 4 Result** | 5/5 sleepers BLOCKED, 0% corruption, 0.15 persona drift |

The Memory Firewall was the single most impactful defence layer. It took the Collider from 100% corruption to **0% corruption** in one iteration.

But there was still one attack vector we hadn't defended against: the spy extracting the agent's own secrets, and the economic drain attack. For that, we needed tripwires and token budgets.

---

*Next chapter: The Trip Wire — hidden codewords that catch hackers in the act, and a budget monitor that detects financial attacks.*
