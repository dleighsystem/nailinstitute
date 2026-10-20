# Prepared reply for SAFE issue #13

Not posted: the GitHub connection returned 403 Resource not accessible by integration. Copy the text below into issue #13 after verifying the destination.

@Gary-Gayle Following your [7 October request](https://github.com/OpenSecureAIAlliance/wg-safe/issues/13#issuecomment-6031295898), here is a focused **synthetic denied-then-approved evidence bundle** at immutable revision `b71a001572351d70b499815686854dc22798f00e`:

**[Bundle and reproduction instructions](https://github.com/dleighsystem/nailinstitute/tree/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair)** · [review PR](https://github.com/dleighsystem/nailinstitute/pull/30)

- [Signed export](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/export.json): nine runtime records plus the Ed25519 `export-head/v1` head in `head`.
- [Public key](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/public-key.hex), [checker revision/source hashes](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/source-revision.json), and [checksums](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/SHA256SUMS).
- [Scenario inputs](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/scenario.json), [separately stated expected outputs](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/expected.json), and [recorded actual outputs with record hashes](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/actual.json).
- [Standalone checker](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/check.py) and [integrity reader](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/integrity.py); [README](https://github.com/dleighsystem/nailinstitute/blob/b71a001572351d70b499815686854dc22798f00e/interoperability/neuravant-safe-pair/README.md) includes a bounded mapping to #39 at candidate head `b5c12f358fc281fc4beec1528a8db4d125edd879`.

Exact reproduction from a fresh checkout:

```sh
git clone https://github.com/dleighsystem/nailinstitute.git
cd nailinstitute
git checkout b71a001572351d70b499815686854dc22798f00e
cd interoperability/neuravant-safe-pair
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
sha256sum -c SHA256SUMS
python check.py > reproduced.json
cmp actual.json reproduced.json
python test_vector.py
```

Expected final line: `PASS: independent expected verdicts; 4/4 negative controls rejected`. Python 3.12 was used. The checker does not read the expected-output file.

The attempts have distinct signed action IDs but equal request/decision digests. Expected approval-policy results are `VIOLATION` for the denied attempt and `NO_VIOLATION` for the approved attempt; both have `NO_VIOLATION` for declared tenant/resource scope. Here the first violation describes the attempted call's missing authorization; the denial is successful enforcement, not unauthorized dispatch.

The existing runtime evidence API generated and verified the export locally using fresh dedicated test signing keys. Its original public-key verifier and the supplied standalone reader both accepted this export. Relevant original hermetic middleware tests passed (9); all four public corruption controls were rejected. Fresh-key local regeneration also reproduced the expected verdicts. All 12 published files were fetched by commit and matched.

**Limits:** the 14 October local archive was unavailable, so this is a synthetic runtime-API fixture, not a new live OpenShell run. The policy checker described in our earlier comment was not found in the retrieved default branches; this contribution therefore identifies its newly supplied bounded checker explicitly rather than claiming to publish that checker. No private implementation, proprietary gateway, production credentials, private signing keys or customer data is included.

The #39 mapping remains a review aid: this does not run GALC's harness or establish GALC conformance. Cryptographic integrity and the two policy predicates remain separate from authority identity, external effects, observation/reconciliation, custody, anchoring and historical completeness, which are not established. In particular, identical decision content never merges the denied attempt into the later approved attempt.

Would welcome your review of the lifecycle bindings and the explicit gaps.
