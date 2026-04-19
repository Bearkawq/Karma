"""Telemetry Snapshot - Current state exposed to UI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from threading import Lock

from core.telemetry.event_bus import TelemetryEventBus, EVENT_TYPES
from core.telemetry.metrics import MetricsCollector, get_metrics_collector


class TelemetrySnapshot:
    """Aggregated telemetry state for UI consumption."""
    
    def __init__(
        self,
        event_bus: Optional[TelemetryEventBus] = None,
        metrics: Optional[MetricsCollector] = None,
    ):
        self._event_bus = event_bus
        self._metrics = metrics or get_metrics_collector()
        self._lock = Lock()
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get complete telemetry snapshot."""
        with self._lock:
            event_summary = {}
            if self._event_bus:
                event_summary = {
                    "counts": self._event_bus.get_event_counts(),
                    "summary": self._event_bus.get_summary(),
                    "recent": [
                        e.to_dict() for e in self._event_bus.get_recent_events(10)
                    ],
                }
            
            metric_names = self._metrics.get_all_metric_names()
            metrics_summary = {
                name: self._metrics.get_stats(name)
                for name in metric_names
            }
            
            return {
                "timestamp": datetime.now().isoformat(),
                "events": event_summary,
                "metrics": metrics_summary,
            }
    
    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent telemetry events."""
        if not self._event_bus:
            return []
        return [e.to_dict() for e in self._event_bus.get_recent_events(limit)]
    
    def get_events_by_type(self, event_type: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get events filtered by type."""
        if not self._event_bus:
            return []
        return [
            e.to_dict() for e in self._event_bus.get_recent_events(limit, event_type)
        ]
    
    def get_metric(self, name: str) -> Dict[str, Any]:
        """Get metric statistics."""
        return self._metrics.get_stats(name)
    
    def save_snapshot(self, path: str) -> None:
        """Persist snapshot to file."""
        snapshot = self.get_snapshot()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(snapshot, f, indent=2)
    
    def load_snapshot(self, path: str) -> Dict[str, Any]:
        """Load snapshot from file."""
        with open(path, "r") as f:
            return json.load(f)


_global_snapshot: Optional[TelemetrySnapshot] = None


def get_telemetry_snapshot() -> TelemetrySnapshot:
    """Get global telemetry snapshot."""
    global _global_snapshot
    if _global_snapshot is None:
        _global_snapshot = TelemetrySnapshot()
    return _global_snapshot
