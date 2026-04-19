# PATTERNS.md — Recurring Failure & Friction Patterns

*Compact operational pattern tracking. Update when new patterns emerge.*

---

## Active Patterns

| # | Pattern | Frequency | Last Seen | Impact |
|---|---------|-----------|-----------|--------|
| 1 | | | | |

---

## Pattern Template

```
### Pattern: [name]

**Frequency**: daily/weekly/sometimes
**Last Seen**: YYYY-MM-DD
**Impact**: high/medium/low

**Symptom**: [what it looks like]
**Root Cause**: [what causes it]
**Affected Roles**: [role]
**Suggested Fix**: [if known]
```

---

## Starter Patterns

### Pattern: Version drift between karma_version.py and config.json

**Frequency**: sometimes
**Last Seen**: 2026-03-25
**Impact**: medium

**Symptom**: Test failures on version checks, confusion about actual version.

**Root Cause**: Manual updates not synced across two files.

**Affected Roles**: Builder, Scope Guard

**Suggested Fix**: Use karma_version.py as single source, auto-sync config.json.

---

### Pattern: Parse evidence rewrites applied before grammar matching

**Frequency**: once (fixed in v3.9)
**Last Seen**: 2026-03-15
**Impact**: high

**Symptom**: "list files" returned wrong result, grammar matched input was overwritten.

**Root Cause**: Order of operations in agent_loop.py.

**Affected Roles**: Builder, Faultfinder

**Suggested Fix**: Apply rewrite only when grammar confidence < 0.7.

---
*Keep this file sharp. Add patterns, not essays.*