"""Karma Bridge - Local worker orchestration via filesystem.

Provides a machine-readable bridge for planner/worker communication
through files only. No cloud services. No external APIs.

Phase 3 enhancements:
- Auto-refresh planner summary on state changes
- Configurable stale threshold
- Changed-file tracking
- Improved summary ordering
- Simple assignment mechanism
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BRIDGE_DIR = "bridge"

# True if the most recent append_event write failed.  Queryable by callers and
# boot-doctor checks without needing to inspect the log file itself.
_last_append_failed: bool = False

# Default paths relative to repo root
DEFAULT_BRIDGE_PATH = Path(__file__).resolve().parent.parent / BRIDGE_DIR

# Configuration
STALE_THRESHOLD_SECONDS = int(os.environ.get("KARMA_STALE_THRESHOLD", 600))  # 10 min default

WORKER_FIELDS = {
    "role": str,
    "status": str,  # idle, active, blocked, completed, failed
    "current_task": str,
    "current_files": list,
    "last_update": str,
    "progress_percent": int,
    "blockers": list,
    "needs_decision": bool,
    "suggested_next_action": str,
    "output_files": list,
    "handoff_target": str,
    "error": str,
    "recent_events": list,
    "last_error": str,
    "changed_files": list,
}

def _get_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def _atomic_write(filepath: Path, content: str) -> None:
    """Write content atomically using temp file + rename."""
    tmp = filepath.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.replace(filepath)

def get_bridge_path() -> Path:
    """Get bridge directory path."""
    env_path = os.environ.get("KARMA_BRIDGE_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_BRIDGE_PATH

def get_stale_threshold() -> int:
    """Get configurable stale threshold in seconds."""
    return int(os.environ.get("KARMA_STALE_THRESHOLD", STALE_THRESHOLD_SECONDS))

def init_bridge(base_path: Path | None = None) -> Path:
    """Initialize bridge directory structure."""
    bp = base_path or get_bridge_path()
    (bp / "inbox").mkdir(parents=True, exist_ok=True)
    (bp / "outbox").mkdir(parents=True, exist_ok=True)
    (bp / "workers").mkdir(parents=True, exist_ok=True)
    (bp / "planner").mkdir(parents=True, exist_ok=True)
    (bp / "events").mkdir(parents=True, exist_ok=True)
    (bp / "locks").mkdir(parents=True, exist_ok=True)
    (bp / "archive").mkdir(parents=True, exist_ok=True)
    return bp

def get_worker_path(role: str, base_path: Path | None = None) -> Path:
    """Get path to worker's state file."""
    bp = base_path or get_bridge_path()
    return bp / "workers" / f"{role}.json"

def _auto_refresh_summary() -> None:
    """Auto-refresh planner summary after state changes."""
    try:
        generate_planner_summary()
    except Exception:
        pass  # Don't fail main operation if summary fails

def update_worker_state(
    role: str,
    status: str = "idle",
    current_task: str = "",
    current_files: list | None = None,
    progress_percent: int = 0,
    blockers: list | None = None,
    needs_decision: bool = False,
    suggested_next_action: str = "",
    output_files: list | None = None,
    handoff_target: str = "",
    error: str = "",
    changed_files: list | None = None,
) -> dict:
    """Update a worker's state file atomically."""
    bp = get_bridge_path()
    worker_path = get_worker_path(role, bp)

    # Load existing state or create new
    if worker_path.exists():
        state = json.loads(worker_path.read_text())
    else:
        state = {"role": role}

    # Update fields
    state.update({
        "status": status,
        "current_task": current_task,
        "current_files": current_files or [],
        "last_update": _get_timestamp(),
        "progress_percent": progress_percent,
        "blockers": blockers or [],
        "needs_decision": needs_decision,
        "suggested_next_action": suggested_next_action,
        "output_files": output_files or [],
        "handoff_target": handoff_target,
        "error": error,
        "recent_events": state.get("recent_events", [])[-5:],
        "last_error": error or state.get("last_error", ""),
        "changed_files": changed_files or state.get("changed_files", []),
    })

    # Atomic write
    _atomic_write(worker_path, json.dumps(state, indent=2))

    # Append event
    append_event(
        event_type="worker_state_update",
        worker=role,
        data={"status": status, "task": current_task, "progress": progress_percent},
    )

    # Auto-refresh planner summary
    _auto_refresh_summary()

    return state

