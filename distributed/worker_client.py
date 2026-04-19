"""Worker Client - Client for communicating with worker nodes.

Local worker implementation that runs tasks directly.
Can be extended for remote workers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from distributed.worker_protocol import WorkerProtocol, WorkerTask, TaskStatus, WorkerResponse
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
    """Client for worker communication.
    
    For local execution, runs tasks directly.
    For remote workers, would make HTTP requests.
    """
    
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
        """Execute a role task.
        
        Args:
            role: Role to execute (planner, retriever, etc.)
            input_data: Task input
            preferred_worker: Preferred worker node ID
            force_local: Force execution on local node
            
        Returns:
            TaskResult with execution result
        """
        task_id = str(uuid.uuid4())[:8]
        start_time = datetime.now()
        
        # Create task
        task = WorkerTask(
            task_id=task_id,
            role=role,
            input_data=input_data,
        )
        self._local_tasks[task_id] = task
        
        try:
            # Determine worker
            if force_local or preferred_worker is None:
                worker = self._registry.get_local()
            else:
                worker = self._registry.get(preferred_worker)
            
            if worker is None:
                # Fall back to local
                worker = self._registry.get_local()
            
            # Mark task as running
            task.status = TaskStatus.RUNNING
            task.worker_id = worker.node_id if worker else "local"
            task.started_at = datetime.now().isoformat()
            
            # Execute locally (simulate worker execution)
            result = self._execute_locally(role, input_data)
            
            # Mark task complete
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = datetime.now().isoformat()
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return TaskResult(
                task_id=task_id,
                success=True,
                result=result,
                error=None,
                worker_id=task.worker_id,
                execution_time_ms=execution_time,
            )
            
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
        """Execute task locally (placeholder).
        
        In a full implementation, this would invoke the actual role handler.
        For now, return a mock result.
        """
        # This would integrate with AgentModelManager
        return {
            "role": role,
            "executed": True,
            "input": input_data,
        }
    
    def load_model(self, model_id: str, worker_id: Optional[str] = None) -> bool:
        """Load a model on a worker.
        
        Args:
            model_id: Model to load
            worker_id: Worker node ID (None = local)
            
        Returns:
            True if successful
        """
        # Placeholder - would trigger actual model loading
        return True
    
    def unload_model(self, model_id: str, worker_id: Optional[str] = None) -> bool:
        """Unload a model from a worker.
        
        Args:
            model_id: Model to unload
            worker_id: Worker node ID (None = local)
            
        Returns:
            True if successful
        """
        # Placeholder - would trigger actual model unloading
        return True
    
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
