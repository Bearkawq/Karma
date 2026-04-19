"""Karma bootstrap — single source of truth for config, version, and agent construction.

All entry points (CLI, web, TUI, golearn) should use this module
instead of independently loading config and constructing AgentLoop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Project root: two levels up from agent/bootstrap.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ensure project root on sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from karma_version import VERSION


def load_config(path: str = "config.json") -> Dict[str, Any]:
    """Load config.json, resolving path relative to project root."""
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = PROJECT_ROOT / path
    with open(p, "r") as f:
        cfg = json.load(f)
    # Inject runtime version (source of truth is this module, not config file)
    cfg.setdefault("system", {})["version"] = VERSION
    return cfg


def build_agent(config: Optional[Dict[str, Any]] = None):
    """Construct and return an AgentLoop instance."""
    from agent.agent_loop import AgentLoop
    if config is None:
        config = load_config()
    return AgentLoop(config)


def get_version() -> str:
    return VERSION


def get_project_root() -> Path:
    return PROJECT_ROOT
