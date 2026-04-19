#!/usr/bin/env python3
"""
Fleet Control Deck - Terminal UI for Multi-Agent System
Operating Model: fleet → project target → project-local context → execute
"""
import os
import sys
import asyncio
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any


KARMA_ROOT = Path("/home/mikoleye/karma")
FLEET_ROOT = KARMA_ROOT / "fleet"
PROJECTS = ["nexus", "nexus-c"]


class FleetControlDeck:
    def __init__(self):
        self.current_project: Optional[str] = None
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.tick = 0
        self.refresh_count = 0
        
    def load_yaml(self, path: Path) -> Optional[Dict]:
        """Load a YAML file safely, handling markdown wrappers."""
        try:
            if not path.exists():
                return None
            with open(path, 'r') as f:
                content = f.read()
                if not content.strip():
                    return None
                if "```yaml" in content:
                    start = content.find("```yaml") + 7
                    end = content.find("```", start)
                    if end > start:
                        content = content[start:end].strip()
                elif "```" in content:
                    first_backtick = content.find("```")
                    if first_backtick > -1 and first_backtick < 50:
                        start = first_backtick + 3
                        end = content.find("```", start)
                        if end > start:
                            content = content[start:end].strip()
                if not content:
                    return None
                return yaml.safe_load(content)
        except yaml.YAMLError as e:
            print(f"  Warning: Invalid YAML in {path.name}: {str(e)[:50]}")
        except Exception as e:
            print(f"  Warning: Failed to load {path.name}: {str(e)[:50]}")
        return None
    
    def load_markdown(self, path: Path, lines: int = 20) -> str:
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
    
    def get_project_context(self, project: str) -> Dict[str, Any]:
        """Load project-local context from .fleet/"""
        fleet_dir = KARMA_ROOT / project / ".fleet"
        context = {
            "project": project,
            "path": str(KARMA_ROOT / project),
            "project_yaml": None,
            "local_rules": None,
            "recent_context": None,
            "task_board": None,
            "handoff_index": None,
            "notes": None,
            "fleet_dir_exists": fleet_dir.exists() if project in PROJECTS else False
        }
        
        if project not in PROJECTS:
            return context
        
        if fleet_dir.exists():
            context["project_yaml"] = self.load_yaml(fleet_dir / "project.yaml")
            context["local_rules"] = self.load_markdown(fleet_dir / "local_rules.md")
            context["recent_context"] = self.load_markdown(fleet_dir / "recent_context.md")
            context["task_board"] = self.load_markdown(fleet_dir / "task_board.md")
            context["handoff_index"] = self.load_markdown(fleet_dir / "handoff_index.md")
            context["notes"] = self.load_markdown(fleet_dir / "notes.md")
        
        return context
    
    def get_fleet_state(self) -> Dict[str, Any]:
        """Load fleet-wide state."""
        state = {
            "workers": {},
            "events": [],
            "planner": {},
            "locks": []
        }
        
        workers_dir = FLEET_ROOT / "state" / "workers"
        if workers_dir.exists():
            for f in workers_dir.glob("*.yaml"):
                data = self.load_yaml(f)
                if data:
                    state["workers"][f.stem] = data
        
        events_dir = FLEET_ROOT / "state" / "events"
        if events_dir.exists():
            for f in sorted(events_dir.glob("*.json"))[-10:]:
                try:
                    with open(f) as fp:
                        state["events"].append(fp.read())
                except:
                    pass
        
        planner_dir = FLEET_ROOT / "state" / "planner"
        if planner_dir.exists():
            for f in planner_dir.glob("*.yaml"):
                data = self.load_yaml(f)
                if data:
                    state["planner"][f.stem] = data
        
        return state
    
    def get_handoffs(self, project: str) -> List[Dict]:
        """Get pending handoffs for a project."""
        handoffs = []
        fleet_dir = KARMA_ROOT / project / ".fleet"
        if fleet_dir.exists():
            handoff_md = self.load_markdown(fleet_dir / "handoff_index.md")
            # Simple parse - just return the raw text for now
            if handoff_md and "None" not in handoff_md and "none yet" not in handoff_md.lower():
                handoffs.append({"raw": handoff_md})
        return handoffs
    
    def get_warnings(self, project: str) -> List[str]:
        """Get warnings for a project."""
        warnings = []
        context = self.get_project_context(project)
        
        # Check for blockers in recent context
        recent = context.get("recent_context", "")
        if "blocker" in recent.lower():
            for line in recent.split("\n"):
                if "blocker" in line.lower():
                    warnings.append(line.strip())
        
        # Check task board for blocked tasks
        task_board = context.get("task_board", "")
        if "blocked" in task_board.lower():
            warnings.append("Tasks in blocked state")
        
        return warnings
    
    def select_project(self, project: str):
        """Set current project target."""
        if project in PROJECTS:
            self.current_project = project
        else:
            print(f"Unknown project: {project}")
    
    def render(self):
        """Render the control deck."""
        self.tick += 1
        
        # Colors
        C = {
            "reset": "\033[0m",
            "dim": "\033[90m",
            "copper": "\033[38;5;172m",
            "bronze": "\033[38;5;216m",
            "accent": "\033[38;5;130m",
            "green": "\033[92m",
            "yellow": "\033[93m",
            "red": "\033[91m",
            "cyan": "\033[36m",
            "bg_dark": "\033[48;5;0m",
            "border": "\033[38;5;244m",
        }
        
        R = C["reset"]
        D = C["dim"]
        
        # Clear screen
        print("\033[2J\033[H", end="")
        
        # ╔══════════════════════════════════════════════════════════════════════════════╗
        # ║  FLEET CONTROL DECK                                           Session: XXXXX  ║
        # ╠══════════════════════════════════════════════════════════════════════════════╣
        
        target = self.current_project or "NONE"
        planner_state = "IDLE"
        
        header = f"{C['copper']}╔{'═'*78}╗{R}\n"
        header += f"{C['copper']}║{R}  {C['bronze']}◈ FLEET CONTROL DECK{R}  " + " " * 40 + f"{C['dim']}Session: {self.session_id}{R}   {C['copper']}║{R}\n"
        header += f"{C['copper']}╠{'═'*78}╣{R}\n"
        
        # Top bar: current target, planner state, timestamp
        top_bar = f"{C['copper']}║{R}  {C['accent']}TARGET:{R} {target:<12} {C['dim']}|{R}  {C['accent']}PLANNER:{R} {planner_state:<10}  {C['dim']}|{R}  {C['accent']}TICK:{R} {self.tick:04d}    {C['copper']}║{R}\n"
        
        print(header + top_bar + f"{C['copper']}╠{'═'*78}╣{R}")
        
        # Content rows - three panel layout
        # LEFT: Fleet roster / workers
        # CENTER: Project summary
        # RIGHT: Handoffs, warnings
        
        rows = 18
        
        # Simulate worker states
        workers = [
            {"name": "builder-1", "status": "idle", "project": "nexus"},
            {"name": "builder-2", "status": "busy", "project": "nexus-c"},
            {"name": "checker-1", "status": "idle", "project": "none"},
            {"name": "scout-1", "status": "blocked", "project": "nexus"},
        ]
        
        def status_icon(s: str) -> str:
            icons = {
                "idle": f"{C['green']}●{R}",
                "busy": f"{C['yellow']}◐{R}",
                "blocked": f"{C['red']}◌{R}",
                "ready": f"{C['green']}▸{R}",
            }
            return icons.get(s, f"{D}○{R}")
        
        # Panel data
        if self.current_project:
            ctx = self.get_project_context(self.current_project)
            proj_summary = ctx.get("project_yaml", {})
            if not proj_summary:
                proj_summary = {"project": {"name": self.current_project.upper(), "type": "unknown"}}
            
            # Extract current objective from task board
            task_board = ctx.get("task_board", "")
            objective = "No active objective"
            for line in task_board.split("\n"):
                if "in_progress" in line:
                    objective = line.strip()
                    break
            
            handoffs = self.get_handoffs(self.current_project)
            warnings = self.get_warnings(self.current_project)
        else:
            proj_summary = {"project": {"name": "NONE"}}
            objective = "Select a project target"
            handoffs = []
            warnings = []
        
        for i in range(rows):
            row = ""
            
            # LEFT PANEL - Workers/Fleet roster (columns 1-25)
            if i < len(workers):
                w = workers[i]
                left = f" {status_icon(w['status'])} {w['name']:<12} {D}→{R} {w['project']:<8}"
            else:
                left = " " * 25
            
            # CENTER PANEL - Project summary (columns 27-52)
            if i == 1:
                center = f" {C['bronze']}PROJECT:{R} {proj_summary['project'].get('name', 'N/A'):<20}"
            elif i == 2:
                center = f" {C['dim']}Type:    {R}{proj_summary['project'].get('type', 'N/A'):<20}"
            elif i == 3:
                center = f" {C['dim']}Language:{R}{proj_summary['project'].get('language', 'N/A'):<20}"
            elif i == 5:
                center = f" {C['accent']}◆ CURRENT OBJECTIVE{R}"
            elif i == 6:
                obj_line = objective[:24] if len(objective) > 24 else objective
                center = f" {C['yellow']}›{R} {obj_line}"
            elif i == 8:
                center = f" {C['dim']}Recent Context:{R}"
            elif i == 9:
                recent = ctx.get("recent_context", "No context loaded")[:24].replace("\n", " ")
                center = f" {D}{recent[:24]}{R}"
            else:
                center = " " * 26
            
            # RIGHT PANEL - Handoffs, warnings (columns 54-78)
            if i == 1:
                right = f" {C['bronze']}HANDOFFS{R}"
            elif i == 2:
                if handoffs:
                    right = f" {C['yellow']}!{R} {C['dim']}Pending: {len(handoffs)}{R}"
                else:
                    right = f" {D}None pending{R}"
            elif i == 4:
                right = f" {C['bronze']}WARNINGS{R}"
            elif i == 5:
                if warnings:
                    w_text = warnings[0][:22]
                    right = f" {C['red']}!{R} {w_text}"
                else:
                    right = f" {D}None{R}"
            elif i == 7:
                right = f" {C['bronze']}STATUS{R}"
            elif i == 8:
                karma_status = f"{C['green']}●{R} Fleet: OK" if KARMA_ROOT.exists() else f"{C['red']}●{R} Fleet: MISSING"
                right = karma_status
            elif i == 9:
                right = f" {C['green']}●{R} Memory: OK"
            elif i == 10:
                right = f" {C['green']}●{R} State: CLEAN"
            else:
                right = " " * 24
            
            row = f"{C['copper']}║{R}{left}{C['dim']}│{R}{center}{C['dim']}│{R}{right}{C['copper']}║{R}"
            print(row)
        
        # ╠══════════════════════════════════════════════════════════════════════════════╣
        # ║  COMMANDS: [T]arget [C]ontext [T]asks [H]andoffs [W]orkers [R]efresh [Q]uit   ║
        # ╚══════════════════════════════════════════════════════════════════════════════╝
        
        print(f"{C['copper']}╠{'═'*78}╣{R}")
        cmds = f"{C['copper']}║{R}  {C['accent']}COMMANDS:{R} [T]arget   [C]ontext   [Tasks]   [H]andoffs   [W]orkers   [R]efresh   [Q]uit"
        cmds += " " * (78 - len(cmds) + 5) + f"{C['copper']}║{R}"
        print(cmds)
        print(f"{C['copper']}╚{'═'*78}╝{R}")
        
        # Footer hint
        print(f"\n{D}Fleet → Project → Context → Execute | {FLEET_ROOT}{R}")
        print(f"{C['accent']}> {R}", end="", flush=True)
    
    async def run(self):
        """Main loop."""
        projects = PROJECTS
        
        print("\033[2J\033[H", end="")
        print(f"{self.session_id}")
        
        # Welcome message
        print(f"\n  {self.session_id}")
        print(f"  Fleet Control Deck v1.0\n")
        
        # Show available projects
        print("  Available projects:")
        for i, p in enumerate(projects):
            print(f"    [{i+1}] {p}")
        print()
        
        # Auto-select first project
        self.current_project = projects[0]
        
        while True:
            self.render()
            try:
                cmd = input().strip().lower()
            except EOFError:
                break
            
            if not cmd:
                continue
                
            if cmd in ['q', 'quit', 'exit']:
                print("\n  Shutting down deck...")
                break
            elif cmd == 't' or cmd.startswith('target'):
                print("  Select project: " + ", ".join([f"{p[0].upper()}{p[1:]}" for p in projects]))
                sel = input("  > ").strip().lower()
                if not sel:
                    print("  No selection made.")
                elif sel.isdigit() and 1 <= int(sel) <= len(projects):
                    self.current_project = projects[int(sel) - 1]
                    print(f"  → Target: {self.current_project}")
                else:
                    for p in projects:
                        if sel == p or sel == p[0]:
                            self.current_project = p
                            print(f"  → Target: {p}")
                            break
                    else:
                        print(f"  Unknown project: {sel}")
            elif cmd in ['c', 'context']:
                if self.current_project:
                    ctx = self.get_project_context(self.current_project)
                    print(f"\n  --- {self.current_project.upper()} CONTEXT ---")
                    print(ctx.get("recent_context", "No context")[:500])
            elif cmd in ['tasks', 't']:
                if self.current_project:
                    ctx = self.get_project_context(self.current_project)
                    print(f"\n  --- {self.current_project.upper()} TASKS ---")
                    print(ctx.get("task_board", "No task board")[:500])
            elif cmd in ['h', 'handoffs']:
                if self.current_project:
                    h = self.get_handoffs(self.current_project)
                    print(f"\n  --- HANDOFFS ({len(h)}) ---")
                    for hd in h:
                        print(hd.get("raw", "None")[:300])
            elif cmd in ['w', 'workers']:
                print("\n  --- WORKERS ---")
                for w in [{"name": "builder-1", "status": "idle"}, 
                          {"name": "builder-2", "status": "busy"},
                          {"name": "checker-1", "status": "idle"},
                          {"name": "scout-1", "status": "blocked"}]:
                    print(f"    {w['name']}: {w['status']}")
            elif cmd in ['r', 'refresh']:
                self.tick = 0
                print("  Deck refreshed.")
            else:
                print(f"  Unknown command: {cmd}")
                print("  Commands: T(arget) C(ontext) Tasks H(andoffs) W(orkers) R(efresh) Q(uit)")


async def main():
    if not KARMA_ROOT.exists():
        print(f"  Error: karma not found at {KARMA_ROOT}")
        print("  Ensure karma directory exists at /home/mikoleye/karma")
        return
    
    deck = FleetControlDeck()
    await deck.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n  Deck offline.")