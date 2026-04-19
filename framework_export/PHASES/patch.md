# Patch

- Phase purpose: correct a defined problem with minimum blast radius.
- Preferred active roles: `Builder` or `Surgeon`, plus `Faultfinder`.
- Preferred support roles: `Scope Guard`, `Stabilizer`.
- Acceptable change size: small.
- Common risks: masking root cause, regression in neighboring code, unnecessary file spread.
- Escalation rules: escalate when the same issue repeats, diagnosis is weak, or the diff stops being small.
- Success shape: the issue is resolved, verified, and tightly contained.
