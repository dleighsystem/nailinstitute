# NAIL Cert Gate — drop-in CI gate

This directory holds **reusable workflow templates**. Copy or `uses:` them
from your downstream repo to wire NAIL certification into your release
pipeline.

## `nail-cert-gate.yml`

Refuses deployment unless the agent ships with a fresh, signed NAIL
certificate at the requested tier or higher.

**Setup (one-time, per org):**

1. Generate the issuer keypair on the cert authority machine:
   ```bash
   nail-arsenal keygen
   # → prints kid + public_key_hex
   ```
2. Copy the `public_key_hex` value into a GitHub org secret named
   `NAIL_ARSENAL_PUBKEY_HEX`. The private key never leaves your authority
   machine.

**Per-release flow:**

1. Run `scripts/run_local_certification.py --target <model>` to produce
   `cert_<run-id>.json`.
2. Sign it: `python scripts/nail_deploy.py sign --cert cert_<run-id>.json`.
3. Commit (or upload as an artifact) and reference its path in the
   workflow's `cert_path:` input.
4. The gate validates schema, composite ≥ tier minimum, age ≤ 30 d, scope
   match, model match, and signature. Any failure exits with code 2 and
   blocks the deploy job.

**Local equivalent (no GitHub):**

```bash
python scripts/nail_deploy.py push \
    --agent my-agent \
    --cert  ./cert.json \
    --tier  AA \
    --scope general \
    --model mistral:7b-instruct \
    --max-age-days 30 \
    --require-signature
echo "exit=$?"   # 0 → deploy, 2 → blocked
```
