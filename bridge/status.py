"""Bridge CLI - Inspect bridge health and status."""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bridge


def status_cmd(args):
    """Show bridge status."""
    bp = bridge.get_bridge_path()

    print(f"Bridge path: {bp}")
    print(f"Exists: {bp.exists()}")
    print(f"Stale threshold: {bridge.get_stale_threshold()}s")
    print()

    # Show worker statuses
    print("=== Worker Statuses ===")
    statuses = bridge.get_worker_statuses()

    if not statuses:
        print("No workers found.")
    else:
        for role, s in statuses.items():
            decision = " [NEEDS DECISION]" if s.get("needs_decision") else ""
            print(f"  {role}: {s['status']} - {s['task']} ({s['progress']}%){decision}")
    print()

    # Show recent events
    print("=== Recent Events (last 5) ===")
    events = bridge.get_events(limit=5)
    for e in events:
        print(f"  [{e['timestamp'][:19]}] {e['worker']}: {e['type']}")
    print()

    # Show planner summary
    print("=== Planner Summary ===")
    try:
        summary = bridge.get_planner_summary()
        print(f"  Decision requests: {len(summary.get('decision_requests', []))}")
        print(f"  Blocked: {len(summary.get('blocked_workers', []))}")
        print(f"  Pending handoffs: {len(summary.get('pending_handoffs', []))}")
        print(f"  Fresh updates: {len(summary.get('fresh_updates', []))}")
        print(f"  Changed files: {len(summary.get('recent_changed_files', []))}")
        print(f"  Stale: {len(summary.get('stale_workers', []))}")
    except Exception as e:
        print(f"  Error: {e}")


def init_cmd(args):
    """Initialize bridge."""
    path = bridge.init_bridge()
    print(f"Bridge initialized at: {path}")


def summary_cmd(args):
    """Generate and show planner summary."""
    summary = bridge.generate_planner_summary()

    print("=== 🔴 Decision Requests ===")
    for d in summary.get("decision_requests", []):
        print(f"  {d['worker']}: {d.get('task')}")
        print(f"    Suggested: {d.get('suggested_action')}")

    print()
    print("=== 🟠 Blocked Workers ===")
    for w in summary.get("blocked_workers", []):
        print(f"  {w['role']}: {w.get('current_task')}")
        for b in w.get("blockers", []):
            print(f"    Blocker: {b}")

    print()
    print("=== 🔵 Pending Handoffs ===")
    for h in summary.get("pending_handoffs", []):
        print(f"  {h['from']} -> {h['to']}: {h.get('task')}")

    print()
    print("=== 🟢 Fresh Updates ===")
    for f in summary.get("fresh_updates", []):
        print(f"  {f['worker']}: {f['status']} - {f['task']}")

    print()
    print("=== 📝 Recent Changed Files ===")
    for cf in summary.get("recent_changed_files", [])[:5]:
        print(f"  {cf['file']} ({cf['worker']}, {cf['type']})")

    print()
    print("=== Stale Workers ===")
    for s in summary.get("stale_workers", []):
        print(f"  {s['role']}: {s.get('last_update')}")


def actionable_cmd(args):
    """Show only actionable items (highest priority)."""
    items = bridge.get_actionable_items()

    if not items:
        print("No actionable items.")
        return

    print("=== Actionable Items (Priority Order) ===")
    for item in items:
        priority = item.get("priority", 99)
        ptype = item.get("type", "unknown")

        if ptype == "decision":
            print(f"🔴 [{priority}] {item['worker']}: needs decision - {item['task']}")
        elif ptype == "blocked":
            print(f"🟠 [{priority}] {item['worker']}: blocked - {item['task']}")
            for b in item.get("blockers", []):
                print(f"       Blocker: {b}")
        elif ptype == "handoff":
            print(f"🔵 [{priority}] {item['from']} -> {item['to']}: {item['task']}")
        elif ptype == "fresh_update":
            print(f"🟢 [{priority}] {item['worker']}: {item['status']} - {item['task']}")


def refresh_cmd(args):
    """Manually refresh planner summary."""
    summary = bridge.generate_planner_summary()
    print(f"Summary refreshed at {summary['generated_at']}")
    print(f"Actionable items: {len(summary.get('actionable_items', []))}")


def changed_files_cmd(args):
    """Show recent changed files."""
    files = bridge.get_changed_files(limit=20)

    if not files:
        print("No changed files recorded.")
        return

    print("=== Recent Changed Files ===")
    for cf in files[:15]:
        print(f"  {cf['file']}")
        print(f"    {cf['worker']} | {cf['type']} | {cf['timestamp'][:19]}")


def inbox_cmd(args):
    """Show inbox tasks."""
    worker = args[0] if args else ""
    tasks = bridge.get_inbox_tasks(worker)

    if not tasks:
        print("No pending inbox tasks.")
        return

    print("=== Inbox Tasks ===")
    for t in tasks:
        print(f"  {t['assigned_to']}: {t['task']}")
        print(f"    ID: {t['id']} | Status: {t['status']}")


def main():
    commands = {
        "status": status_cmd,
        "init": init_cmd,
        "summary": summary_cmd,
        "actionable": actionable_cmd,
        "refresh": refresh_cmd,
        "changed": changed_files_cmd,
        "inbox": inbox_cmd,
    }

    if len(sys.argv) < 2:
        print("Usage: python -m bridge.status <command>")
        print("Commands:")
        print("  status     - Show bridge health")
        print("  init       - Initialize bridge")
        print("  summary    - Show planner summary")
        print("  actionable - Show only actionable items")
        print("  refresh    - Manually refresh summary")
        print("  changed    - Show changed files")
        print("  inbox      - Show inbox tasks")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd not in commands:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands.keys())}")
        sys.exit(1)

    commands[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
