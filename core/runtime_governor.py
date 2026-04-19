"""Runtime governor — lightweight runtime control plane for Karma.

Adds:
- adaptive exploration rate
- tool cooldowns after repeated failures
- intent parse caching
- recent success telemetry for scheduling decisions
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
from typing import Any, Deque, Dict, Optional, Tuple

_MISS = object()


@dataclass
class CachedIntent:
    intent: Optional[Dict[str, Any]]
    hits: int = 0


class RuntimeGovernor:
    def __init__(self, parse_cache_size: int = 64, cooldown_failures: int = 3, cooldown_turns: int = 3):
        self.parse_cache_size = max(8, int(parse_cache_size))
        self.cooldown_failures = max(2, int(cooldown_failures))
        self.cooldown_turns = max(1, int(cooldown_turns))
        self._parse_cache: Dict[str, CachedIntent] = {}
        self._parse_order: Deque[str] = deque()
        self._tool_failures: Dict[str, int] = {}
        self._tool_cooldowns: Dict[str, int] = {}
        self._recent_results: Deque[Tuple[bool, float]] = deque(maxlen=25)
        self._lock = threading.RLock()

    # parse cache
    def has_cached_intent(self, normalized_text: str) -> bool:
        with self._lock:
            return normalized_text in self._parse_cache

    def get_cached_intent(self, normalized_text: str):
        with self._lock:
            entry = self._parse_cache.get(normalized_text, _MISS)
            if entry is _MISS:
                return _MISS
            entry.hits += 1
            value = entry.intent
            if isinstance(value, dict):
                return dict(value)
            return value

    def cache_intent(self, normalized_text: str, intent: Optional[Dict[str, Any]]):
        if not normalized_text:
            return
        with self._lock:
            if normalized_text not in self._parse_cache:
                self._parse_order.append(normalized_text)
            cached = dict(intent) if isinstance(intent, dict) else intent
            self._parse_cache[normalized_text] = CachedIntent(intent=cached)
            while len(self._parse_order) > self.parse_cache_size:
                victim = self._parse_order.popleft()
                self._parse_cache.pop(victim, None)

    # tool cooling
    def allow_tool(self, tool_name: str) -> bool:
        if not tool_name:
            return True
        with self._lock:
            turns = self._tool_cooldowns.get(tool_name, 0)
            return turns <= 0

    def record_tool_result(self, tool_name: str, success: bool):
        if not tool_name:
            return
        with self._lock:
            if success:
                self._tool_failures[tool_name] = 0
                self._tool_cooldowns.pop(tool_name, None)
                return
            failures = self._tool_failures.get(tool_name, 0) + 1
            self._tool_failures[tool_name] = failures
            if failures >= self.cooldown_failures:
                self._tool_cooldowns[tool_name] = self.cooldown_turns

    def decay_cooldowns(self):
        with self._lock:
            expired = []
            for tool, turns in list(self._tool_cooldowns.items()):
                turns -= 1
                if turns <= 0:
                    expired.append(tool)
                else:
                    self._tool_cooldowns[tool] = turns
            for tool in expired:
                self._tool_cooldowns.pop(tool, None)
                self._tool_failures[tool] = 0

    # adaptive exploration
    def record_execution(self, success: bool, confidence: float):
        with self._lock:
            self._recent_results.append((bool(success), max(0.0, min(1.0, float(confidence)))))
        self.decay_cooldowns()

    def exploration_rate(self, base: float = 0.10) -> float:
        with self._lock:
            recent = list(self._recent_results)
        if not recent:
            return base
        success_rate = sum(1 for success, _ in recent if success) / len(recent)
        avg_conf = sum(conf for _, conf in recent) / len(recent)
        rate = base
        if success_rate < 0.45:
            rate += 0.06
        elif success_rate > 0.8:
            rate -= 0.03
        if avg_conf < 0.35:
            rate -= 0.02
        elif 0.35 <= avg_conf <= 0.65:
            rate += 0.02
        return max(0.02, min(0.18, rate))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            recent = list(self._recent_results)
            parse_cache_entries = len(self._parse_cache)
            parse_cache_hits = sum(entry.hits for entry in self._parse_cache.values())
            cooldowns = dict(self._tool_cooldowns)
        success_rate = 0.0
        if recent:
            success_rate = sum(1 for success, _ in recent if success) / len(recent)
        return {
            "parse_cache_entries": parse_cache_entries,
            "parse_cache_hits": parse_cache_hits,
            "cooldowns": cooldowns,
            "recent_success_rate": round(success_rate, 3),
            "exploration_rate": round(self.exploration_rate(), 3),
        }
