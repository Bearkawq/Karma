"""Reflection engine — confidence tracking and post-execution analysis.

Extracted from AgentLoop to keep the orchestrator lean.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


class ReflectionEngine:
    """Handles confidence calculation, reflection, and state updates."""

    def __init__(self, memory, retrieval, governor, current_state: Dict[str, Any]):
        self.memory = memory
        self.retrieval = retrieval
        self.governor = governor
        self.current_state = current_state

    def calculate_confidence(self, intent: Dict[str, Any], action: Optional[Dict[str, Any]]) -> float:
        if not action:
            return 0.0
        ic = float(intent.get("confidence", 0.5))
        ac = float(action.get("confidence", ic))
        return max(0.0, min(1.0, (ic + ac) / 2.0))

    def reflect(self, intent: Dict[str, Any], selected_action: Optional[Dict[str, Any]], execution_result: Dict[str, Any]) -> Dict[str, Any]:
        conf = self.calculate_confidence(intent, selected_action)
        success = bool(execution_result.get("success", False))

        intent_name = intent.get("intent", "")
        reflect_evidence = self.retrieval.retrieve_context_bundle(
            intent_name, "reflect", intent=intent_name,
        )
        for ev in reflect_evidence:
            if ev.type == "workflow" and success:
                conf = min(1.0, conf + 0.05)
                break
            elif ev.type == "failure" and not success:
                conf = max(0.1, conf)
                break

        reflection = {
            "timestamp": datetime.now().isoformat(),
            "intent": intent,
            "selected_action": selected_action,
            "execution_result": execution_result,
            "success": success,
            "confidence": conf,
            "evidence_used": len(reflect_evidence),
        }
        self.memory.store_reflection(reflection)
        self.current_state["execution_log"].append(reflection)
        self.current_state["confidence"] = round(
            0.7 * self.current_state.get("confidence", 0.5) + 0.3 * conf, 3
        )
        if len(self.current_state["execution_log"]) > 1000:
            self.current_state["execution_log"] = self.current_state["execution_log"][-1000:]
        self.governor.record_execution(success, conf)
        return reflection

    def update_state(self, reflection: Dict[str, Any]):
        self.current_state["last_run"] = datetime.now().isoformat()
        intent_name = reflection.get("intent", {}).get("intent", "")
        self.current_state["current_task"] = intent_name
        self.current_state["memory_summary"] = self.memory.get_summary()
        self.current_state["decision_summary"] = {
            "total_decisions": len(self.current_state["execution_log"]),
            "success_rate": self._calculate_success_rate(),
            "average_confidence": self._calculate_average_confidence(),
        }

        success = reflection.get("success", True)
        exec_result = reflection.get("execution_result") or {}

        # Track most recent failure
        if not success:
            self.current_state["last_failure"] = {
                "intent": intent_name,
                "error": exec_result.get("error") or "",
                "ts": reflection.get("timestamp", ""),
            }

        # Detect consecutive failures → blocked
        logs = self.current_state.get("execution_log", [])
        recent_three = logs[-3:] if len(logs) >= 3 else logs
        consecutive_fails = sum(1 for l in recent_three if not l.get("success", True))
        if consecutive_fails >= 2:
            self.current_state["blocked_reason"] = (
                f"{consecutive_fails} consecutive failures"
                + (f" on '{intent_name}'" if intent_name else "")
            )
        elif success and self.current_state.get("blocked_reason"):
            self.current_state.pop("blocked_reason", None)

    def _calculate_success_rate(self) -> float:
        logs = self.current_state.get("execution_log", [])
        if not logs:
            return 0.0
        return sum(1 for log in logs if log.get("success")) / len(logs)

    def _calculate_average_confidence(self) -> float:
        logs = self.current_state.get("execution_log", [])
        if not logs:
            return 0.0
        return sum(float(log.get("confidence", 0.0)) for log in logs) / len(logs)
