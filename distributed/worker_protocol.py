"""Worker Protocol - Communication protocol for worker nodes.

Defines the API contract between Karma core and worker nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum


class TaskStatus(Enum):
    """Status of a worker task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkerTask:
    """Task to be executed on a worker node."""
    task_id: str
    role: str
    input_data: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: TaskStatus = TaskStatus.PENDING
    worker_id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class WorkerResponse:
    """Response from a worker node."""
    success: bool
    task_id: str
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class WorkerProtocol:
    """Protocol for worker communication.
    
    Workers expose these endpoints:
    - GET /health - Health check
    - GET /capabilities - Node capabilities
    - POST /run_role_task - Execute a role task
    - POST /load_model - Load a model
    - POST /unload_model - Unload a model
    - GET /status - Node status
    """
    
    @staticmethod
    def build_health_request() -> Dict[str, Any]:
        """Build health check request."""
        return {
            "endpoint": "/health",
            "method": "GET",
        }
    
    @staticmethod
    def build_capabilities_request() -> Dict[str, Any]:
        """Build capabilities request."""
        return {
            "endpoint": "/capabilities",
            "method": "GET",
        }
    
    @staticmethod
    def build_task_request(task: WorkerTask) -> Dict[str, Any]:
        """Build task execution request."""
        return {
            "endpoint": "/run_role_task",
            "method": "POST",
            "body": {
                "task_id": task.task_id,
                "role": task.role,
                "input_data": task.input_data,
            },
        }
    
    @staticmethod
    def build_load_model_request(model_id: str) -> Dict[str, Any]:
        """Build model load request."""
        return {
            "endpoint": "/load_model",
            "method": "POST",
            "body": {"model_id": model_id},
        }
    
    @staticmethod
    def build_unload_model_request(model_id: str) -> Dict[str, Any]:
        """Build model unload request."""
        return {
            "endpoint": "/unload_model",
            "method": "POST",
            "body": {"model_id": model_id},
        }
    
    @staticmethod
    def build_status_request() -> Dict[str, Any]:
        """Build status request."""
        return {
            "endpoint": "/status",
            "method": "GET",
        }
    
    @staticmethod
    def parse_response(response: Dict[str, Any]) -> WorkerResponse:
        """Parse worker response."""
        return WorkerResponse(
            success=response.get("success", False),
            task_id=response.get("task_id", ""),
            result=response.get("result"),
            error=response.get("error"),
            metadata=response.get("metadata", {}),
        )


# Protocol constants
PROTOCOL_VERSION = "1.0"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
