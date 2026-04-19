#!/usr/bin/env python3
"""
Big Gemma - STG Deep Reasoning Engine
Role: Deep reasoning, heavy analysis, architecture support, escalation target
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
MEMORY_FILE = SCRIPT_DIR / "memory.txt"
ROLE_FILE = SCRIPT_DIR / "role.txt"
KARMA_ROOT = Path("/home/mikoleye/karma")

ROLE = """You are BIG GEMMA, the STG deep reasoning engine.

LOCATION: You live on STG (desktop at /home/mikoleye/karma/gemma/big_gemma/).

CORE JOB: Handle deep reasoning, heavy analysis, architecture debugging, and complex planning. You are the escalation target for Little Gemma on the phone.

YOUR CAPABILITIES:
- Deep reasoning and synthesis
- Architecture analysis and design
- Complex debugging and problem solving
- Planning and orchestration support
- Heavy file analysis and code review

YOUR LIMITS:
- You are NOT a quick command center (that's Little Gemma's job)
- You should NOT respond to trivial queries with verbose output
- You should prioritize STRUCTURED REASONING over fluff
- Focus on quality and correctness over speed

WHO CALLS YOU:
- Little Gemma (phone): Escalates hard tasks that need deep reasoning
- Goose: Planner-orchestrator, coordinates your work
- Other STG workers: May hand off complex tasks

RESPONSE STYLE:
- Be thorough but not verbose
- Use structured reasoning
- Show your thinking process
- Prioritize accuracy over speed
- When appropriate, suggest next actions or decisions needed

TASK RECEIVAL:
- Check bridge/inbox/ for incoming tasks from Little Gemma
- Tasks come as JSON files with: from, to, task, context, priority
- Complete tasks and write results to bridge/outbox/

MEMORY:
- Store persistent memory in memory.txt
- Track ongoing tasks and recent reasoning
"""

DEFAULT_MEMORY = """# Big Gemma Memory

## Role
STG deep reasoning engine, escalation target from phone

## System Info
- Location: /home/mikoleye/karma/gemma/big_gemma/
- Karma Root: /home/mikoleye/karma/
- Bridge: /home/mikoleye/karma/bridge/

## Known Workers
- goose: Planner-orchestrator
- little_gemma: Phone-side command center
- opencode: General coding agent
- codex: Specialist worker

## Active Tasks
- (none yet)

## Recent Reasoning
- System initialized, ready for escalations
"""

ROLE_FILE_PATH = Path("/home/mikoleye/karma/gemma/big_gemma/role.txt")


def load_memory():
    if MEMORY_FILE.exists():
        return MEMORY_FILE.read_text()
    return DEFAULT_MEMORY


def save_memory(content):
    MEMORY_FILE.write_text(content)


def load_role():
    if ROLE_FILE.exists():
        return ROLE_FILE.read_text()
    return ROLE


def check_inbox():
    """Check for incoming tasks from Little Gemma."""
    inbox = KARMA_ROOT / "bridge" / "inbox"
    tasks = []
    if inbox.exists():
        for f in inbox.glob("*.json"):
            try:
                task = json.loads(f.read_text())
                if task.get("to") in ["big_gemma", "gemma", "deep"]:
                    tasks.append(task)
            except:
                pass
    return tasks


def complete_task(task, result):
    """Mark task complete and store result."""
    outbox = KARMA_ROOT / "bridge" / "outbox"
    outbox.mkdir(exist_ok=True)
    
    response = {
        "from": "big_gemma",
        "to": task.get("from", "unknown"),
        "original_task": task.get("task"),
        "result": result,
        "timestamp": datetime.now().isoformat()
    }
    
    outfile = outbox / f"big_gemma_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    outfile.write_text(json.dumps(response, indent=2))
    return outfile


def init_big_gemma():
    """Initialize big Gemma on STG."""
    print("Initializing Big Gemma...")
    
    ROLE_FILE.write_text(ROLE)
    print(f"  Created: {ROLE_FILE}")
    
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text(DEFAULT_MEMORY)
        print(f"  Created: {MEMORY_FILE}")
    
    print(f"  Karma root: {KARMA_ROOT}")
    print(f"  Bridge inbox: {KARMA_ROOT / 'bridge' / 'inbox'}")
    
    print("Big Gemma initialized!")
    return True


def show_status():
    """Show current status."""
    print("\n=== BIG GEMMA STATUS ===")
    print(f"Role: {ROLE_FILE} - {'exists' if ROLE_FILE.exists() else 'MISSING'}")
    print(f"Memory: {MEMORY_FILE} - {'exists' if MEMORY_FILE.exists() else 'MISSING'}")
    print(f"Karma Root: {KARMA_ROOT} - {'exists' if KARMA_ROOT.exists() else 'MISSING'}")
    
    tasks = check_inbox()
    print(f"Pending tasks from Little Gemma: {len(tasks)}")
    for t in tasks:
        print(f"  - {t.get('task', 'unknown')[:50]}")
    print()


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "init":
            init_big_gemma()
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
        elif sys.argv[1] == "inbox":
            tasks = check_inbox()
            print(f"Tasks: {len(tasks)}")
            for t in tasks:
                print(json.dumps(t, indent=2))
            return
    
    print("Big Gemma - STG Deep Reasoning Engine")
    print("Usage: big_gemma.py [init|status|memory|role|inbox]")
    print(f"\nModel: Using gemma4 as Big Gemma on STG")


if __name__ == "__main__":
    main()