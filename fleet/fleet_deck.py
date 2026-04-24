#!/usr/bin/env python3
"""
Fleet Control Deck - Android/Termux Version
Lightweight terminal UI for the multi-agent system

Install on Android:
1. Install Termux from F-Droid
2. pkg update && pkg install python3 pyyaml
3. Copy this file to Termux
4. python3 fleet_deck.py
"""
import os
import asyncio
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict


# Paths - auto-detect platform
def detect_platform():
    if os.path.exists("/data/data/com.termux"):
        return "android"
    return "desktop"

PLATFORM = detect_platform()
HOME = Path(os.path.expanduser("~"))

if PLATFORM == "android":
    KARMA_ROOT = HOME / "storage/shared/karma"
else:
    KARMA_ROOT = Path("/home/mikoleye/karma")

FLEET_ROOT = KARMA_ROOT / "fleet"
PROJECTS = ["nexus", "nexus-c"]

# ANSI Colors
C = {
    "reset": "\033[0m",
    "dim": "\033[90m",
    "copper": "\033[38;5;172m",
    "bronze": "\033[38;5;216m",
    "accent": "\033[38;5;130m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
}
R = C["reset"]
D = C["dim"]


class FleetDeck:
    def __init__(self):
        self.current_project: Optional[str] = PROJECTS[0] if PROJECTS else None
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M")
        self.tick = 0
        self.refresh_count = 0

    def load_yaml(self, path: Path) -> Optional[Dict]:
        """Load YAML file with markdown wrapper handling and error recovery."""
        try:
            if not path.exists():
                return None
            with open(path, 'r') as f:
                content = f.read()
                # Empty file
                if not content.strip():
                    return None
                # Handle markdown-wrapped YAML
                if "```yaml" in content:
                    start = content.find("```yaml") + 7
                    end = content.find("```", start)
                    if end > start:
                        content = content[start:end].strip()
                elif "```" in content:
                    # Check if this looks like yaml block
                    first_backtick = content.find("```")
                    if first_backtick > -1 and first_backtick < 50:
                        start = first_backtick + 3
                        end = content.find("```", start)
                        if end > start:
                            content = content[start:end].strip()
                # Handle empty result
                if not content:
                    return None
                return yaml.safe_load(content)
        except yaml.YAMLError as e:
            print(f"  Warning: Invalid YAML in {path.name}: {str(e)[:50]}")
        except Exception as e:
            print(f"  Warning: Failed to load {path.name}: {str(e)[:50]}")
        return None

    def load_text(self, path: Path, lines: int = 10) -> str:
        """Load text file, return first N lines, handle missing/empty."""
        try:
            if not path.exists():
                return ""
            with open(path, 'r') as f:
                result = []
                for _ in range(lines):
                    line = f.readline()
                    if not line:
                        break
                    result.append(line)
                return "".join(result)
        except:
            return ""

    def get_project_context(self, project: str) -> Dict:
        """Get project context from .fleet directory with graceful missing dir handling."""
        fleet_dir = KARMA_ROOT / project / ".fleet"
        ctx = {
            "project": project,
            "yaml": None,
            "context": "",
            "tasks": "",
            "handoffs": "",
            "notes": "",
            "rules": "",
            "fleet_dir_exists": fleet_dir.exists() if project in PROJECTS else False
        }

        # Project doesn't exist
        if project not in PROJECTS:
            return ctx

        # .fleet directory missing
        if not fleet_dir.exists():
            return ctx

        # Load files, all gracefully handle missing/empty
        ctx["yaml"] = self.load_yaml(fleet_dir / "project.yaml")
        ctx["context"] = self.load_text(fleet_dir / "recent_context.md", 15)
        ctx["tasks"] = self.load_text(fleet_dir / "task_board.md", 20)
        ctx["handoffs"] = self.load_text(fleet_dir / "handoff_index.md", 15)
        ctx["notes"] = self.load_text(fleet_dir / "notes.md", 15)
        ctx["rules"] = self.load_text(fleet_dir / "local_rules.md", 15)

        return ctx

    def render(self):
        """Render the UI."""
        self.tick += 1
        print("\033[2J\033[H", end="")

        target = self.current_project or "NONE"

        # Header
        print(f"{C['copper']}╔{'═'*50}╗{R}")
        print(f"{C['copper']}║{R} {C['bronze']}◈ FLEET DECK{R}           {D}Session: {self.session_id}{R}   {C['copper']}║{R}")
        print(f"{C['copper']}╠{'═'*50}╣{R}")
        print(f"{C['copper']}║{R} {C['accent']}TARGET:{R} {target:<10} {D}|{R} {C['accent']}TICK:{R} {self.tick:03d}        {C['copper']}║{R}")
        print(f"{C['copper']}╠{'═'*50}╣{R}")

        # Workers
        workers = [
            ("builder-1", "idle", "nexus"),
            ("builder-2", "busy", "nexus-c"),
            ("checker-1", "idle", "-"),
            ("scout-1", "blocked", "nexus"),
        ]

        def w_icon(s):
            if s == "idle": return f"{C['green']}●{R}"
            if s == "busy": return f"{C['yellow']}◐{R}"
            return f"{C['red']}◌{R}"

        for w, s, p in workers:
            print(f"{C['copper']}║{R} {w_icon(s)} {w:<10} {D}→{R} {p:<8}                                          {C['copper']}║{R}")

        print(f"{C['copper']}╠{'═'*50}╣{R}")

        # Project info
        if self.current_project:
            ctx = self.get_project_context(self.current_project)
            name = "N/A"
            ptype = "unknown"
            has_context = False

            if ctx.get("yaml") and ctx["yaml"]:
                try:
                    name = ctx["yaml"].get("project", {}).get("name", self.current_project.upper())
                    ptype = ctx["yaml"].get("project", {}).get("type", "unknown")
                except:
                    name = self.current_project.upper()

            # Check if .fleet directory exists
            if ctx.get("fleet_dir_exists", False):
                has_context = bool(ctx.get("context", "").strip())

            if not ctx.get("fleet_dir_exists", False):
                # .fleet dir missing - show warning
                print(f"{C['copper']}║{R} {C['bronze']}PROJECT:{R} {name:<15} {C['red']}⚠ NO .FLEET{R}             {C['copper']}║{R}")
                print(f"{C['copper']}║{R} {D}Context: .fleet directory missing             {C['copper']}║{R}")
            elif not has_context:
                # .fleet exists but no context
                print(f"{C['copper']}║{R} {C['bronze']}PROJECT:{R} {name:<15} Type: {ptype:<10}           {C['copper']}║{R}")
                print(f"{C['copper']}║{R} {D}Context: No context loaded                  {C['copper']}║{R}")
            else:
                # Normal case
                print(f"{C['copper']}║{R} {C['bronze']}PROJECT:{R} {name:<15} Type: {ptype:<10}           {C['copper']}║{R}")
                context_line = ctx.get("context", "").strip().split("\n")[0][:35]
                print(f"{C['copper']}║{R} {D}Context: {context_line:<35}      {C['copper']}║{R}")
        else:
            print(f"{C['copper']}║{R} {D}No project selected{R}                                  {C['copper']}║{R}")

        print(f"{C['copper']}╠{'═'*50}╣{R}")

        # Status indicators
        karma_status = f"{C['green']}●{R} OK" if KARMA_ROOT.exists() else f"{C['red']}●{R} MISSING"
        print(f"{C['copper']}║{R} Fleet: {karma_status}    {C['green']}●{R} Memory: OK   {C['green']}●{R} State: CLEAN              {C['copper']}║{R}")
        print(f"{C['copper']}╠{'═'*50}╣{R}")
        print(f"{C['copper']}║{R} [T]arget [C]ontext [K]tasks [H]andoffs [N]otes [R]efresh [Q]uit {C['copper']}║{R}")
        print(f"{C['copper']}╚{'═'*50}╝{R}")

        print(f"\n{D}{KARMA_ROOT}{R}")
        print(f"{C['accent']}> {R}", end="", flush=True)

    async def run(self):
        """Main loop."""
        print(f"\n  Fleet Deck v1.0 - {self.session_id}\n")
        print(f"  Projects: {', '.join(PROJECTS)}")
        print(f"  Platform: {PLATFORM}")
        print(f"  Karma: {KARMA_ROOT}\n")

        while True:
            self.render()
            try:
                cmd = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if not cmd:
                continue

            if cmd in ['q', 'quit', 'exit']:
                print("\n  Bye!")
                break
            elif cmd == 't':
                print(f"\n  Available: {', '.join(PROJECTS)}")
                sel = input("  Select > ").strip().lower()
                if not sel:
                    print("  No selection made.")
                # Handle numeric selection (1=nexus, 2=nexus-c, etc.)
                elif sel.isdigit() and 1 <= int(sel) <= len(PROJECTS):
                    self.current_project = PROJECTS[int(sel) - 1]
                    print(f"  → Target: {self.current_project}")
                else:
                    matched = False
                    for p in PROJECTS:
                        if sel == p or sel == p[0]:
                            self.current_project = p
                            print(f"  → Target: {p}")
                            matched = True
                            break
                    if not matched:
                        print(f"  Unknown project: {sel}")
            elif cmd == 'c':
                if not self.current_project:
                    print("  No project selected. Use T to select.")
                else:
                    ctx = self.get_project_context(self.current_project)
                    if not ctx.get("fleet_dir_exists", False):
                        print(f"\n  ⚠ No .fleet directory for {self.current_project}")
                    else:
                        print(f"\n  === {self.current_project.upper()} CONTEXT ===")
                        print(ctx.get("context", "No context") or "No context available")
            elif cmd in ['k', 'tasks']:
                if not self.current_project:
                    print("  No project selected. Use T to select.")
                else:
                    ctx = self.get_project_context(self.current_project)
                    if not ctx.get("fleet_dir_exists", False):
                        print(f"\n  ⚠ No .fleet directory for {self.current_project}")
                    else:
                        print(f"\n  === {self.current_project.upper()} TASKS ===")
                        print(ctx.get("tasks", "No tasks") or "No tasks available")
            elif cmd == 'h':
                if not self.current_project:
                    print("  No project selected. Use T to select.")
                else:
                    ctx = self.get_project_context(self.current_project)
                    if not ctx.get("fleet_dir_exists", False):
                        print(f"\n  ⚠ No .fleet directory for {self.current_project}")
                    else:
                        h = ctx.get("handoffs", "").strip()
                        if h and "none" not in h.lower():
                            print("\n  === HANDOFFS ===")
                            print(h)
                        else:
                            print("\n  No pending handoffs")
            elif cmd == 'n':
                if not self.current_project:
                    print("  No project selected. Use T to select.")
                else:
                    ctx = self.get_project_context(self.current_project)
                    if not ctx.get("fleet_dir_exists", False):
                        print(f"\n  ⚠ No .fleet directory for {self.current_project}")
                    else:
                        print("\n  === NOTES ===")
                        print(ctx.get("notes", "No notes") or "No notes available")
            elif cmd == 'r':
                self.refresh_count += 1
                self.tick = 0
                if self.refresh_count > 10:
                    print(f"  Refreshed. (loop warning: {self.refresh_count} refreshes)")
                else:
                    print("  Refreshed.")
            elif cmd:
                print("  Commands: T(arget) C(ontext) K(tasks) H(andoffs) N(otes) R(efresh) Q(uit)")


async def main():
    # Verify paths exist
    if not KARMA_ROOT.exists():
        print(f"  Error: karma not found at {KARMA_ROOT}")
        print("  On Android: Copy karma folder to ~/storage/shared/karma/")
        print("  On Desktop: Should already be at /home/mikoleye/karma")
        return

    deck = FleetDeck()
    await deck.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Offline.")
