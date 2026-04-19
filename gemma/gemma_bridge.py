#!/usr/bin/env python3
"""
Gemma Bridge - Link between Phone (Little) and STG (Big)
Handles task escalation and response passing via file-based bridge.
Works over ADB USB connection.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

# Paths
PHONE_BRIDGE = Path("/storage/emulated/0/karma/bridge")
STG_BRIDGE = Path("/home/mikoleye/karma/bridge")
ADB_DEVICE = ""  # Empty = default device


def adb_shell(cmd):
    """Run command on phone via ADB."""
    result = subprocess.run(
        ["adb", "shell", cmd],
        capture_output=True,
        text=True
    )
    return result.stdout


def adb_pull(phone_path, stg_path):
    """Pull file from phone."""
    subprocess.run(["adb", "pull", phone_path, str(stg_path)], check=False)


def adb_push(stg_path, phone_path):
    """Push file to phone."""
    subprocess.run(["adb", "push", str(stg_path), phone_path], check=False)


def check_phone_inbox():
    """Check phone for outgoing tasks."""
    try:
        result = adb_shell(f"ls {PHONE_BRIDGE}/inbox/*.json 2>/dev/null")
        return result.strip().split("\n") if result.strip() else []
    except:
        return []


def check_stg_inbox():
    """Check STG for outgoing tasks."""
    inbox = STG_BRIDGE / "inbox"
    if not inbox.exists():
        return []
    return list(inbox.glob("*.json"))


def pull_phone_inbox():
    """Pull all pending tasks from phone."""
    tasks = []
    inbox = STG_BRIDGE / "inbox" / "from_phone"
    inbox.mkdir(exist_ok=True)
    
    # List files on phone
    result = adb_shell(f"ls {PHONE_BRIDGE}/inbox/ 2>/dev/null")
    if not result.strip():
        return tasks
    
    for f in result.strip().split("\n"):
        if f.endswith(".json"):
            phone_path = f"{PHONE_BRIDGE}/inbox/{f}"
            stg_path = inbox / f
            adb_pull(phone_path, stg_path)
            if stg_path.exists():
                try:
                    tasks.append(json.loads(stg_path.read_text()))
                except:
                    pass
    return tasks


def push_to_phone(data, filename):
    """Push a response file to phone."""
    outbox = PHONE_BRIDGE / "outbox"
    adb_shell(f"mkdir -p {outbox}")
    
    local_file = STG_BRIDGE / "outbox" / filename
    local_file.parent.mkdir(exist_ok=True)
    local_file.write_text(json.dumps(data, indent=2))
    
    adb_push(local_file, f"{outbox}/{filename}")


def create_escalation(task, context="", priority="medium"):
    """Create an escalation from phone to STG."""
    escalation = {
        "from": "little_gemma",
        "to": "big_gemma",
        "task": task,
        "context": context,
        "priority": priority,
        "timestamp": datetime.now().isoformat()
    }
    
    # Write to phone inbox
    local_file = PHONE_BRIDGE / "inbox" / f"escalation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    local_file.parent.mkdir(exist_ok=True, parents=True)
    local_file.write_text(json.dumps(escalation, indent=2))
    
    # Push to phone
    adb_push(local_file, str(local_file))
    
    return escalation


def sync_bridges():
    """Bidirectional sync between phone and STG bridges."""
    print("=== Gemma Bridge Sync ===")
    
    # Pull from phone to STG
    print("\n1. Pulling from phone inbox...")
    phone_tasks = pull_phone_inbox()
    print(f"   Found {len(phone_tasks)} task(s)")
    for t in phone_tasks:
        print(f"   - {t.get('task', 'unknown')[:40]}...")
    
    # Check STG outbox for responses to phone
    print("\n2. Checking STG outbox for phone responses...")
    stg_outbox = STG_BRIDGE / "outbox"
    responses = list(stg_outbox.glob("*to_little*.json")) if stg_outbox.exists() else []
    print(f"   Found {len(responses)} response(s)")
    
    # Push responses to phone
    print("\n3. Pushing responses to phone...")
    for r in responses:
        dest = PHONE_BRIDGE / "outbox" / r.name
        adb_push(r, dest)
        print(f"   Pushed: {r.name}")
    
    print("\n=== Sync Complete ===")


def status():
    """Show bridge status."""
    print("=== Gemma Bridge Status ===")
    print(f"\nPhone Bridge: {PHONE_BRIDGE}")
    
    # Check phone via ADB
    result = adb_shell(f"ls {PHONE_BRIDGE}/inbox/ 2>/dev/null")
    phone_inbox = [f for f in result.strip().split("\n") if f] if result.strip() else []
    print(f"  Inbox: {len(phone_inbox)} files")
    
    result = adb_shell(f"ls {PHONE_BRIDGE}/outbox/ 2>/dev/null")
    phone_outbox = [f for f in result.strip().split("\n") if f] if result.strip() else []
    print(f"  Outbox: {len(phone_outbox)} files")
    
    print(f"\nSTG Bridge: {STG_BRIDGE}")
    stg_inbox = list(STG_BRIDGE.glob("inbox/*.json"))
    print(f"  Inbox: {len(stg_inbox)} files")
    stg_outbox = list(STG_BRIDGE.glob("outbox/*.json"))
    print(f"  Outbox: {len(stg_outbox)} files")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "sync":
            sync_bridges()
        elif cmd == "status":
            status()
        elif cmd == "test":
            print("Testing bridge connection...")
            result = adb_shell("ls /storage/emulated/0/")
            print(f"Phone storage accessible: {'karma' in result}")
        else:
            print("Usage: gemma_bridge.py [sync|status|test]")
    else:
        print("Gemma Bridge - Phone <-> STG Link")
        print("Usage: gemma_bridge.py [sync|status|test]")


if __name__ == "__main__":
    main()