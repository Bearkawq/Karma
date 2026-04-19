# Kits Index

| Name | Use | Who Uses It | Status |
| --- | --- | --- | --- |
| Bugfix Kit | small targeted code change with quick validation | Builder | active |
| Regression Kit | inspect for breakage, weak checks, and edge cases | Checker | active |
| Repo Discovery Kit | map files, paths, and likely dependencies | Scout | active |
| Recovery Kit | reset a stalled task into manageable steps | Helper | active |

## Bugfix Kit
- define the exact symptom
- confirm the smallest change surface
- patch only the needed files
- run the required checks
- write a short handoff or phase report

## Regression Kit
- restate the claimed change
- look for broken assumptions, missing checks, and adjacent regressions
- point to exact files or behaviors
- recommend the smallest next fix

## Repo Discovery Kit
- identify likely files first
- trace direct dependencies only
- collect enough context for Builder or Checker
- hand off with confidence and next likely step

## Recovery Kit
- restate the blocker in one line
- cut the work into the smallest next action
- choose one recovery step or playbook
- hand back to the best-fit role
