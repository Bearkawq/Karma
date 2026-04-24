"""Node Health - Health monitoring for worker nodes.

Monitors worker node health and availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from distributed.worker_registry import WorkerRegistry, get_worker_registry


@dataclass
class HealthMetrics:
    """Health metrics for a node."""
    node_id: str
    status: str
    last_check: str
    response_time_ms: float = 0
    error_count: int = 0
    consecutive_failures: int = 0
    last_success: Optional[str] = None
    last_failure: Optional[str] = None


class NodeHealth:
    """Monitors health of worker nodes."""

    def __init__(self, worker_registry: Optional[WorkerRegistry] = None):
        self._registry = worker_registry or get_worker_registry()
        self._health: Dict[str, HealthMetrics] = {}
        self._failure_threshold = 3

    def check_node(self, node_id: str) -> HealthMetrics:
        """Check health of a node."""
        worker = self._registry.get(node_id)

        if not worker:
            return HealthMetrics(
                node_id=node_id,
                status="unknown",
                last_check=datetime.now().isoformat(),
            )

        # Get or create metrics
        if node_id not in self._health:
            self._health[node_id] = HealthMetrics(
                node_id=node_id,
                status=worker.status,
                last_check=datetime.now().isoformat(),
            )

        metrics = self._health[node_id]
        metrics.last_check = datetime.now().isoformat()
        metrics.status = worker.status

        return metrics

    def record_success(self, node_id: str, response_time_ms: float = 0) -> None:
        """Record successful interaction."""
        if node_id not in self._health:
            self._health[node_id] = HealthMetrics(
                node_id=node_id,
                status="online",
                last_check=datetime.now().isoformat(),
            )

        metrics = self._health[node_id]
        metrics.status = "online"
        metrics.consecutive_failures = 0
        metrics.last_success = datetime.now().isoformat()
        metrics.response_time_ms = response_time_ms

    def record_failure(self, node_id: str, error: str = "") -> None:
        """Record failed interaction."""
        if node_id not in self._health:
            self._health[node_id] = HealthMetrics(
                node_id=node_id,
                status="offline",
                last_check=datetime.now().isoformat(),
            )

        metrics = self._health[node_id]
        metrics.error_count += 1
        metrics.consecutive_failures += 1
        metrics.last_failure = datetime.now().isoformat()

        if metrics.consecutive_failures >= self._failure_threshold:
            metrics.status = "degraded"

    def is_healthy(self, node_id: str) -> bool:
        """Check if node is healthy."""
        metrics = self._health.get(node_id)
        if not metrics:
            return True
        return metrics.status in ("online", "busy")

    def is_degraded(self, node_id: str) -> bool:
        """Check if node is degraded."""
        metrics = self._health.get(node_id)
        if not metrics:
            return False
        return metrics.status == "degraded"

    def get_all_health(self) -> List[Dict[str, Any]]:
        """Get health of all nodes."""
        results = []

        for worker in self._registry.get_all():
            metrics = self._health.get(worker.node_id)
            results.append({
                "node_id": worker.node_id,
                "name": worker.name,
                "status": metrics.status if metrics else worker.status,
                "last_check": metrics.last_check if metrics else None,
                "response_time_ms": metrics.response_time_ms if metrics else 0,
                "error_count": metrics.error_count if metrics else 0,
                "consecutive_failures": metrics.consecutive_failures if metrics else 0,
                "last_success": metrics.last_success if metrics else None,
                "last_failure": metrics.last_failure if metrics else None,
            })

        return results

    def get_summary(self) -> Dict[str, Any]:
        """Get health summary."""
        all_health = self.get_all_health()

        online = sum(1 for h in all_health if h["status"] == "online")
        offline = sum(1 for h in all_health if h["status"] == "offline")
        degraded = sum(1 for h in all_health if h["status"] == "degraded")

        return {
            "total_nodes": len(all_health),
            "online": online,
            "offline": offline,
            "degraded": degraded,
            "nodes": all_health,
        }


_global_health: Optional[NodeHealth] = None


def get_node_health() -> NodeHealth:
    """Get global node health monitor."""
    global _global_health
    if _global_health is None:
        _global_health = NodeHealth()
    return _global_health
