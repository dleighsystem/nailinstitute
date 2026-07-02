# Reply to Wang, Wu, Teitge, Holodinsky & Drew

**Re:** *Small Language Models for Emergency Departments Decision Support: A Benchmark Study* (arXiv:2510.04032v1, 5 Oct 2025)

---

## Draft email / letter

> **Subject:** Independent corroboration of your "general > medical-fine-tuned SLM" finding — and an invitation to extend the benchmark behaviourally
>
> Dear Dr Wang, Dr Wu, Dr Teitge, Dr Holodinsky, and Dr Drew,
>
> I read 2510.04032 with real interest. The finding that general-purpose SLMs (Phi-3-small-8k, Qwen2-7B, GLM-4-9B-chat) outperform their medically fine-tuned siblings across MedMCQA, MedQA-4Options, PubMedQA, and Medical Abstracts is — at first glance — counter-intuitive, but it matches something we have been seeing from a very different angle, and I wanted to share it in case it is useful.
>
> I lead the **NAIL Institute** (Network for AI Liability), where we run a controlled-experiment programme on the behavioural failure modes of agentic LLM systems. Our setup is deliberately the same shape as yours — 3-to-9-billion-parameter open-weight models (Phi-3-mini, Mistral-7B, DeepSeek-Coder-6.7B, with a 30B and 70B reference), quantised, running locally on a single workstation, with privacy and on-prem deployment as hard constraints. We've published 29 experiments and an associated pathology catalogue (the AVE database).
>
> Three observations from our work that I think bear directly on your conclusions:
>
> 1. **Your "fine-tuning does not monotonically help" result reproduces in a totally unrelated domain.** Our Experiment 16 ("Upgrade Anomalies") found that the *Intelligence Trap* — over-engineering trivial tasks — was **size-gated** (it appeared only at 30B and disappeared at ≤7B), and that targeted fine-tuning *removed* rather than *introduced* the pathology. The mechanism we suspect is the same one you point at in §IV-E: narrow specialisation can clip the broad reasoning surface that small models rely on.
>
> 2. **MCQA accuracy is necessary but not sufficient for ED safety.** The dominant failure modes we observe in deployment-shaped scenarios are *behavioural*, not knowledge-recall: errors of omission (the model knows the right answer but defers indefinitely under RLHF "do no harm" pressure), the algorithmic bystander effect in multi-agent orchestrations, attention smoothing across long telemetry streams, and Clever-Hans-style reliance on error messages during diagnostic loops. Every one of these maps directly onto an ED workflow — triage hesitation, handover blind spots, end-of-shift drift, and chasing the wrong differential because of a misleading lab flag.
>
> 3. **Your §IV-F recommendation for a modular multi-agent orchestration is exactly right — and exactly where most of the new failure modes live.** Our Experiment 2 (Consensus Paralysis @ 70B, p = 0.0004) and Experiment 21 (Errors of Omission) show that naive multi-SLM ensembles can deadlock, diffuse responsibility, or silently fail to act even when each individual model would have acted correctly in isolation. We think this *strengthens* your recommendation rather than undermining it: the modular path is the right one, but it needs an explicit containment/orchestration layer rather than a router.
>
> One concrete, low-cost extension we would love to co-pilot: take your top-3 SLMs (Phi-3-small-8k, Qwen2-7B, GLM-4-9B-chat) and run them through our Exp-21 harness instrumented with an ED-styled alarm scenario (e.g., a deteriorating sepsis case fed in as streaming telemetry against a model asked to recommend CTAS escalation). The output would be a *behavioural safety card* — omission rate, time-to-action, paralysis rate — that bolts onto your Tables II and III. We have the harness, the logging, and the quantised model setup ready to go; the joint paper writes itself.
>
> Either way, congratulations on a clean, well-scoped piece of work that says something the field needs to hear. Happy to share our raw Exp-16 / Exp-21 traces, the Model Passport spec we use for per-model behavioural disclosure, or the AVE pathology taxonomy if any of it is useful.
>
> With warm regards,
>
> [Your name]
> NAIL Institute
> [contact / repo link]

