# Neuravant denied-then-approved interoperability vector

Synthetic runtime-API example prepared 20 October 2026 for [Gary's request](https://github.com/OpenSecureAIAlliance/wg-safe/issues/13#issuecomment-6031295898). No OpenShell gateway, network service, real reviewer, production deployment or customer data was used for this vector. The unavailable 14 October local archive was not used; this is not a new live run.

## Contents and verification boundary

- `export.json`: nine hash-chained runtime records and the Ed25519 `export-head/v1` signed head (`head`), binding exactly this prefix.
- `public-key.hex`: dedicated synthetic Ed25519 public key, also in the signed head. Its identity is a fixture trust declaration, not independently established producer identity.
- `scenario.json`: synthetic call and declared policy context. One logical request, two explicitly distinct attempt IDs; identical request/decision digests do not identify an attempt.
- `check.py`: bounded policy checker `neuravant-synthetic-pair/v1`, using the newly authored standalone `integrity.py` reader. This is newly supplied fixture checking code, not the Apex policy checker mentioned in the discussion (not found in the retrieved default branches).
- `expected.json`: manually stated expected verdicts, separate from the inputs and checker. Checker never reads this file.
- `actual.json`: recorded checker output, including exact record hashes and source hashes.
- `test_vector.py`: compares actual verdicts to the independent expectations and rejects four corruptions.
- `integrity.py`: public-format integrity reader using Python JSON canonicalization, SHA-256 and the cryptography library’s Ed25519 verifier. No private implementation is included.
- `source-revision.json`, `SHA256SUMS`: upstream revision and exact file/checker revisions. The Git commit containing these files is the distribution revision; checker SHA-256 is independently pinned here.

The export was generated and verified locally with the existing Neuravant runtime evidence API from commit `dfd57b3661a1e36a50fb084cf6175de27ab20186` (runtime module Git blob `94adf4c11818d91c2619ded2fd4568a63944742d`). Local SQLite and no-anchor adapters isolated the fixture from production. The sequence mirrors the relevant hermetic middleware tests: signed decision/scope, rejected unapproved intent and denial, approval audit, second decision/scope, atomically consumed approved intent, grant and simulated outcome. No gateway was run. The public package includes only signed synthetic data, newly authored standalone checking code and documentation; no source from either private repository is copied here.

## Exact reproduction

Python 3.12 was used. From this directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
sha256sum -c SHA256SUMS
python check.py > reproduced.json
python test_vector.py
```

Expected final line: `PASS: independent expected verdicts; 4/4 negative controls rejected`. Both programs exit 0 on the published vector. `reproduced.json` should equal `actual.json` byte for byte. The checker authenticates integrity before deriving policy verdicts, and prints source hashes. Its revision is the SHA-256 pair in `source-revision.json` plus the distribution Git commit. The newly authored reader and the original private `verify_export_head` both accepted the published export locally. `test_vector.py` rejects altered payload, truncated records, wrong public key and a rewritten attempt identity.

The public reproduction verifies the fixed signed vector and recomputes its verdicts; it does not regenerate the original private runtime. During local construction, fresh dedicated HMAC and Ed25519 secrets existed only in process memory and were neither written nor printed. A second local generation with new keys reproduced the same expected verdicts. No private signing key is included; regenerating byte-identical signatures is neither possible nor necessary for verification.

## Independently stated policy expectations

| Attempt | Matching approval | Tenant/resource | Enforcement/report |
|---|---|---|---|
| `synthetic-denied-attempt` | `VIOLATION` | `NO_VIOLATION` | Denied; no intent or outcome |
| `synthetic-approved-attempt` | `NO_VIOLATION` | `NO_VIOLATION` | Intent and grant recorded; simulated `http:200` |

`VIOLATION` here describes the attempted call's failure to meet the declared approval requirement. Correct denial is successful enforcement, not evidence of unauthorized dispatch. Scope comparison is exact equality against declared synthetic tenant/resource operands. Approval checking binds approved argument digest, tool, tenant, request hash, policy version, approval audit, consumed action, consumption before expiry and one recorded consumption. Missing approval evidence outside the explicit denial case yields `INSUFFICIENT_EVIDENCE`. This is a bounded vector checker, not a general policy engine.

## Proposed mapping to SAFE PR #39

Compared against candidate head `b5c12f358fc281fc4beec1528a8db4d125edd879`. This table is a review aid, not a schema-conformant GALC envelope or a semantic-verifier result. Preserve source records by their `entry_hash` (listed in `actual.json`) and group by signed `action_id`, never by decision digest alone.

| Source | Candidate record position | Binding and limitation |
|---|---|---|
| `scenario.json` call | `proposal` | Declared synthetic operands; recomputed argument/request digests bind to each signed decision. No signed full GALC proposal |
| `decision` | proposal/decision correlation evidence | Same content digest on two different signed actions. `call_tool` describes captured call intent, not itself an authorization determination |
| `scope` | input to `governance_determination` | Signed declared allowed tenant/resource, exact equality only; no business ownership or authority lineage established |
| `denied` | deny determination / `enforcement_event` evidence | Retains first attempt; never relabelled as later approved attempt |
| approval audit + `grant` | approval determination evidence | Approved arguments, reviewer label, expiry, consumed action; synthetic reviewer label does not prove human identity or authority |
| `intent` | `enforcement_event` evidence | Single-use approval consumed atomically before simulated outcome; separate second attempt |
| `outcome` | `execution_result` evidence | Simulated status and response digest; no provider operation or externally observed effect |
| checker results | scoped comparison, possible `reconciliation_result` input | Approval/scope predicates only; not consequence reconciliation or GALC aggregate results |

No signed typed GALC links, independent observations, external anchors, custody receipts, revocation source or producer-independence evidence are supplied. These remain `NOT_EVALUATED`; absent evidence is not promoted to success. Wall-clock and expiry times are producer claims. An export-head signature authenticates the declared key and selected prefix, not historical completeness, inclusion in a transparency log, truth, genuine human authorization or external effect. Per-record HMAC signatures are retained for the producer; a public-key-only verifier cannot authenticate those HMAC fields separately (the Ed25519 head commits the payload chain).

## Validation record

- Relevant original hermetic middleware tests: 9 passed (TLS/listener/auth transport tests excluded because their service modules were not part of the local evidence-focused checkout).
- Original hermetic cases exercised unapproved denial, approved intent/grant/outcome, token replay refusal, decision attempt correlation and public-key verification with corruption controls.
- Published synthetic runtime-API vector: public-key verification and both policy expectations passed; four corruption controls rejected.
- Fresh generation with new ephemeral keys in a temporary copy: expected verdicts passed again.

Publication supports interoperability review only. It asserts neither SAFE adoption nor full runtime, GALC, authority, custody, anchoring or consequence conformance.
