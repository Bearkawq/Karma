# Recent Context

Rolling state summary of this project. Updated after each significant operation.

## Format

```yaml
last_updated: "2026-04-02T18:00:00Z"
session: "session-123"

summary: |
  Brief description of current project state.
  
  - What's been done recently
  - Current work in progress
  - Known issues or blockers

recent_changes:
  - timestamp: "2026-04-02T17:00:00Z"
    change: "Implemented user login"
    actor: "builder"
    
  - timestamp: "2026-04-02T16:00:00Z"
    change: "Added test suite"
    actor: "builder"

current_work:
  task: "Add password reset"
  status: "in_progress"
  actor: "builder"

blockers:
  - "Need API keys for email service"
  
next_steps:
  - "Complete password reset feature"
  - "Run full test suite"
  - "Update documentation"
```

## Usage

Load this file when starting work on this project to understand recent state.