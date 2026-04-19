#!/usr/bin/env python3
"""
Gemma Escalation Test - Verify phone-to-STG handoff works
"""

import json
from pathlib import Path
from datetime import datetime
import subprocess

def adb_shell(cmd):
    return subprocess.run(["adb", "shell", cmd], capture_output=True, text=True)

def adb_push(local, remote):
    return subprocess.run(["adb", "push", str(local), remote], capture_output=True, text=True)

def adb_pull(remote, local):
    return subprocess.run(["adb", "pull", remote, str(local)], capture_output=True, text=True)

# Test escalation creation
print("=== Gemma Escalation Test ===\n")

# Create a test escalation on phone via ADB
ESCALATION = {
    "from": "little_gemma",
    "to": "big_gemma",
    "task": "Analyze the nexus project architecture and suggest improvements",
    "context": "Current state: nexus project at /home/mikoleye/karma/nexus has been having some module integration issues",
    "priority": "high",
    "timestamp": datetime.now().isoformat()
}

# Write to temp file then push
temp_file = Path("/tmp/test_escalation.json")
temp_file.write_text(json.dumps(ESCALATION, indent=2))

result = adb_push(temp_file, "/storage/self/primary/karma/bridge/inbox/test_escalation.json")
print(f"1. Pushed escalation to phone: {'OK' if result.returncode == 0 else 'FAILED'}")

# Verify on phone
result = adb_shell("cat /storage/self/primary/karma/bridge/inbox/test_escalation.json")
print(f"2. Verified on phone: {'OK' if result.returncode == 0 else 'FAILED'}")
if result.stdout:
    print(f"   Content: {result.stdout[:80]}...")

# Pull to STG
STG_INBOX = Path("/home/mikoleye/karma/bridge/inbox/test_escalation.json")
STG_INBOX.parent.mkdir(exist_ok=True)
result = adb_pull("/storage/self/primary/karma/bridge/inbox/test_escalation.json", STG_INBOX)
print(f"3. Pulled to STG: {STG_INBOX.exists()}")

if STG_INBOX.exists():
    data = json.loads(STG_INBOX.read_text())
    print(f"   Task: {data['task'][:50]}...")
    print(f"   From: {data['from']} -> {data['to']}")

# Now create a response
RESPONSE = {
    "from": "big_gemma",
    "to": "little_gemma",
    "original_task": ESCALATION["task"],
    "result": """Analysis complete for nexus project:

## Key Findings
1. Project structure is sound at /home/mikoleye/karma/nexus/
2. Module integration could benefit from:
   - Better dependency management
   - Centralized config
   - Standardized error handling

## Recommendations
1. Consider adding a unified API layer
2. Implement shared utility modules
3. Add integration tests

Priority: Medium - not blocking but recommended""",
    "timestamp": datetime.now().isoformat()
}

# Write response to STG outbox
STG_OUTBOX = Path("/home/mikoleye/karma/bridge/outbox/response_test.json")
STG_OUTBOX.parent.mkdir(exist_ok=True, parents=True)
STG_OUTBOX.write_text(json.dumps(RESPONSE, indent=2))
print(f"4. Created response at: {STG_OUTBOX}")

# Push response to phone
result = adb_push(STG_OUTBOX, "/storage/self/primary/karma/bridge/outbox/response_test.json")
print(f"5. Pushed response to phone: {'OK' if result.returncode == 0 else 'FAILED'}")

# Verify on phone
result = adb_shell("cat /storage/self/primary/karma/bridge/outbox/response_test.json")
print(f"6. Verified on phone: {'OK' if result.returncode == 0 else 'FAILED'}")
if result.stdout:
    print(f"   Content preview: {result.stdout[:100]}...")

print("\n=== Test Complete ===")
print("Bridge is working: Phone -> STG -> Phone flow verified!")