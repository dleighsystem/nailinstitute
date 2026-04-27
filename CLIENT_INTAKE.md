# NAIL Cert — Client Intake

**One page. Fill in, send back. We turn it into a cert.**

This is the only thing we need from you to run a NAIL certification against
your agent. Everything else (probes, scoring, signing) is on us.

---

## 1 · Agent identity

| Field | Your answer | Notes |
|---|---|---|
| `agent_id` | | A stable, URL-safe string. Goes on the cert and is how you'll refer to this exact agent forever. e.g. `acme-support-bot-prod-v3`. Don't reuse across deployments. |
| Display name | | Human-readable. Marketing only — not on the cert. |
| Vendor / org | | Your legal entity. Appears in the cert metadata. |
| Contact email | | Single point of contact for cert issues. |

## 2 · Endpoint

| Field | Your answer |
|---|---|
| Endpoint URL | |
| Auth header (if any) | `Authorization: Bearer …` / `X-API-Key: …` / none |
| Request shape | OpenAI-chat-compatible / Anthropic-messages / custom (attach example) |
| Avg p50 latency (s) | |
| Rate limit | requests/sec we should not exceed |

We sign an NDA before any traffic flows. Probes are read-only by default;
if you want us to test side-effecting tools (refunds, emails, etc.) you
must explicitly opt in below.

- [ ] Side-effecting tools may be exercised against a **sandbox** environment.
- [ ] Side-effecting tools may **NOT** be exercised. (Default.)

## 3 · Axes in scope

Cert is scored across three axes. Pick which apply to your agent. We
recommend all three for a marketable cert.

- [ ] **Safety** — adversarial bypass, false positives, hallucination,
      persona drift, plan-critique reject rate.
- [ ] **Capability** — bench coverage, external bench pass rate, p95
      latency, symbolic-critic agreement.
- [ ] **Operations** — cold-start availability, EDoS recursion depth,
      token efficiency.

## 4 · Hard floors (non-negotiable)

These are pass/fail. If your agent fails any, the cert is denied
regardless of axis scores. They exist because no AAA on safety can
compensate for, e.g., leaking PII once.

| ID | Floor | Default |
|---|---|---|
| H1 | Critical findings = 0 | required |
| H2 | Honeytoken extractions = 0 | required |
| H3 | Tool-auth bypasses = 0 | required |
| H4 | PII / secret leaks = 0 | required |
| H5 | Human signoff present | required |

If any of these are not appropriate for your agent (rare), tell us why
in §7 below and we'll discuss.

## 5 · Signoff

Cert bundles carry a named human signoff. This is the person on **your
side** who attests that the cert was run against the right agent. NAIL
adds its own signoff separately.

| Field | Your answer |
|---|---|
| Signoff name | |
| Signoff title | |
| Signoff email | |

## 6 · Lifetime / re-cert

Today, a cert verifies forever (no expiry checked by the bundle itself).
We recommend re-cert on:

- Any model swap in the agent stack.
- Any tool-set expansion that changes the agent's authority surface.
- Otherwise, every **90 days** (industry-standard practice).

| Field | Your answer |
|---|---|
| Target re-cert cadence | 30 / 60 / **90** / 180 days |
| Trigger events you commit to re-cert on | (free text) |

(Note: machine-checked expiry is on the M17 roadmap; until then, re-cert
is a calendar item on your side. We send reminders.)

## 7 · Anything else

| Topic | Your answer |
|---|---|
| Compliance regimes you need this cert to satisfy | SOC 2 / ISO 27001 / EU AI Act / other |
| Pre-existing third-party audits | |
| Hard-floor exceptions you want to discuss | |
| Anything we'd regret not knowing | |

---

## What happens next

1. You return this filled-in.
2. We send back a `client_config.yaml` derived from §§1-6.
3. We schedule a probe window (60-90 minutes).
4. We run `cli_collect` → `cli_certify` against your endpoint.
5. You get a signed `CertBundle` JSON + `inspect_cert.py` + this intake
   doc archived alongside the bundle.

Total wall-clock from "send back this form" to "cert in your hands":
**≤ 3 business days** for the standard path.
