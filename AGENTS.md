# AGENTS.md — Multi-Agent Framework Control Plane

## Purpose
This framework orchestrates local code work with one Planner (ChatGPT) and three worker agents using fluid roles, performance memory, and phase-aware operation.

## Read Order
1. AGENTS.md (this file)
2. STATE.md
3. Current phase file (PHASES/)
4. Your assigned role file (ROLES/)
5. Recent HANDOFF.md entries
6. Act only within your current assignment

## Core Roles

| Role | Primary Function |
|------|------------------|
| **Planner** | ChatGPT — assigns work, selects phase, decides escalation, gates innovation |
| **Builder** | Main implementer — produces useful code, controlled diffs |
| **Faultfinder** | Hunts errors, regressions, edge cases, failure evidence |
| **Scout** | Maps terrain, files, dependencies, hidden context |
| **Stabilizer** | Recovers stalled, churning, or failing work |
| **Surgeon** | Tiny, precise, low-blast-radius changes |
| **Scope Guard** | Prevents drift, overbuilding, file churn, inconsistency |
| **Forecaster** | Predicts next phases, files, blockers; prepares packets |
| **Dreamer** | Generates unusual upgrade ideas, architecture mutations |
| **Validator** | Screens Dreamer ideas for feasibility, value, risk |

## Mode States
- **normal** — standard operation
- **triage** — crisis mode, reduced scope, diagnosis priority
- **innovation-open** — Dreamer ideas allowed to flow

## Operating Rules

### Role Assignment
- One primary role per agent
- One secondary role (can step in)
- One standby role (idle behavior)
- Roles can fluidly switch based on performance

### Reassignment Triggers
- Repeated failure on same issue
- Blocked progress >X attempts
- Repeated regressions
- Unclear root cause after diagnosis attempts
- Excessive churn (too many swaps)
- Oversized diffs (>500 lines without reason)
- Low-confidence handoff (confidence <0.6)
- Idle agent available for reinforcement

### Role Borrowing
- Agent lends specific function without full takeover
- Examples:
  - Scout lends dependency tracing to Builder
  - Faultfinder lends diagnosis to Stabilizer
  - Validator lends feasibility check to Dreamer before formal review
- Document in HANDOFF.md with "BORROWED: [role] -> [function]"

### Triage Mode
Triggered when:
- 3+ repeated failures
- Root cause unknown after 2 attempts
- Critical regression introduced
- Work completely stalled

In triage:
- Reduce active scope
- Prioritize diagnosis
- Assign Stabilizer or Faultfinder
- Pause speculative upgrades
- Increase handoff precision (confidence >=0.8 required)
- Set STATE.md mode to "triage"

## Phase-Aware Behavior

| Phase | Preferred Active | Preferred Support | Change Aggressiveness |
|-------|-------------------|-------------------|----------------------|
| prototype | Builder, Scout | Forecaster, Validator | High — explore freely |
| patch | Surgeon, Scope Guard | Faultfinder | Low — minimal diff |
| surgery | Surgeon, Stabilizer | Faultfinder, Builder | Medium — precise cuts |
| audit | Faultfinder, Scope Guard | Scout | None — observe only |
| refactor | Builder, Scope Guard | Faultfinder, Stabilizer | Medium — controlled |
| upgrade | Builder, Dreamer | Validator, Scope Guard | High but validated |

See PHASES/ for full phase definitions.

## Dreamer -> Validator Flow

```
Dreamer -> IDEALS.md (queued) -> Validator reviews -> 
  [accept/prototype/defer/reject] -> Planner decides -> Builder/Surgeon implements
```

Dreamer should generate when:
- System idle
- Milestone reached
- Strategy stagnating
- Planner requests innovation
- Technical debt rising

Validator scores on:
- Novelty (1-5)
- Usefulness (1-5)
- Feasibility (1-5)
- Risk (1-5)
- Testability (1-5)
- Repo fit (1-5)

## Idle Behavior
If not actively assigned:
- Enter Forecaster mode
- Predict next phase, files, blockers
- Prepare future-phase packets
- Collect useful context
- Prepare rescue notes
- Do NOT interfere with active work unless triggered

## Reporting Rules
- One agent owns report per phase
- Include Planner Summary at top (one-line status)
- Use PHASE_REPORT.md for normal completion
- Use MIDPHASE_REPORT.md for large/blocked/reassigned tasks
- Use INCIDENT_REPORT.md for failures/regressions/stalls

## Friction Tracking
Track in STATE.md under "friction_summary":
- Rereading too much context
- Repeated failed attempts
- Excessive role swaps
- Oversized diffs
- Unclear ownership

## Handoff Expectations
Every handoff includes:
- Confidence level (0.0-1.0)
- What is known
- What is uncertain
- Recommended next role

## Performance Memory
See SCORES.md for role fitness tracking by agent.
Update after each significant work chunk.

## Innovation Queue
See IDEAS.md for ranked Dreamer ideas with statuses:
- pending
- validating
- approved for prototype
- deferred
- rejected
- integrated

## Quick Reference

| Trigger | Response |
|---------|----------|
| Task failing repeatedly | Enter triage, assign Stabilizer |
| New idea from Dreamer | Queue in IDEAS.md, trigger Validator |
| Phase changing | Update STATE.md, shift roles |
| Agent idle | Forecaster mode, prepare packets |
| Blocked work | Role borrowing, or reassign |
| Regression detected | Assign Faultfinder, incident report |

---
*Framework version: 1.0 — For Karma v3.9.0*