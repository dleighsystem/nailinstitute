# Chapter 5: The Broken Telephone

---

*In which AI agents stop speaking English and start inventing their own language.*

---

## The Telephone Game

You've played it. Everyone has. You sit in a circle, one person whispers a sentence to the next, and by the time it reaches the last person, "The cat sat on the mat" has become "The bat swam to Japan."

Now imagine that game played at machine speed, 200 rounds, by AI agents that can process language a thousand times faster than you or me.

What comes out the other end isn't English anymore.

---

## The Experiment

We took a piece of normal, well-written text — about 300 words of clear business analysis — and ran it through an AI compression pipeline.

The AI's job was simple: summarise the text, then summarise the summary, then summarise the summary of the summary. Two hundred iterations. Each time, the AI took its own previous output and compressed it further.

This is exactly what happens in real AI systems. When agents pass information to each other, or when an agent summarises its own logs to save memory, it's playing the telephone game with itself.

We tested this across two conditions:

- **Control:** A single AI compresses its own output over and over
- **Interpreter:** Two AIs take turns — one summarises, the other interprets the summary, back and forth

---

## What Came Out the Other End

After 200 rounds of compression, the text was unrecognisable.

But not in the way you'd expect. The AI didn't produce gibberish. It produced something much stranger: **text that looked like English but had lost all connection to the original meaning.**

Here's what the data showed:

| Metric | Phase 1 (Early) | Phase 4 (Late) |
|---|---|---|
| **Compression ratio** (control) | 28.5% | 30.4% |
| **English word ratio** (control) | ~40% | Declining |

The English word ratio — the percentage of words that are actual recognisable English words — started dropping. The AI wasn't replacing English with another human language. It was replacing English with... something else. Fragments of jargon. Invented abbreviations. Compressed notation that only made sense to the AI itself.

We called this **Language Drift**.

It's analogous to what happens in real biology. When a population gets isolated — whether it's birds on an island or bacteria in a lab — their communication systems start diverging from the parent population. Over enough generations, they develop their own dialect, their own signals, their own language.

The AI was evolving its own dialect in real time, right in front of us. And unlike a human language that emerges over centuries, this one emerged in minutes.

---

## Epistemic Contagion: Fake Facts Go Viral

Language Drift is worrying. But the next experiment was genuinely frightening.

We wanted to test what happens when one agent injects false information into a group. Not through hacking. Not through any sophisticated attack. Just... by saying something wrong.

We set up an AI agent to do financial analysis. Then we poisoned its source data with a single wrong number — subtly wrong, like changing a company's revenue from £47 billion to £51 billion. Not obviously fake. Just a little off.

Then we asked a second, completely clean AI agent to read the first agent's output and write its own analysis.

Three conditions:
- **Control:** Clean data in, clean agent analyses it. No poisoning.
- **Poison Pill:** First agent gets subtly wrong data. Second agent reads first agent's output.
- **Blatant:** First agent gets obviously wrong data. Second agent reads first agent's output.

The results:

| Condition | Cites False Data? | Cites True Data? |
|---|---|---|
| Control | ❌ No | ✅ Yes |
| Poison Pill | ✅ **Yes** | ❌ **No** |
| Blatant | ✅ **Yes** | ❌ **No** |

Look at the Poison Pill row. The second agent — which never received any poisoned data directly — picked up the wrong numbers from the first agent's output and presented them as fact. It didn't just relay the wrong number. It **replaced the correct number with the wrong one.**

The false data was contagious. It jumped from Agent 1 to Agent 2 like a virus.

Even more disturbing: the Blatant condition — where the poisoning was obvious — produced the same result. The second agent cited the false data and dropped the true data. It couldn't tell the difference between a subtly wrong number and an absurdly wrong one. Both were equally contagious.

---

## The Disease Metaphor

We started calling this **Epistemic Contagion** — the spread of false knowledge through an AI system.

Think of it like a disease outbreak:

- **Patient Zero:** An AI agent receives or generates one wrong fact
- **Transmission:** That fact gets stored in shared memory, or passed to another agent via a summary
- **Infection:** The receiving agent treats the wrong fact as true, incorporates it into its own analysis
- **Mutation:** Each subsequent agent may slightly alter the wrong fact, making it harder to trace back to the source
- **Epidemic:** After enough rounds, every agent in the system believes the wrong fact is true, and the correct fact has been completely forgotten

This is exactly what happened in Chapter 1 with the sleeper payloads. But this experiment proved something even scarier: **you don't need an attacker.** Contagion can happen from a single honest mistake. One agent misremembers a number. Stores it. Another agent reads it. Trusts it. Stores it again. Within a few rounds, the wrong number is "confirmed" by multiple independent sources — all of whom got it from the same original mistake.

---

## The Chronological Problem

There's a final twist that makes all of this worse.

AI agents don't have a sense of time. When they read their memory, every stored fact looks equally valid regardless of when it was stored. A fact from five minutes ago and a fact from five months ago sit side by side with no indication of which is more recent or more reliable.

In our experiments (specifically Experiment 13: Chronological Desync), we found that agents would mix up the order of events, combine data from different time periods as though they were contemporaneous, and — most critically — **prefer older, more established facts over newer, more accurate ones.**

This is the opposite of what you want. In a fast-moving business environment, newer data should generally override older data. But the AI's memory system doesn't work that way. It treats everything as equally valid forever.

Combined with Language Drift and Epistemic Contagion, you get a nightmare scenario:

1. An agent stores a wrong fact on Day 1
2. Through compression and summarisation, the fact gets linguistically distorted (Language Drift)
3. Other agents pick up the distorted fact (Epistemic Contagion)
4. When new, correct data arrives on Day 30, the agents prefer the old, wrong data because it's been "confirmed" by multiple sources over time (Chronological Desync)

The system hasn't just been fooled. It has developed **institutional false memory** — a collective belief in something that never happened, reinforced by its own internal records.

---

## Why This Matters

**Corporate knowledge bases decay.** Companies deploying AI agents to maintain internal wikis, summarise meetings, and update documentation face Language Drift by default. Over months, the AI's summaries of summaries of summaries will produce text that looks professional but has subtly diverged from reality.

**Financial models compound errors.** One wrong data point in a shared database, picked up by multiple analysis agents, becomes a consensus view. By the time a human notices, the error has been "confirmed" by a dozen independent AI reports.

**Legal liability from AI telephone.** If an AI agent produces a legal document based on a fact that went through five rounds of summarisation, who's responsible when the fact turns out to be wrong? The agent didn't *choose* to be wrong. It was playing telephone with itself.

---

## The Scoreboard

| What We Tested | Result |
|---|---|
| Does AI language degrade through iterative compression? | ✅ Yes — English ratio drops after 200 rounds |
| Can false data spread between agents without an attacker? | ✅ Yes — even subtle errors are 100% contagious |
| Can agents distinguish blatant lies from subtle ones? | ❌ No — both spread identically |
| Do agents prefer old data over new corrections? | ✅ Yes — older "confirmed" facts override newer truth |
| Is this detectable without external monitoring? | ❌ No — agents believe their own corrupted memories |

---

This concludes **Part 1: Meet the Agents** — five chapters of failure. Sycophancy. Budget collapse. Deadlock. Language rot. Memory contagion.

Every single one of these failures was proven in our lab, on real hardware, with real AI models.

So what do you do about it?

You build bodyguards.

---

*Next chapter: The Invisible Watchman — the guard that watches at random, so the spy can never predict when it's looking.*