def get_worker_state(role: str) -> dict | None:
    """Read a worker's state file."""
    worker_path = get_worker_path(role)
    if worker_path.exists():
        return json.loads(worker_path.read_text())
    return None

def get_append_failed() -> bool:
    """Return True if the most recent append_event write failed."""
    return _last_append_failed


def append_event(
    event_type: str,
    worker: str = "",
    data: dict | None = None,
    severity: str = "info",
    changed_files: list | None = None,
) -> dict:
    """Append an event to the event log.

    Write path: open(events.jsonl, 'a') + write.  On POSIX, O_APPEND writes
    smaller than PIPE_BUF (~4 KB) are atomic.  A process kill mid-write of a
    line larger than that can leave a partial JSON line; get_events skips those
    lines gracefully.  On failure the exception propagates to the caller and
    _last_append_failed is set True so boot-doctor checks can surface it.
    """
    global _last_append_failed
    bp = get_bridge_path()
    event_file = bp / "events" / "events.jsonl"

    event = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": _get_timestamp(),
        "type": event_type,
        "worker": worker,
        "severity": severity,
        "data": data or {},
        "changed_files": changed_files or [],
    }

    try:
        event_file.parent.mkdir(parents=True, exist_ok=True)
        with open(event_file, "a") as f:
            f.write(json.dumps(event) + "\n")
        _last_append_failed = False
    except Exception:
        _last_append_failed = True
        raise

    # Auto-refresh summary after event — failure here must not mask write errors.
    try:
        generate_planner_summary()
    except Exception:
        pass

    return event

def get_events(limit: int = 50, worker: str = "") -> list[dict]:
    """Read recent events from the log."""
    bp = get_bridge_path()
    event_file = bp / "events" / "events.jsonl"

    if not event_file.exists():
        return []

    events = []
    with open(event_file) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip partial/corrupt lines left by a mid-write crash
            if not worker or e.get("worker") == worker:
                events.append(e)

    return events[-limit:]

def get_changed_files(limit: int = 20) -> list[dict]:
    """Get recently changed files from events."""
    events = get_events(limit=100)
    changed = []
    for e in events:
        files = e.get("changed_files", [])
        for f in files:
            changed.append({
                "file": f,
                "timestamp": e.get("timestamp"),
                "worker": e.get("worker", "unknown"),
                "type": e.get("type", "unknown"),
            })
    changed.sort(key=lambda x: x["timestamp"], reverse=True)
    return changed[:limit]

