"""Lightweight environment observer — monitors file changes, system stats, memory."""

from __future__ import annotations
import os
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class EnvironmentObserver:
    """Background observer that emits events on meaningful changes."""

    def __init__(self, watch_dirs: List[str], memory, bus, interval: float = 30.0):
        self._watch_dirs = [Path(d) for d in watch_dirs]
        self._memory = memory
        self._bus = bus
        self._interval = interval
        self._snapshot: Dict[str, float] = {}  # path -> mtime
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._take_snapshot()

    def _take_snapshot(self):
        snap: Dict[str, float] = {}
        for d in self._watch_dirs:
            if not d.exists():
                continue
            try:
                for p in d.rglob("*"):
                    if p.is_file():
                        try:
                            snap[str(p)] = p.stat().st_mtime
                        except OSError:
                            pass
            except Exception:
                pass
        self._snapshot = snap

    def _detect_changes(self) -> List[Dict[str, Any]]:
        changes: List[Dict[str, Any]] = []
        new_snap: Dict[str, float] = {}
        for d in self._watch_dirs:
            if not d.exists():
                continue
            try:
                for p in d.rglob("*"):
                    if p.is_file():
                        try:
                            mt = p.stat().st_mtime
                        except OSError:
                            continue
                        sp = str(p)
                        new_snap[sp] = mt
                        if sp not in self._snapshot:
                            changes.append({"type": "created", "path": sp})
                        elif mt != self._snapshot[sp]:
                            changes.append({"type": "modified", "path": sp})
            except Exception:
                pass
        for sp in self._snapshot:
            if sp not in new_snap:
                changes.append({"type": "deleted", "path": sp})
        self._snapshot = new_snap
        return changes

    def _get_sys_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith(("MemAvailable:", "MemTotal:", "SwapFree:")):
                        k, v = line.split(":", 1)
                        stats[k.strip()] = v.strip()
        except Exception:
            pass
        try:
            with open("/proc/loadavg") as f:
                stats["load"] = f.read().split()[0]
        except Exception:
            pass
        return stats

    def _loop(self):
        while not self._stop.is_set():
            changes = self._detect_changes()
            sys_stats = self._get_sys_stats()
            if changes:
                self._bus.emit("env_change", changes=changes[:20])
                self._memory.save_episodic("env_change", {"changes": changes[:20]}, confidence=0.7)
            if sys_stats:
                self._bus.emit("env_stats", stats=sys_stats)
            self._stop.wait(self._interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="env-observer")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
