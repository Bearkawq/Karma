"""Mutation Log - Track state changes.

Mutation record:
- source
- change_type
- object_id
- timestamp
- details
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from threading import Lock
from collections import deque


CHANGE_TYPES = frozenset([
    "memory_add",
    "memory_update",
    "memory_delete",
    "fact_add",
    "fact_update",
    "fact_delete",
    "task_add",
    "task_update",
    "task_complete",
    "tool_create",
    "tool_delete",
    "config_change",
    "state_save",
    "ingest",
    "learn_session",
])


@dataclass
class MutationRecord:
    """Record of a state mutation."""
    timestamp: str
    source: str
    change_type: str
    object_id: str
    details: Dict[str, Any] = field(default_factory=dict)
    previous_value: Optional[Any] = None
    new_value: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("previous_value", None)
        data.pop("new_value", None)
        return data


class MutationLog:
    """Tracks state mutations."""

    def __init__(self, max_records: int = 500):
        self._mutations: deque = deque(maxlen=max_records)
        self._lock = Lock()

    def log(
        self,
        source: str,
        change_type: str,
        object_id: str,
        details: Optional[Dict[str, Any]] = None,
        previous_value: Optional[Any] = None,
        new_value: Optional[Any] = None,
    ) -> MutationRecord:
        """Log a state mutation."""
        if change_type not in CHANGE_TYPES:
            raise ValueError(f"Unknown change type: {change_type}")

        record = MutationRecord(
            timestamp=datetime.now().isoformat(),
            source=source,
            change_type=change_type,
            object_id=object_id,
            details=details or {},
            previous_value=previous_value,
            new_value=new_value,
        )

        with self._lock:
            self._mutations.append(record)

        return record

    def get_latest_mutation(self) -> Optional[MutationRecord]:
        """Get the most recent mutation."""
        with self._lock:
            if self._mutations:
                return self._mutations[-1]
        return None

    def get_recent_mutations(self, limit: int = 20) -> List[MutationRecord]:
        """Get recent mutations."""
        with self._lock:
            return list(self._mutations)[-limit:]

    def get_mutations_by_source(self, source: str) -> List[MutationRecord]:
        """Get mutations from a specific source."""
        with self._lock:
            return [m for m in self._mutations if m.source == source]

    def get_mutations_by_type(self, change_type: str) -> List[MutationRecord]:
        """Get mutations of a specific type."""
        with self._lock:
            return [m for m in self._mutations if m.change_type == change_type]

    def get_mutations_for_object(self, object_id: str) -> List[MutationRecord]:
        """Get mutations for a specific object."""
        with self._lock:
            return [m for m in self._mutations if m.object_id == object_id]

    def get_summary(self) -> Dict[str, Any]:
        """Get mutation statistics."""
        with self._lock:
            total = len(self._mutations)
            if total == 0:
                return {"total": 0, "by_type": {}, "by_source": {}}

            by_type: Dict[str, int] = {}
            by_source: Dict[str, int] = {}

            for m in self._mutations:
                by_type[m.change_type] = by_type.get(m.change_type, 0) + 1
                by_source[m.source] = by_source.get(m.source, 0) + 1

            return {
                "total": total,
                "by_type": by_type,
                "by_source": by_source,
            }

    def save_log(self, path: str) -> None:
        """Persist mutations to file."""
        with self._lock:
            mutations = [m.to_dict() for m in self._mutations]
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(mutations, f, indent=2)

    def clear(self) -> None:
        """Clear all mutations (for testing)."""
        with self._lock:
            self._mutations.clear()


_global_log: Optional[MutationLog] = None


def get_mutation_log() -> MutationLog:
    """Get global mutation log."""
    global _global_log
    if _global_log is None:
        _global_log = MutationLog()
    return _global_log
