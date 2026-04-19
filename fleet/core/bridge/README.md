# Bridge - Inter-Process Communication

The bridge handles communication between fleet components and external systems.

## Purpose

- Route messages between agents
- Bridge events from projects to fleet systems
- Handle IPC for multi-process agent setups

## Usage

```python
from fleet.core.bridge import Bridge

bridge = Bridge()
bridge.send(target="worker-1", message={"task": "analyze", "payload": {...}})
```

## Events

The bridge emits events for:
- `task_received` - New task arrived
- `task_completed` - Worker finished a task
- `handoff` - Agent-to-agent handoff
- `error` - System errors