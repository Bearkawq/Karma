"""Navigator Agent - Helps navigate resources and states.

This agent is a functional role, NOT a personality.
It helps navigate through resources, artifacts, states, queues, memory, and views.
"""

from __future__ import annotations

from typing import Any, Dict
import time

from agents.base_agent import (
    BaseAgent,
    AgentCapabilities,
    AgentContext,
    AgentResult,
    AgentStatus,
)


class NavigatorAgent(BaseAgent):
    """Navigates through resources, states, and views.

    Helps operators move through memory, artifacts, telemetry,
    queues, and different system views.
    """

    def __init__(self):
        super().__init__("navigator", "navigator")
        self._capabilities = AgentCapabilities(
            can_navigate=True,
            requires_model=False,
            deterministic_fallback=True,
            tags=["navigation", "browsing", "exploration"],
        )
        self._status = AgentStatus.READY

    def get_capabilities(self) -> AgentCapabilities:
        return self._capabilities

    _SYSTEM = (
        "You are a navigator. Given a goal and a list of REAL available items, "
        "rank and explain the most relevant ones. "
        "ONLY use items from the 'Available:' list. Do NOT invent file paths or names. "
        "Format: '- <item>: <one-line reason>'. Max 5 items. No padding."
    )

    def run(self, context: AgentContext) -> AgentResult:
        """Navigate resources — model-first only when real context supplied."""
        start_time = time.time()
        try:
            input_data = context.input_data or {}
            target = input_data.get("target", context.task)
            direction = input_data.get("direction", "current")
            available_context = input_data.get("available", "")

            # Only use model when caller provides grounding context
            if not available_context:
                available_context = self._scan_real_paths(context)

            model_text = None
            if available_context:
                model_text = self._try_model(
                    prompt=(
                        f"Goal: {target}\n"
                        f"Available:\n{available_context}\n"
                        "Pick the most relevant (only from the list above):"
                    ),
                    system=self._SYSTEM,
                    max_tokens=250,
                )
            if model_text:
                model_text = self._validate_options(model_text, available_context)
                if model_text:
                    return AgentResult(
                        success=True,
                        output={
                            "options": model_text,
                            "target": target,
                            "model_generated": True,
                        },
                        used_model=self.role_name,
                        execution_time_ms=(time.time() - start_time) * 1000,
                    )

            # Deterministic fallback
            navigation = self._navigate_to(target, direction, context)
            return AgentResult(
                success=True,
                output=navigation,
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            self._last_error = str(e)
            self._record_execution(False)
            return AgentResult(
                success=False,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    _CODE_KEYWORDS = frozenset(
        [
            "code",
            "file",
            "files",
            "repo",
            "function",
            "class",
            "module",
            "import",
            "fix",
            "debug",
            "refactor",
            "src",
            "test",
            "agent",
            "core",
            "model",
            "implement",
            "add",
            "edit",
            "patch",
        ]
    )

    # Abstract task patterns that imply repo/code intent
    _ABSTRACT_CODE_PATTERNS = frozenset(
        [
            "where should",
            "where do i",
            "what file",
            "what handles",
            "what should i",
            "which file",
            "which handles",
            "find where",
            "wire this",
            "connect this",
            "hook this",
            "route to",
            "who handles",
            "who owns",
            "responsible for",
            "manages",
        ]
    )

    # Session context keys that imply active repo work
    _REPO_CONTEXT_KEYS = frozenset(
        [
            "target_file",
            "working_file",
            "open_file",
            "current_file",
            "edit_target",
            "patch_file",
            "refactor_file",
        ]
    )

    # Structural task patterns that imply repo/code intent (no explicit path needed)
    _STRUCTURAL_CODE_PATTERNS = [
        (r"^what\s+(file|module|class|function|method|handler|agent)", "explore"),
        (r"^how\s+does\s+\w+(?:\s+\w+)*\s+(?:work|function)", "explore"),
        (r"^how\s+to\s+\w+", "howto"),
        (r"^find\s+(the\s+)?(file|code|function|class)", "explore"),
        (
            r"(?:explain|describe|tell me about)\s+(the\s+)?(routing|retrieval|navigation)",
            "explore",
        ),
        (r"(?:show|list)\s+(me\s+)?(all\s+)?(files|handlers|routes)", "explore"),
        (r"^where\s+(do|does|can|should)\s+\w+", "locate"),
        (r"^which\s+(file|module|agent)\s+(handles|manages|owns)", "locate"),
    ]

    # Question starters indicating exploration intent
    _QUESTION_EXPLORATION_STARTERS = frozenset(
        ["what", "how", "which", "where", "show", "list", "find", "explain", "describe"]
    )

    @classmethod
    def _scan_real_paths(cls, context: AgentContext) -> str:
        """Return real inventory for grounding.

        Priority:
        1. Literal paths in task text → list their contents
        2. Abstract intent patterns (e.g., "where should I wire this?")
        3. Session context keys indicating active file work
        4. Code/repo keywords in task → scan project files
        5. Empty string → deterministic fallback
        """
        import os
        import re

        task = (context.task or "").lower()
        raw_task = context.task or ""

        # 1 — explicit path tokens
        paths = re.findall(r"(/[\w./\-]+|~[\w./\-]+|\./[\w./\-]+)", raw_task)
        lines = []
        for p in paths[:2]:
            p = os.path.expanduser(p)
            if os.path.isdir(p):
                try:
                    entries = sorted(os.listdir(p))[:30]
                    lines.append(f"{p}/: " + ", ".join(entries))
                except OSError:
                    pass
            elif os.path.isfile(p):
                lines.append(p)
        if lines:
            return "\n".join(lines)

        # 2 — abstract intent detection
        raw_lower = raw_task.lower()
        for pattern in cls._ABSTRACT_CODE_PATTERNS:
            if pattern in raw_lower:
                return cls._scan_project_files()

        # 2a — structural task patterns (no explicit path needed)
        first_word = task.split()[0] if task.split() else ""
        if first_word in cls._QUESTION_EXPLORATION_STARTERS:
            for pattern_regex, intent in cls._STRUCTURAL_CODE_PATTERNS:
                if re.search(pattern_regex, task):
                    return cls._scan_project_files()
                    break

        # 3 — session context detection
        if context.input_data:
            for key in cls._REPO_CONTEXT_KEYS:
                if key in context.input_data:
                    return cls._scan_project_files()

        # 4 — code-task keyword detection → scan project root
        task_words = set(re.split(r"\W+", task))
        if task_words & cls._CODE_KEYWORDS:
            return cls._scan_project_files()

        return ""

    @staticmethod
    def _scan_project_files() -> str:
        """Return a flat inventory of real project files (top 2 levels)."""
        import os

        root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        skip = {
            "__pycache__",
            ".git",
            "node_modules",
            ".venv",
            "venv",
            "data",
            "docs",
            "ml_models",
            "logs",
        }
        lines = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in sorted(dirnames) if d not in skip and not d.startswith(".")
            ]
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > 1:
                dirnames.clear()
                continue
            for fn in sorted(filenames):
                if fn.endswith((".py", ".json", ".md", ".sh", ".ts", ".js")):
                    lines.append(os.path.join(rel, fn) if rel != "." else fn)
            if len(lines) > 80:
                break
        return "\n".join(lines[:80])

    @staticmethod
    def _validate_options(model_text: str, available_context: str) -> str:
        """Keep only output lines whose referenced item appears in available_context.

        Parses '- item: reason' format. If the item token (before ':') is not
        a substring of any line in available_context, drop it.
        Falls back to raw text when no structured lines are found.
        """
        import re

        avail_lower = available_context.lower()
        avail_lines = [
            l.strip().lower() for l in available_context.splitlines() if l.strip()
        ]

        kept = []
        any_structured = False
        for line in model_text.splitlines():
            m = re.match(r"[-*\d.)\s]*(.+?):\s+(.+)", line.strip())
            if not m:
                continue
            item = m.group(1).strip()
            any_structured = True
            # Accept if item token appears in any available line
            item_lower = item.lower()
            if any(item_lower in al or al in item_lower for al in avail_lines):
                kept.append(line.strip())

        if not any_structured:
            return model_text  # unparseable — pass through unchanged
        return "\n".join(kept) if kept else ""

    def _navigate_to(
        self, target: str, direction: str, context: AgentContext
    ) -> Dict[str, Any]:
        """Navigate to target."""
        memory = context.memory
        retrieval = context.retrieval

        # Map targets to navigation results
        target_lower = target.lower()

        if "memory" in target_lower or "facts" in target_lower:
            return self._navigate_memory(memory)
        elif "artifacts" in target_lower:
            return self._navigate_artifacts(context)
        elif "telemetry" in target_lower or "events" in target_lower:
            return self._navigate_telemetry(context)
        elif "tasks" in target_lower:
            return self._navigate_tasks(memory)
        elif "receipts" in target_lower:
            return self._navigate_receipts(context)
        elif "logs" in target_lower:
            return {"target": "logs", "path": "data/logs/karma.log", "available": True}
        else:
            return {
                "target": target,
                "message": f"Unknown navigation target: {target}",
                "available": False,
                "suggestions": [
                    "memory",
                    "artifacts",
                    "telemetry",
                    "tasks",
                    "receipts",
                    "logs",
                ],
            }

    def _navigate_memory(self, memory: Any) -> Dict[str, Any]:
        """Navigate memory/facts."""
        result = {"target": "memory", "available": True, "sections": []}

        if memory:
            if hasattr(memory, "facts"):
                result["sections"].append({"name": "facts", "count": len(memory.facts)})
            if hasattr(memory, "episodes"):
                result["sections"].append(
                    {"name": "episodes", "count": len(memory.episodes)}
                )
            if hasattr(memory, "tasks"):
                result["sections"].append({"name": "tasks", "count": len(memory.tasks)})

        return result

    def _navigate_artifacts(self, context: AgentContext) -> Dict[str, Any]:
        """Navigate artifacts."""
        return {
            "target": "artifacts",
            "available": True,
            "endpoint": "/api/artifacts",
        }

    def _navigate_telemetry(self, context: AgentContext) -> Dict[str, Any]:
        """Navigate telemetry."""
        return {
            "target": "telemetry",
            "available": True,
            "endpoints": ["/api/telemetry", "/api/telemetry/events"],
        }

    def _navigate_tasks(self, memory: Any) -> Dict[str, Any]:
        """Navigate tasks."""
        result = {"target": "tasks", "available": True, "items": []}

        if memory and hasattr(memory, "tasks"):
            for task_id, task in list(memory.tasks.items())[:10]:
                result["items"].append(
                    {
                        "id": task_id,
                        "status": task.get("status", "unknown"),
                    }
                )

        return result

    def _navigate_receipts(self, context: AgentContext) -> Dict[str, Any]:
        """Navigate receipts."""
        return {
            "target": "receipts",
            "available": True,
            "endpoint": "/api/receipts",
        }


def create_navigator_agent() -> NavigatorAgent:
    """Factory function to create navigator agent."""
    return NavigatorAgent()
