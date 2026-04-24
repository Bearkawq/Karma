"""System Posture Model - System health indicator.

Possible states:
- CALM
- ACTIVE
- DEGRADED
- RECOVERING

State determined by:
- error frequency
- research failures
- ingestion errors
- task backlog
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from threading import Lock

from core.telemetry.event_bus import TelemetryEventBus
from core.mutation_log import MutationLog


POSTURE_STATES = frozenset(["CALM", "ACTIVE", "DEGRADED", "RECOVERING"])


@dataclass
class PostureMetrics:
    """Metrics used to determine system posture."""
    error_frequency: float = 0.0
    research_failures: int = 0
    ingestion_errors: int = 0
    task_backlog: int = 0
    success_rate: float = 1.0
    avg_response_time_ms: float = 0.0


class SystemPosture:
    """Determines and tracks system posture."""

    def __init__(
        self,
        event_bus: Optional[TelemetryEventBus] = None,
        mutation_log: Optional[MutationLog] = None,
    ):
        self._event_bus = event_bus
        self._mutation_log = mutation_log
        self._current_posture: str = "CALM"
        self._posture_history: List[Dict[str, Any]] = []
        self._lock = Lock()
        self._last_transition: Optional[datetime] = None

    def compute_posture(self) -> str:
        """Compute current system posture based on metrics."""
        metrics = self._collect_metrics()
        posture = self._determine_posture(metrics)

        with self._lock:
            if posture != self._current_posture:
                self._posture_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "from": self._current_posture,
                    "to": posture,
                    "metrics": {
                        "error_frequency": metrics.error_frequency,
                        "research_failures": metrics.research_failures,
                        "ingestion_errors": metrics.ingestion_errors,
                        "task_backlog": metrics.task_backlog,
                        "success_rate": metrics.success_rate,
                    },
                })
                self._current_posture = posture
                self._last_transition = datetime.now()

        return posture

    def _collect_metrics(self) -> PostureMetrics:
        """Collect metrics from event bus and mutation log."""
        metrics = PostureMetrics()

        if self._event_bus:
            events = self._event_bus.get_recent_events(100)
            if events:
                failures = sum(1 for e in events if e.result_status == "failure")
                successes = sum(1 for e in events if e.result_status == "success")
                total = failures + successes
                metrics.success_rate = successes / total if total > 0 else 1.0
                metrics.error_frequency = failures / total if total > 0 else 0.0

                times = [e.duration_ms for e in events if e.duration_ms is not None]
                if times:
                    metrics.avg_response_time_ms = sum(times) / len(times)

                metrics.research_failures = sum(
                    1 for e in events
                    if e.event_type == "action_failed" and "golearn" in e.action
                )
                metrics.ingestion_errors = sum(
                    1 for e in events
                    if e.event_type == "ingest_event" and e.result_status == "failure"
                )

        if self._mutation_log:
            recent = self._mutation_log.get_recent_mutations(50)
            metrics.task_backlog = sum(
                1 for m in recent
                if m.change_type in ("task_add", "task_update")
            )

        return metrics

    def _determine_posture(self, metrics: PostureMetrics) -> str:
        """Determine posture from metrics."""
        if metrics.error_frequency > 0.3:
            return "DEGRADED"

        if metrics.research_failures > 3 or metrics.ingestion_errors > 3:
            return "DEGRADED"

        if metrics.task_backlog > 10:
            return "RECOVERING"

        if metrics.success_rate < 0.7:
            return "RECOVERING"

        if metrics.avg_response_time_ms > 5000:
            return "ACTIVE"

        return "CALM"

    def get_current_posture(self) -> str:
        """Get current posture without recomputing."""
        with self._lock:
            return self._current_posture

    def get_posture_with_metrics(self) -> Dict[str, Any]:
        """Get current posture with metrics."""
        metrics = self._collect_metrics()
        posture = self._determine_posture(metrics)

        return {
            "posture": posture,
            "metrics": {
                "error_frequency": metrics.error_frequency,
                "research_failures": metrics.research_failures,
                "ingestion_errors": metrics.ingestion_errors,
                "task_backlog": metrics.task_backlog,
                "success_rate": metrics.success_rate,
                "avg_response_time_ms": metrics.avg_response_time_ms,
            },
            "last_transition": self._last_transition.isoformat() if self._last_transition else None,
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get posture transition history."""
        with self._lock:
            return self._posture_history[-limit:]


_global_posture: Optional[SystemPosture] = None


def get_system_posture() -> SystemPosture:
    """Get global system posture."""
    global _global_posture
    if _global_posture is None:
        _global_posture = SystemPosture()
    return _global_posture
