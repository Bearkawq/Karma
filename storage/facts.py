"""Facts memory — key-value store with confidence, decay, and compression.

Extracted from MemorySystem for cleaner boundaries.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from storage.persistence import quarantine_file, save_json_file

_DECAY_RATE = 0.02


class FactStore:
    """Persistent key-value fact store with confidence tracking."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()
        self.facts: Dict[str, Any] = {}
        self._load_quarantined: bool = False
        self._last_save_failed: bool = False
        self.load()

    def load(self):
        self._load_quarantined = False
        if not self.file_path.exists():
            self.facts = {}
            return
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.facts = json.load(f)
        except Exception:
            quarantine_file(self.file_path)
            self._load_quarantined = True
            self.facts = {}

    def save_fact(self, key: str, value: Any, source: str = 'agent',
                  confidence: float = 1.0, topic: str = '', stratum: str = ''):
        with self._lock:
            existing = self.facts.get(key)
            use_count = 0
            influence_count = 0
            last_used = ""
            if isinstance(existing, dict):
                use_count = existing.get("use_count", 0)
                influence_count = existing.get("influence_count", 0)
                last_used = existing.get("last_used", "")
            self.facts[key] = {
                'value': value, 'source': source, 'confidence': confidence,
                'last_updated': datetime.now().isoformat(),
                'use_count': use_count, 'influence_count': influence_count,
                'last_used': last_used,
            }
            if topic:
                self.facts[key]['topic'] = topic
            if stratum:
                self.facts[key]['stratum'] = stratum
            self._save()

    def get(self, key: str, default: Any = None) -> Any:
        return self.facts.get(key, default)

    def get_value(self, key: str, default: Any = None) -> Any:
        entry = self.facts.get(key)
        if entry is None:
            return default
        if isinstance(entry, dict):
            return entry.get("value", entry)
        return entry

    def get_confidence(self, key: str) -> float:
        entry = self.facts.get(key)
        if isinstance(entry, dict):
            return float(entry.get("confidence", 0.0))
        return 0.0

    def mark_used(self, key: str, influenced: bool = False):
        with self._lock:
            entry = self.facts.get(key)
            if not isinstance(entry, dict):
                return
            entry["use_count"] = entry.get("use_count", 0) + 1
            entry["last_used"] = datetime.now().isoformat()
            if influenced:
                entry["influence_count"] = entry.get("influence_count", 0) + 1
            self._save()

    def get_by_source(self, source: str) -> Dict[str, Any]:
        return {k: v for k, v in self.facts.items() if v.get('source') == source}

    def clear(self):
        self.facts = {}
        try:
            if self.file_path.exists():
                self.file_path.unlink()
        except Exception as e:
            print(f"Error clearing facts: {e}")

    def compress(self) -> Dict[str, Any]:
        """Deduplicate, cluster, and decay stale facts."""
        report = {"removed_dupes": 0, "clustered": 0, "decayed": 0, "pruned_dead": 0}
        with self._lock:
            # Dedup
            seen: Dict[str, str] = {}
            dupes: List[str] = []
            for key, entry in list(self.facts.items()):
                val = entry.get("value", entry) if isinstance(entry, dict) else entry
                vh = str(val).strip().lower()[:200]
                if vh in seen:
                    existing_conf = self.get_confidence(seen[vh])
                    this_conf = self.get_confidence(key)
                    if this_conf > existing_conf:
                        dupes.append(seen[vh])
                        seen[vh] = key
                    else:
                        dupes.append(key)
                else:
                    seen[vh] = key
            for k in dupes:
                self.facts.pop(k, None)
            report["removed_dupes"] = len(dupes)

            # Cluster large prefix groups
            clusters: Dict[str, List[str]] = {}
            for key in list(self.facts.keys()):
                parts = key.split(":")
                prefix = ":".join(parts[:3]) if len(parts) >= 3 else key
                clusters.setdefault(prefix, []).append(key)
            for prefix, keys in clusters.items():
                if len(keys) <= 10:
                    continue
                entries = [(k, self.get_confidence(k)) for k in keys]
                entries.sort(key=lambda x: x[1], reverse=True)
                summary_parts = [str(self.get_value(k, ""))[:100] for k, _ in entries[:5]]
                avg_conf = sum(c for _, c in entries) / len(entries)
                for k in keys:
                    self.facts.pop(k, None)
                self.facts[prefix + ":summary"] = {
                    "value": " | ".join(summary_parts),
                    "source": "compression",
                    "confidence": round(min(avg_conf, 1.0), 3),
                    "last_updated": datetime.now().isoformat(),
                    "merged_count": len(keys),
                }
                report["clustered"] += len(keys)

            # Decay stale entries
            cutoff = datetime.now().timestamp() - 7 * 86400
            for _, entry in list(self.facts.items()):
                if not isinstance(entry, dict):
                    continue
                try:
                    ts = datetime.fromisoformat(entry.get("last_updated", "")).timestamp()
                except (ValueError, TypeError):
                    ts = 0
                if ts < cutoff:
                    use_count = entry.get("use_count", 0)
                    influence_count = entry.get("influence_count", 0)
                    usefulness = min(1.0, (use_count * 0.1 + influence_count * 0.2))
                    decay = _DECAY_RATE * max(0.2, 1.0 - usefulness)
                    entry["confidence"] = round(max(0.05, float(entry.get("confidence", 1.0)) - decay), 3)
                    report["decayed"] += 1

            # Prune dead entries
            dead = [k for k, e in self.facts.items()
                    if isinstance(e, dict) and float(e.get("confidence", 1.0)) < 0.06
                    and e.get("use_count", 0) == 0 and e.get("influence_count", 0) == 0]
            for k in dead:
                self.facts.pop(k, None)
            report["pruned_dead"] = len(dead)
            self._save()
        return report

    def _save(self):
        try:
            save_json_file(self.file_path, self.facts)
            self._last_save_failed = False
        except Exception as e:
            self._last_save_failed = True
            print(f"Error saving facts: {e}")
