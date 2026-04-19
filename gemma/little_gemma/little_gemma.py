#!/usr/bin/env python3
"""
Little Gemma - Phone Command Center
Role: Lightweight workflow controller, summarizer, escalation gateway to STG
"""

import os
import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
MEMORY_FILE = SCRIPT_DIR / "memory.txt"
ROLE_FILE = SCRIPT_DIR / "role.txt"
STG_BRIDGE = Path("/storage/emulated/0/karma/bridge")

ROLE = """You are LITTLE GEMMA, the phone-side command center assistant.

LOCATION: You live on the PHONE (Termux/Android).

CORE JOB: Help the user control workflow from their phone. Be concise, fast, and useful as a live console assistant.

YOUR CAPABILITIES:
- Summarize current system state
- Accept commands from the user
- Handle lightweight tasks locally
- Route hard requests upward to STG

YOUR LIMITS:
- You are NOT the deep reasoning engine
- You are NOT a heavy backend
- You should NOT try to do heavy reasoning yourself
- You should NOT pretend to be the entire system
- When a task needs deep reasoning, ARCHITECTURE analysis, or heavy debugging, ESCALATE to STG

WHO IS ON STG:
- Goose: Planner-orchestrator, the main coordinator
- Big Gemma: Deep reasoning engine, handles heavy analysis
- Codex/OpenCode/OpenClaw: Specialist workers for specific tasks

ESCALATION RULES:
- Simple local tasks: Handle yourself
- Deep analysis needed: Escalate to big Gemma on STG  
- Complex planning: Route to Goose on STG
- Heavy debugging: Route to STG workers

TASK HANDOFF FORMAT TO STG:
When escalating, create a handoff file in the bridge:
- Target: "big_gemma" or "goose" or "worker_name"
- Task: Clear description of what you need
- Context: Current state summary
- Priority: low/medium/high

MEMORY: 
- Store persistent memory in memory.txt
- Remember user preferences and recent context

STARTUP: 
1. Load your role from role.txt
2. Load memory from memory.txt  
3. Check STG bridge for any pending handoffs
4. Wait for user input

Be fast, concise, and know when to escalate.
"""

DEFAULT_MEMORY = """# Little Gemma Memory

## Role
Phone-side command center, summarizer, escalation gateway

## User Preferences
- Prefers concise responses
- Wants quick task turnaround on phone

## STG Connection
- STG IP: 192.168.68.59 (via USB network)
- Bridge path: /storage/emulated/0/karma/bridge

## Recent Context
- System initialized
- Ready for commands
"""

STG_HELP = """## STG Escalation

To escalate a task to STG:
1. Write task details to bridge/inbox/little_gemma_handoff.json
2. Format: {"from": "little_gemma", "to": "big_gemma", "task": "...", "priority": "high"}
3. STG will pick it up on next check

To check STG status:
- Look at /storage/emulated/0/karma/bridge/planner/summary.json
"""


def load_memory():
    if MEMORY_FILE.exists():
        return MEMORY_FILE.read_text()
    return DEFAULT_MEMORY


def save_memory(content):
    MEMORY_FILE.write_text(content)


def load_role():
    """Load role from role.txt file."""
    if ROLE_FILE.exists():
        return ROLE_FILE.read_text()
    return ROLE


def init_little_gemma():
    """Initialize little Gemma on phone."""
    print("Initializing Little Gemma...")
    
    # Create role file
    ROLE_FILE.write_text(ROLE)
    print(f"  Created: {ROLE_FILE}")
    
    # Create memory file if not exists
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text(DEFAULT_MEMORY)
        print(f"  Created: {MEMORY_FILE}")
    
    # Create bridge directory structure
    bridge_dir = Path("/storage/emulated/0/karma/bridge")
    bridge_dir.mkdir(parents=True, exist_ok=True)
    for subdir in ["inbox", "outbox", "planner"]:
        (bridge_dir / subdir).mkdir(exist_ok=True)
    print(f"  Created bridge: {bridge_dir}")
    
    print("Little Gemma initialized!")
    return True


def show_status():
    """Show current status."""
    print("\n=== LITTLE GEMMA STATUS ===")
    print(f"Role file: {ROLE_FILE} - {'exists' if ROLE_FILE.exists() else 'MISSING'}")
    print(f"Memory: {MEMORY_FILE} - {'exists' if MEMORY_FILE.exists() else 'MISSING'}")
    print(f"STG Bridge: {STG_BRIDGE} - {'connected' if STG_BRIDGE.exists() else 'not found'}")
    print()
    print("Load memory with: cat memory.txt")
    print("Edit role with: nano role.txt")
    print("To escalate: write to /storage/emulated/0/karma/bridge/inbox/")


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "init":
            init_little_gemma()
            return
        elif sys.argv[1] == "status":
            show_status()
            return
        elif sys.argv[1] == "memory":
            print(load_memory())
            return
        elif sys.argv[1] == "role":
            print(load_role())
            return
    
    # Default: show status
    print("Little Gemma - Phone Command Center")
    print("Usage: little_gemma.py [init|status|memory|role]")


if __name__ == "__main__":
    main()