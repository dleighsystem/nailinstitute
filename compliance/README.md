# nail-compliance

Machine-checkable AI / agentic **regulatory controls** — "an AVE, but for regulations".

Model regulation as structured `ComplianceControl` records, then check a
workflow/deployment profile against them for **gaps and violations**. Each control
points at the NAIL component that already provides evidence of conformity.

```python
from compliance import WorkflowProfile, Party, RiskTier, evaluate

report = evaluate(WorkflowProfile(
    name="refund-agent",
    party=Party.DEPLOYER,
    risk_tier=RiskTier.HIGH,
    capabilities={"human_oversight", "kill_switch", "operational_logging"},
))
report.summary()     # {"satisfied": .., "gap": .., "violation": ..}
report.gaps          # controls not yet satisfied
report.violations    # prohibited practices detected
```

## Coverage
- **P1 (this slice): EU AI Act** — Articles 5, 9–15, 26, 50, 55, 72, split by
  Provider/Deployer and risk tier, wired to NAIL evidence (flight recorder,
  certification passport, fleet kill-switch, detectors, shield provenance…).
- **Next: UK** (principles + UK-GDPR) and **US** (NIST AI RMF + state laws).

## ⚠️ Not legal advice
This is decision-support tooling. Control content must be validated by a qualified
person; controls carry an `effective_date` because the regulatory target moves.
