# STATE.md — Fast Control File

**Last Update**: 2026-04-19
**Mode**: normal

---

## Current Phase
[phase: operational — no active blocking work]

## System Status: READY TO ROLL

Karma is operational on this machine. All major technical seams are closed.

| Capability | Status |
|-----------|--------|
| Storage / `/mnt/fastnvme` | Mounted and healthy; all runtime paths use `/mnt/fastnvme` |
| Ollama | Healthy at localhost:11434 |
| Model pool | `qwen3:4b`, `granite3.3:2b`, `nomic-embed-text`, `gemma3:4b`, `phi4-mini` installed |
| Role assignments | All 6 roles assigned via `data/slot_assignments.json`; `--ready` reports READY |
| Model-first agents | All 5 generation agents (planner/executor/critic/summarizer/navigator) verified model-first |
| Retriever embedding | `nomic-embed-text` wired; 768-dim cosine-similarity search; SQLite persistent cache |
| Operator surface | `--models`, `--assign-role`, `--assign-slot`, `--bootstrap-models`, `--ready` all working |
| Test suite | 330+ tests pass |
| Warm vs idle | Normal Ollama residency behavior — not a failure state |

## Current Task
No blocking task. System is in maintenance / optional-polish phase.

## Target Files
N/A

---

## Current Assignments

| Agent | Primary | Secondary | Standby |
|-------|---------|-----------|---------|
| **OpenCode** | Builder | Surgeon | Dreamer |
| **Codex** | Faultfinder | Validator | Scope Guard |
| **Goose/Qwen** | Scout | Stabilizer | Forecaster |

---

## Current Blockers Summary
- None. `--ready` reports READY.

---

## Current Friction Summary
- `qwen3:4b` generates verbose thinking-style text inline even with `think:false`; extractors compensate
- `granite3.3:2b` sometimes truncates output mid-sentence
- `_validate_options` uses substring match — aliased paths may occasionally slip through

---

## Innovation Queue Summary
- Ideas in queue: 0
- Last validator action: none

---

## Recent Handovers
- 2026-04-19 Claude → next: operator/model-path hardening passes complete (confidence: 0.97)

---

## Triage State
- Active failures: 0
- Root cause known: N/A
- Stabilizer engaged: no

---

*Update this file at phase changes, mode switches, and significant handoffs.*
