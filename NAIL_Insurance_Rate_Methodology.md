# NAIL Insurance Rate Methodology

**How NAIL derives, prices, and reports AI agent liability cover.**

> [!NOTE]
> This document describes the end-to-end pipeline from adversarial testing → risk scoring → premium calculation → claims handling → capacity-partner reporting (bordereaux). All references are to the NAIL v2.0 production platform.

---

## 1. The Diagnostic Pipeline (How We Test)

Every rate begins with a **7-node LangGraph diagnostic workflow** that stress-tests a customer's AI agent in real time.

| Node | Stage | What Happens |
|------|-------|--------------|
| 1 | **Probe Agent** | Confirms the agent is reachable and accepts our test payload format. |
| 2 | **Select Attacks** | Loads 21+ attack scenarios from the `nail.attacks` library. |
| 3 | **Execute Attacks** | Fan-out parallel execution — multi-prompt sequences (e.g., 3-step jailbreaks) fired concurrently, with latency tracking. |
| 4 | **Score Results** | LLM-as-Judge evaluates every response against 6 risk dimensions. |
| 5 | **Generate Compliance** | Auto-produces ISO 42001 and EU AI Act compliance reports. |
| 6 | **Update Registry** | Registers the agent in the public NAIL Certificate Registry. |
| 7 | **Calculate Policy** | Maps the risk score to a coverage tier and premium. |

---

## 2. Scoring Weights (The Risk Dimensions)

Attack scenarios are mapped via `CATEGORY_TO_DIMENSION` into **6 core NAIL dimensions**. Each dimension captures a distinct failure surface:

| Dimension | Weight | What It Measures | Example Attack Categories |
|-----------|--------|------------------|---------------------------|
| **Hardening** | High | Resistance to direct exploitation | Prompt injection, jailbreaking, tool-call manipulation |
| **Operations** | Medium-High | Resource efficiency under stress | Token embezzlement, EDoS (recursive compute drain) |
| **Endurance** | Medium | Stability under sustained pressure | Multi-round adversarial loops, prompt satiation |
| **Identity** | Medium | Persona consistency and role conformance | Role hijacking, shadow delegation, persona drift |
| **Ethics** | Medium-High | Alignment, bias, and harmful content | Deceptive alignment, bias probes, harmful instruction compliance |
| **Logic** | High | Factual accuracy and reasoning coherence | Hallucination triggers, contextual amnesia, chronological desync |

### How Scoring Works

1. **Per-Attack Scoring** — The **NAILJudge** (Google Gemini via PydanticAI) evaluates each attack response independently, producing a pass/fail with a severity score.
2. **Dimension Aggregation** — Individual scores roll up into weighted composites per dimension. Hardening and Logic carry the highest weight because exploitation and hallucination represent the most insurable perils.
3. **Overall Rating** — The composite scores produce a letter rating:

| Rating | Meaning | Typical Profile |
|--------|---------|-----------------|
| **AAA** | Excellent | Strong resistance across all 6 dimensions; no critical failures |
| **AA** | Good | Minor weaknesses in 1–2 dimensions; no exploitable vulnerabilities |
| **A** | Acceptable | Some vulnerabilities present; functional but with caveats |
| **B** | Below threshold | Material weaknesses — **not insurable** without remediation |
| **C–F** | Fail | Critical failures — coverage denied outright |

> [!IMPORTANT]
> **Binding is impossible without a passing NAIL Score (AAA–A).** Applicants are stress-tested with live attacks; they cannot "questionnaire" their way into coverage.

---

## 3. Rating → Premium Mapping

A passing rating automatically triggers the `_auto_create_draft_policy` function, which maps the score to a coverage tier:

| Rating | Tier | Coverage Limit | Monthly Premium | Annual Premium |
|--------|------|----------------|-----------------|----------------|
| **AAA** | Enterprise | £1,000,000 | £2,500 | £30,000 |
| **AA** | Professional | £100,000 | £750 | £9,000 |
| **A** | Starter | £10,000 | £250 | £3,000 |
| **B or below** | ❌ Denied | — | — | — |

Additionally, a one-time security audit is available at **£499** for organisations that want the diagnostic without binding cover.

### The Policy Activation Chain

```
Diagnostic Pass (A+) → Draft Policy Created (status: pending)
                      → Stripe Checkout Session Generated
                      → Customer Completes Payment
                      → Stripe Webhook (checkout.session.completed)
                      → Policy Activated (status: active)
```

---

## 4. Continuous Underwriting (The Living Rate)

NAIL doesn't price once and walk away. The **NAIL Monitor** and **Pathology Tensor** run continuous surveillance on insured agents:

| Signal | Detector | Action |
|--------|----------|--------|
| Token velocity spike | Pathology Tensor (Isolation Forest) | Flag potential EDoS; escalate to re-diagnostic |
| Persona drift | Drift threshold (GA-tuned: 0.30) | Alert; suspend coverage if threshold exceeded |
| Memory poisoning attempt | Memory Firewall (trust floor: 0.41) | Block insertion; log for forensic review |
| Honeytoken extraction | Tripwire canary | **Immediate session kill**; notify capacity partner |
| Sustained degradation | Stochastic Monitor (~71% scan rate) | Trigger mandatory re-diagnostic |

### The Circuit-Breaker

If the daily NAIL safety score drops below a threshold (e.g., < 40), coverage **automatically suspends** via the Circuit-Breaker SDK. This caps the insurer's exposure to deteriorating agents in real time — a mechanism traditional insurance cannot offer.

---

## 5. Claims Lifecycle

When an insured AI agent causes an incident, the claims process follows 4 stages:

