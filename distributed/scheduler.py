"""Scheduler - Role-based task scheduling for distributed workers.

Schedules tasks to appropriate workers based on role requirements,
worker health, and fallback rules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from distributed.worker_client import WorkerClient, get_worker_client
from distributed.worker_registry import WorkerRegistry, get_worker_registry


@dataclass
class SchedulingDecision:
    """Result of scheduling decision."""

    task_id: str
    role: str
    selected_worker: str
    fallback_used: bool
    fallback_reason: Optional[str]
    confidence: float


@dataclass
class ScheduleResult:
    """Result from scheduling execution."""

    success: bool
    task_id: str
    result: Any
    error: Optional[str]
    worker_id: str
    execution_time_ms: float
    scheduling_decision: SchedulingDecision


class Scheduler:
    """Schedules role tasks to appropriate workers."""

    DEFAULT_ROLE_PREFERENCES = {
        "planner": ["phone", "dell"],
        "executor": ["dell"],
        "retriever": ["pi", "dell"],
        "summarizer": ["phone", "dell"],
        "critic": ["phone", "dell"],
        "navigator": ["dell", "pi"],
        "coder": ["dell"],
        "embedder": ["dell", "pi"],
    }

    def __init__(
        self,
        worker_registry: Optional[WorkerRegistry] = None,
        worker_client: Optional[WorkerClient] = None,
    ):
        self._registry = worker_registry or get_worker_registry()
        self._client = worker_client or get_worker_client()
        self._role_preferences = dict(self.DEFAULT_ROLE_PREFERENCES)

    def set_role_preference(self, role: str, worker_order: List[str]) -> None:
        """Set preferred worker order for a role."""
        self._role_preferences[role] = worker_order

    def schedule(
        self,
        role: str,
        input_data: Dict[str, Any],
        force_worker: Optional[str] = None,
        allow_fallback: bool = True,
    ) -> ScheduleResult:
        """Schedule and execute a role task."""
        task_id = str(uuid.uuid4())[:8]
        decision = self._select_worker(role, force_worker, allow_fallback)
        decision.task_id = task_id
        decision.role = role

        if not decision.selected_worker:
            return ScheduleResult(
                success=False,
                task_id=task_id,
                result=None,
                error="no_worker_available",
                worker_id="",
                execution_time_ms=0.0,
                scheduling_decision=decision,
            )

        result = self._client.execute_role(
            role=role,
            input_data=input_data,
            preferred_worker=decision.selected_worker,
            force_local=(decision.selected_worker == "dell"),
        )

        if not result.success and allow_fallback and not decision.fallback_used:
            fallback_worker = self._get_fallback_worker(role)
            if fallback_worker and fallback_worker != decision.selected_worker:
                decision.fallback_used = True
                decision.fallback_reason = "primary_worker_failed"
                decision.selected_worker = fallback_worker
                result = self._client.execute_role(
                    role=role,
                    input_data=input_data,
                    preferred_worker=fallback_worker,
                    force_local=(fallback_worker == "dell"),
                )

        return ScheduleResult(
            success=result.success,
            task_id=task_id,
            result=result.result,
            error=result.error,
            worker_id=result.worker_id,
            execution_time_ms=result.execution_time_ms,
            scheduling_decision=decision,
        )

    def _select_worker(
        self,
        role: str,
        force_worker: Optional[str],
        allow_fallback: bool,
    ) -> SchedulingDecision:
        """Select best worker for a role."""
        if force_worker:
            return SchedulingDecision("", role, force_worker, False, None, 1.0)

        preferred = self._role_preferences.get(role, ["dell"])
        for worker_id in preferred:
            worker = self._registry.get(worker_id)
            if worker and worker.status == "online" and self._worker_can_role(worker, role):
                return SchedulingDecision("", role, worker_id, False, None, 0.9)

        if allow_fallback:
            local = self._registry.get_local()
            if local and local.status == "online" and self._worker_can_role(local, role):
                return SchedulingDecision(
                    "",
                    role,
                    local.node_id,
                    True,
                    "no_preferred_worker_available",
                    0.5,
                )

        return SchedulingDecision("", role, "", False, "no_worker_available", 0.0)

    def _worker_can_role(self, worker, role: str) -> bool:
        """Check if worker can execute a role."""
        caps = worker.capabilities
        role_capability_map = {
            "planner": caps.can_plan,
            "executor": caps.can_execute,
            "retriever": caps.can_retrieve,
            "summarizer": caps.can_summarize,
            "critic": caps.can_criticize,
            "navigator": caps.can_navigate,
            "coder": caps.can_execute,
            "embedder": caps.can_embed,
        }
        return role_capability_map.get(role, False)

    def _get_fallback_worker(self, role: str) -> Optional[str]:
        """Get fallback worker for a role."""
        local = self._registry.get_local()
        if local and local.status == "online" and self._worker_can_role(local, role):
            return local.node_id
        return None

    def get_worker_for_role(self, role: str) -> Optional[str]:
        """Get best worker for a role without executing."""
        decision = self._select_worker(role, None, True)
        return decision.selected_worker if decision.confidence > 0 else None

    def get_schedule_summary(self) -> Dict[str, Any]:
        """Get scheduling system summary."""
        role_workers = {}
        for role in self._role_preferences:
            worker = self.get_worker_for_role(role)
            role_workers[role] = worker
        return {
            "role_preferences": self._role_preferences,
            "role_assignments": role_workers,
            "available_workers": len(self._registry.get_online()),
        }


_global_scheduler: Optional[Scheduler] = None


def get_scheduler() -> Scheduler:
    """Get global scheduler."""
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = Scheduler()
    return _global_scheduler
