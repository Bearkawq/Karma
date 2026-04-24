"""Telemetry Metrics - Aggregated metrics for system observability."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque
from threading import Lock


@dataclass
class MetricPoint:
    """Single metric measurement."""
    timestamp: str
    name: str
    value: float
    tags: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """Collects and aggregates system metrics."""

    def __init__(self, max_points: int = 10000):
        self._metrics: Dict[str, deque] = {}
        self._lock = Lock()
        self._max_points = max_points

    def record(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a metric value."""
        point = MetricPoint(
            timestamp=datetime.now().isoformat(),
            name=name,
            value=value,
            tags=tags or {},
        )

        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = deque(maxlen=self._max_points)
            self._metrics[name].append(point)

    def get_latest(self, name: str, count: int = 1) -> List[MetricPoint]:
        """Get latest metric values."""
        with self._lock:
            if name not in self._metrics:
                return []
            return list(self._metrics[name])[-count:]

    def get_average(self, name: str, window: int = 100) -> float:
        """Get average value over recent window."""
        with self._lock:
            if name not in self._metrics or not self._metrics[name]:
                return 0.0
            points = list(self._metrics[name])[-window:]
            if not points:
                return 0.0
            return sum(p.value for p in points) / len(points)

    def get_stats(self, name: str) -> Dict[str, Any]:
        """Get statistical summary for a metric."""
        with self._lock:
            if name not in self._metrics or not self._metrics[name]:
                return {"count": 0, "min": 0, "max": 0, "avg": 0}

            points = list(self._metrics[name])
            values = [p.value for p in points]

            return {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "latest": values[-1] if values else 0,
            }

    def get_all_metric_names(self) -> List[str]:
        """Get all tracked metric names."""
        with self._lock:
            return list(self._metrics.keys())


_global_metrics: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector."""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = MetricsCollector()
    return _global_metrics