def generate_planner_summary() -> dict:
    """Generate a planner summary of all worker states with improved ordering."""
    bp = get_bridge_path()
    workers_dir = bp / "workers"
    threshold = get_stale_threshold()

    summary = {
        "generated_at": _get_timestamp(),
        "stale_threshold_seconds": threshold,
        "decision_requests": [],
        "blocked_workers": [],
        "pending_handoffs": [],
        "fresh_updates": [],
        "recent_changed_files": [],
        "active_workers": [],
        "idle_workers": [],
        "completed_workers": [],
        "failed_workers": [],
        "stale_workers": [],
        "actionable_items": [],
    }

    # Check each worker
    now = datetime.now(timezone.utc)

    for worker_file in workers_dir.glob("*.json"):
        role = worker_file.stem
        state = json.loads(worker_file.read_text())

        status = state.get("status", "idle")
        last_update = state.get("last_update", "")

        # Check freshness (updated in last 30 seconds)
        try:
            last_time = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
            is_fresh = (now - last_time).total_seconds() < 30
        except ValueError:
            is_fresh = False

        # Check staleness
        try:
            last_time = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
            is_stale = (now - last_time).total_seconds() > threshold
        except ValueError:
            is_stale = False

        # Decision requests (highest priority)
        if state.get("needs_decision"):
            summary["decision_requests"].append({
                "worker": role,
                "task": state.get("current_task"),
                "suggested_action": state.get("suggested_next_action"),
                "blockers": state.get("blockers", []),
            })

        # Blocked workers
        if status == "blocked" or state.get("blockers"):
            summary["blocked_workers"].append(state)

        # Collect pending handoffs from outbox only (not worker state to avoid dupes)

        # Fresh updates (dedupe by worker)
        if is_fresh:
            if not any(f["worker"] == role for f in summary["fresh_updates"]):
                summary["fresh_updates"].append({
                    "worker": role,
                    "status": status,
                    "task": state.get("current_task"),
                    "update": last_update,
                })

        # Other status categories
        if status == "active" and not is_fresh:
            summary["active_workers"].append(state)
        elif status == "completed":
            summary["completed_workers"].append(state)
        elif status == "failed":
            summary["failed_workers"].append(state)
        elif status == "idle":
            summary["idle_workers"].append(state)

        # Stale workers
        if is_stale:
            summary["stale_workers"].append({"role": role, "last_update": last_update})

    # Collect pending handoffs from outbox files (after worker iteration to dedupe)
    outbox_files = list((bp / "outbox").glob("*.json"))
    seen_handoffs = set()
    for of in outbox_files:
        try:
            h = json.loads(of.read_text())
            hkey = (h.get("from"), h.get("to"))
            if h.get("status", "pending") == "pending" and hkey not in seen_handoffs:
                seen_handoffs.add(hkey)
                summary["pending_handoffs"].append({
                    "from": h.get("from"),
                    "to": h.get("to"),
                    "task": h.get("task"),
                })
        except:
            pass

    # Get recent changed files
    summary["recent_changed_files"] = get_changed_files(limit=10)

    # Build actionable items in priority order
    for item in summary["decision_requests"]:
        summary["actionable_items"].append({
            "type": "decision",
            "worker": item["worker"],
            "task": item["task"],
            "priority": 1,
        })

    for w in summary["blocked_workers"]:
        summary["actionable_items"].append({
            "type": "blocked",
            "worker": w["role"],
            "task": w.get("current_task"),
            "blockers": w.get("blockers", []),
            "priority": 2,
        })

    for h in summary["pending_handoffs"]:
        summary["actionable_items"].append({
            "type": "handoff",
            "from": h["from"],
            "to": h["to"],
            "task": h["task"],
            "priority": 3,
        })

    for f in summary["fresh_updates"]:
        summary["actionable_items"].append({
            "type": "fresh_update",
            "worker": f["worker"],
            "status": f["status"],
            "task": f["task"],
            "priority": 4,
        })

    # Sort actionable items by priority
    summary["actionable_items"].sort(key=lambda x: x["priority"])

    # Write planner summary
    summary_path = bp / "planner" / "summary.json"
    _atomic_write(summary_path, json.dumps(summary, indent=2))

    # Also write markdown summary
    md_summary = _generate_markdown_summary(summary)
    md_path = bp / "planner" / "summary.md"
    _atomic_write(md_path, md_summary)

    return summary

