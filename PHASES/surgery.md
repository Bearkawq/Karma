# PHASES/surgery.md

## Phase: Surgery

### Purpose
Precise, targeted changes that touch multiple files but stay controlled.

### Preferred Active Roles
- Surgeon (primary)
- Stabilizer (support)

### Preferred Support Roles
- Faultfinder (regression check)
- Builder (if complexity warrants)

### Acceptable Change Size
**Medium** — Multi-file but precise.

### Common Risks
- Propagation errors
- Missing related touchpoints
- Under-testing across files

### Escalation Rules
- If scope expands beyond 3-4 files, escalate to refactor
- If unstable, enter triage mode
- If fix is risky, consult Scope Guard

### Success Shape
- Multi-file fix works
- All related tests pass
- Change is contained

---
*Use for fixes that span files but aren't full refactors.*