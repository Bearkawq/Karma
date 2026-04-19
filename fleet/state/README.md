# State - Live Operational State

Fleet maintains operational state for coordination. This state is ephemeral and regenerated on restart.

## Directories

- **planner/** - Planner's current plans and objectives
- **workers/** - Worker status, active tasks, capacity
- **sessions/** - Active session data
- **events/** - Event log of fleet operations
- **inbox/** - Incoming tasks/messages
- **outbox/** - Outgoing messages to external systems
- **locks/** - Distributed locks for coordination
- **summaries/** - Periodic state summaries