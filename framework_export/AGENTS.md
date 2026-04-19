# Karma Shared Framework

This repo uses ChatGPT as Planner with three active workers and a lightweight shared Armory. The Armory exists to help Builder, Checker, and Scout reuse good methods without dragging them through a large documentation system.

## Repo Rules

### Testing & Validation
- Show raw outputs for tests and runtime validation.
- Unified diffs only unless asked otherwise.
- Do not say "fixed" unless runtime validation passes.
- Always run `pytest -q` after patching.
- Always run `python3 tests/smoke_test.py` after patching.
- Preserve shell and file hardening.

### Code Changes
- Prefer surgical edits over rewrites.
- If uncertain, state what is still weak.
- For GoLearn changes, show `stop_reason`, artifact paths, and live outputs.

### Simulation Pattern
For coding changes, simulate:
```text
read code /tmp/sample.py
run /tmp/sample.py
debug /tmp/buggy.py
go on
summarize that
```

### File Transfer to Phone
- SSH port: `8022`.
- Use: `scp -P 8022 <file> user@192.168.68.59:~/storage/shared/Download/`
- Verify with: `ssh -p 8022 user@192.168.68.59 "ls -la ~/storage/shared/Download/<filename>"`

## Read Order
1. Read `AGENTS.md`.
2. Read `STATE.md`.
3. Read your assigned role file in `ROLES/`.
4. Read recent `HANDOFF.md` entries.
5. Check one Armory item only if it helps the current task.
6. Act only within the current assignment.

## Live Setup
- Planner: `ChatGPT`
- OpenCode: `Builder`
- Codex: `Checker`
- Goose/Qwen: `Scout`
- Support roles available later: `Helper`, `Dreamer`, `Validator`

## Operating Rules
- Planner sets the task, assigns roles, decides role switches, requests reports, and chooses the next step after reports or blockers.
- Builder makes code or file changes, keeps diffs small, stays on target, and logs changes clearly.
- Checker checks work for bugs, weak logic, regressions, and missing checks; points to exact problems; recommends focused fixes.
- Scout finds likely files, maps paths and dependencies, gathers context fast, and predicts next likely steps.
- Helper assists when work is stuck and helps recover momentum.
- Dreamer proposes strange but useful upgrade ideas and sends them to Validator.
- Validator checks Dreamer ideas for usefulness, fit, feasibility, and risk, then marks `accept`, `prototype`, `defer`, or `reject`.

## Armory Use
- Start with `ARMORY/LOADOUTS.md`.
- Open only the one Armory item that helps the current task.
- Use the Armory to avoid repeated work, not as a reading project.
- Keep names obvious and entries compact.

## Role Switching
- Roles may change later based on performance, task type, or blockers.
- Reassign when output quality or task fit clearly shifts.
- Activate `Helper` when work stalls or handoffs are too weak.
- Activate `Dreamer` and `Validator` only when the Planner opens upgrade work.

## Reporting
- `PHASE_REPORT.md` for completed chunks. Default owner: Builder after implementation-heavy work.
- `MIDPHASE_REPORT.md` for larger or partially blocked work. Default owner: Scout when search or pathfinding is the issue.
- `INCIDENT_REPORT.md` for repeated failures, regressions, or stuck work. Default owner: Checker.
- Each report starts with a Planner Summary block and stays concise.

## Handoffs
- Every handoff includes confidence, known facts, uncertainties, recommended next role, and useful Armory items.
- Low-confidence handoffs are not treated as settled work.
- `HANDOFF.md` stays append-only and short.

## Triage Mode
- Enter triage when repeated failures, regressions, or churn threaten momentum.
- Shrink scope to diagnosis, recovery, scouting, checking, and the smallest corrective patch.
- Pause Dreamer work unless the Planner explicitly opens it to solve the problem.

## Friction Rules
- Avoid rereading broad context that is not assignment-critical.
- Avoid unnecessary role swaps.
- Avoid oversized diffs when a narrower patch exists.
- Avoid Armory clutter. Trim or deprecate items that stop earning their keep.
