# Handling Handoffs

## When to Handoff

- After completing your part of a task
- When you need another role's expertise
- When passing to next phase (e.g., build → check)

## Handoff Process

1. **Document work done**
   - What was completed
   - What files were modified
   - Any relevant context

2. **Create handoff entry**
   - Add to `.fleet/handoff_index.md`
   - Include context for next agent

3. **Notify next agent**
   - Use `fleet/comms/handoffs/` protocol
   - Or direct notification

4. **Next agent reads handoff**
   - Load `.fleet/handoff_index.md`
   - Review context
   - Continue work

## Example Handoff (builder → checker)

```yaml
from_role: builder
to_role: checker
task: "implement-login"
summary: "Login feature complete"
files_changed:
  - "models/user.py"
  - "handlers/auth.py"
next_action: "Review code and verify tests pass"
```