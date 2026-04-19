# PHASES/refactor.md

## Phase: Refactor

### Purpose
Restructure code while preserving behavior. Controlled large-scale changes.

### Preferred Active Roles
- Builder (primary)
- Scope Guard (support)

### Preferred Support Roles
- Faultfinder (regression prevention)
- Stabilizer (if work stalls)

### Acceptable Change Size
**Medium** — Significant but controlled.

### Common Risks
- Breaking functionality
- Scope creep
- Over-refactoring

### Escalation Rules
- If changes get too large, break into multiple phases
- If behavior changes, escalate to Planner
- If stalling, call Stabilizer

### Success Shape
- Code restructured
- All tests pass
- Behavior preserved

---
*Use when improving code structure without changing behavior.*