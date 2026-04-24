from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional
import json
import os


@dataclass
class Event:
    t: str
    kind: str
    data: Dict[str, Any]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class EventBus:
    """Small JSONL event bus with bounded on-disk growth."""

    def __init__(self, log_file: Optional[str] = None, max_bytes: int = 10 * 1024 * 1024):
        self._subs: List[Callable[[Event], None]] = []
        self.log_file = log_file
        self.max_bytes = max_bytes
        self._lock = RLock()

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subs.append(fn)

    def _rotate_if_needed(self) -> None:
        if not self.log_file:
            return
        path = Path(self.log_file)
        if not path.exists() or path.stat().st_size <= self.max_bytes:
            return
        archive = path.with_suffix(path.suffix + ".old")
        try:
            if archive.exists():
                archive.unlink()
            os.replace(path, archive)
            path.touch()
            try:
                dir_fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                pass
        except Exception:
            pass

    def emit(self, kind: str, **data: Any) -> None:
        ev = Event(t=now_iso(), kind=kind, data=data)
        if self.log_file:
            with self._lock:
                try:
                    os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
                    self._rotate_if_needed()
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(asdict(ev), ensure_ascii=False, default=str) + "\n")
                        f.flush()
                except Exception:
                    pass
        for fn in list(self._subs):
            try:
                fn(ev)
            except Exception:
                pass
