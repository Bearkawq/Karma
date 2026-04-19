"""ToolBuilder — create and manage user-defined bash/python tools at runtime."""

import json
import os
import stat
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class ToolBuilder:
    def __init__(self, base_dir, tool_manager):
        self.base_dir = Path(base_dir)
        self.tools_dir = self.base_dir / "data" / "user_tools"
        self.registry_file = self.tools_dir / "registry.json"
        self.tool_manager = tool_manager
        self.registry: List[Dict[str, Any]] = []
        self.tools_dir.mkdir(parents=True, exist_ok=True)

    # ── persistence ────────────────────────────────────────────

    def load_registry(self):
        """Load saved tools and register them in ToolManager."""
        if not self.registry_file.exists():
            return
        try:
            with open(self.registry_file) as f:
                self.registry = json.load(f)
        except Exception:
            self.registry = []
        for entry in self.registry:
            self._register_tool(entry)

    def _save_registry(self):
        from storage.persistence import atomic_write_text
        try:
            atomic_write_text(self.registry_file, json.dumps(self.registry, indent=2))
        except Exception as e:
            print(f"ToolBuilder: registry save failed: {e}")

    # ── create ─────────────────────────────────────────────────

    def create(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new custom tool."""
        name = params.get("name", "").strip()
        lang = params.get("lang", "bash").strip().lower()
        code = params.get("code", "").strip()

        if not name or not code:
            return {"success": False, "error": "Need name and code."}
        if lang not in ("bash", "python"):
            return {"success": False, "error": "Language must be bash or python."}
        # Sanitize name
        safe_name = "".join(c for c in name if c.isalnum() or c == "_")
        if not safe_name:
            return {"success": False, "error": "Invalid tool name."}

        ext = ".sh" if lang == "bash" else ".py"
        script_path = self.tools_dir / f"{safe_name}{ext}"

        # Write script
        if lang == "bash":
            content = f"#!/bin/bash\n{code}\n"
        else:
            content = f"#!/usr/bin/env python3\n{code}\n"

        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

        # Registry entry
        entry = {
            "name": safe_name,
            "lang": lang,
            "path": str(script_path),
            "created": datetime.now().isoformat(),
        }

        # Update or add
        self.registry = [e for e in self.registry if e["name"] != safe_name]
        self.registry.append(entry)
        self._save_registry()
        self._register_tool(entry)

        return {"success": True, "output": f"Tool '{safe_name}' created ({lang})."}

    # ── run ────────────────────────────────────────────────────

    def run(self, name: str) -> Dict[str, Any]:
        """Run a custom tool by name."""
        entry = self._find(name)
        if not entry:
            return {"success": False, "error": f"No custom tool '{name}'."}

        script = entry["path"]
        if not os.path.isfile(script):
            return {"success": False, "error": f"Script missing: {script}"}

        lang = entry.get("lang", "bash")
        cmd = ["bash", script] if lang == "bash" else ["python3", script]

        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, cwd=str(self.base_dir)
            )
            return {
                "success": r.returncode == 0,
                "output": r.stdout.strip() or r.stderr.strip(),
                "error": r.stderr.strip() if r.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Tool timed out (30s)."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── list / delete ──────────────────────────────────────────

    def list_tools(self) -> Dict[str, Any]:
        if not self.registry:
            return {"success": True, "output": "No custom tools yet."}
        lines = ["Custom tools:"]
        for e in self.registry:
            lines.append(f"  {e['name']} ({e['lang']})")
        return {"success": True, "output": "\n".join(lines)}

    def delete(self, name: str) -> Dict[str, Any]:
        entry = self._find(name)
        if not entry:
            return {"success": False, "error": f"No custom tool '{name}'."}
        # Remove file
        try:
            os.unlink(entry["path"])
        except OSError:
            pass
        self.registry = [e for e in self.registry if e["name"] != name]
        self._save_registry()
        return {"success": True, "output": f"Deleted tool '{name}'."}

    # ── internal ───────────────────────────────────────────────

    def _find(self, name: str) -> Optional[Dict[str, Any]]:
        for e in self.registry:
            if e["name"] == name:
                return e
        return None

    def _register_tool(self, entry: Dict[str, Any]):
        """Register a custom tool in the ToolManager."""
        name = f"custom_{entry['name']}"
        self.tool_manager.register_tool(name, {
            "name": name,
            "category": "custom",
            "description": f"User tool: {entry['name']} ({entry['lang']})",
            "parameters": {},
            "preconditions": [],
            "effects": [],
            "cost": 1,
            "failure_modes": ["timeout", "nonzero_exit"],
            "_custom_entry": entry,
        })
