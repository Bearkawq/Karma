"""Multi-step plan execution and adaptive replan logic.

Extracted from AgentLoop; AgentLoop delegates to PlanExecutionService for all
plan step execution and replan recovery. No UI or API surface touched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

MAX_PLAN_STEPS: int = 10
PLAN_STEP_TIMEOUT: int = 30
REPLAN_TIMEOUT: int = 30


class PlanExecutionService:
    def __init__(self, memory, logger) -> None:
        self._memory = memory
        self._logger = logger

    def execute_plan_steps(
        self,
        steps: List[Dict[str, Any]],
        task_desc: str,
        allow_replan: bool = True,
        seed_prior: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        from core.agent_model_manager import get_agent_model_manager

        steps = steps[:MAX_PLAN_STEPS]

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
            outputs = []
            prior_results = []
            for state, step in zip(step_states, steps):
                state["status"] = "done"
                state["output"] = (
                    f"{step.get('action', '')} {step.get('target', '')}".strip()
                )
                outputs.append(f"Step {state['step']}: {state['output']}")
                prior_results.append({
                    "step": state["step"],
                    "action": state["action"],
                    "target": state["target"],
                    "output": state["output"],
                })
            _run_artifact = {
                "task": task_desc,
                "plan": [
                    {"step": s.get("step"), "action": s.get("action"), "target": s.get("target")}
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

        all_step_descriptors = [
            {"step": s.get("step"), "action": s.get("action"), "target": s.get("target")}
            for s in steps
        ]
        outputs: List[str] = []
        prior_results: List[Dict[str, Any]] = list(seed_prior) if seed_prior else []

        for step, state in zip(steps, step_states):
            state["status"] = "running"
            step_task = (
                f"{step.get('action', '')} {step.get('target', '')}".strip() or task_desc
            )
            prior_snapshot = list(prior_results)

            def _run(task=step_task, prior=prior_snapshot):
                return mgr.execute(
                    task=task,
                    context={
                        "plan_steps": all_step_descriptors,
                        "prior_results": prior,
                        "memory": self._memory,
                        "intent": "execute",
                    },
                    explicit_role="executor",
                )

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(_run).result(timeout=PLAN_STEP_TIMEOUT)

                if result.success and result.output:
                    out = result.output
                    text = (
                        out.get("execution", str(out)) if isinstance(out, dict) else str(out)
                    )
                    state["status"] = "done"
                    state["output"] = text
                    outputs.append(f"Step {state['step']}: {text}")
                    prior_results.append({
                        "step": state["step"],
                        "action": state["action"],
                        "target": state["target"],
                        "output": text,
                    })
                else:
                    state["status"] = "failed"
                    state["error"] = getattr(result, "error", None) or "step returned failure"
                    self._logger.debug(f"Plan step {state['step']} failed: {state['error']}")
                    break

            except FuturesTimeout:
                state["status"] = "failed"
                state["error"] = "timeout"
                self._logger.warning(f"Plan step {state['step']} timed out")
                break
            except Exception as exc:
                state["status"] = "failed"
                state["error"] = str(exc)
                self._logger.debug(f"Plan step {state['step']} error: {exc}")
                break

        for state in step_states:
            if state["status"] == "pending":
                state["status"] = "skipped"

        failed = [s for s in step_states if s["status"] == "failed"]
        combined = "\n".join(outputs) if outputs else None

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
            recovery_steps = self.replan_after_failure(
                failed_state, completed_states, skipped_specs, task_desc, mgr, _run_artifact,
            )
            replan_artifact["recovery_plan"] = recovery_steps or None
            _run_artifact["recovery"] = replan_artifact
            if recovery_steps:
                recovery_result = self.execute_plan_steps(
                    recovery_steps, task_desc, allow_replan=False, seed_prior=prior_results,
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
                recovery_exec_artifact = recovery_result.get("_run_artifact")
                if recovery_exec_artifact:
                    replan_artifact["recovery_execution"] = recovery_exec_artifact
                rec_failed = [
                    s for s in step_states
                    if s["status"] == "failed" and not s.get("recovery")
                ]
                return {
                    "success": len(rec_failed) == 0 and bool(outputs),
                    "output": combined,
                    "error": None if recovery_result.get("success") else recovery_result.get("error"),
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

    def replan_after_failure(
        self,
        failed_state: Dict[str, Any],
        completed_states: List[Dict[str, Any]],
        remaining_steps: List[Dict[str, Any]],
        task_desc: str,
        mgr,
        run_artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
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
                        "memory": self._memory,
                    },
                    explicit_role="planner",
                )

            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_call).result(timeout=REPLAN_TIMEOUT)

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