def _generate_markdown_summary(summary: dict) -> str:
    """Generate markdown summary for humans with improved ordering."""
    lines = ["# Planner Summary", "", f"Generated: {summary['generated_at']}", ""]

    # Decision requests (highest priority)
    if summary["decision_requests"]:
        lines.append("## 🔴 NEEDS DECISION")
        for d in summary["decision_requests"]:
            lines.append(f"- **{d['worker']}**: {d.get('task', 'N/A')}")
            for b in d.get("blockers", []):
                lines.append(f"  - Blocker: {b}")
            lines.append(f"  - Suggested: {d.get('suggested_action', 'N/A')}")
        lines.append("")

    # Blocked workers
    if summary["blocked_workers"]:
        lines.append("## 🟠 Blocked Workers")
        for w in summary["blocked_workers"]:
            lines.append(f"- **{w['role']}**: {w.get('current_task', 'N/A')}")
            for b in w.get("blockers", []):
                lines.append(f"  - Blocker: {b}")
        lines.append("")

    # Pending handoffs
    if summary["pending_handoffs"]:
        lines.append("## 🔵 Pending Handoffs")
        for h in summary["pending_handoffs"]:
            lines.append(f"- **{h['from']}** -> **{h['to']}**: {h.get('task', 'N/A')}")
        lines.append("")

    # Fresh updates
    if summary["fresh_updates"]:
        lines.append("## 🟢 Fresh Updates")
        for f in summary["fresh_updates"]:
            lines.append(f"- **{f['worker']}**: {f.get('status')} - {f.get('task', 'N/A')}")
        lines.append("")

    # Recent changed files
    if summary["recent_changed_files"]:
        lines.append("## 📝 Recent Changed Files")
        for cf in summary["recent_changed_files"][:5]:
            lines.append(f"- {cf['file']} ({cf['worker']}, {cf['type']})")
        lines.append("")

    # Stale workers
    if summary["stale_workers"]:
        lines.append("## ⚪ Stale Workers")
        for s in summary["stale_workers"]:
            lines.append(f"- **{s['role']}**: last update {s.get('last_update', 'unknown')}")
        lines.append("")

    # Active workers
    if summary["active_workers"]:
        lines.append("## ⏳ Active Workers")
        for w in summary["active_workers"]:
            pct = w.get("progress_percent", 0)
            lines.append(f"- **{w['role']}**: {w.get('current_task', 'N/A')} ({pct}%)")
        lines.append("")

    # Completed workers
    if summary["completed_workers"]:
        lines.append("## ✅ Completed Workers")
        for w in summary["completed_workers"]:
            lines.append(f"- **{w['role']}**: {', '.join(w.get('output_files', []))}")
        lines.append("")

    if not any([summary["decision_requests"], summary["blocked_workers"],
                summary["active_workers"], summary["fresh_updates"]]):
        lines.append("All workers idle or completed.")

    return "\n".join(lines)

def publish_handoff(
    from_role: str,
    to_role: str,
    task: str,
    context: dict | None = None,
) -> dict:
    """Publish a handoff from one worker to another."""
    bp = get_bridge_path()

    handoff = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": _get_timestamp(),
        "from": from_role,
        "to": to_role,
        "task": task,
        "context": context or {},
        "status": "pending",  # pending, accepted, completed
    }

    # Write to outbox
    outbox_file = bp / "outbox" / f"{from_role}_to_{to_role}_{handoff['id']}.json"
    _atomic_write(outbox_file, json.dumps(handoff, indent=2))

    # Update source worker state
    update_worker_state(
        role=from_role,
        status="idle",
        current_task="",
        handoff_target=to_role,
    )

    # Update target worker state
    update_worker_state(
        role=to_role,
        status="active",
        current_task=task,
        progress_percent=0,
    )

    # Append event
    append_event(
        event_type="handoff",
        worker=from_role,
        data={"to": to_role, "task": task},
    )

    # Auto-refresh summary
    _auto_refresh_summary()

    return handoff

def claim_task(role: str, task: str, files: list | None = None, changed_files: list | None = None) -> dict:
    """Claim a task as a worker."""
    state = update_worker_state(
        role=role,
        status="active",
        current_task=task,
        current_files=files or [],
        progress_percent=0,
        changed_files=changed_files,
    )

    append_event(
        event_type="task_claim",
        worker=role,
        data={"task": task, "files": files or []},
        changed_files=changed_files,
    )

    return state

def complete_task(
    role: str,
    artifacts: list | None = None,
    next_worker: str = "",
    next_action: str = "",
    changed_files: list | None = None,
) -> dict:
    """Mark a task as completed."""
    state = update_worker_state(
        role=role,
        status="completed",
        current_task="",
        progress_percent=100,
        output_files=artifacts or [],
        handoff_target=next_worker,
        suggested_next_action=next_action,
        changed_files=changed_files,
    )

    append_event(
        event_type="task_complete",
        worker=role,
        data={"artifacts": artifacts or [], "next_worker": next_worker},
        changed_files=changed_files,
    )

    return state

