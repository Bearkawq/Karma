# Signals

Lightweight asynchronous signals between agents.

## Signal Types

- `ready` - Agent ready for work
- `blocked` - Waiting on dependency
- `help` - Needs assistance
- `done` - Task complete
- `error` - Encountered error

## Format

```json
{
  "signal": "blocked",
  "from": "builder-1",
  "to": "planner",
  "reason": "Need API credentials"
}
```