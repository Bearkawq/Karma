# Karma Bridge - Local Worker Orchestration

A local machine-readable bridge for planner/worker communication through files only. No cloud services. No external APIs.

## Folder Structure

```
bridge/
├── inbox/          # Incoming tasks (future use)
├── outbox/         # Completed handoffs
├── workers/        # Worker state files (role.json)
│   ├── planner.json
│   ├── scout.json
│   ├── coder.json
│   └── tester.json
├── planner/        # Planner-facing summaries
│   ├── summary.json
│   └── summary.md
├── events/         # Event log (JSONL)
│   └── events.jsonl
├── locks/          # File locks (future use)
└── archive/        # Archived handoffs
```

## Worker State Schema

Each worker has a `workers/<role>.json` file:

```json
{
  "role": "scout",
  "status": "active",        // idle, active, blocked, completed, failed
  "current_task": "Find test files",
  "current_files": ["tests/test_gui.py"],
  "last_update": "2026-03-31T12:00:00Z",
  "progress_percent": 50,
  "blockers": [],
  "needs_decision": false,
  "suggested_next_action": "Read file X",
  "output_files": [],
  "handoff_target": "",
  "error": ""
}
```

## Worker Lifecycle

1. **Claim Task**: Worker claims a task
   ```python
   bridge.claim_task("scout", "Find files", ["tests/test_gui.py"])
   ```

2. **Update Progress**: Worker updates progress
   ```python
   bridge.update_worker_state("scout", progress_percent=50)
   ```

3. **Handle Blockers**: Worker marks itself blocked
   ```python
   bridge.mark_blocked("scout", "Cannot find file", "Create or skip?")
   ```

4. **Complete**: Worker finishes and declares next steps
   ```python
   bridge.complete_task("scout", artifacts=["file.txt"], next_worker="coder", next_action="Fix it")
   ```

## How Planner Reads Bridge

1. Read `bridge/planner/summary.json` for full state
2. Or use CLI: `python -m bridge.status summary`

```bash
# Show all worker statuses
python -m bridge.status status

# Show planner summary
python -m bridge.status summary

# Initialize bridge
python -m bridge.status init
```

## Planner Summary Contents

The `summary.json` always contains:

- `active_workers` - Workers currently working
- `blocked_workers` - Workers needing help
- `decision_requests` - Workers needing a decision
- `stale_workers` - Workers not updated in 10+ minutes
- `open_blockers` - All blockers collected
- `recent_changes` - Last 10 events
- `highest_priority_reads` - Files to read first

## Handoffs

To handoff from one worker to another:

```python
bridge.publish_handoff(
    from_role="scout",
    to_role="coder",
    task="Fix the bug",
    context={"file": "ui/web.py", "line": 145}
)
```

Creates `outbox/scout_to_coder_<id>.json` and updates both worker states.

## Events

All worker actions log events to `events/events.jsonl`:

```json
{"id": "abc123", "timestamp": "...", "type": "worker_state_update", "worker": "scout", "data": {...}}
```

## Configuration

Set bridge path via environment:
```bash
export KARMA_BRIDGE_PATH=/path/to/bridge
```

## Integration with Existing Systems

The bridge is independent. To use it:

1. Import: `import bridge`
2. Initialize: `bridge.init_bridge()`
3. Use functions: `bridge.claim_task()`, `bridge.update_worker_state()`, etc.
4. Read summary: `bridge.get_planner_summary()`

## API

| Function | Purpose |
|----------|---------|
| `init_bridge()` | Create bridge directories |
| `update_worker_state(...)` | Update worker status |
| `get_worker_state(role)` | Read worker status |
| `claim_task(role, task, files)` | Worker claims task |
| `complete_task(role, artifacts, next_worker)` | Worker completes task |
| `mark_blocked(role, blocker, decision)` | Worker gets blocked |
| `publish_handoff(from, to, task, context)` | Transfer work |
| `append_event(type, worker, data)` | Log event |
| `get_events(limit)` | Read recent events |
| `generate_planner_summary()` | Create summary |
| `get_planner_summary()` | Read latest summary |
| `get_worker_statuses()` | Quick status check |

## Example: Scout → Coder → Tester Flow

```python
# Scout finds files
bridge.claim_task("scout", "Find failing test file")
bridge.update_worker_state("scout", progress_percent=50, current_files=["tests/test_gui.py"])

# Scout hands off to coder
bridge.publish_handoff("scout", "coder", "Fix test at line 145")

# Coder gets the task, fixes it
state = bridge.get_worker_state("coder")
bridge.update_worker_state("coder", progress_percent=100)

# Coder hands off to tester
bridge.publish_handoff("coder", "tester", "Verify fix")

# Tester verifies and completes
bridge.complete_task("tester", artifacts=["test_results.txt"], next_worker="", next_action="")
```

Then planner reads `bridge/planner/summary.json` to see the completed flow.
