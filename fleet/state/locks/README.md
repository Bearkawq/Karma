# Locks

Distributed locks for coordinating workers.

## Purpose

- Prevent concurrent modifications to shared resources
- Ensure only one worker handles a task
- Coordinate access to external services

## Format

```yaml
locks/
  task-123.lock:
    holder: worker-1
    acquired: "2026-04-02T18:30:00Z"
    expires: "2026-04-02T18:45:00Z"
```