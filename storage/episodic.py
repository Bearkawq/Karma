"""Episodic memory — append-only event log with rotation and compression.

Extracted from MemorySystem for cleaner boundaries.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from storage.persistence import atomic_write_text


class EpisodicStore:
    """Append-only JSONL event log with size rotation."""

    _MAX_ENTRIES = 5000
    _MAX_FILE_MB = 10

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()
        self.log: List[Dict[str, Any]] = []
        self._last_save_failed: bool = False
        self.load()

    def load(self):
        self.log = []
        if not self.file_path.exists():
            return
        try:
            size_mb = self.file_path.stat().st_size / (1024 * 1024)
            if size_mb > self._MAX_FILE_MB:
                self._rotate()
            with open(self.file_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    try:
                        self.log.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if len(self.log) > self._MAX_ENTRIES:
                self.log = self.log[-self._MAX_ENTRIES:]
        except Exception as e:
            print(f"Error loading episodic memory: {e}")

    def save(self, event: str, context: Dict[str, Any] = None,
             outcome: str = None, confidence: float = 1.0):
        # Append guarantee: each entry is a single JSON line followed by '\n'.
        # f.flush() pushes to the OS buffer; a crash after flush but before the
        # OS writes to disk can lose the entry. A crash mid-write leaves a partial
        # (non-JSON) last line, which load() silently skips — no data corruption
        # to previously written entries. The in-memory log always reflects the
        # append regardless of disk outcome; _last_save_failed tracks disk failures.
        entry = {
            'timestamp': datetime.now().isoformat(),
            'event': event,
            'context': context or {},
            'outcome': outcome,
            'confidence': confidence,
        }
        with self._lock:
            self.log.append(entry)
            try:
                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                # If the file has content not ending in '\n' (partial line from
                # an interrupted prior write), prepend '\n' so this entry starts
                # on a clean line. load() skips the partial line; without this
                # the new entry would merge with it and also be lost on reload.
                prefix = ''
                if self.file_path.exists() and self.file_path.stat().st_size > 0:
                    with open(self.file_path, 'rb') as rf:
                        rf.seek(-1, 2)
                        if rf.read(1) != b'\n':
                            prefix = '\n'
                with open(self.file_path, 'a', encoding='utf-8') as f:
                    f.write(prefix + json.dumps(entry) + '\n')
                    f.flush()
                self._last_save_failed = False
            except Exception as e:
                self._last_save_failed = True
                print(f"Error saving episodic memory: {e}")

    def get_events(self, event_type: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        events = self.log[-limit:]
        if event_type:
            events = [e for e in events if e.get('event') == event_type]
        return events

    def get_recent(self, minutes: int = 60) -> List[Dict[str, Any]]:
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return [e for e in self.log if datetime.fromisoformat(e['timestamp']) > cutoff]

    def clear(self):
        self.log = []
        try:
            if self.file_path.exists():
                self.file_path.unlink()
        except Exception as e:
            print(f"Error clearing episodic memory: {e}")

    def _rotate(self):
        try:
            lines = self.file_path.read_text(encoding='utf-8', errors='replace').splitlines()
            keep = len(lines) // 2
            archive = self.file_path.with_suffix('.old.jsonl')
            atomic_write_text(archive, "\n".join(lines[:len(lines) - keep]) + ("\n" if lines else ""))
            atomic_write_text(self.file_path, "\n".join(lines[-keep:]) + ("\n" if keep else ""))
        except Exception:
            pass
