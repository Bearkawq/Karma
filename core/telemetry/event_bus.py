"""Telemetry Event Bus - Structured observability for Karma.

Tracks system events including:
- action_started
- action_completed
- action_failed
- research_attempt
- ingest_event
- memory_write
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from threading import Lock
from collections import deque


EVENT_TYPES = frozenset([
    "action_started",
    "action_completed",
    "action_failed",
    "research_attempt",
    "ingest_event",
    "memory_write",
    "system_start",
    "system_stop",
    "provider_error",
    "provider_success",
])


RESULT_STATUS = frozenset([
    "success",
    "failure",
    "pending",
    "skipped",
    "timeout",
])


@dataclass
class TelemetryEvent:
    """Structured telemetry event."""
    timestamp: str
    event_type: str
    action: str
    duration_ms: Optional[float] = None
    result_status: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TelemetryEventBus:
    """Thread-safe event bus for telemetry tracking."""

    def __init__(self, max_events: int = 1000, log_file: Optional[str] = None):
        self._events: deque = deque(maxlen=max_events)
        self._lock = Lock()
        self._log_file = Path(log_file) if log_file else None
        self._event_counts: Dict[str, int] = {}
        self._start_time = datetime.now()

    def emit(
        self,
        event_type: str,
        action: str,
        duration_ms: Optional[float] = None,
        result_status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TelemetryEvent:
        """Emit a telemetry event."""
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {event_type}")
        if result_status is not None and result_status not in RESULT_STATUS:
            raise ValueError(f"Unknown result status: {result_status}")

        event = TelemetryEvent(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            action=action,
            duration_ms=duration_ms,
            result_status=result_status,
            metadata=metadata or {},
        )

        with self._lock:
            self._events.append(event)
            self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1

            if self._log_file:
                self._write_to_log(event)

        return event

    def _write_to_log(self, event: TelemetryEvent) -> None:
        """Write event to persistent log file."""
        try:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_file, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception:
            pass

    def get_recent_events(self, limit: int = 50, event_type: Optional[str] = None) -> List[TelemetryEvent]:
        """Get recent events, optionally filtered by type."""
        with self._lock:
            events = list(self._events)

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        return events[-limit:]

    def get_events_by_action(self, action: str, limit: int = 20) -> List[TelemetryEvent]:
        """Get events for a specific action."""
        with self._lock:
            events = [e for e in self._events if e.action == action]
        return events[-limit:]

    def get_event_counts(self) -> Dict[str, int]:
        """Get counts of each event type."""
        with self._lock:
            return dict(self._event_counts)

    def get_summary(self) -> Dict[str, Any]:
        """Get telemetry summary."""
        with self._lock:
            events = list(self._events)

        total_duration = sum(
            e.duration_ms for e in events
            if e.duration_ms is not None
        )

        success_count = sum(
            1 for e in events
            if e.result_status == "success"
        )
        failure_count = sum(
            1 for e in events
            if e.result_status == "failure"
        )

        uptime = (datetime.now() - self._start_time).total_seconds()

        return {
            "total_events": len(events),
            "event_counts": dict(self._event_counts),
            "total_duration_ms": total_duration,
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_count / len(events) if events else 0,
            "uptime_seconds": uptime,
        }

    def clear(self) -> None:
        """Clear all events (for testing)."""
        with self._lock:
            self._events.clear()
            self._event_counts.clear()


def create_telemetry_bus(base_dir: Optional[str] = None) -> TelemetryEventBus:
    """Create a telemetry event bus with default configuration."""
    log_file = None
    if base_dir:
        log_file = str(Path(base_dir) / "data" / "telemetry" / "events.jsonl")
    return TelemetryEventBus(log_file=log_file)
