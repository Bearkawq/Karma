# Planner State

Active plans and objectives being worked on.

## Structure

```
planner/
  active.yaml      - Current plan being executed
  queue.yaml       - Upcoming tasks
  completed.yaml  - Recently completed tasks
  blocked.yaml    - Tasks blocked on dependencies
```

## Usage

Planner writes state here, workers read to know what to do.