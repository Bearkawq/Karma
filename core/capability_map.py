"""Capability map — tracks tool performance, capability clusters, and repeated patterns.

v2: Richer capability graph with context/workflow/failure patterns per tool.
    tool_score() now considers recency, context match, failure streaks.
"""

from __future__ import annotations
import json
import os
import tempfile
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class CapabilityMap:
    """Capability graph tracking tool performance, contexts, and task clusters."""

    def __init__(self, persist_path: str = "data/capability_map.json"):
        self._path = Path(persist_path)
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._intent_counts: Dict[str, int] = defaultdict(int)
        self._failure_streaks: Dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                self._tools = data.get("tools", {})
                self._intent_counts = defaultdict(int, data.get("intent_counts", {}))
                self._failure_streaks = defaultdict(int, data.get("failure_streaks", {}))
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
            data = {
                "tools": self._tools,
                "intent_counts": dict(self._intent_counts),
                "failure_streaks": dict(self._failure_streaks),
                "updated": datetime.now().isoformat(),
            }
            self._atomic_write(json.dumps(data, indent=2))

    def _ensure_entry(self, tool_name: str) -> Dict[str, Any]:
        if tool_name not in self._tools:
            self._tools[tool_name] = {
                "successes": 0, "failures": 0, "tasks": [],
                "best_contexts": [], "failure_contexts": [],
                "common_inputs": [], "linked_workflows": [],
                "recent_results": [],
            }
        return self._tools[tool_name]

    def record(self, tool_name: str, intent_name: str, success: bool,
               context: str = "", inputs: str = ""):
        with self._lock:
            entry = self._ensure_entry(tool_name)
            if success:
                entry["successes"] += 1
                self._failure_streaks[intent_name] = 0
                if context and context not in entry.get("best_contexts", []):
                    entry.setdefault("best_contexts", []).append(context)
                    entry["best_contexts"] = entry["best_contexts"][-10:]
            else:
                entry["failures"] += 1
                self._failure_streaks[intent_name] = self._failure_streaks.get(intent_name, 0) + 1
                if context and context not in entry.get("failure_contexts", []):
                    entry.setdefault("failure_contexts", []).append(context)
                    entry["failure_contexts"] = entry["failure_contexts"][-10:]
            recent = entry.setdefault("recent_results", [])
            recent.append(success)
            if len(recent) > 20:
                entry["recent_results"] = recent[-20:]
            if intent_name not in entry["tasks"]:
                entry["tasks"].append(intent_name)
            if inputs and inputs not in entry.get("common_inputs", []):
                entry.setdefault("common_inputs", []).append(inputs)
                entry["common_inputs"] = entry["common_inputs"][-20:]
            self._intent_counts[intent_name] += 1
        self._save()

    def success_rate(self, tool_name: str) -> float:
        with self._lock:
            entry = self._tools.get(tool_name)
            if not entry:
                return 0.5
            total = entry["successes"] + entry["failures"]
            return entry["successes"] / total if total > 0 else 0.5

    def recent_success_rate(self, tool_name: str) -> float:
        with self._lock:
            entry = self._tools.get(tool_name)
            if not entry:
                return 0.5
            recent = list(entry.get("recent_results", []))
        if not recent:
            return self.success_rate(tool_name)
        return sum(1 for r in recent if r) / len(recent)

    def tool_score(self, tool_name: str, context: str = "",
                   intent: str = "", input_shape: str = "") -> float:
        with self._lock:
            entry = self._tools.get(tool_name)
            if not entry:
                return 0.5
            best = list(entry.get("best_contexts", []))
            common = list(entry.get("common_inputs", []))
            workflows = list(entry.get("linked_workflows", []))
            streak = self._failure_streaks.get(intent, 0) if intent else 0
        score = 0.0
        score += self.recent_success_rate(tool_name) * 0.4
        score += self.success_rate(tool_name) * 0.2
        if context:
            if context in best:
                score += 0.15
            elif any(context in c or c in context for c in best):
                score += 0.07
        if input_shape:
            if input_shape in common:
                score += 0.1
            elif any(input_shape in c for c in common):
                score += 0.05
        if workflows:
            score += 0.05
            if intent and any(intent in wf for wf in workflows):
                score += 0.05
        if streak >= 3:
            score -= 0.1 * min(streak, 5) / 5
        return max(0.0, min(1.0, score))

    def get_capability_cluster(self, intent: str) -> Dict[str, Any]:
        with self._lock:
            items = list(self._tools.items())
        cluster_tools = []
        cluster_contexts = set()
        cluster_workflows = []
        success_patterns = []
        failure_patterns = []
        for tool_name, entry in items:
            if intent in entry.get("tasks", []):
                sr = self.success_rate(tool_name)
                cluster_tools.append({"tool": tool_name, "success_rate": sr})
                cluster_contexts.update(entry.get("best_contexts", []))
                cluster_workflows.extend(entry.get("linked_workflows", []))
                if sr > 0.7:
                    success_patterns.append(tool_name)
                elif sr < 0.3:
                    failure_patterns.append(tool_name)
        return {
            "intent": intent,
            "tools": cluster_tools,
            "contexts": list(cluster_contexts)[:10],
            "workflows": cluster_workflows[:10],
            "success_patterns": success_patterns,
            "failure_patterns": failure_patterns,
        }

    def detect_pressure(self, threshold_repeats: int = 5, threshold_failures: int = 3) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []
        with self._lock:
            intent_counts = list(self._intent_counts.items())
            failure_streaks = dict(self._failure_streaks)
            tools_items = list(self._tools.items())
        for intent, count in intent_counts:
            if count >= threshold_repeats:
                related_wf = []
                for _, t_data in tools_items:
                    if intent in t_data.get("tasks", []):
                        related_wf.extend(t_data.get("linked_workflows", []))
                streak = failure_streaks.get(intent, 0)
                utility = count + streak * 2
                proposals.append({
                    "type": "repeated_task",
                    "intent": intent,
                    "need_count": count,
                    "failed_workarounds": streak,
                    "related_workflows": related_wf[:5],
                    "estimated_utility": utility,
                    "suggestion": f"Create helper tool for '{intent}' (executed {count}x, utility={utility})",
                })
        for intent, streak in failure_streaks.items():
            if streak >= threshold_failures:
                proposals.append({
                    "type": "failure_streak",
                    "intent": intent,
                    "streak": streak,
                    "estimated_utility": streak * 3,
                    "suggestion": f"Repeated failures on '{intent}' ({streak}x) — consider alternate approach or new tool",
                })
        proposals.sort(key=lambda p: p.get("estimated_utility", 0), reverse=True)
        return proposals

    def prune_tools(self, valid_tools: List[str]) -> List[str]:
        valid = set(valid_tools or [])
        with self._lock:
            removed = [name for name in list(self._tools.keys()) if name not in valid]
            for name in removed:
                self._tools.pop(name, None)
        if removed:
            self._save()
        return removed

    def get_map(self) -> Dict[str, Any]:
        with self._lock:
            items = list(self._tools.items())
        result = {}
        for name, entry in items:
            total = entry["successes"] + entry["failures"]
            result[name] = {
                "success_rate": round(entry["successes"] / total, 2) if total else 0.5,
                "total_uses": total,
                "tasks": entry["tasks"],
            }
        return result

    def get_full_map(self) -> Dict[str, Any]:
        with self._lock:
            items = list(self._tools.items())
        result = {}
        for name, entry in items:
            total = entry["successes"] + entry["failures"]
            result[name] = {
                "success_rate": round(entry["successes"] / total, 2) if total else 0.5,
                "total_uses": total,
                "tasks": entry.get("tasks", []),
                "best_contexts": entry.get("best_contexts", []),
                "failure_contexts": entry.get("failure_contexts", []),
                "common_inputs": entry.get("common_inputs", []),
                "linked_workflows": entry.get("linked_workflows", []),
                "recent_success_rate": round(self.recent_success_rate(name), 2),
            }
        return result
