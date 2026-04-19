#!/usr/bin/env python3
"""Karma — Local Autonomous Hybrid Agent

Implements the core agent loop with:
- state recovery and persistence
- symbolic intent parsing + planning
- lightweight ML fallback and scoring
- modular tools
- disk-based memory

This project is intentionally offline: no external APIs and no remote inference.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import json
import os
import logging
import tempfile
import re
import threading
from core.events import EventBus
import random
from pathlib import Path

from core.observer import EnvironmentObserver
from core.capability_map import CapabilityMap
from core.meta import MetaObserver
from core.retrieval import RetrievalBus
from core.health import HealthMonitor
from core.runtime_governor import RuntimeGovernor, _MISS
from core.dialogue import (
    classify_dialogue_act,
    choose_response_goal,
    retrieval_mode_for_goal,
    command_signal_score,
)
from core.conversation_state import ConversationState
from core.symbolic import SymbolicCore
from core.planner import Planner
from core.normalize import Normalizer
from ml.ml import MLModelManager
from storage.memory import MemorySystem
from tools.tool_interface import ToolManager
from core.responder import Responder
from core.grammar import grammar_match
from tools.tool_builder import ToolBuilder
from tools.code_tool import CodeTool
from tools.self_upgrade import SelfUpgrade
from core.post_execute import PostExecutor
from core.maintenance import MaintenanceScheduler
from agent.dialogue_manager import DialogueManager
from agent.reflection_engine import ReflectionEngine
from core.action_registry import ACTION_REGISTRY


class UserInputContext:
    """Context manager for safe _current_user_input lifecycle.

    Ensures cleanup always occurs, even if an exception is raised.
    """

    def __init__(self, agent, user_input: str):
        self.agent = agent
        self.user_input = user_input

    def __enter__(self):
        self.agent._current_user_input = self.user_input
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self.agent, "_current_user_input"):
            try:
                delattr(self.agent, "_current_user_input")
            except AttributeError:
                pass
        return False


def _safe_execute_action(agent, selected_action):
    """Execute action with safe user_input context management."""
    with UserInputContext(agent, agent._current_user_input):
        return agent._execute_action(selected_action)


def _register_action_handlers(agent):
    """Register action handlers with the action registry."""
    from core.actions.golearn_handler import GoLearnHandler
    from core.actions.ingest_handler import IngestHandler
    from core.actions.digest_handler import DigestHandler
    from core.actions.navigate_handler import NavigateHandler
    from core.actions.pulse_handler import PulseHandler

    ACTION_REGISTRY.register("golearn", GoLearnHandler(agent).execute, "golearn")
    ACTION_REGISTRY.register(
        "salvage_golearn", GoLearnHandler(agent).execute, "golearn"
    )
    ACTION_REGISTRY.register("ingest", IngestHandler(agent).execute, "ingest")
    ACTION_REGISTRY.register("digest", DigestHandler(agent).execute, None)
    ACTION_REGISTRY.register("navigate", NavigateHandler(agent).execute, None)
    ACTION_REGISTRY.register("pulse", PulseHandler(agent).execute, None)


# Routing lanes - explicit paths for different input types
class RoutingLane:
    CHAT = "chat"  # Free-form conversation / questions
    COMMAND = "command"  # Explicit commands (run X, list files)
    MEMORY = "memory"  # Memory operations (remember, forget)
    LEARN = "learn"  # GoLearn sessions
    TOOL = "tool"  # Direct tool execution


class AgentLoop:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_dir = Path(__file__).resolve().parent.parent

        # Logging first (used by state loader)
        self._setup_logging()
        self.bus = EventBus(log_file=str(self.base_dir / "data" / "events.jsonl"))

        # Subsystems
        mem_cfg = self.config.get("memory", {})

        def _rp(x, default):
            p = Path(mem_cfg.get(x, default))
            if not p.is_absolute():
                p = self.base_dir / p
            return str(p)

        self.memory = MemorySystem(
            episodic_file=_rp("episodic_file", "data/episodic.jsonl"),
            facts_file=_rp("facts_file", "data/facts.json"),
            tasks_file=_rp("tasks_file", "data/tasks.json"),
        )

        # Normalizer (loads language mappings from memory)
        langmap_facts = {
            k: v for k, v in self.memory.facts.items() if k.startswith("lang:map:")
        }
        self.normalizer = Normalizer(langmap_facts if langmap_facts else None)

        self.tool_manager = ToolManager()
        self._register_tools_from_config()

        # Capability map (#7) — must init before planner
        cap_path = str(self.base_dir / "data" / "capability_map.json")
        self.capability_map = CapabilityMap(persist_path=cap_path)

        self.symbolic_core = SymbolicCore()
        self._register_default_rules()

        self.planner = Planner(
            capability_map=self.capability_map, workspace_root=str(self.base_dir)
        )
        self.ml_manager = MLModelManager()
        self.ml_manager.auto_train()

        # Retrieval bus — unified evidence retrieval across memory strata
        self.retrieval = RetrievalBus(
            memory=self.memory,
            capability_map=self.capability_map,
            data_dir=str(self.base_dir / "data"),
        )
        self.retrieval.tool_manager = self.tool_manager

        # Code tool (AST-aware code ops)
        self.code_tool = CodeTool(memory=self.memory)

        # Conversation + tool creation (with retrieval bus for evidence-first answering)
        self.responder = Responder(
            str(self.base_dir), self.config, retrieval_bus=self.retrieval
        )
        self.tool_builder = ToolBuilder(self.base_dir, self.tool_manager)
        self.tool_builder.load_registry()

        self.current_state = self._load_state()
        self.running = False
        self._run_lock = threading.RLock()

        # Mark session start so session-summary queries can filter execution_log
        self.current_state["session_start_ts"] = datetime.now().isoformat()

        # Confidence economy (#1)
        conf_cfg = self.config.get("confidence", {})
        self._conf_threshold = float(conf_cfg.get("threshold", 0.4))
        self._conf_low_action = conf_cfg.get("low_action", "clarify")
        self.current_state.setdefault("confidence", 0.5)

        # Meta observer (#6 + #5 time awareness)
        meta_cfg = self.config.get("meta", {})
        meta_path = str(self.base_dir / "data" / "meta_state.json")
        self.meta = MetaObserver(
            persist_path=meta_path,
            cycle_interval=int(meta_cfg.get("cycle_interval", 20)),
        )

        # Health monitor (self-check + repair)
        self.health = HealthMonitor(
            str(self.base_dir),
            self.memory,
            capability_map=self.capability_map,
            retrieval_bus=self.retrieval,
        )

        # Environment observer (#2)
        obs_cfg = self.config.get("observer", {})
        if obs_cfg.get("enabled", False):
            watch = [
                str(self.base_dir / d) for d in obs_cfg.get("watch_dirs", ["data"])
            ]
            self._observer = EnvironmentObserver(
                watch, self.memory, self.bus, float(obs_cfg.get("interval", 30))
            )
            self._observer.start()

        # Post-execution handler (offloaded from loop)
        self._post_executor = PostExecutor(
            self.meta, self.capability_map, self.retrieval
        )

        # Maintenance scheduler (offloaded from loop)
        self._maintenance = MaintenanceScheduler(
            self.meta,
            self.capability_map,
            self.memory,
            self.health,
            self.retrieval,
            self.bus,
        )

        gov_cfg = self.config.get("governor", {})
        self.governor = RuntimeGovernor(
            parse_cache_size=int(gov_cfg.get("parse_cache_size", 64)),
            cooldown_failures=int(gov_cfg.get("cooldown_failures", 3)),
            cooldown_turns=int(gov_cfg.get("cooldown_turns", 3)),
        )

        # Context memory for pronoun resolution
        self._last_intent: Optional[Dict[str, Any]] = None
        self._last_entities: Dict[str, str] = {}
        self._last_result: Optional[str] = None
        self._last_code_context: Optional[Dict[str, Any]] = (
            None  # last code op for follow-ups
        )
        self._command_history: List[Dict[str, Any]] = []  # last N commands for context
        self.conversation = ConversationState(max_turns=8)
        self.retrieval.conversation_state = self.conversation

        # Extracted managers — delegate dialogue + reflection
        self._dialogue_mgr = DialogueManager(
            self.conversation, self.retrieval, self.responder, self.memory
        )
        self._reflection_engine = ReflectionEngine(
            self.memory, self.retrieval, self.governor, self.current_state
        )

        # Safe mode: when True, free-form natural language ALWAYS goes to chat
        # This prevents misrouting of prose to file/path tools
        self._safe_mode = False

        # State revision system for stale response protection
        self._state_revision = 0
        self._last_mutation: Dict[str, Any] = {
            "source": "init",
            "ts": datetime.now().isoformat(),
        }

        # Current routing lane (for diagnostics)
        self._current_lane = RoutingLane.CHAT

        # Register action handlers
        _register_action_handlers(self)

    # ---------- setup ----------
    def _setup_logging(self):
        log_cfg = self.config.get("logging", {})
        level_name = str(log_cfg.get("level", "INFO")).upper()
        level = getattr(logging, level_name, logging.INFO)

        # Prefer a log dir; default to data/logs
        log_dir = Path(log_cfg.get("log_dir", "data/logs"))
        if not log_dir.is_absolute():
            log_dir = self.base_dir / log_dir
        log_dir.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(str(log_dir / "karma.log")),
            ],
        )
        self.logger = logging.getLogger("karma")

    def _register_tools_from_config(self):
        tools_cfg = self.config.get("tools", {})
        enabled = tools_cfg.get("enabled", ["shell", "file", "system"])

        if "shell" in enabled:
            shell_cfg = tools_cfg.get("shell", {})
            self.tool_manager.register_tool(
                "shell",
                {
                    "name": "shell",
                    "category": "shell",
                    "description": "Execute an allowlisted shell command",
                    "parameters": {"command": {"type": "string", "required": True}},
                    "preconditions": ["filesystem_available"],
                    "effects": ["shell_output_available"],
                    "cost": 2,
                    "failure_modes": ["timeout", "command_not_allowed", "nonzero_exit"],
                    "allowed_commands": shell_cfg.get("allowed_commands", []),
                    "timeout": shell_cfg.get("timeout", 30),
                },
            )

        if "file" in enabled:
            file_cfg = tools_cfg.get("file", {})
            self.tool_manager.register_tool(
                "file",
                {
                    "name": "file",
                    "category": "file",
                    "description": "File operations (read/write/list/search) within allowed paths",
                    "parameters": {
                        "operation": {"type": "string", "required": True},
                        "path": {"type": "string", "required": False},
                        "pattern": {"type": "string", "required": False},
                        "content": {"type": "string", "required": False},
                        "mode": {"type": "string", "required": False},
                    },
                    "preconditions": ["filesystem_available"],
                    "effects": ["filesystem_state_changed"],
                    "cost": 1,
                    "failure_modes": [
                        "permission_denied",
                        "path_not_found",
                        "file_too_large",
                    ],
                    "max_size": file_cfg.get("max_size", 10 * 1024 * 1024),
                    "workspace_root": str(self.base_dir),
                    "allowed_paths": list(
                        dict.fromkeys(
                            file_cfg.get("allowed_paths", [])
                            + [
                                str(self.base_dir),
                                str(Path.cwd().resolve()),
                                "~",
                                "/tmp",
                                "/home",
                                "/opt",
                            ]
                        )
                    ),
                },
            )

        if "system" in enabled:
            self.tool_manager.register_tool(
                "system",
                {
                    "name": "system",
                    "category": "system",
                    "description": "System inspection (info/disk/memory/cpu)",
                    "parameters": {"operation": {"type": "string", "required": True}},
                    "preconditions": [],
                    "effects": ["system_info_available"],
                    "cost": 1,
                    "failure_modes": ["dependency_missing"],
                },
            )

    def _register_default_rules(self):
        # --- file operations ---
        self.symbolic_core.add_rule(
            r"(?P<command>list|show)\s+(?:(?:the|my|all)\s+)?files(?:\s+(?:in|at|from)\s+(?P<path>\S+))?",
            "list_files",
            0.9,
        )
        self.symbolic_core.add_rule(
            r"(?P<command>read)\s+(?:the\s+)?file\s+(?:named?\s+)?(?P<filename>\S+)",
            "read_file",
            0.85,
        )
        self.symbolic_core.add_rule(
            r"(?P<command>find|search)\s+(?:for\s+)?(?:files?\s+)?(?:named?\s+|matching\s+|with\s+)?(?P<pattern>\S+)(?:\s+(?:in|at|from)\s+(?P<path>\S+))?",
            "search_files",
            0.8,
        )
        # --- tool creation (before generic run/execute!) ---
        self.symbolic_core.add_rule(
            r'create\s+tool\s+"(?P<name>[^"]+)"\s+(?P<lang>bash|python)\s+"(?P<code>.+)"',
            "create_tool",
            0.95,
        )
        self.symbolic_core.add_rule(
            r"(?:run|use)\s+tool\s+(?P<name>\S+)", "run_custom_tool", 0.9
        )
        self.symbolic_core.add_rule(
            r"(?:list|show)\s+(?:my\s+)?tools", "list_custom_tools", 0.9
        )
        self.symbolic_core.add_rule(
            r"(?:delete|remove)\s+tool\s+(?P<name>\S+)", "delete_tool", 0.9
        )
        # --- teach/forget responses ---
        self.symbolic_core.add_rule(
            r'teach\s+"(?P<trigger>[^"]+)"\s+"(?P<response>.+)"', "teach_response", 0.95
        )
        self.symbolic_core.add_rule(
            r'forget\s+response\s+"(?P<trigger>[^"]+)"', "forget_response", 0.9
        )
        # --- code run (before generic shell — match .py/.sh paths) ---
        self.symbolic_core.add_rule(
            r"(?:run|execute)\s+(?:the\s+)?(?:code\s+|script\s+)?(?P<path>\S+\.(?:py|sh))",
            "code_run",
            0.85,
        )
        # --- generic shell (after tool rules) ---
        self.symbolic_core.add_rule(
            r"(?P<verb>run|execute)\s+(?P<cmd>.+)$", "run_shell", 0.7
        )
        # --- capabilities ---
        self.symbolic_core.add_rule(r"what.*can.*you.*do", "list_capabilities", 0.95)
        # --- golearn ---
        self.symbolic_core.add_rule(
            r'golearn\s+"?(?P<topic>[^"]+?)"?\s+(?P<minutes>\d+)(?:\s+(?P<mode>depth|breadth|auto))?',
            "golearn",
            0.95,
        )
        # --- salvage golearn ---
        self.symbolic_core.add_rule(
            r'salvage\s+golearn\s+"?(?P<topic>[^"]+?)"?\s+(?P<minutes>\d+)',
            "salvage_golearn",
            0.95,
        )
        # --- self upgrade ---
        self.symbolic_core.add_rule(
            r"(?:self[\s-]?upgrade|upgrade\s+yourself|analyze\s+(?:code|codebase))",
            "self_upgrade",
            0.95,
        )
        # --- reload language mappings ---
        self.symbolic_core.add_rule(r"reload\s+language", "reload_language", 0.95)
        # --- code tool ---
        self.symbolic_core.add_rule(
            r"(?:read|show|view)\s+(?:the\s+)?code\s+(?:in\s+|from\s+|of\s+)?(?P<path>\S+)",
            "code_read",
            0.85,
        )
        self.symbolic_core.add_rule(
            r"(?:structure|outline|analyze)\s+(?:the\s+)?(?:code\s+)?(?:in\s+|of\s+)?(?P<path>\S+)",
            "code_structure",
            0.85,
        )
        self.symbolic_core.add_rule(r"debug\s+(?P<path>\S+)", "code_debug", 0.9)
        self.symbolic_core.add_rule(
            r"test\s+(?P<path>\S+)(?:\s+(?P<function>\w+))?", "code_test", 0.85
        )
        self.symbolic_core.add_rule(
            r"(?:recall|lookup|search)\s+(?:code\s+)?(?:knowledge\s+)?(?:about\s+|for\s+)?(?P<topic>.+)",
            "code_recall",
            0.8,
        )
        # --- health / repair ---
        self.symbolic_core.add_rule(
            r"(?:self[\s-]?check|health[\s-]?check|diagnos(?:e|tics?))",
            "self_check",
            0.95,
        )
        self.symbolic_core.add_rule(
            r"(?:repair[\s-]?report|show[\s-]?repairs?|fix[\s-]?report)",
            "repair_report",
            0.95,
        )
        # --- crystallize ---
        self.symbolic_core.add_rule(
            r'crystallize\s+"?(?P<topic>[^"]+?)"?$', "crystallize", 0.95
        )

    # ---------- state ----------
    def _state_file(self) -> Path:
        mem_cfg = self.config.get("memory", {})
        p = Path(mem_cfg.get("state_file", "data/agent_state.json"))
        if not p.is_absolute():
            p = self.base_dir / p
        return p

    # ---------- revision & safe mode ----------
    def increment_revision(self, source: str) -> int:
        """Increment state revision and record mutation metadata."""
        self._state_revision += 1
        self._last_mutation = {
            "source": source,
            "revision": self._state_revision,
            "ts": datetime.now().isoformat(),
        }
        return self._state_revision

    def get_revision(self) -> int:
        return self._state_revision

    def get_last_mutation(self) -> Dict[str, Any]:
        return dict(self._last_mutation)

    def set_safe_mode(self, enabled: bool) -> None:
        """Enable/disable safe mode. When enabled, free-form input always goes to chat."""
        self._safe_mode = enabled

    def is_safe_mode(self) -> bool:
        return self._safe_mode

    def get_current_lane(self) -> str:
        return self._current_lane

    def _determine_lane(
        self, user_input: str, intent: Optional[Dict[str, Any]], dialogue_act: str
    ) -> str:
        """Determine which routing lane the input should take.

        Safe mode: all free-form input goes to chat.
        Explicit commands go to command lane.
        Memory operations go to memory lane.
        GoLearn goes to learn lane.
        """
        if self._safe_mode:
            return RoutingLane.CHAT

        text = (user_input or "").strip().lower()

        # Check for explicit command prefixes
        if text.startswith(
            (
                "run ",
                "execute ",
                "list ",
                "show ",
                "search ",
                "find ",
                "read ",
                "open ",
                "create ",
                "delete ",
                "shell ",
            )
        ):
            return RoutingLane.COMMAND

        # Check for memory operations
        if any(
            text.startswith(p) for p in ("remember ", "forget ", "store ", "recall ")
        ):
            return RoutingLane.MEMORY

        # Check for golearn
        if text.startswith("golearn ") or " golearn" in text:
            return RoutingLane.LEARN

        # Check for explicit tool syntax
        if text.startswith(("tool ", "file ", "shell ")):
            return RoutingLane.TOOL

        # Questions and free-form conversation go to chat
        if dialogue_act == "question" or "?" in (user_input or ""):
            return RoutingLane.CHAT

        # If no intent or low confidence, default to chat
        if not intent or float(intent.get("confidence", 0)) < 0.5:
            return RoutingLane.CHAT

        # If intent is a tool operation, use command lane
        intent_name = intent.get("intent", "")
        if intent_name in ("list_files", "read_file", "search_files", "run_shell"):
            return RoutingLane.COMMAND

        # Default to chat for free-form input
        return RoutingLane.CHAT

    def _quarantine_json(self, path: Path, reason: str = "corrupt") -> Optional[Path]:
        if not path.exists():
            return None
        target = path.with_suffix(path.suffix + f".{reason}.bak")
        idx = 1
        while target.exists():
            target = path.with_suffix(path.suffix + f".{reason}.{idx}.bak")
            idx += 1
        try:
            os.replace(path, target)
            return target
        except Exception:
            return None

    def _atomic_write_json(self, path: Path, payload: Dict[str, Any]):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except Exception:
                    pass

    def _load_state(self) -> Dict[str, Any]:
        state_file = self._state_file()
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self.logger.info(f"Loaded state from {state_file}")
                return state
            except Exception as e:
                self.logger.error(f"Failed to load state: {e}")
                self._quarantine_json(state_file)
                return self._create_initial_state()
        return self._create_initial_state()

    def _create_initial_state(self) -> Dict[str, Any]:
        return {
            "last_run": None,
            "current_task": None,
            "task_history": [],
            "memory_summary": {},
            "decision_summary": {},
            "execution_log": [],
        }

    def _save_state(self):
        state_file = self._state_file()
        try:
            self._atomic_write_json(state_file, self.current_state)
            self.logger.info(f"Saved state to {state_file}")
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")

    # ---------- observe ----------
    def _observe_environment(self) -> Dict[str, Any]:
        system_info = {
            "timestamp": datetime.now().isoformat(),
            "uptime": self._get_uptime(),
            "memory_usage": self._get_memory_usage(),
            "disk_usage": self._get_disk_usage(),
            "running_processes": self._get_running_processes(),
        }
        pending_tasks = self.memory.get_pending_tasks()
        return {
            "system_info": system_info,
            "pending_tasks": pending_tasks,
            "user_input": None,
        }

    def _get_uptime(self) -> str:
        try:
            with open("/proc/uptime", "r") as f:
                uptime = float(f.read().split()[0])
            return f"{uptime:.2f} seconds"
        except Exception:
            return "Unknown"

    def _get_memory_usage(self) -> Dict[str, str]:
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            mem = {
                line.split(":")[0]: line.split(":")[1].strip()
                for line in lines
                if ":" in line
            }
            return {
                "total": mem.get("MemTotal", "Unknown"),
                "available": mem.get("MemAvailable", "Unknown"),
            }
        except Exception:
            return {"total": "Unknown", "available": "Unknown"}

    def _get_disk_usage(self) -> Dict[str, str]:
        try:
            import shutil

            total, used, free = shutil.disk_usage("/")
            gb = 2**30
            return {
                "total": f"{total // gb} GB",
                "used": f"{used // gb} GB",
                "free": f"{free // gb} GB",
            }
        except Exception:
            return {"total": "Unknown", "used": "Unknown", "free": "Unknown"}

    def _get_running_processes(self) -> int:
        # No pipes; count ps output lines.
        try:
            import subprocess

            r = subprocess.run(
                ["ps", "ax"], capture_output=True, text=True, check=False
            )
            return max(0, len(r.stdout.splitlines()) - 1)
        except Exception:
            return 0

    # ---------- intent chaining ----------
    _CHAIN_SPLIT = re.compile(
        r"\s+(?:then|and\s+then|after\s+that|next|also)\s+", re.IGNORECASE
    )

    def _split_chain(self, text: str) -> List[str]:
        """Split compound sentences into individual commands."""
        parts = self._CHAIN_SPLIT.split(text)
        return [p.strip() for p in parts if p.strip()]

    # ---------- context resolution ----------
    _PRONOUNS = re.compile(
        r"\b(it|that|this|the same|that one|the file|the same file|same)\b",
        re.IGNORECASE,
    )
    _AGAIN = re.compile(
        r"\b(again|repeat|redo|do it again|same thing)\b", re.IGNORECASE
    )

    def _resolve_references(self, text: str, normalized: str) -> Tuple[str, str]:
        """Replace pronouns/references with entities from last context."""
        if not self._last_entities:
            return text, normalized

        # "do it again" / "repeat" → re-run last intent entirely
        if self._AGAIN.search(normalized) and self._last_intent:
            return text, normalized  # handled in run() directly

        # Replace pronouns with last known entities
        replacements = (
            self._last_entities.get("filename")
            or self._last_entities.get("path")
            or self._last_entities.get("pattern")
            or self._last_entities.get("name")
            or self._last_entities.get("topic")
        )
        if replacements and self._PRONOUNS.search(normalized):
            normalized = self._PRONOUNS.sub(replacements, normalized, count=1)
            text = self._PRONOUNS.sub(replacements, text, count=1)
            self.logger.debug(f"Resolved reference: {text}")

        return text, normalized

    # ---------- context builder ----------
    def _build_context(self, user_input: str) -> Dict[str, Any]:
        """Build lightweight context from recent history and memory."""
        ctx: Dict[str, Any] = {}

        # Last 3 commands
        ctx["recent_commands"] = [
            {
                "input": h["input"],
                "intent": h.get("intent", ""),
                "success": h.get("success", False),
            }
            for h in self._command_history[-3:]
        ]

        # Active task
        active = self.current_state.get("current_task")
        if active:
            ctx["active_task"] = active

        # Top 5 relevant facts (keyword overlap with input)
        if user_input:
            words = set(user_input.lower().split())
            scored_facts = []
            for key in self.memory.facts:
                key_words = set(key.lower().replace(":", " ").replace("_", " ").split())
                overlap = len(words & key_words)
                if overlap > 0:
                    scored_facts.append((key, overlap))
            scored_facts.sort(key=lambda x: x[1], reverse=True)
            ctx["relevant_facts"] = [k for k, _ in scored_facts[:5]]

        return ctx

    def _record_dialogue(
        self,
        user_input: str,
        response: str,
        act: str,
        intent: Optional[Dict[str, Any]] = None,
        response_goal: Optional[str] = None,
    ):
        entities = intent.get("entities", {}) if intent else {}
        intent_name = intent.get("intent") if intent else None
        self.conversation.note_turn(
            user_input=user_input,
            response=response,
            act=act,
            intent=intent_name,
            entities=entities,
            response_goal=response_goal,
        )
        _SKIP = (
            "Got it.",
            "I'm tracking",
            "Which ",
            "Noted for",
            "Current subject",
            "Current topic",
            "No active",
            "No current",
            "No changes",
            "No alternative",
            "No unresolved",
            "Thread:",
            "Active artifacts",
            "Unresolved ref",
            "Subject:",
            "Summary of",
            "Continuing on",
            "Previous conclusions",
            "Corrected artifacts",
            "Superseded conclusions",
        )
        if not any(response.startswith(p) for p in _SKIP):
            self.conversation.register_answer_fragment(
                text=response,
                response_goal=response_goal
                or choose_response_goal(user_input, act=act),
            )

    def _dialogue_uncertain(self, mode: str) -> bool:
        bundle = self.retrieval.retrieve_context_bundle(
            self.conversation.current_topic or "", mode
        )
        if not bundle:
            return True
        top = bundle[0]
        flags = self.conversation.uncertainty_flags()
        return bool(
            top.confidence < 0.45
            or top.relevance < 0.3
            or flags.get("has_unresolved_references")
        )

    _JUNK_PATTERNS = re.compile(
        r"(?:__pycache__|\.pyc$|\.git(?:/|$)|\.DS_Store|\.venv|\.pytest_cache|\.egg-info|node_modules)",
        re.IGNORECASE,
    )

    def _is_junk_artifact(self, name: str) -> bool:
        return bool(self._JUNK_PATTERNS.search(name))

    def _register_result_artifacts(
        self, execution_result: Dict[str, Any], intent: Optional[Dict[str, Any]]
    ):
        out = execution_result.get("output")
        if (
            isinstance(out, dict)
            and "result" in out
            and isinstance(out.get("result"), dict)
        ):
            out = out.get("result")
        if not isinstance(out, dict):
            return
        if "matches" in out:
            idx = 1
            for match in out.get("matches", [])[:16]:
                if not self._is_junk_artifact(str(match)):
                    self.conversation.register_artifact(
                        type="match", gist=str(match), raw=str(match), ordering=idx
                    )
                    idx += 1
                    if idx > 8:
                        break
        elif "entries" in out:
            idx = 1
            for entry in out.get("entries", [])[:16]:
                if not self._is_junk_artifact(str(entry)):
                    self.conversation.register_artifact(
                        type="entry", gist=str(entry), raw=str(entry), ordering=idx
                    )
                    idx += 1
                    if idx > 8:
                        break
        elif (
            out.get("path")
            and intent
            and intent.get("intent") in {"read_file", "list_files", "search_files"}
        ):
            self.conversation.register_artifact(
                type="path", gist=str(out.get("path")), raw=str(out.get("path"))
            )

    def _clarification_prompt(self, user_input: str) -> str:
        return self._dialogue_mgr.clarification_prompt(user_input)

    def _build_dialogue_response(self, user_input: str, act: str) -> str:
        self._dialogue_mgr.set_last_result(self._last_result)
        return self._dialogue_mgr._build_dialogue_response(user_input, act)

    def _handle_introspection(self, user_input: str) -> str:
        return self._dialogue_mgr._handle_introspection(user_input)

    def _handle_dialogue_turn(
        self, user_input: str, dialogue: Dict[str, str]
    ) -> Optional[str]:
        self._dialogue_mgr.set_last_result(self._last_result)
        self._dialogue_mgr.set_last_code_context(self._last_code_context)
        response = self._dialogue_mgr.handle_turn(user_input, dialogue)
        if response is not None:
            act = dialogue.get("act", "statement")
            goal = (
                "answer"
                if act == "introspection"
                else (
                    "clarify"
                    if act == "clarification_answer"
                    else choose_response_goal(user_input, act=act)
                )
            )
            self._record_dialogue(user_input, response, act, None, response_goal=goal)
        return response

    def _record_command(
        self, user_input: str, intent: Optional[Dict[str, Any]], success: bool
    ):
        """Record command in history for context building."""
        self._command_history.append(
            {
                "input": user_input,
                "intent": intent.get("intent", "") if intent else "",
                "success": success,
            }
        )
        # Keep last 10
        if len(self._command_history) > 10:
            self._command_history = self._command_history[-10:]

    # ---------- reasoning ----------
    def _parse_intent(
        self, input_text: str, normalized_text: str = ""
    ) -> Optional[Dict[str, Any]]:
        text = normalized_text or input_text
        cache_key = text.strip().lower()
        cached_intent = self.governor.get_cached_intent(cache_key)
        if cached_intent is not _MISS:
            return cached_intent

        # Retrieval-assisted parsing: check lexicon evidence for input rewrites
        # Only apply rewrite if grammar matching fails - evidence might help with ambiguous/partial queries
        parse_evidence = self.retrieval.retrieve_context_bundle(text, "parse")

        # Grammar engine first — try original text
        gram = grammar_match(text)
        if gram and gram.get("confidence", 0) > 0.7:
            gram["entities"] = self.symbolic_core._fallback_heuristics(
                text, gram.get("intent", ""), gram.get("entities", {}) or {}
            )
            self.logger.debug(
                f"Grammar match: {gram['intent']} ({gram['confidence']:.2f})"
            )
            self.governor.cache_intent(cache_key, gram)
            return gram

        # Grammar didn't match well - try rewrite from parse evidence
        for ev in parse_evidence:
            if ev.effect_hint == "rewrite_input" and ev.value and ev.relevance >= 0.5:
                rewrite = (
                    ev.value.get("to") if isinstance(ev.value, dict) else str(ev.value)
                )
                if rewrite:
                    self.logger.debug(
                        f"Parse evidence rewrite: '{text}' -> '{rewrite}'"
                    )
                    text = rewrite
                    # Try grammar again with rewritten text
                    gram = grammar_match(text)
                    if gram and gram.get("confidence", 0) > 0.7:
                        gram["entities"] = self.symbolic_core._fallback_heuristics(
                            text, gram.get("intent", ""), gram.get("entities", {}) or {}
                        )
                        self.logger.debug(
                            f"Grammar match after rewrite: {gram['intent']} ({gram['confidence']:.2f})"
                        )
                        self.governor.cache_intent(cache_key, gram)
                        return gram

        # Symbolic rules
        intent = self.symbolic_core.parse_intent(text)
        if intent:
            self.governor.cache_intent(cache_key, intent)
            return intent

        # Before ML: check if responder would handle this (greetings, time, etc.)
        # to avoid ML misclassifying conversational input
        if self.responder._base_response(
            text.strip().lower()
        ) != self.responder._unknown(text.strip().lower()):
            self.governor.cache_intent(cache_key, None)
            return None  # let responder handle it

        # ML fallback (dict) — require >= 0.75 confidence
        try:
            ml_intent = self.ml_manager.classify_intent_dict(text)
            if (
                ml_intent.get("intent") != "unknown"
                and ml_intent.get("confidence", 0) >= 0.75
            ):
                self.governor.cache_intent(cache_key, ml_intent)
                return ml_intent
        except Exception:
            pass

        self.governor.cache_intent(cache_key, None)
        return None

    # Intents that bypass planner and go directly to code tool / special handlers
    _DIRECT_INTENTS = frozenset(
        {
            "list_capabilities",
            "golearn",
            "salvage_golearn",
            "ingest",
            "pulse",
            "digest",
            "navigate",
            "self_upgrade",
            "reload_language",
            "create_tool",
            "run_custom_tool",
            "list_custom_tools",
            "delete_tool",
            "teach_response",
            "forget_response",
            "code_read",
            "code_structure",
            "code_debug",
            "code_test",
            "code_recall",
            "code_run",
            "self_check",
            "repair_report",
            "crystallize",
            "status_query",
        }
    )

    def _generate_candidates(
        self, intent: Dict[str, Any], plan_evidence: List = None
    ) -> List[Dict[str, Any]]:
        intent_name = intent.get("intent", "")

        # Direct-dispatch intents: skip planner, create action from intent directly
        # Map intent names to their tool names (None for intents that don't use tool_manager)
        _DIRECT_TOOL_MAP = {
            "list_capabilities": None,
            "golearn": "golearn",
            "salvage_golearn": "golearn",
            "ingest": "ingest",
            "pulse": None,
            "digest": None,
            "navigate": None,
            "status_query": None,
            "self_upgrade": None,
            "reload_language": None,
            "create_tool": None,
            "run_custom_tool": None,
            "list_custom_tools": None,
            "delete_tool": None,
            "teach_response": None,
            "forget_response": None,
            "code_read": None,
            "code_structure": None,
            "code_debug": None,
            "code_test": None,
            "code_recall": None,
            "code_run": None,
            "self_check": None,
            "repair_report": None,
            "crystallize": None,
        }
        if intent_name in self._DIRECT_INTENTS:
            return [
                {
                    "name": intent_name,
                    "tool": _DIRECT_TOOL_MAP.get(intent_name),
                    "parameters": intent.get("entities", {}),
                    "cost": 0,
                    "confidence": float(intent.get("confidence", 0.9)),
                }
            ]

        candidates = self.planner.plan_actions(intent, evidence=plan_evidence)
        # Planner seat augment: when core planner has no candidates, ask the seat
        if not candidates:
            candidates = self._planner_seat_candidates(intent)
        return self.ml_manager.refine_actions(intent, candidates)

    def _score_candidates(
        self, intent: Dict[str, Any], candidates: List[Dict[str, Any]]
    ) -> List[Tuple[Dict[str, Any], float]]:
        scored: List[Tuple[Dict[str, Any], float]] = []
        intent_name = intent.get("intent", "")
        entities = intent.get("entities", {}) or {}

        # Retrieve evidence for planning phase (shape-aware)
        plan_evidence = self.retrieval.retrieve_context_bundle(
            intent_name,
            "plan",
            intent=intent_name,
            entities=entities,
            tool=candidates[0].get("tool", "") if candidates else "",
        )
        workflow_boost = {}
        failure_penalty = {}
        hits = len(plan_evidence)
        used = 0
        for ev in plan_evidence:
            if ev.effect_hint == "boost_action" and ev.type == "workflow":
                wf = ev.value
                if isinstance(wf, dict):
                    for tool in wf.get("tool_sequence", []):
                        workflow_boost[tool] = max(
                            workflow_boost.get(tool, 0), ev.relevance * 0.15
                        )
                        used += 1
            elif ev.effect_hint == "block_action" and ev.type == "failure":
                fp = ev.value
                if isinstance(fp, dict):
                    failure_penalty[fp.get("tool", "")] = max(
                        failure_penalty.get(fp.get("tool", ""), 0), ev.relevance * 0.2
                    )
                    used += 1

        for action in candidates:
            sym = float(self.symbolic_core.score_action(action, intent))
            ml = float(self.ml_manager.score_action(action, intent))
            # Capability map bonus (#7)
            cap = 0.0
            tool = action.get("tool")
            if tool:
                cap = self.capability_map.tool_score(tool)
            # Meta-adjusted weights (#6)
            w = self.meta
            final = w.sym_weight * sym + w.ml_weight * ml + w.cap_weight * cap
            # Retrieval influence: workflow boost + failure penalty
            if tool:
                final += workflow_boost.get(tool, 0)
                final -= failure_penalty.get(tool, 0)
            final = max(0.0, min(1.0, final))
            scored.append((action, final))

        # Log retrieval metrics (#10)
        self.retrieval.log_decision_metrics(hits, used, hits - used)

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _select_action(
        self, scored_candidates: List[Tuple[Dict[str, Any], float]]
    ) -> Optional[Dict[str, Any]]:
        if not scored_candidates:
            return None
        best_action, _best_score = scored_candidates[0]
        # 10% exploration
        if random.random() < 0.1:
            best_action = random.choice(scored_candidates)[0]
        return best_action

    # ---------- act ----------
    def _run_golearn(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a golearn research session."""
        from research.session import GoLearnSession

        topic = params.get("topic", "")
        minutes = float(params.get("minutes", 5))
        mode = params.get("mode") or "auto"

        if not topic:
            return {"success": False, "output": None, "error": "No topic provided"}

        # Cap to prevent runaway sessions
        max_minutes = (
            self.config.get("tools", {})
            .get("research", {})
            .get("max_session_minutes", 30)
        )
        minutes = min(minutes, max_minutes)

        session_dir = self.base_dir / "data" / "learn"
        session = GoLearnSession(
            topic=topic,
            minutes=minutes,
            mode=mode,
            memory=self.memory,
            bus=self.bus,
            base_dir=str(session_dir),
        )
        result = session.run()

        # Auto-reload language mappings learned during session
        langmap_facts = {
            k: v for k, v in self.memory.facts.items() if k.startswith("lang:map:")
        }
        if langmap_facts:
            self.normalizer.reload_from_memory(self.memory)

        session_status = result["session"]["status"]
        stop_reason = result["session"].get("stop_reason")
        provider_diag = result["session"].get("provider_diagnostic")
        provider_code = result["session"].get("provider_code")
        accepted_sources = result["session"].get("accepted_sources", 0)
        useful_artifacts = result["session"].get("useful_artifacts", 0)

        # Determine if we actually acquired useful results
        acquired_useful_results = accepted_sources > 0 and useful_artifacts > 0

        if session_status == "completed":
            # Check for provider-level failures
            if provider_code in (
                "search_provider_blocked",
                "search_timeout",
                "search_parse_error",
                "search_empty",
            ):
                return {
                    "success": False,
                    "output": result,
                    "error": f"Search provider failed: {provider_diag or provider_code}. Try again later or with a different topic.",
                }

            if stop_reason in ("low_yield", "queue_exhausted"):
                diag_msg = (
                    provider_diag
                    or f"Research completed with limited results ({stop_reason}). Try a broader topic."
                )
                return {
                    "success": True,
                    "output": result,
                    "error": None,
                    "diagnostic": diag_msg,
                }

            # Report acquisition stats
            if not acquired_useful_results:
                return {
                    "success": False,
                    "output": result,
                    "error": f"Research completed but no useful content was acquired. Provider: {provider_diag or provider_code or 'unknown'}",
                }

            return {
                "success": True,
                "output": result,
                "error": None,
            }
        else:
            return {
                "success": False,
                "output": result,
                "error": f"Research failed: {stop_reason or 'unknown error'}",
            }

    def _run_ingest(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest knowledge from local path into Karma."""
        from research.ingestor import get_ingestor

        path = params.get("path", "")
        if not path:
            return {
                "success": False,
                "output": None,
                "error": "No path provided for ingestion. Use: ingest <path>",
            }

        # Get ingestor and run ingestion
        ingestor = get_ingestor()

        try:
            stats = ingestor.ingest_path(path, move_processed=True, move_rejected=True)

            # Build output
            lines = [
                "# Ingestion Complete",
                "",
                f"**Files scanned**: {stats.files_scanned}",
                f"**Files accepted**: {stats.files_accepted}",
                f"**Files rejected**: {stats.files_rejected}",
                f"**Duplicates skipped**: {stats.duplicates_skipped}",
                "",
                "## Topic Counts",
            ]

            for topic, count in sorted(stats.topic_counts.items()):
                lines.append(f"- {topic}: {count}")

            lines.extend(
                [
                    "",
                    "## Provenance Counts",
                ]
            )

            for prov, count in sorted(stats.provenance_counts.items()):
                lines.append(f"- {prov}: {count}")

            if stats.errors:
                lines.extend(
                    [
                        "",
                        "## Errors",
                    ]
                )
                for err in stats.errors[:5]:
                    lines.append(f"- {err}")

            # Check total items
            all_items = ingestor.get_all_items()
            lines.extend(
                [
                    "",
                    f"**Total items in knowledge base**: {len(all_items)}",
                ]
            )

            return {
                "success": True,
                "output": {"content": "\n".join(lines)},
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"Ingestion failed: {str(e)}",
            }

    def _run_digest(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run digest to auto-ingest files from drop folders."""
        from research.dropbox_digest import get_digest, run_digest

        try:
            stats = run_digest()

            lines = [
                "# Dropbox Digest Complete",
                "",
                f"**Files scanned**: {stats.files_scanned}",
                f"**Files ingested**: {stats.files_ingested}",
                f"**Files failed**: {stats.files_failed}",
                "",
                "## Drop Folder Status",
            ]

            digest = get_digest()
            status = digest.get_drop_folder_status()
            for folder, info in status.items():
                lines.append(f"- {folder}: {info['count']} files")

            if stats.errors:
                lines.extend(["", "## Errors"])
                for err in stats.errors[:5]:
                    lines.append(f"- {err}")

            return {
                "success": True,
                "output": {"content": "\n".join(lines)},
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"Digest failed: {str(e)}",
            }

    def _run_navigate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Navigate a site (e.g., Wikipedia) to gather information."""
        from navigator import navigate_wikipedia

        topic = params.get("topic", "").strip()
        if not topic:
            return {
                "success": False,
                "output": None,
                "error": "No topic provided. Use: navigate wikipedia <topic>",
            }

        # Determine site
        site = params.get("site", "wikipedia")

        try:
            session_dir = self.base_dir / "data" / "learn"
            result = navigate_wikipedia(
                topic, max_pages=5, max_depth=2, session_dir=session_dir
            )

            if not result.success or not result.pages:
                return {
                    "success": False,
                    "output": None,
                    "error": f"Navigation failed: {result.stop_reason}",
                }

            # Build output
            lines = [
                f"# Wikipedia Navigation: {topic}",
                "",
                f"**Pages visited**: {len(result.pages)}",
                f"**Stop reason**: {result.stop_reason}",
                "",
            ]

            for i, page in enumerate(result.pages, 1):
                lines.append(f"## {i}. {page.title}")
                lines.append(f"URL: {page.url}")
                lines.append(f"Depth: {page.depth}")
                lines.append("")
                # Show first 300 chars of content
                content_preview = page.content[:300].replace("\n", " ")
                lines.append(content_preview)
                lines.append("")
                lines.append("---")
                lines.append("")

            lines.extend(
                [
                    "",
                    f"**Total content**: {len(result.total_content)} chars",
                    "",
                    "Content saved to local knowledge for future use.",
                ]
            )

            return {
                "success": True,
                "output": {"content": "\n".join(lines)},
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"Navigation failed: {str(e)}",
            }

    def _run_pulse(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Show Karma pulse status."""
        from research.pulse import get_pulse
        from research.pulse_words import get_status_summary

        pulse = get_pulse()
        summary = pulse.generate_summary()

        # Generate markdown
        lines = [
            "# Karma Pulse",
            "",
            "## Recent Activity",
        ]

        # Recent events
        for e in summary.get("recent_events", [])[:5]:
            icon = {"info": "•", "warning": "⚠", "error": "✗", "success": "✓"}.get(
                e.get("severity", "info"), "•"
            )
            lines.append(
                f"{icon} [{e.get('subsystem', 'system')}] {e.get('message', '')}"
            )

        # Needs
        if summary.get("needs"):
            lines.extend(
                [
                    "",
                    "## Needs",
                ]
            )
            for n in summary["needs"][:3]:
                lines.append(
                    f"- **{n.get('topic', 'unknown')}**: {n.get('description', '')}"
                )

        # Blockers
        if summary.get("blockers"):
            lines.extend(
                [
                    "",
                    "## Blockers",
                ]
            )
            for b in summary["blockers"][:3]:
                lines.append(f"- {b.get('message', '')}")

        # Wins
        if summary.get("wins"):
            lines.extend(
                [
                    "",
                    "## Recent Wins",
                ]
            )
            for w in summary["wins"][:3]:
                lines.append(f"- ✓ {w.get('message', '')}")

        # Feed Me - use requested_topic, not topic (fixes malformed "****:")
        if summary.get("feed_me"):
            lines.extend(
                [
                    "",
                    "## Feed Me",
                ]
            )
            for f in summary["feed_me"][:3]:
                topic = f.get("requested_topic") or f.get("topic", "docs")
                folder = f.get("suggested_folder") or f.get("folder", "?")
                reason = f.get("reason", "")
                lines.append(f"- {topic}: Drop in `{folder}`")
                if reason:
                    lines.append(f"  - {reason}")

        # Status summary line
        status_line = get_status_summary(summary)
        lines.extend(
            [
                "",
                f"**Status**: {status_line}",
            ]
        )

        return {
            "success": True,
            "output": {"content": "\n".join(lines)},
            "error": None,
        }

    def _run_salvage_golearn(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run GoLearn then generate a tool scaffold from what was learned."""
        result = self._run_golearn(params)
        if not result.get("success"):
            return result

        topic = params.get("topic", "unknown")
        safe_name = re.sub(r"[^a-z0-9_]", "_", topic.lower().strip())[:40]

        # Gather facts learned about this topic
        facts = []
        for key, val in self.memory.facts.items():
            if topic.lower() in key.lower():
                v = val.get("value", val) if isinstance(val, dict) else val
                facts.append(str(v)[:200])

        # Generate tool scaffold
        gen_dir = self.base_dir / "tools" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        scaffold_path = gen_dir / f"{safe_name}.sh"

        lines = [
            "#!/bin/bash",
            f"# Auto-generated tool from golearn: {topic}",
            f"# Generated: {datetime.now().isoformat()}",
            f"# Facts learned: {len(facts)}",
            "#",
        ]
        for i, fact in enumerate(facts[:10], 1):
            lines.append(f"# Fact {i}: {fact[:120]}")
        lines.extend(
            [
                "",
                "# TODO: implement tool logic based on learned knowledge",
                f'echo "Tool for {topic} — edit this scaffold"',
            ]
        )

        scaffold_path.write_text("\n".join(lines) + "\n")
        scaffold_path.chmod(0o755)

        summary = result.get("output", "")
        if isinstance(summary, dict):
            summary = summary.get("summary", str(summary))

        return {
            "success": True,
            "output": f"{summary}\n\nTool scaffold created: tools/generated/{safe_name}.sh ({len(facts)} facts embedded)",
            "error": None,
        }

    def _execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        if not action:
            return {"success": False, "output": None, "error": "No action selected"}
        name = action.get("name")
        params = action.get("parameters", {}) or {}
        tool_name = action.get("tool")

        def _finish(result: Dict[str, Any]) -> Dict[str, Any]:
            self.meta.end_action(name or tool_name or "unknown")
            self.governor.record_tool_result(
                tool_name or "", bool(result.get("success", False))
            )
            return result

        self.meta.start_action()

        if name == "help":
            return _finish(
                {
                    "success": True,
                    "output": 'Available commands: list files, read file named <file>, search <pattern>, what can you do, teach when I say ... respond ..., forget response for ..., create tool "name" bash|python "code"',
                    "error": None,
                }
            )
        if name == "repair_report":
            path = self.base_dir / "data" / "upgrades"
            count = 0
            lines = ["Repair report:"]
            if path.exists():
                for p in sorted(path.glob("*.json"))[:15]:
                    count += 1
                    lines.append(f"  - {p.name}")
            if count == 0:
                lines.append("  No repair artifacts found.")
            return _finish({"success": True, "output": "\n".join(lines), "error": None})
        if name == "self_check":
            report = self.health.run_check()
            txt = [
                f"Health: {report.get('status', 'unknown').upper()} ({report.get('issues_found', 0)} issues)"
            ]
            for issue in report.get("issues", [])[:10]:
                txt.append(
                    f"  - [{issue.get('severity', '?')}] {issue.get('issue', '')}"
                )
            gov = self.governor.snapshot()
            txt.append(
                f"Governor: success={gov['recent_success_rate']:.0%}, explore={gov['exploration_rate']:.0%}, cooldowns={len(gov['cooldowns'])}"
            )
            return _finish({"success": True, "output": "\n".join(txt), "error": None})
        if name == "crystallize":
            topic = params.get("topic", "")
            crystal = self.retrieval.crystallize(topic)
            if crystal:
                return _finish(
                    {
                        "success": True,
                        "output": crystal.get("summary", "Done."),
                        "error": None,
                    }
                )
            return _finish(
                {
                    "success": False,
                    "output": None,
                    "error": f"Not enough knowledge to crystallize '{topic}'",
                }
            )
        if name == "list_capabilities":
            return _finish(
                {
                    "success": True,
                    "output": {
                        "tools": self.tool_manager.list_tools(),
                        "memory_stats": self.memory.get_stats(),
                        "governor": self.governor.snapshot(),
                    },
                    "error": None,
                }
            )
        if name == "create_tool":
            return _finish(self.tool_builder.create(params))
        if name == "run_custom_tool":
            return _finish(self.tool_builder.run(params.get("name", "")))
        if name == "list_custom_tools":
            return _finish(self.tool_builder.list_tools())
        if name == "delete_tool":
            return _finish(self.tool_builder.delete(params.get("name", "")))
        if name == "golearn":
            result = self._run_golearn(params)
            # Store golearn result for follow-up queries
            if result.get("output"):
                self._dialogue_mgr.set_last_golearn_result(result["output"])
            return _finish(result)
        if name == "salvage_golearn":
            result = self._run_salvage_golearn(params)
            # Store golearn result for follow-up queries
            if result.get("output"):
                self._dialogue_mgr.set_last_golearn_result(result["output"])
            return _finish(result)
        if name == "ingest":
            result = self._run_ingest(params)
            return _finish(result)
        if name == "pulse":
            result = self._run_pulse(params)
            return _finish(result)
        if name == "digest":
            result = self._run_digest(params)
            return _finish(result)
        if name == "navigate":
            result = self._run_navigate(params)
            return _finish(result)
        if name == "status_query":
            # Route through dialogue manager for follow-up handling
            user_text = params.get("text", "") if params else ""
            if not user_text and hasattr(self, "_current_user_input"):
                user_text = self._current_user_input
            status_response = self._dialogue_mgr._handle_status_followup(user_text)
            if status_response:
                return _finish(
                    {
                        "success": True,
                        "output": {"content": status_response},
                        "error": None,
                    }
                )
            return _finish(
                {
                    "success": True,
                    "output": {"content": "No status to report"},
                    "error": None,
                }
            )
        if name in (
            "code_read",
            "code_structure",
            "code_debug",
            "code_test",
            "code_recall",
            "code_run",
        ):
            op_map = {
                "code_read": "read",
                "code_structure": "structure",
                "code_debug": "debug",
                "code_test": "test",
                "code_recall": "recall",
                "code_run": "run",
            }
            code_params = dict(params)
            code_params["operation"] = op_map[name]
            result = self.code_tool.execute(code_params)
            out = (
                result.get("content")
                or result.get("structure")
                or result.get("output")
                or result.get("stdout")
                or ""
            )
            err = result.get("error") or result.get("stderr") or ""
            # Store last code context for follow-ups
            self._last_code_context = {
                "path": code_params.get("path", ""),
                "action": name,
                "result": (out or err)[:500],
                "error_type": result.get("error", "")[:100]
                if not result.get("success")
                else None,
                "success": result.get("success", False),
            }
            if result.get("success"):
                return _finish(
                    {"success": True, "output": out or "Done.", "error": None}
                )
            return _finish(
                {
                    "success": False,
                    "output": out,
                    "error": err or "Code operation failed",
                }
            )
        if name == "teach_response":
            text = self.responder.teach(
                params.get("trigger", ""), params.get("response", "")
            )
            return _finish({"success": True, "output": text, "error": None})
        if name == "forget_response":
            text = self.responder.forget(params.get("trigger", ""))
            return _finish({"success": True, "output": text, "error": None})

        # Planner-seat-generated candidates: execute all plan steps in order.
        if action.get("_seat_generated"):
            task_str = params.get("task", name or "unknown task")
            plan = params.get("plan", [])
            try:
                step_result = self._execute_plan_steps(plan or [], task_str)
                if step_result.get("output"):
                    return _finish(
                        {
                            "success": step_result.get("success", False),
                            "output": step_result["output"],
                            "error": step_result.get("error"),
                            "_step_states": step_result.get("_step_states"),
                            "_run_artifact": step_result.get("_run_artifact"),
                        }
                    )
            except Exception as _e:
                self.logger.debug(f"Plan step execution failed: {_e}")
            # Deterministic fallback: render plan steps as readable text
            if plan:
                lines = [
                    f"{s.get('step', i + 1)}. {s.get('action', '')} {s.get('target', '')}".strip()
                    for i, s in enumerate(plan)
                ]
                return _finish(
                    {"success": True, "output": "\n".join(lines), "error": None}
                )
            return _finish({"success": True, "output": task_str, "error": None})

        tool = self.tool_manager.get_tool(tool_name) if tool_name else None
        if not tool:
            return _finish(
                {
                    "success": False,
                    "output": None,
                    "error": f"Tool not found: {tool_name}",
                }
            )

        result = tool.execute(params)
        return _finish(
            {
                "success": bool(result.get("success", False)),
                "output": result,
                "error": result.get("error"),
            }
        )

    def _post_execute(self, action: Dict[str, Any], result: Dict[str, Any]):
        """Post-execution hooks — delegated to PostExecutor."""
        self._post_executor.run(action, result)

    # ---------- reflect (delegated to ReflectionEngine) ----------
    def _calculate_confidence(
        self, intent: Dict[str, Any], action: Optional[Dict[str, Any]]
    ) -> float:
        return self._reflection_engine.calculate_confidence(intent, action)

    def _reflect(
        self,
        intent: Dict[str, Any],
        selected_action: Optional[Dict[str, Any]],
        execution_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self._reflection_engine.reflect(
            intent, selected_action, execution_result
        )

    def _update_state(self, reflection: Dict[str, Any]):
        self._reflection_engine.update_state(reflection)

    def _calculate_success_rate(self) -> float:
        return self._reflection_engine._calculate_success_rate()

    def _calculate_average_confidence(self) -> float:
        return self._reflection_engine._calculate_average_confidence()

    # ---------- seat agent helpers ----------
    # Intents that warrant automatic critic review after execution
    _CRITIC_INTENTS = frozenset(
        {
            "golearn",
            "salvage_golearn",
            "run_shell",
            "code_run",
            "code_debug",
            "code_test",
            "self_upgrade",
        }
    )

    # Multi-step execution limits
    _MAX_PLAN_STEPS: int = 10  # hard cap — prevents runaway decomposition
    _PLAN_STEP_TIMEOUT: int = 30  # per-step executor timeout (seconds)
    _REPLAN_TIMEOUT: int = 30  # replanner call timeout (seconds)

    def _planner_seat_candidates(self, intent: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ask planner seat to decompose intent when core planner returns nothing.

        Returns a list of candidate action dicts (may be empty on failure).
        Swallows all exceptions — this is a best-effort augment.
        """
        try:
            from core.agent_model_manager import get_agent_model_manager

            mgr = get_agent_model_manager()
            if mgr._no_model_mode:
                return []
            intent_name = intent.get("intent", "unknown")
            entities = intent.get("entities", {}) or {}
            task_desc = f"{intent_name}: {entities}" if entities else intent_name
            result = mgr.execute(
                task=task_desc,
                context={
                    "intent": intent_name,
                    "entities": entities,
                    "memory": self.memory,
                },
                explicit_role="planner",
            )
            if not result.success or not result.output:
                return []
            out = result.output
            if isinstance(out, dict) and "plan_steps" in out:
                steps = out["plan_steps"]
                if steps:
                    # Wrap the first meaningful step as an executor candidate
                    # so the loop has something to act on
                    first = steps[0]
                    return [
                        {
                            "name": first.get("action", "process"),
                            "tool": None,
                            "parameters": {
                                "task": first.get("target") or task_desc,
                                "plan": [
                                    {
                                        "step": s.get("step"),
                                        "action": s.get("action"),
                                        "target": s.get("target"),
                                    }
                                    for s in steps
                                ],
                            },
                            "cost": 1,
                            "confidence": 0.55,
                            "_seat_generated": True,
                        }
                    ]
        except Exception:
            pass
        return []

    def _seat_critique(
        self, execution_result: Dict[str, Any], intent_name: str
    ) -> Optional[str]:
        """Run critic seat on a result.

        Two paths:
        - _run_artifact present: critique the full multi-step run (sequence quality,
          wasted steps, recovery quality, final vs intermediate outcome).
          Fires regardless of intent — multi-step runs always warrant review.
        - No _run_artifact: legacy path — only fires for _CRITIC_INTENTS, passes
          raw output string as before.

        Returns critique string (not "OK") or None.
        """
        if not execution_result.get("success"):
            return None

        _run_artifact = execution_result.get("_run_artifact")

        parent_paths: List[str] = []
        recovery_paths: List[str] = []

        if _run_artifact:
            # Multi-step path: use structured artifact
            if not _run_artifact.get("steps"):
                return None
            content = self._format_run_artifact_content(_run_artifact)
            content_type = "run_artifact"
            parent_paths = AgentLoop._extract_touched_paths(_run_artifact)
            _recovery = _run_artifact.get("recovery") or {}
            _rec_plan = _recovery.get("recovery_plan") or []
            if _rec_plan:
                recovery_paths = AgentLoop._extract_touched_paths({"plan": _rec_plan})
            # Attach structured path findings to run_artifact now (deterministic, no model)
            if parent_paths or recovery_paths:
                from agents.critic_agent import CriticAgent as _CA
                _pf = _CA._analyze_touched_paths(parent_paths, recovery_paths)
                if _pf:
                    _run_artifact["path_findings"] = _pf
        else:
            # Legacy single-step path
            if intent_name not in self._CRITIC_INTENTS:
                return None
            output = execution_result.get("output")
            if not output:
                return None
            content = str(output)[:1200]
            content_type = "result"

        _CRITIC_TIMEOUT = 30

        def _run_critic(
            content=content,
            content_type=content_type,
            parent_paths=parent_paths,
            recovery_paths=recovery_paths,
        ):
            from core.agent_model_manager import get_agent_model_manager

            mgr = get_agent_model_manager()
            if mgr._no_model_mode:
                return None
            result = mgr.execute(
                task="review result",
                context={
                    "content_type": content_type,
                    "content": content[:1500],
                    "memory": self.memory,
                    "touched_paths_parent": parent_paths,
                    "touched_paths_recovery": recovery_paths,
                },
                explicit_role="critic",
            )
            if not result.success or not result.output:
                return None
            out = result.output
            if isinstance(out, dict):
                critique = out.get("critique") or str(out.get("issues", ""))
            else:
                critique = str(out)
            critique = critique.strip()
            return (
                critique
                if critique and critique.upper() not in ("OK", "") and len(critique) > 4
                else None
            )

        try:
            from concurrent.futures import (
                ThreadPoolExecutor,
                TimeoutError as FuturesTimeout,
            )

            with ThreadPoolExecutor(max_workers=1) as _pool:
                future = _pool.submit(_run_critic)
                try:
                    return future.result(timeout=_CRITIC_TIMEOUT)
                except FuturesTimeout:
                    self.logger.warning("Critic seat timed out; skipping review")
                    return None
        except Exception:
            pass
        return None

    def _try_seat_response(self, user_input: str) -> Optional[str]:
        """Try seat pipeline for free-form queries not handled by responder.

        Returns model-generated answer string or None (caller falls back).
        Bounded timeout prevents chat path from hanging on a slow seat model.
        """
        _SEAT_RESPONSE_TIMEOUT = 15  # seconds — chat fallback must be fast

        def _run():
            from core.agent_model_manager import get_agent_model_manager

            mgr = get_agent_model_manager()
            if mgr._no_model_mode:
                return None
            result = mgr.execute(
                task=user_input,
                context={
                    "memory": self.memory,
                    "retrieval": self.retrieval,
                    "intent": "respond",
                },
            )
            if result.success and result.output and isinstance(result.output, str):
                text = result.output.strip()
                if len(text) > 10:
                    return text
            return None

        try:
            from concurrent.futures import (
                ThreadPoolExecutor,
                TimeoutError as FuturesTimeout,
            )

            with ThreadPoolExecutor(max_workers=1) as _pool:
                future = _pool.submit(_run)
                try:
                    return future.result(timeout=_SEAT_RESPONSE_TIMEOUT)
                except FuturesTimeout:
                    self.logger.warning(
                        "Seat response timed out; using responder fallback"
                    )
                    return None
        except Exception:
            pass
        return None

    def _seat_summarize(self, text: str) -> str:
        """Run long text through the summarizer seat. Returns original on failure."""
        if len(text) < 800:
            return text
        try:
            from core.agent_model_manager import get_agent_model_manager

            mgr = get_agent_model_manager()
            if mgr._no_model_mode:
                return text
            result = mgr.execute(
                task="summarize result",
                context={
                    "content_type": "general",
                    "content": text[:3000],
                    "memory": self.memory,
                },
                explicit_role="summarizer",
            )
            if result.success and result.output:
                out = result.output
                if isinstance(out, dict):
                    out = out.get("summary", text)
                if isinstance(out, str) and len(out.strip()) > 10:
                    return out.strip()
        except Exception:
            pass
        return text

    @staticmethod
    def _format_run_artifact_content(run_artifact: Dict[str, Any]) -> str:
        """Format _run_artifact into a compact content string for summarization."""
        task = run_artifact.get("task", "unknown")
        outcome = run_artifact.get("outcome", "unknown")
        steps = run_artifact.get("steps", [])
        outputs = run_artifact.get("outputs", [])
        failed = run_artifact.get("failed", [])
        recovery = run_artifact.get("recovery")

        n_done = sum(1 for s in steps if s.get("status") == "done")
        n_failed = sum(1 for s in steps if s.get("status") == "failed")
        n_skipped = sum(1 for s in steps if s.get("status") == "skipped")

        lines = [
            f"Task: {task}",
            f"Outcome: {outcome}",
            f"Steps: {len(steps)} total ({n_done} done, {n_failed} failed, {n_skipped} skipped)",
        ]

        done_steps = [s for s in steps if s.get("status") == "done"]
        if done_steps:
            descs = [f"{s.get('action', '?')} {s.get('target', '')}".strip() for s in done_steps[:6]]
            lines.append(f"Completed: {', '.join(descs)}")

        for fs in failed[:3]:
            err = (fs.get("error") or "")[:100]
            lines.append(
                f"Failed: step {fs.get('step')} ({fs.get('action', '?')} {fs.get('target', '').strip()})"
                + (f" — {err}" if err else "")
            )

        if outputs and n_done > 0:
            lines.append("Output:")
            for o in outputs[:3]:
                lines.append(f"  {str(o)[:120]}")

        if recovery:
            rec_outcome = recovery.get("outcome", "unknown")
            rec_exec = recovery.get("recovery_execution") or {}
            rec_n = len(rec_exec.get("steps", [])) or len(recovery.get("recovery_plan") or [])
            lines.append(f"Recovery: {rec_outcome} ({rec_n} step(s))")
            rec_failed = rec_exec.get("failed") or []
            if rec_failed:
                rf = rec_failed[0]
                lines.append(f"  Recovery failed at: {rf.get('action', '?')} — {(rf.get('error') or '')[:80]}")

        return "\n".join(lines)

    @staticmethod
    def _build_compact_digest_summary(run_artifact: Dict[str, Any]) -> str:
        """Build a short ≤5-line deterministic digest summary, operator-readable."""
        task = run_artifact.get("task", "unknown")
        outcome = run_artifact.get("outcome", "unknown")
        steps = run_artifact.get("steps", [])
        failed = run_artifact.get("failed", [])
        recovery = run_artifact.get("recovery")

        done = [s for s in steps if s.get("status") == "done"]
        n_skip = sum(1 for s in steps if s.get("status") == "skipped")

        # Single-tool path: no steps, use tool + target
        if run_artifact.get("run_kind") == "tool" and not steps:
            tool = run_artifact.get("tool", "")
            target = run_artifact.get("target", "")
            desc = f"{tool} {target}".strip() if target else tool
            parts = [f"{task}: {outcome}"]
            if desc:
                parts.append(f"tool={desc}")
            if failed:
                err = (failed[0].get("error") or "")[:70]
                parts.append(f"error={err}" if err else "error=unknown")
            elif run_artifact.get("key_output"):
                parts.append(f"out={run_artifact['key_output'][:60]}")
            return " | ".join(parts)

        parts = [f"{task}: {outcome}"]
        if done:
            descs = [f"{s.get('action', '?')} {s.get('target', '')}".strip() for s in done[:4]]
            parts.append(f"done={', '.join(descs)}")
        if failed:
            fs = failed[0]
            err = (fs.get("error") or "")[:70]
            parts.append(f"failed={fs.get('action', '?')}" + (f"({err})" if err else ""))
        if n_skip:
            parts.append(f"skipped={n_skip}")
        if recovery:
            rec_out = recovery.get("outcome", "unknown")
            parts.append(f"recovery={rec_out}")
        return " | ".join(parts)

    @staticmethod
    def _extract_touched_paths(run_artifact: Dict[str, Any]) -> List[str]:
        """Extract file/path targets from a run artifact's step records.

        Only keeps targets that look like filesystem paths (absolute, relative,
        or bare names with a file extension). Returns a deduplicated ordered list
        capped at 20 entries. Returns [] when no path-like targets are found.
        """
        import re

        # Match paths: /abs, ./rel, ~/home, or bare-name.ext (no spaces, has dot+ext)
        _PATH_RE = re.compile(
            r"^(?:/|\.{1,2}/|~/)[\w./\-]+"  # /abs, ./rel, ~/home
            r"|^[\w./\-]+\.\w{1,8}$"  # bare relative: src/foo.py, README.md
        )

        seen: set = set()
        paths: List[str] = []
        for collection in ("steps", "plan"):
            for step in run_artifact.get(collection, []):
                target = (step.get("target") or "").strip()
                if target and _PATH_RE.match(target) and target not in seen:
                    seen.add(target)
                    paths.append(target)
        return paths[:20]

    @staticmethod
    def _resolve_touched_paths(
        paths: List[str],
        base_dir: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Resolve touched paths against filesystem state.

        Returns a list of resolved path info dicts with keys:
          - path: original path string
          - status: "file" | "directory" | "missing" | "unresolvable"
          - resolved: absolute path if resolved, else original

        Uses optional base_dir to resolve relative paths; defaults to cwd.
        Skips paths outside base_dir or that can't be safely resolved.
        """
        import os

        if not paths:
            return []

        base = base_dir or os.getcwd()
        results: List[Dict[str, Any]] = []

        for p in paths:
            if not isinstance(p, str) or not p.strip():
                continue

            try:
                # Resolve relative to base, expand user home
                expanded = os.path.expanduser(p)
                if not os.path.isabs(expanded):
                    expanded = os.path.join(base, expanded)
                resolved = os.path.normpath(os.path.abspath(expanded))

                # Security: ensure resolved path is under base
                common = os.path.commonpath([resolved, os.path.abspath(base)])
                if common != os.path.abspath(base):
                    results.append(
                        {
                            "path": p,
                            "status": "unresolvable",
                            "resolved": resolved,
                        }
                    )
                    continue

                # Check filesystem state
                if os.path.isfile(resolved):
                    status = "file"
                elif os.path.isdir(resolved):
                    status = "directory"
                elif os.path.exists(resolved):
                    status = "unknown"
                else:
                    status = "missing"

                results.append(
                    {
                        "path": p,
                        "status": status,
                        "resolved": resolved,
                    }
                )
            except Exception:
                results.append(
                    {
                        "path": p,
                        "status": "unresolvable",
                        "resolved": p,
                    }
                )

        return results

    def _seat_summarize_run(self, run_artifact: Dict[str, Any]) -> str:
        """Generate a compact summary of a completed run via summarizer seat.

        Returns a short digest string. Falls back to deterministic format on failure.
        """
        content = self._format_run_artifact_content(run_artifact)
        try:
            from core.agent_model_manager import get_agent_model_manager

            mgr = get_agent_model_manager()
            if not mgr._no_model_mode:
                result = mgr.execute(
                    task="summarize run",
                    context={
                        "content_type": "run_artifact",
                        "content": content,
                        "memory": self.memory,
                    },
                    explicit_role="summarizer",
                )
                if result.success and result.output:
                    out = result.output
                    summary = (
                        out.get("summary", "") if isinstance(out, dict) else str(out)
                    )
                    if isinstance(summary, str) and len(summary.strip()) > 10:
                        return summary.strip()
        except Exception:
            pass
        # Deterministic fallback: compact one-liner
        return AgentLoop._build_compact_digest_summary(run_artifact)

    # Actions that generate no operator-useful digest (housekeeping / meta / conversation)
    _DIGEST_SKIP_NAMES = frozenset({
        "help", "status_query", "list_capabilities", "repair_report",
        "teach_response", "forget_response", "list_custom_tools",
    })

    @staticmethod
    def _should_digest_single_tool(selected_action: Dict[str, Any]) -> bool:
        """Return True if this single-tool execution is worth persisting as a digest."""
        name = selected_action.get("name") or ""
        if name in AgentLoop._DIGEST_SKIP_NAMES:
            return False
        # Skip _seat_generated — those produce _run_artifact via _execute_plan_steps
        if selected_action.get("_seat_generated"):
            return False
        return True

    @staticmethod
    def _extract_tool_output(raw_output, max_len: int = 200) -> str:
        """Extract a clean string from a tool execution output value."""
        if raw_output is None:
            return ""
        if isinstance(raw_output, str):
            return raw_output[:max_len].strip()
        if isinstance(raw_output, (list, tuple)):
            items = [str(x) for x in raw_output[:12]]
            return ", ".join(items)[:max_len]
        if isinstance(raw_output, dict):
            # Priority: human-readable string fields
            for key in ("output", "stdout", "content", "text", "result", "summary", "message"):
                v = raw_output.get(key)
                if v and isinstance(v, str) and v.strip():
                    return v[:max_len].strip()
            # List-valued fields — join items
            for key in ("files", "items", "results", "lines", "entries"):
                v = raw_output.get(key)
                if v and isinstance(v, (list, tuple)):
                    items = [str(x) for x in v[:12]]
                    return ", ".join(items)[:max_len]
            # Last resort: strip well-known meta keys and stringify remainder
            skip = {"success", "error", "exit_code", "stderr", "returncode"}
            meaningful = {k: v for k, v in raw_output.items() if k not in skip and v not in (None, "", False)}
            if meaningful:
                # Single non-empty value → use it directly
                vals = list(meaningful.values())
                if len(vals) == 1:
                    return str(vals[0])[:max_len]
                return str(meaningful)[:max_len]
        return str(raw_output)[:max_len]

    @staticmethod
    def _build_single_tool_artifact(
        intent: Dict[str, Any],
        selected_action: Dict[str, Any],
        execution_result: Dict[str, Any],
        user_input: str = "",
    ) -> Dict[str, Any]:
        """Build a minimal _run_artifact-compatible dict for a single-tool execution."""
        name = selected_action.get("name") or ""
        tool = selected_action.get("tool") or name
        params = selected_action.get("parameters") or {}
        target = (
            params.get("target") or params.get("path") or
            params.get("command") or params.get("name") or ""
        )
        task = (user_input or intent.get("intent", name) or name)[:120]
        success = bool(execution_result.get("success", False))
        outcome = "success" if success else "failed"

        raw_output = execution_result.get("output")
        key_output = AgentLoop._extract_tool_output(raw_output)

        error = (execution_result.get("error") or "")[:120]

        return {
            "task": task,
            "outcome": outcome,
            "run_kind": "tool",
            "tool": tool,
            "target": str(target)[:80],
            "steps": [],
            "outputs": [key_output] if key_output else [],
            "failed": [
                {"step": 1, "action": tool, "target": str(target)[:80], "error": error}
            ] if not success and error else [],
            "recovery": None,
            "key_output": key_output,
            "key_error": error,
        }

    def _persist_run_digest(self, run_artifact: Dict[str, Any], summary: str) -> None:
        """Persist a compact run digest to Karma memory, plus a linked child entry
        if the run contains a completed recovery execution.

        Parent writes:
        - run:last          — always the most recent parent run (overwritten)
        - run:<hash8>       — stable per-run key; stored as digest["run_id"]

        Recovery child writes (when recovery_execution is present):
        - run:recovery:<hash8>  — linked child entry; stored as digest["run_id"]
        Child digest references parent via parent_run_id; parent digest references
        child via recovery_run_id.

        Recursion safety: recovery artifacts produced by allow_replan=False cannot
        contain recovery_execution themselves, so this method never recurses.
        """
        import hashlib

        try:
            task = run_artifact.get("task", "unknown")
            outcome = run_artifact.get("outcome", "unknown")
            failed = run_artifact.get("failed", [])
            recovery = run_artifact.get("recovery")
            ts = __import__("datetime").datetime.now().isoformat(timespec="seconds")

            # Stable parent key
            run_key = "run:" + hashlib.md5(f"{task}{ts}".encode()).hexdigest()[:8]

            # Persist recovery child first so we can reference its run_id in parent
            recovery_run_id: Optional[str] = None
            recovery_exec = recovery.get("recovery_execution") if recovery else None
            if recovery_exec and recovery_exec.get("steps"):
                rec_task = recovery_exec.get("task", task)
                rec_outcome = recovery_exec.get("outcome", "unknown")
                rec_ts = (
                    __import__("datetime").datetime.now().isoformat(timespec="seconds")
                )
                rec_key = (
                    "run:recovery:"
                    + hashlib.md5(f"{rec_task}{rec_ts}".encode()).hexdigest()[:8]
                )
                recovery_run_id = rec_key

                rec_n_steps = len(recovery_exec.get("steps", []))
                rec_paths = AgentLoop._extract_touched_paths(recovery_exec)
                rec_steps = recovery_exec.get("steps", [])
                rec_done = [s for s in rec_steps if s.get("status") == "done"]
                rec_fail = recovery_exec.get("failed", [])
                rec_compact = AgentLoop._build_compact_digest_summary(recovery_exec)
                rec_digest = {
                    "run_id": rec_key,
                    "run_kind": "recovery",
                    "parent_run_id": run_key,
                    "parent_task": task,
                    "task": rec_task,
                    "outcome": rec_outcome,
                    "n_steps": rec_n_steps,
                    "n_failed": len(rec_fail),
                    "n_skipped": sum(1 for s in rec_steps if s.get("status") == "skipped"),
                    "completed_steps": [
                        {"step": s.get("step"), "action": s.get("action"), "target": s.get("target", "")}
                        for s in rec_done[:8]
                    ],
                    "failed_steps": [
                        {"step": s.get("step"), "action": s.get("action"),
                         "target": s.get("target", ""), "error": (s.get("error") or "")[:120]}
                        for s in rec_fail[:3]
                    ],
                    "key_errors": list(dict.fromkeys(
                        (s.get("error") or "")[:80] for s in rec_fail if s.get("error")
                    ))[:3],
                    "summary": rec_compact,
                    "ts": rec_ts,
                    "touched_paths": rec_paths,
                    "path_findings": run_artifact.get("path_findings") or [],
                }
                self.memory.save_fact(
                    rec_key,
                    rec_digest,
                    source="run_artifact",
                    confidence=0.9,
                    topic="run_history",
                )

            steps = run_artifact.get("steps", [])
            done_steps = [s for s in steps if s.get("status") == "done"]
            fail_steps = [s for s in steps if s.get("status") == "failed"]
            n_skipped = sum(1 for s in steps if s.get("status") == "skipped")
            compact_summary = AgentLoop._build_compact_digest_summary(run_artifact)
            parent_paths = AgentLoop._extract_touched_paths(run_artifact)
            run_kind = run_artifact.get("run_kind", "primary")
            digest = {
                "run_id": run_key,
                "run_kind": run_kind,
                "task": task,
                "outcome": outcome,
                "n_steps": len(steps),
                "n_failed": len(failed),
                "n_skipped": n_skipped,
                "completed_steps": [
                    {"step": s.get("step"), "action": s.get("action"), "target": s.get("target", "")}
                    for s in done_steps[:8]
                ],
                "failed_steps": [
                    {"step": s.get("step"), "action": s.get("action"),
                     "target": s.get("target", ""), "error": (s.get("error") or "")[:120]}
                    for s in fail_steps[:3]
                ],
                "key_errors": list(dict.fromkeys(
                    (s.get("error") or "")[:80] for s in fail_steps if s.get("error")
                ))[:3],
                "recovery_outcome": recovery.get("outcome") if recovery else None,
                "recovery_run_id": recovery_run_id,
                "summary": compact_summary,
                "ts": ts,
                "touched_paths": parent_paths,
                "path_findings": run_artifact.get("path_findings") or [],
            }
            # Tool-run extras: include key output/error directly in digest
            if run_kind == "tool":
                digest["tool"] = run_artifact.get("tool", "")
                digest["target"] = run_artifact.get("target", "")
                digest["key_output"] = run_artifact.get("key_output", "")
                digest["key_error"] = run_artifact.get("key_error", "")

            self.memory.save_fact(
                "run:last",
                digest,
                source="run_artifact",
                confidence=0.9,
                topic="run_history",
            )
            self.memory.save_fact(
                run_key,
                digest,
                source="run_artifact",
                confidence=0.9,
                topic="run_history",
            )
        except Exception:
            pass

    def _execute_plan_steps(
        self,
        steps: List[Dict[str, Any]],
        task_desc: str,
        allow_replan: bool = True,
        seed_prior: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Execute planner-seat-generated steps in sequence.

        Per-step states: pending → running → done | failed | skipped.
        Policy: stop on first failure; preserve partial output from completed steps.
        Returns a standard execution-result dict with '_step_states' attached.
        """
        from concurrent.futures import (
            ThreadPoolExecutor,
            TimeoutError as FuturesTimeout,
        )
        from core.agent_model_manager import get_agent_model_manager

        steps = steps[: self._MAX_PLAN_STEPS]

        step_states: List[Dict[str, Any]] = [
            {
                "step": s.get("step", i + 1),
                "action": s.get("action", ""),
                "target": s.get("target", ""),
                "status": "pending",
                "output": None,
                "error": None,
            }
            for i, s in enumerate(steps)
        ]

        mgr = get_agent_model_manager()

        if mgr._no_model_mode:
            # Deterministic path: render each step description
            outputs = []
            prior_results = []
            for state, step in zip(step_states, steps):
                state["status"] = "done"
                state["output"] = (
                    f"{step.get('action', '')} {step.get('target', '')}".strip()
                )
                outputs.append(f"Step {state['step']}: {state['output']}")
                prior_results.append(
                    {
                        "step": state["step"],
                        "action": state["action"],
                        "target": state["target"],
                        "output": state["output"],
                    }
                )
            _run_artifact = {
                "task": task_desc,
                "plan": [
                    {
                        "step": s.get("step"),
                        "action": s.get("action"),
                        "target": s.get("target"),
                    }
                    for s in steps
                ],
                "steps": step_states,
                "outputs": outputs,
                "prior_results": prior_results,
                "failed": [],
                "recovery": None,
                "outcome": "success",
            }
            return {
                "success": True,
                "output": "\n".join(outputs),
                "error": None,
                "_step_states": step_states,
                "_run_artifact": _run_artifact,
            }

        # Snapshot of all step descriptors passed as context to every executor call
        all_step_descriptors = [
            {
                "step": s.get("step"),
                "action": s.get("action"),
                "target": s.get("target"),
            }
            for s in steps
        ]
        outputs: List[str] = []
        # Seed from caller (e.g. recovery run inherits original run's completed outputs)
        prior_results: List[Dict[str, Any]] = list(seed_prior) if seed_prior else []

        for step, state in zip(steps, step_states):
            state["status"] = "running"
            step_task = (
                f"{step.get('action', '')} {step.get('target', '')}".strip()
                or task_desc
            )
            # Snapshot prior_results at closure-definition time (before this step runs)
            prior_snapshot = list(prior_results)

            def _run(task=step_task, prior=prior_snapshot):
                return mgr.execute(
                    task=task,
                    context={
                        "plan_steps": all_step_descriptors,
                        "prior_results": prior,
                        "memory": self.memory,
                        "intent": "execute",
                    },
                    explicit_role="executor",
                )

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(_run).result(timeout=self._PLAN_STEP_TIMEOUT)

                if result.success and result.output:
                    out = result.output
                    text = (
                        out.get("execution", str(out))
                        if isinstance(out, dict)
                        else str(out)
                    )
                    state["status"] = "done"
                    state["output"] = text
                    outputs.append(f"Step {state['step']}: {text}")
                    prior_results.append(
                        {
                            "step": state["step"],
                            "action": state["action"],
                            "target": state["target"],
                            "output": text,
                        }
                    )
                else:
                    state["status"] = "failed"
                    state["error"] = (
                        getattr(result, "error", None) or "step returned failure"
                    )
                    self.logger.debug(
                        f"Plan step {state['step']} failed: {state['error']}"
                    )
                    break

            except FuturesTimeout:
                state["status"] = "failed"
                state["error"] = "timeout"
                self.logger.warning(f"Plan step {state['step']} timed out")
                break
            except Exception as exc:
                state["status"] = "failed"
                state["error"] = str(exc)
                self.logger.debug(f"Plan step {state['step']} error: {exc}")
                break

        # Mark any still-pending steps as skipped
        for state in step_states:
            if state["status"] == "pending":
                state["status"] = "skipped"

        failed = [s for s in step_states if s["status"] == "failed"]
        combined = "\n".join(outputs) if outputs else None

        # Build structured run artifact (always present)
        _run_artifact: Dict[str, Any] = {
            "task": task_desc,
            "plan": all_step_descriptors,
            "steps": step_states,
            "outputs": outputs,
            "prior_results": prior_results,
            "failed": failed,
            "recovery": None,
            "outcome": "failed" if failed else ("success" if outputs else "empty"),
        }

        # Adaptive replan: one cycle only, when allowed and a failure occurred
        replan_artifact: Optional[Dict[str, Any]] = None
        if failed and allow_replan and not mgr._no_model_mode:
            failed_state = failed[0]
            completed_states = [s for s in step_states if s["status"] == "done"]
            skipped_specs = [
                {"step": s["step"], "action": s["action"], "target": s["target"]}
                for s in step_states
                if s["status"] == "skipped"
            ]
            replan_artifact = {
                "original_plan": [
                    {"step": s["step"], "action": s["action"], "target": s["target"]}
                    for s in step_states
                ],
                "failed_step": failed_state,
                "recovery_plan": None,
                "outcome": "stopped",
            }
            recovery_steps = self._replan_after_failure(
                failed_state,
                completed_states,
                skipped_specs,
                task_desc,
                mgr,
                _run_artifact,
            )
            replan_artifact["recovery_plan"] = recovery_steps or None
            _run_artifact["recovery"] = replan_artifact
            if recovery_steps:
                recovery_result = self._execute_plan_steps(
                    recovery_steps,
                    task_desc,
                    allow_replan=False,
                    seed_prior=prior_results,
                )
                for rs in recovery_result.get("_step_states", []):
                    rs["recovery"] = True
                    step_states.append(rs)
                if recovery_result.get("output"):
                    outputs.append("[Recovery] " + recovery_result["output"])
                combined = "\n".join(outputs) if outputs else None
                replan_artifact["outcome"] = (
                    "recovered" if recovery_result.get("success") else "recovery_failed"
                )
                _run_artifact["outcome"] = replan_artifact["outcome"]
                # Thread recovery execution artifact into replan_artifact for linked persistence.
                # allow_replan=False guarantees no nested recovery inside recovery_exec_artifact.
                recovery_exec_artifact = recovery_result.get("_run_artifact")
                if recovery_exec_artifact:
                    replan_artifact["recovery_execution"] = recovery_exec_artifact
                rec_failed = [
                    s
                    for s in step_states
                    if s["status"] == "failed" and not s.get("recovery")
                ]
                return {
                    "success": len(rec_failed) == 0 and bool(outputs),
                    "output": combined,
                    "error": None
                    if recovery_result.get("success")
                    else recovery_result.get("error"),
                    "_step_states": step_states,
                    "_replan_artifact": replan_artifact,
                    "_run_artifact": _run_artifact,
                }

        return {
            "success": len(failed) == 0 and bool(outputs),
            "output": combined,
            "error": failed[0]["error"] if failed else None,
            "_step_states": step_states,
            "_replan_artifact": replan_artifact,
            "_run_artifact": _run_artifact,
        }

    def _replan_after_failure(
        self,
        failed_state: Dict[str, Any],
        completed_states: List[Dict[str, Any]],
        remaining_steps: List[Dict[str, Any]],
        task_desc: str,
        mgr,
        run_artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Ask planner seat for a recovery plan after a step failure.

        Passes structured run history to planner seat so it can make informed
        recovery decisions. Returns parsed plan_steps (or [] on any failure).
        """
        from concurrent.futures import ThreadPoolExecutor

        try:
            completed_summary = (
                ", ".join(
                    f"step {s['step']} ({s['action']}): {str(s.get('output', ''))[:80]}"
                    for s in completed_states
                )
                or "none"
            )
            remaining_summary = (
                ", ".join(
                    f"step {s['step']} ({s['action']} {s.get('target', '')})"
                    for s in remaining_steps
                )
                or "none"
            )
            replan_task = (
                f"Recovery replan for: {task_desc}\n"
                f"Failed step {failed_state['step']} ({failed_state['action']} "
                f"{failed_state.get('target', '')}):\n"
                f"  error: {failed_state.get('error', 'unknown error')}\n"
                f"  output: {str(failed_state.get('output', ''))[:120]}\n"
                f"Completed: {completed_summary}\n"
                f"Remaining: {remaining_summary}\n"
                "Provide a revised plan to recover and complete the goal."
            )

            def _call():
                return mgr.execute(
                    task=replan_task,
                    context={
                        "intent": "replan",
                        "failed_step": failed_state,
                        "completed": completed_states,
                        "remaining": remaining_steps,
                        "run_artifact": run_artifact,
                        "memory": self.memory,
                    },
                    explicit_role="planner",
                )

            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_call).result(timeout=self._REPLAN_TIMEOUT)

            if not result.success or not result.output:
                return []
            out = result.output
            if isinstance(out, dict) and "plan_steps" in out:
                steps = out["plan_steps"]
                if isinstance(steps, list):
                    return steps
            return []
        except Exception:
            return []

    # ---------- output helpers ----------
    # Keys to strip from output (telemetry / internal)
    _STRIP_KEYS = frozenset(
        {
            "timestamp",
            "last_updated",
            "updated_at",
            "created_at",
            "execution_time",
            "params",
            "tool",
            "exception",
            "start_ts",
            "end_ts",
            "elapsed_seconds",
            "artifact_ids",
            "evidence",
            "session",
        }
    )

    @staticmethod
    def _format_review_targets(
        touched_paths: List[str],
        path_findings: List[Dict[str, Any]],
        label_prefix: str = "",
    ) -> str:
        """Format a prioritized review-target list from touched_paths + path_findings.

        Risk-implicated paths appear first (overlap_risk / gap_risk / broad_spread),
        then remaining touched paths grouped as existing vs missing.
        Returns empty string when no paths are available.
        """
        if not touched_paths and not path_findings:
            return ""

        # Collect risk-specific paths per finding kind
        _RISK_KINDS_WITH_PATHS = ("overlap_risk", "gap_risk", "broad_spread")
        _RISK_LABELS = {
            "overlap_risk": "overlap with failed run",
            "gap_risk": "missed by recovery",
            "broad_spread": "new in recovery",
            "weak_coverage": "recovery skipped failed-run files",
        }
        risk_lines: List[str] = []
        risk_seen: set = set()

        for f in path_findings or []:
            kind = f.get("kind", "")
            if kind not in _RISK_LABELS:
                continue
            f_paths = f.get("paths") or []
            label = _RISK_LABELS.get(kind, kind)
            if kind in _RISK_KINDS_WITH_PATHS and f_paths:
                for p in f_paths:
                    risk_seen.add(p)
                risk_lines.append(f"  [{label}] {', '.join(f_paths[:5])}")
            else:
                # No specific paths (weak_coverage, or finding lacks paths field)
                risk_lines.append(f"  Risks: {label}")

        # Remaining paths not already called out
        other_paths = [p for p in touched_paths if p not in risk_seen]
        resolved_other = AgentLoop._resolve_touched_paths(other_paths) if other_paths else []
        existing_other = [r["path"] for r in resolved_other if r["status"] in ("file", "directory")]
        missing_other = [r["path"] for r in resolved_other if r["status"] == "missing"]

        lines: List[str] = []
        if risk_lines:
            header = f"{label_prefix}Review targets (risk-first):" if label_prefix else "Review targets (risk-first):"
            lines.append(header)
            lines.extend(risk_lines)
        if existing_other:
            lines.append(f"  Other paths (exist): {', '.join(existing_other[:10])}")
        if missing_other:
            lines.append(f"  Other paths (missing): {', '.join(missing_other[:10])}")
        if not lines and touched_paths:
            # No risk findings — just show resolved paths normally
            resolved_all = AgentLoop._resolve_touched_paths(touched_paths)
            existing = [r["path"] for r in resolved_all if r["status"] in ("file", "directory")]
            missing = [r["path"] for r in resolved_all if r["status"] == "missing"]
            prefix = f"{label_prefix}Paths:" if label_prefix else "Paths:"
            if existing:
                lines.append(f"{prefix} {', '.join(existing[:10])}")
            if missing:
                lines.append(f"Missing paths: {', '.join(missing[:10])}")
        return "\n".join(lines)

    @staticmethod
    def _format_linked_run_result(linked: Dict[str, Any]) -> str:
        """Format a linked_run_history dict into a coherent structured explanation.

        Expects linked = {"kind": "linked_run_history", "parent": {...}, "recovery": {...}}.
        Uses available summaries and outcome fields; never dumps raw nested structures.
        """
        parent = linked.get("parent") or {}
        recovery = linked.get("recovery") or {}

        lines: list = []

        # Parent run
        p_task = parent.get("task") or "unknown task"
        p_outcome = parent.get("outcome") or "unknown"
        p_summary = parent.get("summary") or ""
        p_paths = parent.get("touched_paths") or []
        resolved_p = AgentLoop._resolve_touched_paths(p_paths)
        lines.append(f"Failed run: {p_task}")
        lines.append(f"Outcome: {p_outcome}")
        if p_summary and p_summary.strip() != p_task:
            lines.append(f"Details: {p_summary.strip()[:200]}")
        p_findings = parent.get("path_findings") or []
        rt = AgentLoop._format_review_targets(p_paths, p_findings, label_prefix="Failed-run ")
        if rt:
            lines.append(rt)

        lines.append("")

        # Recovery attempt
        r_task = recovery.get("task") or "recovery"
        r_outcome = recovery.get("outcome") or "unknown"
        r_summary = recovery.get("summary") or ""
        r_n_steps = recovery.get("n_steps") or 0
        r_n_failed = recovery.get("n_failed") or 0
        r_paths = recovery.get("touched_paths") or []
        lines.append(f"Recovery attempt: {r_task}")
        lines.append(f"Recovery outcome: {r_outcome}")
        if r_n_steps:
            lines.append(f"Steps attempted: {r_n_steps}")
        if r_summary and r_summary.strip() != r_task:
            lines.append(f"Summary: {r_summary.strip()[:200]}")
        rrt = AgentLoop._format_review_targets(r_paths, [], label_prefix="Recovery ")
        if rrt:
            lines.append(rrt)

        # Remaining issues or success note
        if r_n_failed > 0:
            lines.append(f"Remaining failures: {r_n_failed} step(s) did not complete.")
        elif r_outcome in ("success", "recovered"):
            lines.append("Recovery succeeded.")

        return "\n".join(lines)

    @staticmethod
    def _format_retrieval_results(output: Any) -> Optional[str]:
        """Format a retriever output dict into human-readable text.

        Returns None if `output` is not a retriever result dict (no "results"/"method" keys).
        Handles linked_run_history results with a structured path; falls back to plain
        run_history summary lines for non-linked entries.
        """
        if not isinstance(output, dict):
            return None
        if "results" not in output or "method" not in output:
            return None

        results = output.get("results") or []
        if not results:
            return None

        sections: list = []
        for r in results:
            if not isinstance(r, dict):
                continue
            linked = r.get("linked")
            if isinstance(linked, dict) and linked.get("kind") == "linked_run_history":
                sections.append(AgentLoop._format_linked_run_result(linked))
            else:
                # Plain run_history or other source
                val = r.get("value")
                if isinstance(val, dict):
                    task = val.get("task") or r.get("key") or ""
                    outcome = val.get("outcome") or ""
                    summary = val.get("summary") or ""
                    run_kind = val.get("run_kind", "primary")
                    paths = val.get("touched_paths") or []
                    resolved = AgentLoop._resolve_touched_paths(paths)
                    if task:
                        # Tool runs: compact single-line
                        if run_kind == "tool":
                            entry = [f"[tool] {summary.strip()}" if summary else f"[tool] {task}: {outcome}"]
                            key_err = val.get("key_error", "")
                            if key_err and outcome == "failed":
                                entry.append(f"  error: {key_err[:120]}")
                            sections.append("\n".join(entry))
                            continue
                        # Recovery child: show [recovery] prefix + parent context
                        if run_kind == "recovery":
                            parent_task = val.get("parent_task", "")
                            label = f"[recovery for: {parent_task}]" if parent_task else "[recovery]"
                            s = summary.strip()
                            prefix_cut = f"{task}: {outcome} | "
                            if s.startswith(prefix_cut):
                                s = s[len(prefix_cut):]
                            entry = [f"{label} {task}: {outcome}"]
                            if s and s != task:
                                entry.append(f"  {s[:200]}")
                            sections.append("\n".join(entry))
                            continue
                        header = f"Run: {task}"
                        if outcome:
                            header += f" — {outcome}"
                        entry = [header]
                        if summary:
                            # Strip redundant "task: outcome | " prefix — header already has it
                            s = summary.strip()
                            prefix_cut = f"{task}: {outcome} | "
                            if s.startswith(prefix_cut):
                                s = s[len(prefix_cut):]
                            if s and s != task:
                                entry.append(f"  {s[:200]}")
                        pf = val.get("path_findings") or []
                        rt = AgentLoop._format_review_targets(paths, pf)
                        if rt:
                            for rt_line in rt.splitlines():
                                entry.append(f"  {rt_line}" if not rt_line.startswith("  ") else rt_line)
                        else:
                            if resolved:
                                existing = [
                                    rp["path"]
                                    for rp in resolved
                                    if rp["status"] in ("file", "directory")
                                ]
                                missing = [
                                    rp["path"]
                                    for rp in resolved
                                    if rp["status"] == "missing"
                                ]
                                if existing:
                                    entry.append(
                                        f"  Paths (exist): {', '.join(existing[:10])}"
                                    )
                                if missing:
                                    entry.append(
                                        f"  Paths (missing): {', '.join(missing[:10])}"
                                    )
                        sections.append("\n".join(entry))
                elif val is not None:
                    sections.append(str(val)[:200])

        text = "\n\n".join(s for s in sections if s)
        return text if text else None

    def _try_run_history_response(self, user_input: str) -> Optional[str]:
        """Pre-pass for free-form run-history and recovery-oriented queries.

        Detects whether the query is about recent execution history or a recovery
        attempt, invokes the retriever directly, and formats the result.
        Returns formatted text or None (caller falls through to other paths).
        """
        try:
            from agents.retriever_agent import RetrieverAgent
            from agents.base_agent import AgentContext

            query = (user_input or "").strip()
            if not (
                RetrieverAgent._is_recovery_linked_query(query)
                or RetrieverAgent._is_recent_task_query(query)
                or RetrieverAgent._is_path_query(query)
            ):
                return None

            agent = RetrieverAgent()
            ctx = AgentContext(
                task=query,
                input_data={"query": query},
                memory=self.memory,
            )
            result = agent.run(ctx)
            if not result.success or not result.output:
                return None
            return self._format_retrieval_results(result.output)
        except Exception:
            return None

    # Live-status query triggers — words that signal a "current state" question
    _LIVE_STATUS_TRIGGERS = (
        "what are you doing",
        "what are you working on",
        "what is blocked",
        "what's blocked",
        "whats blocked",
        "what failed",
        "what just failed",
        "what failed most recently",
        "what happens next",
        "what's next",
        "whats next",
        "what are you waiting",
        "what should i inspect",
        "what should i look at next",
        "are you blocked",
        "are you stuck",
        "what is karma doing",
        "what is karma working on",
        "current status",
        "what is your status",
        "what's your status",
        "show status",
        "show me status",
        "agent status",
        "what task",
        "current task",
        "how confident",
        "what is your confidence",
        "what's your confidence",
        "success rate",
        "how healthy",
        "are you healthy",
        "system health",
        "karma health",
        "health check",
    )
    _LIVE_STATUS_ANTITOKENS = (
        "architecture",
        "how does",
        "explain the",
        "history of",
        "what is karma",
    )

    @classmethod
    def _is_live_status_query(cls, query: str) -> bool:
        """Return True when query is asking about current agent state."""
        q = query.lower().strip()
        for anti in cls._LIVE_STATUS_ANTITOKENS:
            if anti in q:
                return False
        for trigger in cls._LIVE_STATUS_TRIGGERS:
            if trigger in q:
                return True
        return False

    def _get_live_status_snapshot(self) -> Dict[str, Any]:
        """Build a compact status snapshot from current_state + memory run:last."""
        snap: Dict[str, Any] = {
            "current_task": self.current_state.get("current_task"),
            "last_run": self.current_state.get("last_run"),
            "confidence": self.current_state.get("confidence", 0.0),
            "last_failure": self.current_state.get("last_failure"),
            "blocked_reason": self.current_state.get("blocked_reason"),
            "decision_summary": self.current_state.get("decision_summary") or {},
            "run_last": None,
        }
        try:
            run_last = self.memory.get_fact_value("run:last")
            if not isinstance(run_last, dict):
                # Fallback: find most recent run:<hash> when run:last is absent/stale
                run_last = self._find_most_recent_run_digest()
            if isinstance(run_last, dict):
                snap["run_last"] = run_last
        except Exception:
            pass
        return snap

    def _find_most_recent_run_digest(self) -> Optional[Dict[str, Any]]:
        """Return the most recent run:<hash> digest from memory, or None."""
        try:
            best_ts = ""
            best_val = None
            for key, outer in self.memory.facts.items():
                if not isinstance(outer, dict) or outer.get("topic") != "run_history":
                    continue
                if key == "run:last":
                    continue
                ts = outer.get("last_updated", "")
                if ts > best_ts:
                    best_ts = ts
                    best_val = outer.get("value", outer)
            return best_val if isinstance(best_val, dict) else None
        except Exception:
            return None

    def _format_live_status(self, snap: Dict[str, Any], query: str) -> Optional[str]:
        """Format a concise answer to a live-status query from a snapshot.

        Routes to sub-format based on query keywords. Returns None when the
        snapshot has no useful state (avoids fake 'currently running' claims).
        """
        q = query.lower()
        current_task = snap.get("current_task")
        blocked = snap.get("blocked_reason")
        last_failure = snap.get("last_failure")
        run_last = snap.get("run_last") or {}
        confidence = snap.get("confidence", 0.0)
        decision_summary = snap.get("decision_summary") or {}

        # --- blocked / stuck ---
        if any(k in q for k in ("blocked", "stuck", "waiting")):
            if blocked:
                return f"Blocked: {blocked}"
            last_fail_intent = (last_failure or {}).get("intent", "")
            if last_fail_intent:
                err = (last_failure or {}).get("error", "")
                return f"Not currently blocked, but last failure was '{last_fail_intent}'" + (
                    f": {err}" if err else ""
                )
            return "Nothing is blocked."

        # --- latest failure ---
        if any(k in q for k in ("failed", "failure", "error")):
            if last_failure and last_failure.get("intent"):
                intent = last_failure["intent"]
                err = last_failure.get("error", "")
                ts = last_failure.get("ts", "")
                line = f"Last failure: '{intent}'"
                if err:
                    line += f" — {err}"
                if ts:
                    line += f" (at {ts[:19]})"
                return line
            # Fall back to run:last
            rl_outcome = run_last.get("outcome", "")
            rl_task = run_last.get("task", "")
            if rl_outcome in ("failed", "recovery_failed") and rl_task:
                return f"Last failure: '{rl_task}' — outcome: {rl_outcome}"
            return "No recent failures recorded."

        # --- inspect next (before 'next' check to avoid swallowing "inspect next") ---
        if "inspect" in q or ("look at" in q and "next" in q):
            pf = run_last.get("path_findings") or []
            tp = run_last.get("touched_paths") or []
            rt = AgentLoop._format_review_targets(tp, pf)
            if rt:
                return rt
            if tp:
                return f"Files from last run: {', '.join(tp[:5])}"
            return "No file targets available."

        # --- next action ---
        if any(k in q for k in ("next", "happens next", "what's next", "whats next")):
            if blocked:
                return f"Blocked ({blocked}) — resolve the failure before proceeding."
            if last_failure and last_failure.get("intent"):
                return f"Suggested: retry or diagnose '{last_failure['intent']}'"
            if current_task:
                return f"Last task was '{current_task}'. Ready for next input."
            return "Ready — no active task."

        # --- health / confidence ---
        if any(k in q for k in ("confident", "confidence", "success rate", "health", "healthy")):
            lines: List[str] = []
            if confidence > 0:
                lines.append(f"Confidence: {confidence:.0%}")
            sr = decision_summary.get("success_rate")
            if sr is not None:
                lines.append(f"Success rate: {sr:.0%}")
            total = decision_summary.get("total_decisions")
            if total:
                lines.append(f"Decisions tracked: {total}")
            if blocked:
                lines.append(f"Blocked: {blocked}")
            if not lines:
                return "No health data recorded yet."
            return "\n".join(lines)

        # --- doing / working on ---
        if not current_task and not run_last:
            return None  # nothing to say — avoid fake claims

        lines: List[str] = []
        if current_task:
            conf_str = f" (confidence {confidence:.0%})" if confidence > 0 else ""
            lines.append(f"Last task: {current_task}{conf_str}")
        elif run_last.get("task"):
            lines.append(f"Last task: {run_last['task']} — {run_last.get('outcome', 'unknown')}")

        if blocked:
            lines.append(f"Blocked: {blocked}")
        elif last_failure and last_failure.get("intent"):
            lines.append(f"Last failure: {last_failure['intent']}")

        last_run_ts = snap.get("last_run") or run_last.get("ts", "")
        if last_run_ts:
            lines.append(f"Last run: {last_run_ts[:19]}")

        return "\n".join(lines) if lines else None

    def _try_live_status_response(self, user_input: str) -> Optional[str]:
        """Pre-pass for live-status / current-state queries."""
        try:
            query = (user_input or "").strip()
            if not AgentLoop._is_live_status_query(query):
                return None
            snap = self._get_live_status_snapshot()
            return self._format_live_status(snap, query)
        except Exception:
            return None

    # ── session/boot summary ──────────────────────────────────────────────────

    _SESSION_SUMMARY_TRIGGERS = (
        "last session",
        "this session",
        "since startup",
        "since boot",
        "since start",
        "what happened this",
        "what did you do",
        "what did karma do",
        "summarize recent work",
        "summarize what",
        "session summary",
        "boot summary",
        "what changed since",
        "what have you done",
        "what tasks",
        "recent work",
    )
    _SESSION_SUMMARY_ANTITOKENS = (
        "last session of",
        "architecture",
        "how does",
        "explain",
        "history of",
    )

    @classmethod
    def _is_session_summary_query(cls, query: str) -> bool:
        q = query.lower().strip()
        for anti in cls._SESSION_SUMMARY_ANTITOKENS:
            if anti in q:
                return False
        for trigger in cls._SESSION_SUMMARY_TRIGGERS:
            if trigger in q:
                return True
        return False

    def _build_session_summary(self) -> Dict[str, Any]:
        """Build a compact summary of the current session from execution_log."""
        session_start = self.current_state.get("session_start_ts", "")
        logs = self.current_state.get("execution_log", [])

        # Filter to current session by timestamp
        if session_start:
            session_logs = [l for l in logs if l.get("timestamp", "") >= session_start]
        else:
            session_logs = logs[-20:]

        if not session_logs:
            # No session activity yet — fall back to run:last from memory
            run_last = None
            try:
                run_last = self.memory.get_fact_value("run:last")
            except Exception:
                pass
            return {
                "empty": True,
                "session_start": session_start,
                "run_last": run_last if isinstance(run_last, dict) else None,
            }

        succeeded = [l for l in session_logs if l.get("success")]
        failed = [l for l in session_logs if not l.get("success")]
        intents = [
            l.get("intent", {}).get("intent", "")
            for l in session_logs
            if isinstance(l.get("intent"), dict)
        ]
        success_intents = list(dict.fromkeys(
            l.get("intent", {}).get("intent", "") for l in succeeded
            if isinstance(l.get("intent"), dict)
        ))
        # Deduplicate by intent, keeping last occurrence per intent
        _seen_fail: Dict[str, Dict[str, str]] = {}
        for l in failed:
            _intent = l.get("intent", {}).get("intent", "") if isinstance(l.get("intent"), dict) else ""
            _seen_fail[_intent] = {
                "intent": _intent,
                "error": (l.get("execution_result") or {}).get("error") or "",
            }
        fail_entries = list(_seen_fail.values())[-3:]

        return {
            "empty": False,
            "session_start": session_start,
            "total": len(session_logs),
            "n_succeeded": len(succeeded),
            "n_failed": len(failed),
            "success_intents": success_intents[:6],
            "fail_entries": fail_entries,
            "last_intent": intents[-1] if intents else None,
            "blocked_reason": self.current_state.get("blocked_reason"),
            "run_last": None,
        }

    def _format_session_summary(self, summary: Dict[str, Any]) -> Optional[str]:
        """Format session summary dict into compact human-readable text."""
        if summary.get("empty"):
            run_last = summary.get("run_last") or {}
            if run_last.get("task"):
                return (
                    f"No tasks this session yet. "
                    f"Last known run: '{run_last['task']}' — {run_last.get('outcome', 'unknown')}"
                )
            return "No tasks this session yet."

        total = summary["total"]
        n_ok = summary["n_succeeded"]
        n_fail = summary["n_failed"]
        session_start = (summary.get("session_start") or "")[:19]

        header = f"Session ({session_start}): {total} task(s) — {n_ok} ok, {n_fail} failed"
        lines = [header]

        if summary["success_intents"]:
            lines.append(f"Done: {', '.join(summary['success_intents'])}")
        if summary["fail_entries"]:
            for fe in summary["fail_entries"]:
                intent = fe.get("intent", "?")
                err = fe.get("error", "")
                lines.append(f"Failed: {intent}" + (f" — {err}" if err else ""))
        if summary.get("blocked_reason"):
            lines.append(f"Blocked: {summary['blocked_reason']}")
        last = summary.get("last_intent")
        success_intents = summary.get("success_intents") or []
        if last and last != (success_intents[-1] if success_intents else None):
            lines.append(f"Last: {last}")

        return "\n".join(lines)

    def _try_session_summary_response(self, user_input: str) -> Optional[str]:
        """Pre-pass for session/boot-summary queries."""
        try:
            query = (user_input or "").strip()
            if not AgentLoop._is_session_summary_query(query):
                return None
            summary = self._build_session_summary()
            return self._format_session_summary(summary)
        except Exception:
            return None

    # ── self-check / diagnose ─────────────────────────────────────────────────

    _SELF_CHECK_TRIGGERS = (
        "run a quick self-check",
        "run self check",
        "self-check",
        "self check",
        "diagnose yourself",
        "diagnose karma",
        "run diagnostics",
        "quick diagnostics",
        "check yourself",
        "run a check",
    )

    @classmethod
    def _is_self_check_query(cls, query: str) -> bool:
        q = query.lower().strip()
        for trigger in cls._SELF_CHECK_TRIGGERS:
            if trigger in q:
                return True
        return False

    def _try_self_check_response(self, user_input: str) -> Optional[str]:
        """Run health.run_check() and format results compactly."""
        try:
            query = (user_input or "").strip()
            if not AgentLoop._is_self_check_query(query):
                return None
            report = self.health.run_check()
            status = report.get("status", "unknown")
            n_issues = report.get("issues_found", 0)
            issues = report.get("issues") or []

            if n_issues == 0:
                return f"Self-check: {status} (no issues found)"

            lines = [f"Self-check: {status} ({n_issues} issue(s))"]
            for issue in issues[:5]:
                sev = issue.get("severity", "info")
                subsystem = issue.get("subsystem", "")
                text = issue.get("issue", "")[:80]
                prefix = f"  [{sev}]" + (f" {subsystem}:" if subsystem else "")
                lines.append(f"{prefix} {text}")
                suggestion = issue.get("suggestion", "")
                if suggestion:
                    lines.append(f"    → {suggestion[:80]}")
            return "\n".join(lines)
        except Exception:
            return None

    @staticmethod
    def _result_to_text(execution_result: Dict[str, Any]) -> str:
        """Convert an execution result to a clean human-readable string."""
        if not execution_result:
            return "No result."

        err = execution_result.get("error")
        if err:
            return f"Error: {err}"

        out = execution_result.get("output")
        if out is None:
            return "Done." if execution_result.get("success") else "No output."

        if isinstance(out, str):
            return out

        # Retriever output — format structured results (linked recovery, run_history)
        retrieval_text = AgentLoop._format_retrieval_results(out)
        if retrieval_text is not None:
            return retrieval_text

        # GoLearn result — use the summary directly
        if (
            isinstance(out, dict)
            and "summary" in out
            and isinstance(out["summary"], str)
        ):
            return out["summary"]

        # Tool result with 'result' key
        if isinstance(out, dict) and "result" in out:
            inner = out["result"]
            if isinstance(inner, str):
                return inner
            if isinstance(inner, (dict, list)):
                out = inner

        # Capabilities listing
        if isinstance(out, dict) and "tools" in out and "memory_stats" in out:
            return AgentLoop._format_capabilities(out)

        if isinstance(out, dict) and "entries" in out and "path" in out:
            entries = out.get("entries", [])
            shown = entries[:20]
            text = [f"path: {out.get('path')}", "entries:"]
            text.extend(f"  {name}" for name in shown)
            if len(entries) > 20:
                text.append(f"  ... and {len(entries) - 20} more")
            return "\n".join(text)

        if isinstance(out, dict) and "matches" in out and "pattern" in out:
            matches = out.get("matches", [])
            shown = matches[:20]
            text = [
                f"path: {out.get('path')}",
                f"pattern: {out.get('pattern')}",
                "matches:",
            ]
            text.extend(f"  {name}" for name in shown)
            if len(matches) > 20:
                text.append(f"  ... and {len(matches) - 20} more")
            if not matches:
                text.append("  No matches found.")
            return "\n".join(text)

        if isinstance(out, dict):
            return AgentLoop._dict_to_text(out)
        if isinstance(out, list):
            items = []
            for item in out[:20]:
                items.append(
                    AgentLoop._dict_to_text(item)
                    if isinstance(item, dict)
                    else str(item)
                )
            text = "\n".join(items)
            if len(out) > 20:
                text += f"\n... and {len(out) - 20} more"
            return text

        return str(out)

    @staticmethod
    def _format_capabilities(out: Dict[str, Any]) -> str:
        tools = out.get("tools", [])
        stats = out.get("memory_stats", {})
        lines = ["Here's what I can work with:"]
        if tools:
            lines.append(f"  Tools: {', '.join(str(t) for t in tools)}")
        facts = stats.get("facts_count", 0)
        episodes = stats.get("episodic_count", 0)
        lines.append(f"  Memory: {facts} facts, {episodes} episodes")
        return "\n".join(lines)

    @staticmethod
    def _dict_to_text(d: Dict[str, Any], indent: int = 0) -> str:
        """Recursively render a dict as concise readable lines."""
        lines: list = []
        prefix = "  " * indent
        for k, v in d.items():
            if k in AgentLoop._STRIP_KEYS:
                continue
            label = k.replace("_", " ")
            if isinstance(v, dict):
                lines.append(f"{prefix}{label}:")
                lines.append(AgentLoop._dict_to_text(v, indent + 1))
            elif isinstance(v, list):
                if not v:
                    continue
                if isinstance(v[0], dict):
                    lines.append(f"{prefix}{label}:")
                    for item in v[:10]:
                        lines.append(AgentLoop._dict_to_text(item, indent + 1))
                    if len(v) > 10:
                        lines.append(f"{prefix}  ... and {len(v) - 10} more")
                else:
                    shown = v[:15]
                    tail = f" ... +{len(v) - 15} more" if len(v) > 15 else ""
                    lines.append(
                        f"{prefix}{label}: {', '.join(str(x) for x in shown)}{tail}"
                    )
            else:
                lines.append(f"{prefix}{label}: {v}")
        return "\n".join(lines)

    # ---------- run ----------
    def run(self, user_input) -> str:
        with self._run_lock:
            if user_input:
                parts = self._split_chain(user_input)
                if len(parts) > 1:
                    self.logger.info(f"Chained input: {len(parts)} parts")
                    results = []
                    for part in parts:
                        r = self._run_single(part)
                        results.append(r)
                    return "\n".join(results)

            return self._run_single(user_input)

    def _run_single(self, user_input) -> str:
        self.bus.emit("loop_start", text=user_input)
        self.running = True
        reflection: Optional[Dict[str, Any]] = None
        self._current_lane = RoutingLane.CHAT  # Reset lane

        try:
            observation = self._observe_environment()
            observation["user_input"] = user_input

            intent = None
            normalized = ""
            dialogue_act = "statement"

            if user_input:
                self.logger.info(f"User input: {user_input}")
                normalized = self.normalizer.normalize_for_match(user_input)
                self.logger.debug(f"Normalized: {normalized}")
                dialogue_dict = classify_dialogue_act(user_input)
                dialogue_act = dialogue_dict.get("act", "statement")

                # "again" / "repeat" → replay last intent
                if self._AGAIN.search(normalized) and self._last_intent:
                    self.logger.info("Replaying last intent")
                    intent = self._last_intent
                else:
                    # Corrections/continuations/clarifications with unresolvable refs
                    # should go to dialogue handler, not the intent pipeline
                    act = dialogue_act
                    if (
                        act
                        in (
                            "correction",
                            "clarification_answer",
                            "continuation",
                            "summary_request",
                            "introspection",
                        )
                        and dialogue_dict.get("route") != "act_and_report"
                    ):
                        pass  # skip intent parsing + pronoun resolution — dialogue handler resolves references itself
                    else:
                        # Resolve pronouns ("read it", "that file") before intent parsing
                        user_input, normalized = self._resolve_references(
                            user_input, normalized
                        )
                        intent = self._parse_intent(user_input, normalized)
            else:
                self.logger.info("No user input provided")

            # Determine routing lane BEFORE any execution
            # This is critical: safe mode forces chat, otherwise determine based on input
            self._current_lane = self._determine_lane(user_input, intent, dialogue_act)
            self.logger.info(f"Routing lane: {self._current_lane}")

            # SAFE MODE: Force chat lane - skip tool execution for free-form input
            if self._safe_mode and self._current_lane == RoutingLane.CHAT:
                self.logger.info("Safe mode: forcing chat lane")

            if intent:
                self.bus.emit("intent_parsed", intent=intent)

            # Confidence economy gate (#1) — if intent confidence too low, try alternate
            if intent and float(intent.get("confidence", 1.0)) < self._conf_threshold:
                self.bus.emit("low_confidence", intent=intent)
                if self._conf_low_action == "clarify":
                    self.running = False
                    return f"I'm not sure what you mean. Did you want to: {intent.get('intent', '?')}? (confidence: {intent.get('confidence', 0):.0%})"
                elif self._conf_low_action == "golearn":
                    topic = intent.get("entities", {}).get("topic", user_input)
                    return self._run_single(f'golearn "{topic}" 2')

            if user_input and not intent:
                # SAFE MODE: Skip command signal scoring - go directly to chat
                if self._safe_mode:
                    # In safe mode, skip command parsing entirely for questions/statements
                    pass
                elif dialogue_act == "question":
                    cmd_score = command_signal_score(user_input)
                    # Scar bias: lower threshold if question-shaped commands were previously swallowed
                    threshold = 0.32
                    if (
                        self.conversation.scar_severity("question_command_swallow")
                        > 0.0
                    ):
                        threshold = max(
                            0.2,
                            threshold
                            - self.conversation.scar_severity(
                                "question_command_swallow"
                            )
                            * 0.1,
                        )
                    if cmd_score >= threshold:
                        tentative = self._parse_intent(user_input, normalized)
                        if tentative:
                            intent = tentative

            # SAFE MODE: If still no intent (question/statement), force chat
            if self._safe_mode and not intent:
                self.logger.info("Safe mode: no intent parsed, forcing chat")
                response = self.responder.respond(user_input, self.memory)
                if response.startswith(
                    ("I don't understand", "Not sure what you mean")
                ):
                    # Self-check pre-pass
                    sc_response = self._try_self_check_response(user_input)
                    if sc_response:
                        response = sc_response
                    else:
                        # Session-summary pre-pass
                        ss_response = self._try_session_summary_response(user_input)
                        if ss_response:
                            response = ss_response
                        else:
                            # Live-status pre-pass
                            ls_response = self._try_live_status_response(user_input)
                            if ls_response:
                                response = ls_response
                            else:
                                # Run-history pre-pass
                                rh_response = self._try_run_history_response(user_input)
                                if rh_response:
                                    response = rh_response
                                else:
                                    seat_response = self._try_seat_response(user_input)
                                    if seat_response:
                                        response = seat_response
                self._record_dialogue(user_input, response, dialogue_act, None)
                self.bus.emit("responded", text=response)
                self.running = False
                return response

            if user_input and not intent:
                handled = self._handle_dialogue_turn(
                    user_input, {"act": dialogue_act, "route": "respond_only"}
                )
                if handled is not None:
                    self.bus.emit("responded", text=handled)
                    self.logger.info(f"Dialogue response: {handled[:80]}")
                    self.running = False
                    return handled
                # Conversation fallback — respond using responder (original text)
                # Track scar if a question-shaped command was swallowed by dialogue routing
                if (
                    dialogue_act == "question"
                    and command_signal_score(user_input) >= 0.2
                ):
                    self.conversation.add_scar(
                        "question_command_swallow",
                        reason=user_input[:80],
                        severity=0.05,
                    )
                response = self.responder.respond(user_input, self.memory)
                # If responder couldn't answer, try full pre-pass pipeline
                if response.startswith(
                    ("I don't understand", "Not sure what you mean")
                ):
                    sc_response = self._try_self_check_response(user_input)
                    if sc_response:
                        response = sc_response
                    else:
                        ss_response = self._try_session_summary_response(user_input)
                        if ss_response:
                            response = ss_response
                        else:
                            ls_response = self._try_live_status_response(user_input)
                            if ls_response:
                                response = ls_response
                            else:
                                rh_response = self._try_run_history_response(user_input)
                                if rh_response:
                                    response = rh_response
                                else:
                                    seat_response = self._try_seat_response(user_input)
                                    if seat_response:
                                        response = seat_response
                self._record_dialogue(user_input, response, dialogue_act, None)
                self.bus.emit("responded", text=response)
                self.logger.info(f"Conversation response: {response[:80]}")
                self.running = False
                return response

            # Retrieve evidence early so planner can use it for candidate generation
            _pre_evidence = []
            if intent:
                intent_name = intent.get("intent", "")
                entities = intent.get("entities", {}) or {}
                _pre_evidence = self.retrieval.retrieve_context_bundle(
                    intent_name,
                    "plan",
                    intent=intent_name,
                    entities=entities,
                )
            candidates = (
                self._generate_candidates(intent, _pre_evidence) if intent else []
            )
            scored = (
                self._score_candidates(intent, candidates)
                if intent and candidates
                else []
            )
            self.bus.emit("scored", count=len(scored))
            selected_action = self._select_action(scored) if scored else None
            # Use safe execution with context manager for _current_user_input cleanup
            if selected_action:
                with UserInputContext(self, user_input):
                    execution_result = self._execute_action(selected_action)
            else:
                execution_result = {"success": False, "error": "No action selected"}
            self.bus.emit("executed", result=execution_result)
            if intent:
                self._register_result_artifacts(execution_result, intent)
            if selected_action:
                self._post_execute(selected_action, execution_result)

            if intent:
                reflection = self._reflect(intent, selected_action, execution_result)
                self.bus.emit("reflected", reflection=reflection)
                self._update_state(reflection)
            else:
                # Always update timestamp even for conversation fallback
                self.current_state["last_run"] = datetime.now().isoformat()

            if reflection:
                self.logger.info(
                    f"Loop completed. Success: {reflection.get('success')}, Confidence: {reflection.get('confidence', 0.0):.2f}"
                )

            # Maintenance tick — meta, pressure, compression, health, crystallize
            self._maintenance.tick(self.current_state.get("execution_log", []))

            # Sync code context to conversation state for follow-up resolution
            if self._last_code_context:
                self.conversation.last_code_context = self._last_code_context

            # Save context for pronoun resolution + collect ML training data
            if intent:
                self._last_intent = intent
                self._last_entities = intent.get("entities", {})
                self._record_command(
                    user_input or "", intent, execution_result.get("success", False)
                )
                if execution_result.get("success") and user_input:
                    self.ml_manager.collect_training_example(
                        user_input, intent.get("intent", "")
                    )
            # Critic pass — automatic review for heavy intents on success
            _intent_name_for_critic = intent.get("intent", "") if intent else ""
            _critique = self._seat_critique(execution_result, _intent_name_for_critic)
            if _critique:
                self.logger.info(f"Critic: {_critique[:120]}")
                self.bus.emit(
                    "critic_flagged", critique=_critique, intent=_intent_name_for_critic
                )

            result_text = self._result_to_text(execution_result)
            result_text = self._seat_summarize(result_text)
            if _critique:
                result_text = result_text + "\n\n[Review] " + _critique

            # Run artifact persistence: multi-step planned runs + single-tool runs
            _run_artifact = execution_result.get("_run_artifact")
            if _run_artifact and len(_run_artifact.get("steps", [])) > 0:
                run_summary = self._seat_summarize_run(_run_artifact)
                self._persist_run_digest(_run_artifact, run_summary)
            elif (
                intent
                and selected_action
                and not execution_result.get("_run_artifact")
                and AgentLoop._should_digest_single_tool(selected_action)
            ):
                _st_artifact = AgentLoop._build_single_tool_artifact(
                    intent, selected_action, execution_result, user_input or ""
                )
                self._persist_run_digest(_st_artifact, "")
            if user_input and intent:
                route = "act_and_report" if selected_action else "retrieve_and_respond"
                self._record_dialogue(
                    user_input,
                    result_text,
                    route,
                    intent,
                    response_goal=choose_response_goal(user_input, act=dialogue_act),
                )

            # Increment revision on successful execution
            if execution_result.get("success"):
                self.increment_revision("execution")
            self._last_result = result_text

            return str(result_text) if result_text else "Done."

        except Exception as e:
            self.logger.error(f"Agent loop failed: {e}")
            return f"Error: {e}"
        finally:
            self._save_state()
            self.running = False

    def stop(self):
        self.running = False
        if hasattr(self, "_observer"):
            self._observer.stop()
        self._save_state()
        self.logger.info("Karma stopped")


def load_config(path: str = "config.json") -> Dict[str, Any]:
    from agent.bootstrap import load_config as _bootstrap_load

    return _bootstrap_load(path)


if __name__ == "__main__":
    from agent.bootstrap import load_config as _bl, build_agent, get_version

    config = _bl()
    agent = build_agent(config)

    # Readline support for arrow-key history
    try:
        import readline

        _history_file = str(agent.base_dir / "data" / "cli_history")
        try:
            readline.read_history_file(_history_file)
        except FileNotFoundError:
            pass
        readline.set_history_length(500)
    except ImportError:
        _history_file = None

    v = config.get("system", {}).get("version", "?")
    facts_count = len(agent.memory.facts)
    print(f"Karma v{v} — Local Agent ({facts_count} facts loaded)")
    print("Type 'help' for commands, 'exit' to quit")
    print("=" * 40)

    while True:
        try:
            user_input = input("\n> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Later.")
                break
            result = agent.run(user_input)
            if isinstance(result, str) and result:
                print(result)
        except (KeyboardInterrupt, EOFError):
            print("\nLater.")
            break
        finally:
            if _history_file:
                try:
                    readline.write_history_file(_history_file)
                except Exception:
                    pass
