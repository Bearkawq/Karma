# Events

Event log of all fleet operations.

## Event Types

- `task_created` - New task entered system
- `task_assigned` - Task given to worker
- `task_started` - Worker began task
- `task_completed` - Task finished successfully
- `task_failed` - Task failed
- `handoff` - Agent handoff occurred
- `context_loaded` - Project context loaded
- `policy_violation` - Policy check failed

## Format

```json
{
  "timestamp": "2026-04-02T18:30:00Z",
  "type": "task_completed",
  "task_id": "task-123",
  "worker": "worker-1",
  "project": "nexus"
}
```