"""Memory System — facade over episodic, facts, and task stores.

Delegates to:
- storage.episodic.EpisodicStore
- storage.facts.FactStore
- storage.persistence (atomic writes, quarantine)

All existing callers use MemorySystem — this preserves the interface.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from storage.episodic import EpisodicStore
from storage.facts import FactStore
from storage.persistence import atomic_write_text, load_json_file, save_json_file


class MemorySystem:
    """Persistent memory system for autonomous agent."""

    def __init__(self, episodic_file: str = "data/episodic.jsonl",
                 facts_file: str = "data/facts.json",
                 tasks_file: str = "data/tasks.json"):
        self._episodic = EpisodicStore(Path(episodic_file))
        self._facts = FactStore(Path(facts_file))
        self.tasks_file = Path(tasks_file)
        self._lock = threading.RLock()
        self.tasks: Dict[str, Any] = {}
        self.load_tasks()

    # ── backward-compatible properties ────────────────────────────
    @property
    def episodic_file(self) -> Path:
        return self._episodic.file_path

    @property
    def facts_file(self) -> Path:
        return self._facts.file_path

    @property
    def episodic_log(self) -> List[Dict[str, Any]]:
        return self._episodic.log

    @episodic_log.setter
    def episodic_log(self, value):
        self._episodic.log = value

    @property
    def facts(self) -> Dict[str, Any]:
        return self._facts.facts

    @facts.setter
    def facts(self, value):
        self._facts.facts = value

    @property
    def facts_quarantined(self) -> bool:
        """True if the facts file was corrupt/unreadable at last load."""
        return self._facts._load_quarantined

    # ── load ──────────────────────────────────────────────────────
    def load_all(self):
        self._episodic.load()
        self._facts.load()
        self.load_tasks()

    def load_episodic(self):
        self._episodic.load()

    def load_facts(self):
        self._facts.load()

    def load_tasks(self):
        self.tasks = load_json_file(self.tasks_file, {})

    # ── episodic ──────────────────────────────────────────────────
    def save_episodic(self, event: str, context: Dict[str, Any] = None,
                      outcome: str = None, confidence: float = 1.0):
        self._episodic.save(event, context, outcome, confidence)

    def get_episodic_events(self, event_type: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        return self._episodic.get_events(event_type, limit)

    def get_recent_events(self, minutes: int = 60) -> List[Dict[str, Any]]:
        return self._episodic.get_recent(minutes)

    def clear_episodic(self):
        self._episodic.clear()

    # ── facts ─────────────────────────────────────────────────────
    def save_fact(self, key: str, value: Any, source: str = 'agent',
                  confidence: float = 1.0, topic: str = '', stratum: str = ''):
        self._facts.save_fact(key, value, source, confidence, topic, stratum)

    def get_fact(self, key: str, default: Any = None) -> Any:
        return self._facts.get(key, default)

    def get_fact_value(self, key: str, default: Any = None) -> Any:
        return self._facts.get_value(key, default)

    def get_fact_confidence(self, key: str) -> float:
        return self._facts.get_confidence(key)

    def mark_used(self, key: str, influenced: bool = False):
        self._facts.mark_used(key, influenced)

    def get_facts_by_source(self, source: str) -> Dict[str, Any]:
        return self._facts.get_by_source(source)

    def clear_facts(self):
        self._facts.clear()

    def compress(self) -> Dict[str, Any]:
        return self._facts.compress()

    # ── tasks ─────────────────────────────────────────────────────
    def save_task(self, task: Dict[str, Any]):
        with self._lock:
            task_id = task['id']
            task['updated_at'] = datetime.now().isoformat()
            self.tasks[task_id] = task
            self._save_tasks_file()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.tasks.get(task_id)

    def get_tasks_by_status(self, status: str) -> List[Dict[str, Any]]:
        return [t for t in self.tasks.values() if t.get('status') == status]

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        return list(self.tasks.values())

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        return self.get_tasks_by_status('pending')

    def clear_tasks(self):
        self.tasks = {}
        try:
            if self.tasks_file.exists():
                self.tasks_file.unlink()
        except Exception as e:
            print(f"Error clearing tasks: {e}")

    def _save_tasks_file(self):
        try:
            save_json_file(self.tasks_file, self.tasks)
        except Exception as e:
            print(f"Error saving tasks: {e}")

    # ── aggregate ─────────────────────────────────────────────────
    def store_reflection(self, reflection: Dict[str, Any]) -> None:
        self.save_episodic(
            'reflection', context=reflection,
            outcome='success' if reflection.get('success') else 'failure',
            confidence=float(reflection.get('confidence', 1.0)),
        )

    def get_stats(self) -> Dict[str, Any]:
        return {
            'episodic_count': len(self._episodic.log),
            'facts_count': len(self._facts.facts),
            'tasks_count': len(self.tasks),
            'episodic_file_size': self._episodic.file_path.stat().st_size if self._episodic.file_path.exists() else 0,
            'facts_file_size': self._facts.file_path.stat().st_size if self._facts.file_path.exists() else 0,
            'tasks_file_size': self.tasks_file.stat().st_size if self.tasks_file.exists() else 0,
        }

    def get_summary(self) -> Dict[str, Any]:
        stats = self.get_stats()
        last = self._episodic.log[-10:]
        successes = sum(1 for e in last if e.get('outcome') == 'success')
        return {
            'stats': stats,
            'recent_reflections': len([e for e in last if e.get('event') == 'reflection']),
            'recent_successes': successes,
            'recent_count': len(last),
        }
