# Dispatcher - Task Distribution

The dispatcher allocates work to available workers based on role, capacity, and task requirements.

## Purpose

- Match tasks to suitable workers
- Balance load across worker pool
- Handle task queuing and prioritization

## Task Flow

1. Task received → 2. Route to dispatcher → 3. Select worker → 4. Assign task → 5. Monitor completion

## Configuration

```yaml
dispatcher:
  max_workers: 5
  default_role: builder
  timeout: 300
  retry_attempts: 3