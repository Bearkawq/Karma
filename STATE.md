# STATE.md — Fast Control File

**Last Update**: 2026-03-31
**Mode**: normal

---

## Current Phase
[phase: patch]

## Current Task
[task description]
[success criteria]

## Target Files
- `path/to/file.py`

---

## Current Assignments

| Agent | Primary | Secondary | Standby |
|-------|---------|-----------|---------|
| **OpenCode** | Builder | Surgeon | Dreamer |
| **Codex** | Faultfinder | Validator | Scope Guard |
| **Goose/Qwen** | Scout | Stabilizer | Forecaster |

---

## Standby Roles
- OpenCode: Dreamer
- Codex: Scope Guard
- Goose/Qwen: Forecaster

---

## Mode Status
- **normal** / triage / innovation-open

---

## Reassignment Rules (Triggers)
1. Repeated failure on same issue (>2 attempts)
2. Blocked progress (>3 attempts)
3. Repeated regressions
4. Unclear root cause after diagnosis
5. Excessive churn (>3 role swaps in session)
6. Oversized diffs (>500 lines)
7. Low-confidence handoff (<0.6)
8. Idle agent available

---

## Current Blockers Summary
- [blocker 1]
- [blocker 2]

---

## Current Friction Summary
- [friction point]
- [friction point]

---

## Innovation Queue Summary
- Ideas in queue: 0
- Last validator action: none

---

## Recent Handovers
- [date] [agent] -> [agent]: [task] (confidence: X.X)

---

## Triage State
- Active failures: 0
- Root cause known: N/A
- Stabilizer engaged: no

---

*Update this file at phase changes, mode switches, and significant handoffs.*