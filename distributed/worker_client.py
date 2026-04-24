"""Worker Client - Client for communicating with worker nodes.

Local worker implementation delegates to AgentModelManager. Remote workers are
not faked: unsupported remote execution returns an explicit failure until a real
RPC transport is implemented.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from distributed.worker_protocol import TaskStatus, WorkerTask
from distributed.worker_registry import WorkerRegistry, get_worker_registry


@dataclass
class TaskResult:
    """Result from task execution."""

    task_id: str
    success: bool
    result: Any
    error: Optional[str]
    worker_id: str
    execution_time_ms: float


class WorkerClient:
    """Client for worker communication."""

    def __init__(self, worker_registry: Optional[WorkerRegistry] = None):
        self._registry = worker_registry or get_worker_registry()
        self._local_tasks: Dict[str, WorkerTask] = {}

    def execute_role(
        self,
        role: str,
        input_data: Dict[str, Any],
        preferred_worker: Optional[str] = None,
        force_local: bool = False,
    ) -> TaskResult:
        """Execute a role task."""
        task_id = str(uuid.uuid4())[:8]
        start_time = datetime.now()
        task = WorkerTask(task_id=task_id, role=role, input_data=input_data)
        self._local_tasks[task_id] = task

        try:
            if force_local or preferred_worker is None:
                worker = self._registry.get_local()
            else:
                worker = self._registry.get(preferred_worker)

            if worker is None:
                raise RuntimeError(f"Worker not found: {preferred_worker or 'local'}")
            if worker.status != "online":
                raise RuntimeError(f"Worker not online: {worker.node_id} ({worker.status})")

            task.status = TaskStatus.RUNNING
            task.worker_id = worker.node_id
            task.started_at = datetime.now().isoformat()

            if self._registry.is_local(worker.node_id):
                result = self._execute_locally(role, input_data)
            else:
                raise NotImplementedError(
                    f"Remote worker transport not implemented for worker '{worker.node_id}'"
                )

            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = datetime.now().isoformat()
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            return TaskResult(task_id, True, result, None, task.worker_id, execution_time)

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now().isoformat()
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            return TaskResult(
                task_id=task_id,
                success=False,
                result=None,
                error=str(e),
                worker_id=task.worker_id or "unknown",
                execution_time_ms=execution_time,
            )

    def _execute_locally(self, role: str, input_data: Dict[str, Any]) -> Any:
        """Execute a role locally through AgentModelManager."""
        from core.agent_model_manager import get_agent_model_manager

        task = str(input_data.get("task") or input_data.get("query") or role)
        context = dict(input_data)
        mgr = get_agent_model_manager()
        result = mgr.execute(task=task, context=context, explicit_role=role)
        return {
            "role": role,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "pipeline_type": result.pipeline_type,
            "role_used": result.role_used,
            "model_used": result.model_used,
            "execution_time_ms": result.execution_time_ms,
        }

    def load_model(self, model_id: str, worker_id: Optional[str] = None) -> bool:
        """Load a model on a worker. Only local loading is currently implemented."""
        worker = self._registry.get(worker_id) if worker_id else self._registry.get_local()
        if worker is None or not self._registry.is_local(worker.node_id):
            return False
        from core.agent_model_manager import get_agent_model_manager

        return get_agent_model_manager().load_model(model_id)

    def unload_model(self, model_id: str, worker_id: Optional[str] = None) -> bool:
        """Unload a model from a worker. Only local unloading is currently implemented."""
        worker = self._registry.get(worker_id) if worker_id else self._registry.get_local()
        if worker is None or not self._registry.is_local(worker.node_id):
            return False
        from core.agent_model_manager import get_agent_model_manager

        return get_agent_model_manager().unload_model(model_id)

    def get_task_status(self, task_id: str) -> Optional[WorkerTask]:
        """Get status of a task."""
        return self._local_tasks.get(task_id)

    def get_worker_health(self, worker_id: str) -> Dict[str, Any]:
        """Get health of a worker."""
        worker = self._registry.get(worker_id)
        if not worker:
            return {"status": "unknown", "error": "Worker not found"}
        return {
            "node_id": worker.node_id,
            "name": worker.name,
            "status": worker.status,
            "last_seen": worker.last_seen,
            "roles": worker.roles,
            "capabilities": worker.capabilities.__dict__,
        }


def get_worker_client() -> WorkerClient:
    """Get worker client instance."""
    return WorkerClient()
