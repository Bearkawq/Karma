"""Meta observation — analyzes execution history and adjusts planner weights."""

from __future__ import annotations
import json
import os
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class MetaObserver:
    """Every N cycles, analyze agent performance and adjust scoring."""

    def __init__(self, persist_path: str = "data/meta_state.json", cycle_interval: int = 20):
        self._path = Path(persist_path)
        self._cycle_interval = cycle_interval
        self._cycle_count = 0
        # Adjustable scoring weights
        self.sym_weight = 0.5
        self.ml_weight = 0.5
        self.cap_weight = 0.0  # capability map bonus
        # Time tracking
        self._action_times: Dict[str, List[float]] = defaultdict(list)
        self._action_start: Optional[float] = None
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                self.sym_weight = data.get("sym_weight", 0.5)
                self.ml_weight = data.get("ml_weight", 0.5)
                self.cap_weight = data.get("cap_weight", 0.0)
                self._cycle_count = data.get("cycle_count", 0)
                self._action_times = defaultdict(list, {
                    k: v for k, v in data.get("action_times", {}).items()
                })
            except Exception:
                pass

    def _atomic_write(self, text: str):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self._path.name + '.', suffix='.tmp', dir=str(self._path.parent))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self._path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except Exception:
                    pass

    def _save(self):
        with self._lock:
            trimmed = {k: v[-50:] for k, v in self._action_times.items()}
            data = {
                "sym_weight": round(self.sym_weight, 3),
                "ml_weight": round(self.ml_weight, 3),
                "cap_weight": round(self.cap_weight, 3),
                "cycle_count": self._cycle_count,
                "action_times": trimmed,
                "updated": datetime.now().isoformat(),
            }
            self._atomic_write(json.dumps(data, indent=2))

    def start_action(self):
        """Call before executing an action to track duration."""
        with self._lock:
            self._action_start = time.monotonic()

    def end_action(self, action_name: str):
        """Call after executing an action to record duration."""
        with self._lock:
            if self._action_start is not None:
                elapsed = time.monotonic() - self._action_start
                self._action_times[action_name].append(round(elapsed, 3))
                if len(self._action_times[action_name]) > 50:
                    self._action_times[action_name] = self._action_times[action_name][-50:]
                self._action_start = None

    def avg_duration(self, action_name: str) -> Optional[float]:
        """Average duration for an action type."""
        with self._lock:
            times = list(self._action_times.get(action_name, []))
        if not times:
            return None
        return sum(times) / len(times)

    def tick(self, execution_log: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Called every cycle. Returns adjustment report every N cycles."""
        self._cycle_count += 1
        if self._cycle_count % self._cycle_interval != 0:
            return None

        # Analyze last N entries
        recent = execution_log[-self._cycle_interval:]
        if not recent:
            self._save()
            return None

        successes = sum(1 for e in recent if e.get("success"))
        total = len(recent)
        success_rate = successes / total if total else 0.5

        # Adjust weights: if success rate is low, lean more on capability map
        if success_rate < 0.5:
            self.cap_weight = min(0.3, self.cap_weight + 0.05)
            self.sym_weight = max(0.35, self.sym_weight - 0.025)
            self.ml_weight = max(0.35, self.ml_weight - 0.025)
        elif success_rate > 0.8:
            # Performing well, slowly normalize
            self.cap_weight = max(0.0, self.cap_weight - 0.02)
            self.sym_weight = min(0.5, self.sym_weight + 0.01)
            self.ml_weight = min(0.5, self.ml_weight + 0.01)

        report = {"cycle": self._cycle_count, "success_rate": round(success_rate, 2),
                  "weights": {"sym": self.sym_weight, "ml": self.ml_weight, "cap": self.cap_weight}}
        self._save()
        return report
