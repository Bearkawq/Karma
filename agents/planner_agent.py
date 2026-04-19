"""Planner Agent - Decomposes goals into steps.

This agent is a functional role, NOT a personality.
It decomposes user goals into executable steps.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import time

from agents.base_agent import (
    BaseAgent, AgentCapabilities, AgentContext, AgentResult, AgentStatus
)


class PlannerAgent(BaseAgent):
    """Decomposes goals into task plans.
    
    This agent breaks down high-level goals into actionable steps.
    Does not directly mutate system state unless explicitly allowed.
    """
    
    def __init__(self):
        super().__init__("planner", "planner")
        self._capabilities = AgentCapabilities(
            can_plan=True,
            requires_model=False,  # Can work deterministically
            deterministic_fallback=True,
            model_role_preference="planner",
            tags=["planning", "decomposition", "task-analysis"],
        )
        self._status = AgentStatus.READY
    
    def get_capabilities(self) -> AgentCapabilities:
        return self._capabilities
    
    _SYSTEM = (
        "You are a task planner. Output a numbered action plan only. "
        "Each step: one line, format '1. ACTION: target'. "
        "Be specific. No explanation. No padding. Max 6 steps."
    )

    def run(self, context: AgentContext) -> AgentResult:
        """Decompose task into steps — model-first, deterministic fallback."""
        start_time = time.time()
        try:
            task = context.task
            input_data = context.input_data or {}
            intent_name = input_data.get("intent", "unknown")
            entities = input_data.get("entities", {})

            # Model path
            model_text = self._try_model(
                prompt=f"Task: {task}\nContext: intent={intent_name}, entities={entities}\nPlan:",
                system=self._SYSTEM,
                max_tokens=300,
            )
            if model_text:
                from agents.base_agent import _extract_numbered_lines
                model_text = _extract_numbered_lines(model_text) or model_text
                steps = self._parse_model_plan(model_text)
                return AgentResult(
                    success=True,
                    output={"plan_steps": steps, "intent": intent_name,
                            "task": task, "model_generated": True,
                            "raw": model_text},
                    used_model=self.role_name,
                    execution_time_ms=(time.time() - start_time) * 1000,
                )

            # Deterministic fallback
            steps = self._decompose_task(intent_name, task, entities)
            return AgentResult(
                success=True,
                output={"plan_steps": steps, "intent": intent_name, "task": task},
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            self._last_error = str(e)
            self._record_execution(False)
            return AgentResult(success=False, error=str(e),
                               execution_time_ms=(time.time() - start_time) * 1000)

    @staticmethod
    def _parse_model_plan(text: str) -> List[Dict[str, Any]]:
        """Parse numbered lines into step dicts.

        Handles both '1. ACTION: target' and '1. Full sentence' formats.
        """
        import re
        steps = []
        for line in text.strip().splitlines():
            line = line.strip()
            m = re.match(r"(\d+)[.)]\s*(.+)", line)
            if not m:
                continue
            n, body = int(m.group(1)), m.group(2).strip().rstrip(".")
            # Only split on colon if it looks like "VERB: target" (short verb, no spaces before colon)
            colon_match = re.match(r"([A-Z][A-Z_\s]{0,20}):\s*(.+)", body)
            if colon_match:
                action = colon_match.group(1).strip()
                target = colon_match.group(2).strip()
            else:
                action = body
                target = ""
            steps.append({"step": n, "action": action, "target": target})
        if not steps:
            steps = [{"step": 1, "action": "process", "target": text[:120]}]
        return steps
    
    def _decompose_task(
        self, 
        intent: str, 
        task: str, 
        entities: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Decompose task into actionable steps."""
        steps = []
        
        # Map intents to step templates
        if intent in ("golearn", "salvage_golearn"):
            steps = [
                {"step": 1, "action": "research", "target": entities.get("topic", task)},
                {"step": 2, "action": "ingest", "target": "learn_results"},
                {"step": 3, "action": "summarize", "target": "findings"},
            ]
        elif intent in ("read_file", "list_files", "search_files"):
            steps = [
                {"step": 1, "action": "file_operation", "target": entities.get("filename") or entities.get("path") or entities.get("pattern")},
            ]
        elif intent in ("run_shell", "code_run"):
            steps = [
                {"step": 1, "action": "execute", "target": entities.get("cmd") or entities.get("path")},
            ]
        elif intent in ("create_tool", "run_custom_tool"):
            steps = [
                {"step": 1, "action": "tool_operation", "target": entities.get("name")},
            ]
        elif intent in ("self_check", "diagnostics"):
            steps = [
                {"step": 1, "action": "health_check", "target": "system"},
                {"step": 2, "action": "report", "target": "findings"},
            ]
        else:
            # Default: treat as single step
            steps = [
                {"step": 1, "action": "process", "target": task},
            ]
        
        return steps


def create_planner_agent() -> PlannerAgent:
    """Factory function to create planner agent."""
    return PlannerAgent()
