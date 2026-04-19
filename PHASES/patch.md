# PHASES/patch.md

## Phase: Patch

### Purpose
Fix specific issues with minimal diffs and controlled changes.

### Preferred Active Roles
- Surgeon (primary)
- Scope Guard (support)

### Preferred Support Roles
- Faultfinder (verify fix)
- Builder (if surgery too large)

### Acceptable Change Size
**Low** — Minimal, precise fixes.

### Common Risks
- Breaking adjacent functionality
- Under-testing
- Fixing symptoms not root cause

### Escalation Rules
- If fix needs multiple files, escalate to surgery
- If root cause unclear, call Faultfinder
- If stalling, call Stabilizer

### Success Shape
- Fix works
- No regressions
- Diff under 100 lines typical

---
*Use when fixing known bugs or adding small features.*