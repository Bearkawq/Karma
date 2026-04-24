"""Scratchpad - Persistent notes storage for operators.

Features:
- Simple text storage
- Session persistence
- Quick operator notes
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class ScratchNote:
    """Single scratchpad note."""
    note_id: str
    content: str
    timestamp: str
    tags: List[str] = field(default_factory=list)


class Scratchpad:
    """Persistent scratchpad for operator notes."""

    def __init__(self, storage_path: Optional[str] = None):
        self._notes: List[ScratchNote] = []
        self._lock = Lock()
        self._storage_path = storage_path
        if storage_path:
            self._load()

    def add_note(self, content: str, tags: Optional[List[str]] = None) -> ScratchNote:
        """Add a new note."""
        import uuid
        note = ScratchNote(
            note_id=str(uuid.uuid4())[:8],
            content=content,
            timestamp=datetime.now().isoformat(),
            tags=tags or [],
        )

        with self._lock:
            self._notes.append(note)

        self._save()
        return note

    def update_note(self, note_id: str, content: str) -> bool:
        """Update an existing note."""
        with self._lock:
            for note in self._notes:
                if note.note_id == note_id:
                    note.content = content
                    note.timestamp = datetime.now().isoformat()
                    self._save()
                    return True
        return False

    def delete_note(self, note_id: str) -> bool:
        """Delete a note."""
        with self._lock:
            for i, note in enumerate(self._notes):
                if note.note_id == note_id:
                    self._notes.pop(i)
                    self._save()
                    return True
        return False

    def get_note(self, note_id: str) -> Optional[ScratchNote]:
        """Get a note by ID."""
        with self._lock:
            for note in self._notes:
                if note.note_id == note_id:
                    return note
        return None

    def get_all_notes(self) -> List[ScratchNote]:
        """Get all notes."""
        with self._lock:
            return list(self._notes)

    def get_recent_notes(self, limit: int = 20) -> List[ScratchNote]:
        """Get recent notes."""
        with self._lock:
            return self._notes[-limit:]

    def search_notes(self, query: str) -> List[ScratchNote]:
        """Search notes by content."""
        with self._lock:
            query_lower = query.lower()
            return [
                n for n in self._notes
                if query_lower in n.content.lower()
            ]

    def get_notes_by_tag(self, tag: str) -> List[ScratchNote]:
        """Get notes with a specific tag."""
        with self._lock:
            return [n for n in self._notes if tag in n.tags]

    def _save(self) -> None:
        """Persist to disk."""
        if not self._storage_path:
            return
        try:
            p = Path(self._storage_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {
                    "note_id": n.note_id,
                    "content": n.content,
                    "timestamp": n.timestamp,
                    "tags": n.tags,
                }
                for n in self._notes
            ]
            with open(p, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load(self) -> None:
        """Load from disk."""
        if not self._storage_path:
            return
        p = Path(self._storage_path)
        if not p.exists():
            return
        try:
            with open(p, "r") as f:
                data = json.load(f)
            self._notes = [
                ScratchNote(
                    note_id=d["note_id"],
                    content=d["content"],
                    timestamp=d["timestamp"],
                    tags=d.get("tags", []),
                )
                for d in data
            ]
        except Exception:
            pass

    def clear(self) -> None:
        """Clear all notes."""
        with self._lock:
            self._notes.clear()
        self._save()


_global_scratchpad: Optional[Scratchpad] = None


def get_scratchpad(storage_path: Optional[str] = None) -> Scratchpad:
    """Get global scratchpad."""
    global _global_scratchpad
    if _global_scratchpad is None:
        _global_scratchpad = Scratchpad(storage_path=storage_path)
    return _global_scratchpad
