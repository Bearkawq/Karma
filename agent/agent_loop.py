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
import sys
import random
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.events import EventBus
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

        # Collect startup warnings before any load so _load_state and memory init can append
        self._startup_warnings: list = []

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
        if self.memory.facts_quarantined:
            self._startup_warnings.append(
                "Facts file was corrupted and quarantined at startup — memory is empty. All stored facts lost."
            )
        if self.memory.tasks_quarantined:
            self._startup_warnings.append(
                "Tasks file was corrupted and quarantined at startup — all pending tasks lost."
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

        # Inject startup warnings so boot doctor can surface them (stripped before save)
        if self._startup_warnings:
            self.current_state["_startup_warnings"] = list(self._startup_warnings)

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

        # Extracted services — delegate run-history, status-query, plan-execution
        from agent.services.run_history_service import RunHistoryService
        from agent.services.status_query_service import StatusQueryService
        from agent.services.plan_execution_service import PlanExecutionService
        self._run_history_svc = RunHistoryService(self.memory)
        self._status_query_svc = StatusQueryService(
            self.current_state, self.memory, self.health,
            tool_builder=self.tool_builder,
            run_history_svc=self._run_history_svc,
        )
        self._plan_exec_svc = PlanExecutionService(self.memory, self.logger)

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
                self._startup_warnings.append(
                    "Agent state file was corrupted and quarantined at startup — prior task history lost."
                )
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
            # Strip ephemeral keys — session-only, not persisted to disk
            _EPHEMERAL = frozenset({"_startup_warnings", "_state_save_failed"})
            state_to_save = {k: v for k, v in self.current_state.items() if k not in _EPHEMERAL}
            self._atomic_write_json(state_file, state_to_save)
            self.logger.info(f"Saved state to {state_file}")
            self.current_state.pop("_state_save_failed", None)
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
            self.current_state["_state_save_failed"] = str(e)[:120]

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
            # Multi-step path: pass full structured artifact to critic
            if not _run_artifact.get("steps"):
                return None
            content = _run_artifact  # full dict — critic formats for model, reads directly for deterministic
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
                    "content": content,  # dict for run_artifact, string for legacy result
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

    def _critique_single_tool_failure(
        self,
        execution_result: Dict[str, Any],
        selected_action: Optional[Dict[str, Any]],
        intent: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Deterministic critique for failed single-tool runs.

        Fires only when:
        - execution failed (success=False)
        - no _run_artifact (single-tool path, not a plan)
        - action is not in skip list and not seat-generated
        - an error string is present

        Returns a compact bullet critique string or None.
        """
        if execution_result.get("success"):
            return None
        if execution_result.get("_run_artifact"):
            return None
        if not selected_action:
            return None
        name = selected_action.get("name") or ""
        if name in self._DIGEST_SKIP_NAMES:
            return None
        if selected_action.get("_seat_generated"):
            return None
        error = (execution_result.get("error") or "")
        if not error or not error.strip():
            return None
        from agents.critic_agent import CriticAgent as _CA
        tool = selected_action.get("tool") or name
        return _CA._critique_tool_failure(tool, error)

    # Patterns for queries that must NOT be routed to the seat model.
    # These are conversational / identity queries; the responder base templates
    # should handle them, and if they somehow slipped through, a model will only
    # return context-contaminated or hallucinated output.
    _SEAT_CONV_SKIP = re.compile(
        r"^(are|is|do|does|can|could|would|will|have|has)\s+you\b"
        r"|^(tell\s+me\s+more|go\s+on|continue|proceed|elaborate|expand)\b"
        r"|^(interesting|cool|nice|makes\s+sense|understood|i\s+see|got\s+it)\b"
        r"|^(what\s+are\s+you|who\s+are\s+you|what\s+is\s+karma)\b",
        re.IGNORECASE,
    )

    def _try_seat_response(self, user_input: str) -> Optional[str]:
        """Try seat pipeline for free-form queries not handled by responder.

        Returns model-generated answer string or None (caller falls back).
        Bounded timeout prevents chat path from hanging on a slow seat model.

        Conversational / identity queries are blocked from the seat — the model
        has no reliable identity context and would return garbage or hallucinations.
        """
        _SEAT_RESPONSE_TIMEOUT = 15  # seconds — chat fallback must be fast

        # Block conversational queries — seat model won't answer these better
        # than the responder's base templates, and risks returning retrieved garbage.
        if user_input and self._SEAT_CONV_SKIP.match(user_input.strip()):
            self.logger.debug("Seat skipped: conversational query — %s", user_input[:60])
            return None

        # Very short inputs (≤ 2 words) with no knowledge-question word also skip the seat.
        _KW = {"what", "why", "how", "when", "where", "who", "which"}
        words = set((user_input or "").strip().lower().split())
        if len(words) <= 2 and not (words & _KW):
            self.logger.debug("Seat skipped: too short — %s", user_input[:60])
            return None

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
        from agent.services.run_history_service import format_run_artifact_content
        return format_run_artifact_content(run_artifact)

    @staticmethod
    def _build_compact_digest_summary(run_artifact: Dict[str, Any]) -> str:
        from agent.services.run_history_service import build_compact_digest_summary
        return build_compact_digest_summary(run_artifact)

    @staticmethod
    def _extract_touched_paths(run_artifact: Dict[str, Any]) -> List[str]:
        from agent.services.run_history_service import extract_touched_paths
        return extract_touched_paths(run_artifact)

    @staticmethod
    def _resolve_touched_paths(
        paths: List[str],
        base_dir: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from agent.services.run_history_service import resolve_touched_paths
        return resolve_touched_paths(paths, base_dir)

    def _seat_summarize_run(self, run_artifact: Dict[str, Any]) -> str:
        return self._run_history_svc.seat_summarize_run(run_artifact)

    # Actions that generate no operator-useful digest (housekeeping / meta / conversation)
    _DIGEST_SKIP_NAMES = frozenset({
        "help", "status_query", "list_capabilities", "repair_report",
        "teach_response", "forget_response", "list_custom_tools",
    })

    @staticmethod
    def _should_digest_single_tool(selected_action: Dict[str, Any]) -> bool:
        from agent.services.run_history_service import should_digest_single_tool
        return should_digest_single_tool(selected_action)

    @staticmethod
    def _extract_tool_output(raw_output, max_len: int = 200) -> str:
        from agent.services.run_history_service import extract_tool_output
        return extract_tool_output(raw_output, max_len)

    @staticmethod
    def _build_single_tool_artifact(
        intent: Dict[str, Any],
        selected_action: Dict[str, Any],
        execution_result: Dict[str, Any],
        user_input: str = "",
    ) -> Dict[str, Any]:
        from agent.services.run_history_service import build_single_tool_artifact
        return build_single_tool_artifact(intent, selected_action, execution_result, user_input)

    def _persist_run_digest(self, run_artifact: Dict[str, Any], summary: str) -> None:
        self._run_history_svc.persist_run_digest(run_artifact, summary)

    # ---------- operator-facing summary / doctor API ----------

    def build_operator_summary(self) -> Dict[str, Any]:
        """Return unified operator payload (task, last run, failure, health, session)."""
        self._status_query_svc._health = self.health
        return self._status_query_svc.build_operator_summary()

    def format_operator_summary(self) -> str:
        """Return operator summary as compact multi-line text."""
        self._status_query_svc._health = self.health
        summary = self._status_query_svc.build_operator_summary()
        return self._status_query_svc.format_operator_summary(summary)

    def build_boot_doctor_summary(self) -> Dict[str, Any]:
        """Return boot-time health + last-run-state payload."""
        self._status_query_svc._health = self.health
        return self._status_query_svc.build_boot_doctor_summary()

    def format_boot_doctor_summary(self) -> str:
        """Return boot doctor as compact multi-line text."""
        self._status_query_svc._health = self.health
        summary = self._status_query_svc.build_boot_doctor_summary()
        return self._status_query_svc.format_boot_doctor_summary(summary)

    def get_run_detail(self, run_key: str = "run:last") -> Optional[Dict[str, Any]]:
        """Return enriched run detail for a given run key (default: last run)."""
        from agent.services.run_history_service import build_run_detail
        return build_run_detail(run_key, self.memory)

    def _execute_plan_steps(
        self,
        steps: List[Dict[str, Any]],
        task_desc: str,
        allow_replan: bool = True,
        seed_prior: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return self._plan_exec_svc.execute_plan_steps(steps, task_desc, allow_replan, seed_prior)

    def _replan_after_failure(
        self,
        failed_state: Dict[str, Any],
        completed_states: List[Dict[str, Any]],
        remaining_steps: List[Dict[str, Any]],
        task_desc: str,
        mgr,
        run_artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return self._plan_exec_svc.replan_after_failure(
            failed_state, completed_states, remaining_steps, task_desc, mgr, run_artifact
        )

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
    @staticmethod
    def _format_review_targets(
        touched_paths: List[str],
        path_findings: List[Dict[str, Any]],
        label_prefix: str = "",
    ) -> str:
        from agent.services.run_history_service import format_review_targets
        return format_review_targets(touched_paths, path_findings, label_prefix)

    @staticmethod
    def _format_linked_run_result(linked: Dict[str, Any]) -> str:
        from agent.services.run_history_service import format_linked_run_result
        return format_linked_run_result(linked)

    @staticmethod
    def _format_retrieval_results(output: Any) -> Optional[str]:
        from agent.services.run_history_service import format_retrieval_results
        return format_retrieval_results(output)

    def _try_run_history_response(self, user_input: str) -> Optional[str]:
        return self._status_query_svc.try_run_history_response(user_input)

    # -- live status ----------------------------------------------------------

    # Class-level constants kept for test compatibility (delegate to service module)
    from agent.services.status_query_service import (
        LIVE_STATUS_TRIGGERS as _LIVE_STATUS_TRIGGERS,
        LIVE_STATUS_ANTITOKENS as _LIVE_STATUS_ANTITOKENS,
        SESSION_SUMMARY_TRIGGERS as _SESSION_SUMMARY_TRIGGERS,
        SESSION_SUMMARY_ANTITOKENS as _SESSION_SUMMARY_ANTITOKENS,
        SELF_CHECK_TRIGGERS as _SELF_CHECK_TRIGGERS,
    )

    @classmethod
    def _is_live_status_query(cls, query: str) -> bool:
        from agent.services.status_query_service import is_live_status_query
        return is_live_status_query(query)

    def _get_live_status_snapshot(self) -> Dict[str, Any]:
        return self._status_query_svc.get_live_status_snapshot()

    def _find_most_recent_run_digest(self) -> Optional[Dict[str, Any]]:
        return self._status_query_svc.find_most_recent_run_digest()

    def _format_live_status(self, snap: Dict[str, Any], query: str) -> Optional[str]:
        return self._status_query_svc.format_live_status(snap, query)

    def _try_live_status_response(self, user_input: str) -> Optional[str]:
        return self._status_query_svc.try_live_status_response(user_input)

    # -- session summary ------------------------------------------------------

    @classmethod
    def _is_session_summary_query(cls, query: str) -> bool:
        from agent.services.status_query_service import is_session_summary_query
        return is_session_summary_query(query)

    def _build_session_summary(self) -> Dict[str, Any]:
        return self._status_query_svc.build_session_summary()

    def _format_session_summary(self, summary: Dict[str, Any]) -> Optional[str]:
        return self._status_query_svc.format_session_summary(summary)

    def _try_session_summary_response(self, user_input: str) -> Optional[str]:
        return self._status_query_svc.try_session_summary_response(user_input)

    # -- self-check -----------------------------------------------------------

    @classmethod
    def _is_self_check_query(cls, query: str) -> bool:
        from agent.services.status_query_service import is_self_check_query
        return is_self_check_query(query)

    def _try_self_check_response(self, user_input: str) -> Optional[str]:
        return self._status_query_svc.try_self_check_response(user_input, health=self.health)

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
            # Deterministic critique for failed single-tool runs (no model, zero latency)
            if not _critique:
                _critique = self._critique_single_tool_failure(
                    execution_result, selected_action, intent
                )
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
                if _critique:
                    _run_artifact["critic"] = _critique
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
                if _critique:
                    _st_artifact["critic"] = _critique
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
    import sys as _sys

    from agent.bootstrap import load_config as _bl, build_agent, get_version

    # --doctor: run health check and exit (0=healthy, 1=warning/issues)
    if "--doctor" in _sys.argv:
        config = _bl()
        agent = build_agent(config)
        summary = agent.build_boot_doctor_summary()
        print(agent.format_boot_doctor_summary())
        _sys.exit(0 if summary.get("status") == "healthy" else 1)

    # --models / --model-status: report models, slots, assignments
    if "--models" in _sys.argv or "--model-status" in _sys.argv:
        config = _bl()
        agent = build_agent(config)
        from core.agent_model_manager import get_agent_model_manager
        from core.slot_manager import get_slot_manager
        from agent.services.model_operator_service import build_model_status_text

        mgr = get_agent_model_manager()
        slot_mgr = get_slot_manager(str(agent.base_dir / "data" / "slot_assignments.json"))
        print(build_model_status_text(mgr, slot_mgr))
        _sys.exit(0)

    # --ready / --bootstrap-check: read-only local model readiness verdict
    if "--ready" in _sys.argv or "--bootstrap-check" in _sys.argv:
        config = _bl()
        agent = build_agent(config)
        from core.agent_model_manager import get_agent_model_manager
        from core.slot_manager import get_slot_manager
        from agent.services.model_operator_service import build_readiness_text

        mgr = get_agent_model_manager()
        slot_mgr = get_slot_manager(str(agent.base_dir / "data" / "slot_assignments.json"))
        ready, text = build_readiness_text(mgr, slot_mgr)
        print(text)
        _sys.exit(0 if ready else 1)

    # --assign-role ROLE MODEL_ID
    if "--assign-role" in _sys.argv:
        idx = _sys.argv.index("--assign-role")
        try:
            role = _sys.argv[idx + 1]
            model_id = _sys.argv[idx + 2]
        except Exception:
            print("Usage: --assign-role <role> <model_id> [--deterministic]")
            _sys.exit(2)
        config = _bl()
        agent = build_agent(config)
        from core.agent_model_manager import get_agent_model_manager
        from core.slot_manager import get_slot_manager
        from agent.services.model_operator_service import assign_model_to_role

        mgr = get_agent_model_manager()
        slot_mgr = get_slot_manager(str(agent.base_dir / "data" / "slot_assignments.json"))
        ok, msg = assign_model_to_role(
            mgr,
            slot_mgr,
            role,
            model_id,
            deterministic="--deterministic" in _sys.argv,
        )
        print(msg)
        _sys.exit(0 if ok else 2)

    # --assign-slot SLOT MODEL_ID
    if "--assign-slot" in _sys.argv:
        idx = _sys.argv.index("--assign-slot")
        try:
            slot = _sys.argv[idx + 1]
            model_id = _sys.argv[idx + 2]
        except Exception:
            print("Usage: --assign-slot <slot> <model_id> [--deterministic]")
            _sys.exit(2)
        config = _bl()
        agent = build_agent(config)
        from core.agent_model_manager import get_agent_model_manager
        from core.slot_manager import get_slot_manager
        from agent.services.model_operator_service import assign_model_to_slot

        mgr = get_agent_model_manager()
        slot_mgr = get_slot_manager(str(agent.base_dir / "data" / "slot_assignments.json"))
        ok, msg = assign_model_to_slot(
            mgr,
            slot_mgr,
            slot,
            model_id,
            deterministic="--deterministic" in _sys.argv,
        )
        print(msg)
        _sys.exit(0 if ok else 2)

    # --bootstrap-layout / --bootstrap-models: assign recommended small-model layout
    if "--bootstrap-layout" in _sys.argv or "--bootstrap-models" in _sys.argv:
        config = _bl()
        agent = build_agent(config)
        from core.agent_model_manager import get_agent_model_manager
        from core.slot_manager import get_slot_manager
        from agent.services.model_operator_service import bootstrap_layout

        mgr = get_agent_model_manager()
        slot_mgr = get_slot_manager(str(agent.base_dir / "data" / "slot_assignments.json"))
        report = bootstrap_layout(mgr, slot_mgr)
        print("Bootstrap layout report:")
        for a in report.get("assigned", []):
            print(
                f"  Assigned {a['model']} -> role {a['role']} "
                f"(slot {a['slot']}, ollama {a['ollama_model']})"
            )
        for s in report.get("skipped", []):
            print(f"  Skipped role {s['role']} ({s['reason']})")
        _sys.exit(0)

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
