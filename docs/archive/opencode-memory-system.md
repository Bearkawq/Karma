# OpenCode Durable Memory System

## Memory Layout
This memory system provides persistent context for OpenCode sessions that survive:
- Browser disconnects
- SSH drops
- Service restarts
- Machine reboots
- Interrupted tasks

## Directory Structure
```
/opt/ai/mem/
├── state.md           # Current system state and environment
├── tasks.md           # Unfinished task ledger
├── log.md             # Append-only operational log
├── episodic.jsonl     # Session history (JSON Lines)
├── facts.json         # Durable fact store
├── failure_memory.json # Known failures and workarounds
├── workflows.json     # Workflow patterns
└── last_session.json  # Recovery pointer (read on startup)
```

## File Purposes

### state.md
- System configuration snapshot
- Active services and their status
- Environment variables
- Network state
- Updated at startup and after major changes

### tasks.md
- Unfinished task ledger
- Each task has: ID, description, priority, status, created timestamp
- Use `## ACTIVE` and `## DONE` sections
- Never lose track of work in progress

### log.md
- Append-only operational log
- Format: `[YYYY-MM-DD HH:MM:SS] ACTION: details`
- Records all significant decisions and actions
- Never delete - only append

### episodic.jsonl
- Session history in JSON Lines format
- Each line: `{"timestamp": "...", "session_id": "...", "event": "...", "data": {...}}`
- Preserves conversation context

### facts.json
- Durable fact store
- Format: `{"facts": [{"id": "...", "content": "...", "confidence": 0.0-1.0, "source": "...", "timestamp": "..."}]}`
- Searchable knowledge base

### failure_memory.json
- Known failures and workarounds
- Format: `{"failures": [{"symptom": "...", "cause": "...", "workaround": "...", "timestamp": "..."}]}`

### workflows.json
- Reusable workflow patterns
- Format: `{"workflows": [{"name": "...", "steps": [...], "last_used": "..."}]}`

### last_session.json
- Recovery pointer for startup
- Format: `{"last_session_id": "...", "last_task_id": "...", "resume_point": "...", "timestamp": "..."}`
- Read by startup scripts to restore context

## Safe Write Rules
1. For JSON files - write to temp file, then atomic rename
2. For markdown files - append or use atomic write
3. Always update last_session.json after completing work
4. Checkpoint every 5-10 minutes during active use

## Resume Procedure
1. On startup, read last_session.json
2. Load active task from tasks.md
3. Restore context from state.md
4. Read recent log.md entries
5. Continue where left off

## Usage in OpenCode Sessions
- Start by reading /opt/ai/mem/last_session.json
- Check /opt/ai/mem/tasks.md for ACTIVE work
- Restore context from state.md
- Log all decisions to log.md
- Checkpoint before ending sessions