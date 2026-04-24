"""Drop Bay - File/folder ingestion interface.

Operators can:
- drop files
- drop folders
- trigger ingest action

Shows:
- queued files
- processing state
- ingest results
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from threading import Lock
from collections import deque


DROP_STATES = frozenset(["queued", "processing", "completed", "failed"])


@dataclass
class DropItem:
    """File or folder in drop bay."""
    path: str
    is_directory: bool
    timestamp: str
    state: str = "queued"
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

    @property
    def name(self) -> str:
        return os.path.basename(self.path) or self.path


class DropBay:
    """File/folder drop queue for ingestion."""

    def __init__(self, max_items: int = 100):
        self._items: deque = deque(maxlen=max_items)
        self._lock = Lock()
        self._processing = False

    def add_drop(self, path: str) -> DropItem:
        """Add a file or folder to drop bay."""
        item = DropItem(
            path=path,
            is_directory=os.path.isdir(path),
            timestamp=datetime.now().isoformat(),
            state="queued",
        )

        with self._lock:
            self._items.append(item)

        return item

    def add_multiple(self, paths: List[str]) -> List[DropItem]:
        """Add multiple files/folders."""
        return [self.add_drop(p) for p in paths]

    def get_queued_items(self) -> List[DropItem]:
        """Get all queued items."""
        with self._lock:
            return [i for i in self._items if i.state == "queued"]

    def get_processing_items(self) -> List[DropItem]:
        """Get items being processed."""
        with self._lock:
            return [i for i in self._items if i.state == "processing"]

    def get_completed_items(self, limit: int = 20) -> List[DropItem]:
        """Get completed items."""
        with self._lock:
            completed = [i for i in self._items if i.state == "completed"]
            return completed[-limit:]

    def get_failed_items(self) -> List[DropItem]:
        """Get failed items."""
        with self._lock:
            return [i for i in self._items if i.state == "failed"]

    def get_all_items(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all items as dicts."""
        with self._lock:
            items = list(self._items)[-limit:]
            return [
                {
                    "path": i.path,
                    "name": i.name,
                    "is_directory": i.is_directory,
                    "timestamp": i.timestamp,
                    "state": i.state,
                    "error": i.error,
                }
                for i in items
            ]

    def mark_processing(self, path: str) -> bool:
        """Mark an item as processing."""
        with self._lock:
            for item in self._items:
                if item.path == path and item.state == "queued":
                    item.state = "processing"
                    return True
        return False

    def mark_completed(self, path: str, result: Optional[Dict[str, Any]] = None) -> bool:
        """Mark an item as completed."""
        with self._lock:
            for item in self._items:
                if item.path == path and item.state == "processing":
                    item.state = "completed"
                    item.result = result
                    return True
        return False

    def mark_failed(self, path: str, error: str) -> bool:
        """Mark an item as failed."""
        with self._lock:
            for item in self._items:
                if item.path == path:
                    item.state = "failed"
                    item.error = error
                    return True
        return False

    def get_status(self) -> Dict[str, Any]:
        """Get drop bay status."""
        with self._lock:
            queued = sum(1 for i in self._items if i.state == "queued")
            processing = sum(1 for i in self._items if i.state == "processing")
            completed = sum(1 for i in self._items if i.state == "completed")
            failed = sum(1 for i in self._items if i.state == "failed")

            return {
                "total": len(self._items),
                "queued": queued,
                "processing": processing,
                "completed": completed,
                "failed": failed,
                "is_processing": self._processing,
            }

    def clear_completed(self) -> None:
        """Clear completed items."""
        with self._lock:
            self._items = deque(
                (i for i in self._items if i.state not in ("completed", "failed")),
                maxlen=self._items.maxlen
            )

    def clear_all(self) -> None:
        """Clear all items."""
        with self._lock:
            self._items.clear()


_global_bay: Optional[DropBay] = None


def get_drop_bay() -> DropBay:
    """Get global drop bay."""
    global _global_bay
    if _global_bay is None:
        _global_bay = DropBay()
    return _global_bay
