# Handoffs

Protocol for transferring work between agents.

## Handoff Format

```yaml
handoff:
  from: builder
  to: checker
  project: nexus
  task: "implement-login"
  status: in_progress
  context:
    - "User model in models/user.py"
    - "Auth handler in handlers/auth.py"
    - "Tests need to pass"
  next_action: "Verify tests and review code quality"
```

## Flow

1. Agent completes their work
2. Creates handoff file in project .fleet/handoff_index.md
3. Notifies next agent via bridge
4. Next agent reads handoff and continues