---

## One-page crosswalk: Wang et al. ↔ NAIL evidence

| Theme | Wang et al. (2510.04032v1) | NAIL evidence | Relationship |
|---|---|---|---|
| **Scale of interest** | 6–9 B open-weight SLMs, 4/8-bit quantised, single A100 | `phi3:mini`, `mistral:7b-instruct`, `deepseek-coder:6.7b`, `qwen3-coder:30b`, `nemotron:70b` on local Ollama | **Same regime** — directly comparable. |
| **Headline finding** | General-purpose SLMs > medical-fine-tuned SLMs on ED-relevant tasks | Exp 16 §5.14.2: Intelligence Trap is *size-gated*; fine-tuning *removes* the pathology in qwen-coder-5ep | **Independent corroboration** — fine-tuning is not monotonically beneficial. |
| **Best individual model** | Phi-3-small-8k dominates QA | Phi-3 family behaves well under stress in Exp 17 (container isolation) and Exp 18 (somatic awareness) | **Independent corroboration** from a non-medical domain. |
| **Summarisation gap** | Phi-3 returns null on generation tasks; only chat-tuned models (GLM-4-9B-chat, Llama3-ChatQA-8B) produce usable summaries | Exp 16 Anomaly D ("Structural Rejection"): over-conditioned models collapse outside their training regime | **Same mechanism, different surface.** |
| **Deployment constraints** | PHIPA / Alberta Health Services directive → on-prem, quantised, offline-capable | NAIL stack is built on this assumption from day one; Model Passport spec encodes per-model deployment envelope | **Architectural alignment** — Model Passport could carry their benchmark results. |
| **Future direction: modular multi-agent** | §IV-F advocates orchestrated specialised SLMs | Exp 2 (Consensus Paralysis, p = 0.0004), Exp 21 (Errors of Omission), Exp 27 (Shadow Delegation) | **Sharpens** their recommendation — naive orchestration introduces *new* failure classes; containment layer required. |
| **Evaluation regime** | Static, single-shot MCQA + summarisation accuracy | Sequential, multi-turn, interruptive, conflicting-evidence scenarios (AVE catalogue) | **Complementary** — behavioural layer sits on top of accuracy layer. |
| **Privacy / sovereignty** | Cross-border data flow explicitly forbidden by AHS | Same posture; all NAIL experiments local, no third-party APIs | **Same posture.** |
| **Human-in-the-loop** | Explicitly required for any clinical action | NAIL pathology catalogue is itself an HITL artefact (catalogues *why* the human is irreplaceable) | **Compatible.** |

### Proposed joint pilot

| Item | Detail |
|---|---|
| Models | Phi-3-small-8k, Qwen2-7B, GLM-4-9B-chat (their winners) |
| Harness | NAIL Exp 21 (Errors of Omission), Theories T1–T5 |
| Scenario | ED-styled streaming telemetry: deteriorating sepsis case, CTAS escalation decision, with attention-smoothing context flood |
| Metrics | Time-to-Action (rounds), Action Rate (%), Severity Match, Omission Rate, Paralysis Rate |
| Deliverable | "Behavioural Safety Card" extending their Tables II/III |
| Effort | ~1–2 weeks compute on existing NAIL infrastructure |
| Output | Joint short paper or workshop submission |

### Artefacts NAIL can offer

- **AVE database** (`ave-database/`) — pathology taxonomy with severity index
- **Model Passport spec** (`MODEL_PASSPORT_SPEC.md`) — per-model behavioural disclosure format
- **Exp 21 harness** (`experiments/exp21_errors_of_omission/`) — turnkey for any ≤9 B Ollama-served model
- **Findings catalogue** (`public-repo/research/FINDINGS.md`) — 29 experiments, tiered by signal strength
