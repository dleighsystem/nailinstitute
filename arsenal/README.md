# NAIL Arsenal

> Capability provisioning. The third package of the NAIL **BEFORE** stack
> (after `diagnostic/` cert and `shield/` input neutralisation).

## Why

Runtime-gate vendors (e.g. Execlave) operate with **negative policies** —
the universe of forbidden actions is enumerated, everything else is allowed.
This is unmaintainable: a clever attacker only needs one allowed-by-default
action that composes with another into something forbidden.

Arsenal inverts the model: **agents start with zero capabilities**. Tools
must be issued per-session as short-lived, ed25519-signed, attested tokens.
A tool call without a valid token is rejected at the SDK layer — it never
reaches the network.

```
┌─────────────────────────────┐         ┌──────────────────────┐
│ Session Manifest             │ ──────▶ │ nail-arsenal mint    │
│  agent: customer-support-v2  │         │  (ed25519 sign)      │
│  user:  u-123 (OIDC)         │         └──────────┬───────────┘
│  scope: refund_processing    │                    │
│  tools_requested:            │            ┌───────▼────────┐
│   - tickets.read             │            │ Capability     │
│   - refunds.issue            │            │ Tokens         │
└─────────────────────────────┘            │  t1: tickets.read │
                                            │  t2: refunds.issue│
                                            │       limit £200  │
                                            │       hold ≥ £50  │
                                            │       exp 30 min  │
                                            └───────┬────────┘
                                                    │
                                            ┌───────▼────────┐
                                            │ @requires_token│
                                            │ enforcer shim   │
                                            │  (DENY default) │
                                            └────────────────┘
```

## Quick start

```bash
# 1. One-time: generate the issuer keypair (defaults to ~/.nail/arsenal/)
nail-arsenal keygen

# 2. Mint a session of capability tokens
nail-arsenal mint \
    --agent customer-support-v2 \
    --session sess-abc123 \
    --tool 'tickets.read:calls=50' \
    --tool 'refunds.issue:calls=5,cumulative_gbp=200,hold_above_gbp=50' \
    --ttl 1800

# 3. Inspect any token
echo "$TOKEN" | nail-arsenal inspect

# 4. Verify any token
echo "$TOKEN" | nail-arsenal verify
```

```python
# In your agent's tool layer:
from arsenal import requires_token, set_session_tokens

set_session_tokens([token1, token2])      # at session start

@requires_token("refunds.issue")
def issue_refund(amount_gbp: float, customer_id: str) -> str:
    # body only runs if a valid, unexpired, non-exhausted token for
    # 'refunds.issue' is in the current contextvar AND the per-call
    # limits (cumulative_gbp, calls) and conditions (hold_above_gbp)
    # are satisfied.
    ...
```

## Token format

Compact 3-part dot-separated string: `header.payload.signature`

* `header`     — base64url(`{"alg":"ed25519","typ":"NAIL-CAP","kid":"<key-id>"}`)
* `payload`    — base64url(json claims)
* `signature`  — base64url(ed25519(`header + "." + payload`))

Claims include: `tool`, `agent`, `session`, `iat`, `exp`, `limits`,
`conditions`, `ave_chain_id`, `nonce`.

## Status

v0.1.0 — keys, tokens, sessions, enforcer, CLI. 100% local, no external
dependencies beyond `cryptography`.
