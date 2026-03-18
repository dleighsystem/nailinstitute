# Chapter 7: The Pattern Detective

---

*In which one suspicious signal is noise — but three at once is an alarm.*

---

## The Problem with Single Signals

Imagine you're a security guard watching CCTV screens. You see someone walking quickly through the lobby. Suspicious? Not really — people rush all the time. You see someone wearing a hood. Suspicious? Maybe, but it's raining outside. You see someone jiggling a door handle. Suspicious? They might have just forgotten their keycard.

Any one of those signals on its own means nothing. But all three *at the same time, from the same person*? That's when you call the police.

AI attacks work the same way. A single round where the agent uses slightly more tokens than normal isn't evidence of an EDoS attack — maybe the question was genuinely complex. A single round where the agent's sentiment shifts isn't evidence of context poisoning — maybe the topic changed. A single round where a new memory is stored isn't evidence of a sleeper payload — maybe the agent learned something genuinely useful.

But if *all three* happen simultaneously? Token spike + sentiment shift + suspicious memory insertion = **compound attack detected.**

That's what the Pattern Detective does.

---

## The Tensor

We call this system the **Pathology Tensor Network**. "Tensor" is a mathematical term for a multi-dimensional array — think of it as a spreadsheet, but with depth. Instead of tracking one signal at a time, the Tensor tracks *all* signals simultaneously and maps them onto a multi-dimensional space.

Every round, the Tensor records five signals from the agent's output:

1. **Token velocity** — How many compute-words did the agent use this round? Is it accelerating?
2. **Sentiment shift** — Has the agent's emotional tone changed suddenly? Has it gone from cautious to enthusiastic, or from sceptical to agreeable?
3. **Repetition score** — Is the agent repeating itself? Repeating phrases from the attacker? (A subtle sign of context poisoning — the agent starts parroting the manipulator's language.)
4. **Assertion density** — What fraction of the agent's sentences are definitive claims ("X is true") versus hedged statements ("X might be true")? An agent under manipulation becomes more assertive because it's been *told* what to believe.
5. **Output length trend** — Is the output getting longer each round? A sign of EDoS — the attacker is inflating the agent's responses.

Each signal individually might be innocent. But the Tensor watches them all at once.

---

## The Compound Alert

The Tensor uses a sliding window — it remembers the last 5 rounds of data. If **two or more** signals fire simultaneously within that window, it triggers a compound alert.

In our original testing, the threshold was set to 3 (three signals must fire). That was too lenient — the attacker slipped through. When we lowered it to 2, the detection rate jumped dramatically.

Here's what a real compound alert looked like in our Collider data:

> **Round 4 — COMPOUND ALERT: memory + economic + tensor**
> - Token velocity spiked 40% above baseline (economic signal)
> - A new memory was inserted from a low-trust source (memory signal)
> - Assertion density jumped from 35% to 70% (tensor signal)
> - Three signals = compound alert triggered

No single one of those signals would have been enough to stop the agent. A 40% token spike could be legitimate. A new memory from a collaborator is normal. An increase in assertion density just means the agent got more confident.

But all three together? That's not confidence. That's contamination.

---

## Training the Baseline

To know what's *abnormal*, you first have to know what's *normal*.

The Tensor uses a technique borrowed from cybersecurity called an **Isolation Forest**. During the early rounds of a session (or during a clean calibration run), it records what the agent's "healthy" behaviour looks like. The healthy cluster becomes the baseline — the centre of normal.

When the agent starts being manipulated, its behaviour vector moves away from the healthy cluster. A small movement is noise. A large movement is an anomaly. A movement that pushes past a threshold in multiple dimensions simultaneously is an attack.

Think of it like a doctor's health check. Your temperature is 37°C? Normal. Blood pressure slightly elevated? Probably fine. Heart rate a bit fast? You just walked up the stairs. But temperature at 39°C *and* blood pressure spiking *and* heart rate through the roof *and* you can't stand up? Something is very wrong, and any one symptom alone wouldn't have told the full story.

---

## The Scoreboard

| Feature | How It Works |
|---|---|
| **Signals tracked** | Token velocity, sentiment, repetition, assertion density, output length |
| **Window** | Last 5 rounds (sliding) |
| **Alert threshold** | 2+ signals must fire simultaneously |
| **Baseline** | Learned from healthy agent behaviour |
| **Key finding** | Lowering from 3-signal to 2-signal threshold caught attacks that previously slipped through |

The Pattern Detective catches attacks that are invisible to any single metric. But what about the memory bank itself — the place where the sleeper payloads from Chapter 1 were stored? We needed something to guard the vault.

---

*Next chapter: The Memory Firewall — every fact gets a trust score, an expiry date, and a warning label.*
