"""Episodic memory — append-only event log with rotation and compression.

Extracted from MemorySystem for cleaner boundaries.
"""

from __future__ import annotations

import json
import os
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
        # Append guarantees:
        # - Each entry is one JSON line terminated by '\n'.
        # - If the file's last byte is not '\n' (truncated tail from a prior
        #   interrupted write), a '\n' is prepended so the new entry starts on a
        #   clean line. load() already skips the partial line; without this guard
        #   the new entry would merge with it and be lost on reload.
        # - flush() moves data from Python buffers to the OS page cache.
        # - fsync() on the file requests that the OS flush the page cache to
        #   durable storage. A process crash after fsync() will not lose the entry.
        # - First-create durability: when appending to a brand-new file, the
        #   directory entry itself may not be durable until the parent directory is
        #   fsynced. A power/OS crash between file-fsync and dir-fsync can leave the
        #   file missing even though its data was flushed. We close this gap by
        #   fsyncing the parent directory only on first create.
        # - Subsequent appends to an existing file do not re-fsync the directory;
        #   the inode is already linked and durable.
        # - A crash mid-write (before flush/fsync) leaves a partial non-JSON last
        #   line; load() skips it, leaving all prior entries intact.
        # - Rotation durability: _rotate() rewrites both the archive and the main
        #   file via atomic_write_text (temp write + os.replace). After both
        #   replacements, the parent directory is fsynced once so the renamed
        #   directory entries are durable. Rotation dir-fsync failures set
        #   _last_save_failed without aborting the rotation itself.
        # - Still not a transactional WAL: concurrent writes are not coordinated.
        # - The in-memory log always reflects the append regardless of disk outcome.
        # - _last_save_failed is set on any exception (including dir-fsync), cleared
        #   on full success.
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
                is_new_file = not self.file_path.exists()
                prefix = ''
                if not is_new_file and self.file_path.stat().st_size > 0:
                    with open(self.file_path, 'rb') as rf:
                        rf.seek(-1, 2)
                        if rf.read(1) != b'\n':
                            prefix = '\n'
                with open(self.file_path, 'a', encoding='utf-8') as f:
                    f.write(prefix + json.dumps(entry) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
                if is_new_file:
                    dir_fd = os.open(str(self.file_path.parent), os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
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
        # Rotation rewrites both archive and main file via atomic replace.
        # After both writes succeed, fsync the parent directory once so both
        # renamed directory entries are durable. If the writes fail, silently
        # skip (as before); if only the dir-fsync fails, set _last_save_failed
        # but do not abort — the data is written, just not directory-durable.
        try:
            lines = self.file_path.read_text(encoding='utf-8', errors='replace').splitlines()
            keep = len(lines) // 2
            archive = self.file_path.with_suffix('.old.jsonl')
            atomic_write_text(archive, "\n".join(lines[:len(lines) - keep]) + ("\n" if lines else ""))
            # fsync parent directory after archive replace to make the rename durable
            try:
                dir_fd = os.open(str(self.file_path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception as e:
                self._last_save_failed = True
                print(f"Error fsyncing directory after archive replace: {e}")
            atomic_write_text(self.file_path, "\n".join(lines[-keep:]) + ("\n" if keep else ""))
            # fsync parent directory after main file replace as well
            try:
                dir_fd = os.open(str(self.file_path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception as e:
                self._last_save_failed = True
                print(f"Error fsyncing directory after main replace: {e}")
        except Exception:
            return
