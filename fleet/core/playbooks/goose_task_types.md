# Goose Task Types

Use these mission classes to keep Goose bounded and useful.

## 1. Project Reconnaissance
Use when:
- a project is new or poorly understood

Deliverables:
- entrypoints
- configs
- scripts
- test roots
- docs roots
- subsystem map

## 2. File Organization Survey
Use when:
- the tree feels messy or ownership is unclear

Deliverables:
- clutter zones
- file sprawl notes
- probable duplicates
- stale vs active classification

## 3. Cleanup Classification
Use when:
- there is pressure to tidy but not enough evidence to delete

Deliverables:
- confirmed safe cleanup candidates
- quarantined uncertain items
- no speculative removals

## 4. Dependency / Environment Survey
Use when:
- setup, runtime, or toolchain behavior is unclear

Deliverables:
- dependency entrypoints
- config files
- version surfaces
- probable mismatch zones

## 5. Task Extraction
Use when:
- TODO/FIXME comments or scattered work candidates need consolidation

Deliverables:
- extracted task list
- grouped by subsystem
- ranked by likely impact

## 6. Subsystem Mapping
Use when:
- a builder needs targeted context on one area

Deliverables:
- subsystem summary
- main files
- inputs and outputs
- known tests
- sharp risks

## 7. Documentation Gap Analysis
Use when:
- docs are stale, sparse, or misleading

Deliverables:
- missing docs
- misleading docs
- high-friction onboarding gaps

## 8. Failure Pattern Analysis
Use when:
- similar failures keep appearing

Deliverables:
- recurring failure clusters
- likely shared files
- risky surfaces
- unresolved unknowns

## 9. Test Surface Mapping
Use when:
- validation strategy is unclear

Deliverables:
- tests by subsystem
- gaps
- weak coverage zones
- recommended validation commands

## Mission close rules
Every mission ends with:
- one final scout report using the scout prompt contract
- optional handoff packets for builder-ready tasks
- explicit completion status
