# Workers State

Status of all workers in the fleet.

## Track

- Current task
- Role/type
- Capacity available
- Last heartbeat
- Skills/capabilities

## File Format

```yaml
workers:
  worker-1:
    role: builder
    status: busy
    current_task: implement-login
    capacity: 0
```