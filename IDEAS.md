# IDEAS.md — Innovation Queue

*Ranked Dreamer ideas queue with validator verdict fields.*

---

## Queue Status

| # | Idea | Dreamer | Score | Validator | Status |
|---|------|---------|-------|-----------|--------|
| 1 | | | | | pending |

---

## Template for New Ideas

```
## Idea: [short title]

**Dreamer**: [agent]
**Date**: YYYY-MM-DD
**Phase Context**: [current phase]

### Description
[What the idea is]

### Potential Value
[Why this could matter]

### Risks
[What could go wrong]

### Testability
[How to validate]

---
**Validator Verdict**:
- Novelty (1-5): _
- Usefulness (1-5): _
- Feasibility (1-5): _
- Risk (1-5): _
- Testability (1-5): _
- Repo Fit (1-5): _
- **Verdict**: [accept/prototype/defer/reject]
- **Notes**: [optional]
```

---

## Example Entry (Starter)

## Idea: Add auto-rollback for failed patches

**Dreamer**: OpenCode (standby)
**Date**: 2026-03-31
**Phase Context**: patch

### Description
When a patch fails tests, automatically revert to last known good state instead of leaving repo in broken state.

### Potential Value
Reduces time spent on recovery after failed patches. Makes experiments safer.

### Risks
Could hide real errors. Need clear "last known good" definition.

### Testability
Run 10 random failing patches, verify auto-rollback triggers correctly.

---
**Validator Verdict**:
- Novelty (1-5): 3
- Usefulness (1-5): 4
- Feasibility (1-5): 4
- Risk (1-5): 2
- Testability (1-5): 5
- Repo Fit (1-5): 4
- **Verdict**: prototype
- **Notes**: Good for surgery phase, defer until patch flow is stable

---

## Status Legend

| Status | Meaning |
|--------|---------|
| pending | Awaiting Validator review |
| validating | Currently being assessed |
| approved for prototype | Planner approved, ready to implement |
| deferred | Good but not now |
| rejected | Not suitable |
| integrated | Implemented and working |

---
*Append new ideas. Validator updates verdict. Planner decides action.*