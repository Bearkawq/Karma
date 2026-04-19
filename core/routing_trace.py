"""Routing Trace - Track routing decisions for each input.

Records:
- input_text
- detected_intent
- confidence
- selected_action
- fallback_reason
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from threading import Lock
from collections import deque


@dataclass
class RouteTrace:
    """Record of a single routing decision."""
    timestamp: str
    input_text: str
    detected_intent: Optional[str] = None
    confidence: float = 0.0
    selected_action: Optional[str] = None
    fallback_reason: Optional[str] = None
    lane: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RouteTracer:
    """Tracks routing decisions for each input."""
    
    def __init__(self, max_traces: int = 100):
        self._traces: deque = deque(maxlen=max_traces)
        self._lock = Lock()
        self._current_trace: Optional[RouteTrace] = None
    
    def start_trace(self, input_text: str) -> RouteTrace:
        """Begin tracking a new input routing."""
        trace = RouteTrace(
            timestamp=datetime.now().isoformat(),
            input_text=input_text,
        )
        with self._lock:
            self._current_trace = trace
        return trace
    
    def record_intent(
        self,
        intent: Optional[str],
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record detected intent and confidence."""
        with self._lock:
            if self._current_trace:
                self._current_trace.detected_intent = intent
                self._current_trace.confidence = confidence
                if metadata:
                    self._current_trace.metadata.update(metadata)
    
    def record_action(self, action: str) -> None:
        """Record selected action."""
        with self._lock:
            if self._current_trace:
                self._current_trace.selected_action = action
    
    def record_fallback(self, reason: str) -> None:
        """Record fallback reason."""
        with self._lock:
            if self._current_trace:
                self._current_trace.fallback_reason = reason
    
    def record_lane(self, lane: str) -> None:
        """Record routing lane."""
        with self._lock:
            if self._current_trace:
                self._current_trace.lane = lane
    
    def finalize_trace(self) -> Optional[RouteTrace]:
        """Complete and store the current trace."""
        with self._lock:
            if self._current_trace:
                self._traces.append(self._current_trace)
                trace = self._current_trace
                self._current_trace = None
                return trace
        return None
    
    def get_latest_trace(self) -> Optional[RouteTrace]:
        """Get the most recent trace."""
        with self._lock:
            if self._traces:
                return self._traces[-1]
        return None
    
    def get_recent_traces(self, limit: int = 10) -> List[RouteTrace]:
        """Get recent traces."""
        with self._lock:
            return list(self._traces)[-limit:]
    
    def get_all_traces(self) -> List[RouteTrace]:
        """Get all traces."""
        with self._lock:
            return list(self._traces)
    
    def get_traces_for_action(self, action: str) -> List[RouteTrace]:
        """Get traces for a specific action."""
        with self._lock:
            return [t for t in self._traces if t.selected_action == action]
    
    def save_traces(self, path: str) -> None:
        """Persist traces to file."""
        with self._lock:
            traces = [t.to_dict() for t in self._traces]
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(traces, f, indent=2)
    
    def clear(self) -> None:
        """Clear all traces (for testing)."""
        with self._lock:
            self._traces.clear()
            self._current_trace = None


_global_tracer: Optional[RouteTracer] = None


def get_route_tracer() -> RouteTracer:
    """Get global route tracer."""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = RouteTracer()
    return _global_tracer
