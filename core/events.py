from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime
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
    def __init__(self, log_file: Optional[str] = None):
        self._subs: List[Callable[[Event], None]] = []
        self.log_file = log_file

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subs.append(fn)

    def emit(self, kind: str, **data: Any) -> None:
        ev = Event(t=now_iso(), kind=kind, data=data)
        # write jsonl (optional)
        if self.log_file:
            try:
                os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(ev), ensure_ascii=False, default=str) + "\n")
            except Exception:
                pass
        for fn in list(self._subs):
            try:
                fn(ev)
            except Exception:
                pass  # never let subscriber errors crash the agent
