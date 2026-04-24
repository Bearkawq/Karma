"""Executor Agent - Performs structured actions.

This agent is a functional role, NOT a personality.
It executes actions through existing Karma tooling.
"""

from __future__ import annotations

from typing import Any, Dict, List
import time

from agents.base_agent import (
    BaseAgent, AgentCapabilities, AgentContext, AgentResult, AgentStatus
)


class ExecutorAgent(BaseAgent):
    """Performs structured actions through Karma's tooling.
    
    Executes actions defined in plans. Works through existing
    Karma command systems and tools.
    """

    def __init__(self):
        super().__init__("executor", "executor")
        self._capabilities = AgentCapabilities(
            can_execute=True,
            requires_model=False,
            deterministic_fallback=True,
            tags=["execution", "action", "tooling"],
        )
        self._status = AgentStatus.READY

    def get_capabilities(self) -> AgentCapabilities:
        return self._capabilities

    _SYSTEM = (
        "You are an executor. Given a task and prior context, output the exact concrete "
        "steps or commands needed. Tool-grounded: prefer specific commands, file paths, "
        "function names. No explanation. No padding. Output actionable items only."
    )

    @staticmethod
    def _build_prior_context(prior_results: List[Dict[str, Any]]) -> str:
        """Format prior step results as a compact context block."""
        if not prior_results:
            return ""
        lines = ["Prior results:"]
        for r in prior_results:
            out = str(r.get("output", "")).strip()[:150]
            label = f"{r.get('action','')} {r.get('target','')}".strip()
            lines.append(f"- Step {r.get('step')} ({label}): {out}")
        return "\n".join(lines) + "\n\n"

    def run(self, context: AgentContext) -> AgentResult:
        """Execute a step — model-first when task present, deterministic fallback."""
        start_time = time.time()
        try:
            input_data = context.input_data or {}
            plan_steps = input_data.get("plan_steps", [])
            prior_results: List[Dict[str, Any]] = input_data.get("prior_results", [])
            memory = context.memory
            tool_manager = context.metadata.get("tool_manager")

            # Model path: task-present takes priority; plan_steps is context, not a blocker
            if context.task:
                prior_ctx = self._build_prior_context(prior_results)
                prompt = f"{prior_ctx}Task: {context.task}\nExecute:"
                model_text = self._try_model(
                    prompt=prompt,
                    system=self._SYSTEM,
                    max_tokens=350,
                )
                if model_text:
                    from agents.base_agent import _extract_numbered_lines
                    clean = _extract_numbered_lines(model_text)
                    if not clean or clean == model_text:
                        clean = model_text
                    return AgentResult(
                        success=True,
                        output={"execution": clean, "model_generated": True},
                        used_model=self.role_name,
                        execution_time_ms=(time.time() - start_time) * 1000,
                    )

            # Deterministic step execution (fallback when no task or no model)
            results = []
            for step in plan_steps:
                step_result = self._execute_step(step, memory, tool_manager)
                results.append(step_result)
                if not step_result.get("success", True):
                    break

            result = AgentResult(
                success=all(r.get("success", True) for r in results),
                output={"step_results": results},
                execution_time_ms=(time.time() - start_time) * 1000,
            )
            self._record_execution(result.success)
            return result
        except Exception as e:
            self._last_error = str(e)
            self._record_execution(False)
            return AgentResult(success=False, error=str(e),
                               execution_time_ms=(time.time() - start_time) * 1000)

    def _execute_step(
        self,
        step: Dict[str, Any],
        memory: Any,
        tool_manager: Any
    ) -> Dict[str, Any]:
        """Execute a single step."""
        action = step.get("action", "")
        target = step.get("target", "")

        # Deterministic action mapping
        action_map = {
            "research": "golearn",
            "ingest": "ingest",
            "summarize": "digest",
            "file_operation": "file",
            "execute": "shell",
            "tool_operation": "tool",
            "health_check": "self_check",
            "process": "process",
        }

        return {
            "step": step.get("step"),
            "action": action,
            "target": target,
            "mapped_action": action_map.get(action, action),
            "success": True,
        }


def create_executor_agent() -> ExecutorAgent:
    """Factory function to create executor agent."""
    return ExecutorAgent()
