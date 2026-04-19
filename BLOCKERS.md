# BLOCKERS.md — Active Blockers

*Compact active blocker tracking. Update when blockers clear.*

---

## Active Blockers

| # | Blocker | Agent | Since | Severity | Status |
|---|---------|-------|-------|----------|--------|
| 1 | | | | | |

---

## Template
```
## Blocker: [brief title]

**Agent**: [who is blocked]
**Since**: YYYY-MM-DD
**Severity**: critical/high/medium/low
**Phase**: [phase]

**Description**: [what is blocking]

**Workaround**: [if any]

**Unblock Steps**:
1. [step 1]
2. [step 2]

**Cleared**: [date or N/A]
```

---

## Starter Entry

## Blocker: Flask not installed

**Agent**: Builder
**Since**: 2026-03-25
**Severity**: high
**Phase**: patch

**Description**: Web UI crashes on import — Flask module not present in environment.

**Workaround**: Install Flask before running ui/web.py

**Unblock Steps**:
1. pip3 install flask
2. Verify ui/web.py imports successfully

**Cleared**: 2026-03-25

---
*Keep this file active. Remove cleared blockers.*