def mark_blocked(role: str, blocker: str, decision_needed: str = "", changed_files: list | None = None) -> dict:
    """Mark a worker as blocked."""
    state = get_worker_state(role)
    blockers = state.get("blockers", []) if state else []
    blockers.append(blocker)

    state = update_worker_state(
        role=role,
        status="blocked",
        blockers=blockers,
        needs_decision=bool(decision_needed),
        suggested_next_action=decision_needed,
        changed_files=changed_files,
    )

    append_event(
        event_type="worker_blocked",
        worker=role,
        data={"blocker": blocker, "decision_needed": decision_needed},
        severity="warning",
        changed_files=changed_files,
    )

    return state

def record_file_operation(
    role: str,
    operation: str,  # read, write, execute
    files: list,
    task_context: str = "",
) -> None:
    """Record file operations for changed-file tracking."""
    append_event(
        event_type=f"file_{operation}",
        worker=role,
        data={"operation": operation, "task": task_context, "files": files},
        changed_files=files,
    )

    # Update worker's changed_files
    state = get_worker_state(role)
    if state:
        current_changed = state.get("changed_files", [])
        updated_changed = list(set(current_changed + files))
        update_worker_state(role, changed_files=updated_changed)

def get_planner_summary() -> dict:
    """Read the current planner summary."""
    bp = get_bridge_path()
    summary_path = bp / "planner" / "summary.json"

    if summary_path.exists():
        return json.loads(summary_path.read_text())

    # Generate if doesn't exist
    return generate_planner_summary()

def get_worker_statuses() -> dict:
    """Get quick status of all workers."""
    bp = get_bridge_path()
    workers_dir = bp / "workers"

    statuses = {}
    for worker_file in workers_dir.glob("*.json"):
        state = json.loads(worker_file.read_text())
        statuses[state["role"]] = {
            "status": state.get("status"),
            "task": state.get("current_task"),
            "progress": state.get("progress_percent"),
            "needs_decision": state.get("needs_decision"),
        }

    return statuses

def get_actionable_items() -> list:
    """Get only actionable items sorted by priority."""
    summary = get_planner_summary()
    return summary.get("actionable_items", [])

def get_pending_handoffs() -> list:
    """Get pending handoffs."""
    bp = get_bridge_path()
    outbox = bp / "outbox"
    handoffs = []
    for f in outbox.glob("*.json"):
        handoffs.append(json.loads(f.read_text()))
    return sorted(handoffs, key=lambda x: x.get("timestamp", ""))

def assign_task_via_inbox(task: str, assigned_to: str, context: dict | None = None) -> dict:
    """Simple assignment: write task to inbox for worker to pick up."""
    bp = get_bridge_path()

    assignment = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": _get_timestamp(),
        "task": task,
        "assigned_to": assigned_to,
        "context": context or {},
        "status": "pending",
    }

    inbox_file = bp / "inbox" / f"{assigned_to}_{assignment['id']}.json"
    _atomic_write(inbox_file, json.dumps(assignment, indent=2))

    append_event(
        event_type="task_assigned",
        worker=assigned_to,
        data={"task": task, "source": "planner"},
    )

    _auto_refresh_summary()

    return assignment

def get_inbox_tasks(worker: str = "") -> list:
    """Get pending tasks from inbox."""
    bp = get_bridge_path()
    inbox = bp / "inbox"

    tasks = []
    pattern = f"{worker}_*.json" if worker else "*.json"

    for f in inbox.glob(pattern):
        tasks.append(json.loads(f.read_text()))

    return sorted(tasks, key=lambda x: x.get("timestamp", ""))

def accept_inbox_task(worker: str, task_id: str) -> dict | None:
    """Worker accepts a task from inbox."""
    bp = get_bridge_path()
    inbox_file = bp / "inbox" / f"{worker}_{task_id}.json"

    if not inbox_file.exists():
        return None

    task = json.loads(inbox_file.read_text())
    task["status"] = "accepted"
    task["accepted_at"] = _get_timestamp()

    # Move to archive
    archive_file = bp / "archive" / f"{worker}_{task_id}.json"
    _atomic_write(archive_file, json.dumps(task, indent=2))

    # Remove from inbox
    inbox_file.unlink()

    # Claim the task
    claim_task(worker, task["task"], task.get("context", {}).get("files"))

    return task