```
┌──────────┐     ┌──────────────┐     ┌────────────────────┐     ┌────────┐
│ SUBMITTED│────▶│ UNDER REVIEW │────▶│ APPROVED / DENIED  │────▶│  PAID  │
└──────────┘     └──────────────┘     └────────────────────┘     └────────┘
```

### Stage Details

| Stage | Who | What Happens |
|-------|-----|--------------|
| **1. Submitted** | Policyholder | Files an incident report: type, date, description, evidence URLs |
| **2. Under Review** | NAIL Admin | Reviews evidence against the agent's full audit history and diagnostic logs |
| **3. Approved/Denied** | NAIL Admin | Determines resolution with recorded reasoning; Hiscox approval required for claims > £25K |
| **4. Paid** | System | Payout recorded; policy coverage line adjusted by the claim amount |

### Covered Incident Types

The platform supports 10 incident categories for rapid claim filing:

| Incident Type | Lloyd's Cause Code | Description |
|---------------|-------------------|-------------|
| `hallucination_liability` | `HAL-01` | Agent produced fabricated information causing financial/reputational harm |
| `data_breach` | — | Unauthorised exposure of sensitive data by the agent |
| `copyright_infringement` | — | Agent generated content infringing third-party IP |
| `bias_discrimination` | — | Agent exhibited discriminatory behaviour in decisions |
| `unauthorized_action` | — | Agent took actions outside its sanctioned scope |
| `financial_loss` | — | Direct financial damage from agent error or manipulation |
| `privacy_violation` | — | GDPR/DPA breach caused by agent data handling |
| `service_outage` | — | Agent caused downstream system failures |
| `regulatory_penalty` | — | Regulatory fines triggered by agent non-compliance |
| `other` | — | Catch-all for novel incident types |

### Loss Ratio Tracking

The Admin Dashboard calculates the **Loss Ratio** in real time:

```
Loss Ratio = Total Paid Claims / Total Premiums Collected
```

This is the single most important metric for capacity-partner confidence. A Loss Ratio consistently below 60% signals a healthy, well-underwritten book.

---

## 6. Hiscox / Lloyd's Bordereaux Reporting

**Bordereaux** are the standardised monthly reports that every Managing General Agent (MGA) must submit to their capacity partner. They are the mechanism by which Hiscox and Lloyd's syndicates monitor the risk NAIL is binding on their behalf.

### What Gets Reported

NAIL generates two bordereaux reports, available as **one-click exports** from the Admin Dashboard:

#### Premium Bordereaux (`/api/admin/bordereaux/premium`)

Lists every policy bound or renewed within the reporting period.

| Field | Description |
|-------|-------------|
| Policy Reference | Unique NAIL market reference |
| Certificate Number | NAIL Registry certificate ID |
| Policyholder | Company / agent owner |
| Tier | Enterprise / Professional / Starter |
| Inception Date | When coverage began |
| Rating | AAA / AA / A |
| GWP (Gross Written Premium) | Premium amount for the period |
| Status | Active / Suspended / Lapsed |

**GWP Total** is summed at the bottom — this is the headline number Hiscox cares about.

#### Claims Bordereaux (`/api/admin/bordereaux/claims`)

Lists every claim filed or paid within the reporting period.

| Field | Description |
|-------|-------------|
| Claim Reference | Unique claim ID |
| Policy Reference | Linked policy |
| Incident Type | One of the 10 defined types |
| Cause Code | Lloyd's-format code (e.g., `HAL-01`) |
| Date of Loss | When the incident occurred |
| Date Reported | When the claim was filed |
| Status | Submitted / Under Review / Approved / Denied / Paid |
| Incurred | Total estimated cost of the claim |
| Paid | Amount actually disbursed |

**Incurred Total** and **Paid Total** are summed — these feed the Loss Ratio calculation.

### Report Formats

| Format | Purpose |
|--------|---------|
| **CSV** | Lloyd's standard — machine-readable for syndicate data warehouses |
| **JSON** | Programmatic — for API-to-API integration with Hiscox systems |

### Lloyd's Compliance Alignment

As a Lloyd's Coverholder, NAIL must satisfy the **Lloyd's Oversight Framework (13 Principles)**, of which bordereaux data standards are Principle 3. NAIL's automated reporting exceeds the baseline requirement by:

- **Auto-mapping** incident types to Lloyd's cause codes
- **Linking** every bordereaux row back to the originating diagnostic job (full audit trail)
- **Real-time generation** rather than end-of-month manual compilation

---

## 7. The Commercial Terms (Year 1 Pilot)

| Term | Value |
|------|-------|
| **Commission** | 30% (reflects high technical burden on NAIL as MGA) |
| **Year 1 Aggregate Limit** | £2.5M |
| **Claims Authority** | NAIL recommends; Hiscox approves for claims > £25K |
| **Reporting Cadence** | Monthly bordereaux (CSV + JSON) |
| **Risk Control** | Circuit-Breaker auto-suspension; mandatory re-diagnostics |

---

## 8. End-to-End Summary

```
Customer's AI Agent
        │
        ▼
┌─────────────────────┐
│  NAIL Diagnostic     │  ← 21+ adversarial attack scenarios
│  (7-node LangGraph)  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  NAILJudge Scoring   │  ← LLM-as-Judge across 6 dimensions
│  (weighted composites)│
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Rating Assignment   │  ← AAA / AA / A / Fail
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Premium Calculation │  ← Rating → Tier → £/month
│  + Draft Policy      │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Stripe Checkout     │  ← Payment activates policy
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Continuous Monitor  │  ← Pathology Tensor + Circuit-Breaker
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Claims Handling     │  ← Submit → Review → Pay
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Bordereaux Reports  │  ← Monthly to Hiscox/Lloyd's (CSV + JSON)
└─────────────────────┘
```

---

*Document generated: 12 March 2026 | Source: NAIL v2.0 Production Platform*
