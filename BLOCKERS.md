# BLOCKERS.md — Active Blockers

*Compact active blocker tracking. Update when blockers clear.*

---

## Active Blockers

**None.** System is operational. `python3 agent/agent_loop.py --ready` reports READY.

Last cleared: 2026-04-19 — storage/model-path integration complete, all agents verified model-first.

---

## Recently Cleared (reference)

| Cleared | Was | Cleared By |
|---------|-----|------------|
| 2026-04-19 | `embed_index.db` cold-start `FileNotFoundError` in `RetrieverAgent` | Added `os.path.exists()` guard (line 81) |
| 2026-04-19 | Test assertions mismatched service output terminology | Aligned `present_on_disk:`/`loaded(warm):` strings |
| 2026-04-16 | Agents not reaching real model generation | Wired `_try_model()` + `_get_embed_adapter()` in all 6 agents |
| 2026-04-16 | Slot assignments not persisted across restarts | `SlotManager` persistence via `data/slot_assignments.json` |
| 2026-04-16 | No operator surface for model management | `--models`, `--assign-role`, `--assign-slot`, `--bootstrap-models`, `--ready` added |

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
*Keep this file active. Remove cleared blockers after 30 days.*
