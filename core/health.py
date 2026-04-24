"""Health monitor — periodic self-check, diagnosis, repair classes, and learned repair policy.

v2: Adds repair classification, outcome tracking, and lazy-file detection.
"""

from __future__ import annotations
import json
import importlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Repair classes for issue classification
REPAIR_CLASSES = {
    "import_error": {"severity": "critical", "auto_fixable": False},
    "missing_file": {"severity": "warning", "auto_fixable": True},
    "memory_bloat": {"severity": "warning", "auto_fixable": True},
    "confidence_collapse": {"severity": "critical", "auto_fixable": False},
    "bad_tool": {"severity": "warning", "auto_fixable": False},
    "corrupted_memory": {"severity": "warning", "auto_fixable": True},
    "logging_bloat": {"severity": "warning", "auto_fixable": True},
    "empty_generated_tool": {"severity": "warning", "auto_fixable": True},
}

# Files that are lazy-created (not truly missing if absent)
_LAZY_FILES = {"data/tasks.json", "data/episodic.jsonl", "data/capability_map.json",
               "data/workflows.json", "data/failure_fingerprints.json",
               "data/concept_crystals.json", "data/health_memory.json"}


class HealthMonitor:
    """Checks agent subsystems for failures, corruption, and anomalies.

    Tracks repair history and learns which fixes work.
    """

    def __init__(self, base_dir: str, memory, capability_map=None, retrieval_bus=None):
        self._base_dir = Path(base_dir)
        self._memory = memory
        self._cap_map = capability_map
        self._retrieval = retrieval_bus
        self._last_check: Optional[str] = None
        # Repair outcome tracking: {repair_class: [{attempt, outcome, timestamp}]}
        self._repair_history: Dict[str, List[Dict[str, Any]]] = {}
        self._load_repair_history()

    def _repair_history_path(self) -> Path:
        return self._base_dir / "data" / "repair_history.json"

    def _load_repair_history(self):
        p = self._repair_history_path()
        if p.exists():
            try:
                self._repair_history = json.loads(p.read_text())
            except Exception:
                self._repair_history = {}

    def _save_repair_history(self):
        p = self._repair_history_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._repair_history, indent=2, default=str))

    def record_repair_outcome(self, repair_class: str, attempt: str, success: bool):
        """Record whether a repair attempt worked."""
        self._repair_history.setdefault(repair_class, [])
        self._repair_history[repair_class].append({
            "attempt": attempt,
            "success": success,
            "timestamp": datetime.now().isoformat(),
        })
        # Keep last 20 per class
        self._repair_history[repair_class] = self._repair_history[repair_class][-20:]
        self._save_repair_history()

    def get_repair_success_rate(self, repair_class: str) -> float:
        """Success rate for a repair class. 0.5 if no history."""
        history = self._repair_history.get(repair_class, [])
        if not history:
            return 0.5
        return sum(1 for h in history if h["success"]) / len(history)

    def _classify_issue(self, issue: Dict[str, Any]) -> str:
        """Classify an issue into a repair class."""
        subsystem = issue.get("subsystem", "")
        issue_text = issue.get("issue", "").lower()

        if subsystem == "imports" or "import" in issue_text:
            return "import_error"
        if subsystem == "storage" and "missing" in issue_text:
            return "missing_file"
        if subsystem == "memory" and ("large" in issue_text or "mb" in issue_text):
            return "memory_bloat"
        if subsystem == "memory" and "malformed" in issue_text:
            return "corrupted_memory"
        if subsystem == "confidence" or "collapse" in issue_text:
            return "confidence_collapse"
        if subsystem == "tools" and "success rate" in issue_text:
            return "bad_tool"
        if subsystem == "logging" or "log" in issue_text:
            return "logging_bloat"
        if "empty" in issue_text and "generated" in issue_text:
            return "empty_generated_tool"
        return "unknown"

    def run_check(self) -> Dict[str, Any]:
        """Full self-check. Returns health report with classified issues."""
        issues: List[Dict[str, Any]] = []
        self._last_check = datetime.now().isoformat()

        issues.extend(self._check_tool_failures())
        issues.extend(self._check_imports())
        issues.extend(self._check_missing_files())
        issues.extend(self._check_memory_health())
        issues.extend(self._check_log_growth())
        issues.extend(self._check_confidence_collapse())
        issues.extend(self._check_generated_tools())

        # Classify each issue
        for issue in issues:
            rc = self._classify_issue(issue)
            issue["repair_class"] = rc
            issue["repair_success_rate"] = self.get_repair_success_rate(rc)

        # Retrieve past repair evidence if retrieval bus available
        repair_evidence = []
        if self._retrieval and issues:
            query = " ".join(i["issue"][:30] for i in issues[:3])
            repair_evidence = self._retrieval.retrieve_context_bundle(query, "repair")

        # Store health events
        if self._retrieval:
            for issue in issues:
                self._retrieval.store_health_event(
                    issue["issue"], issue["severity"],
                    issue.get("suggestion", ""), issue.get("subsystem", ""),
                )

        report = {
            "timestamp": self._last_check,
            "issues_found": len(issues),
            "issues": issues,
            "past_repairs": [e.to_dict() for e in repair_evidence[:5]],
            "repair_policy": {rc: self.get_repair_success_rate(rc)
                              for rc in set(i.get("repair_class", "") for i in issues) if rc},
            "status": "healthy" if not issues else (
                "critical" if any(i["severity"] == "critical" for i in issues) else "warning"
            ),
        }
        return report

    def _check_tool_failures(self) -> List[Dict[str, Any]]:
        issues = []
        if not self._cap_map:
            return issues

        # Ignore stale capability entries for tools that are no longer registered.
        valid_tools = None
        if self._retrieval and hasattr(self._retrieval, "tool_manager") and hasattr(self._retrieval.tool_manager, "list_tools"):
            try:
                valid_tools = set(self._retrieval.tool_manager.list_tools())
            except Exception:
                valid_tools = None
        if valid_tools is not None and hasattr(self._cap_map, "prune_tools"):
            try:
                self._cap_map.prune_tools(sorted(valid_tools))
            except Exception:
                pass

        for name, info in self._cap_map.get_map().items():
            if valid_tools is not None and name not in valid_tools:
                continue
            if info["total_uses"] >= 5 and info["success_rate"] < 0.3:
                issues.append({
                    "subsystem": "tools",
                    "severity": "warning",
                    "issue": f"Tool '{name}' has {info['success_rate']:.0%} success rate over {info['total_uses']} uses",
                    "suggestion": f"Review tool '{name}' configuration or consider replacing it",
                })
        return issues

    def _check_imports(self) -> List[Dict[str, Any]]:
        issues = []
        modules = [
            "core.symbolic", "core.planner", "core.grammar", "core.normalize",
            "core.events", "core.responder", "core.retrieval", "core.evidence_score",
            "storage.memory", "ml.ml",
            "tools.tool_interface", "tools.tool_builder", "tools.code_tool",
        ]
        for mod in modules:
            try:
                importlib.import_module(mod)
            except Exception as e:
                issues.append({
                    "subsystem": "imports",
                    "severity": "critical",
                    "issue": f"Cannot import {mod}: {e}",
                    "suggestion": f"Check {mod.replace('.', '/')}.py for syntax errors",
                })
        return issues

    def _check_missing_files(self) -> List[Dict[str, Any]]:
        issues = []
        # Only flag truly critical files, not lazy-created ones
        critical = ["data/facts.json", "data/agent_state.json", "config.json"]
        for f in critical:
            p = self._base_dir / f
            if not p.exists():
                issues.append({
                    "subsystem": "storage",
                    "severity": "warning",
                    "issue": f"Missing expected file: {f}",
                    "suggestion": "File will be recreated on next write, but data may be lost",
                })
        return issues

    def _check_memory_health(self) -> List[Dict[str, Any]]:
        issues = []
        if self._memory.facts_file.exists():
            size_mb = self._memory.facts_file.stat().st_size / (1024 * 1024)
            if size_mb > 5:
                issues.append({
                    "subsystem": "memory",
                    "severity": "warning",
                    "issue": f"Facts file is {size_mb:.1f}MB (large)",
                    "suggestion": "Run memory compression to reduce size",
                })
        if self._memory.episodic_file.exists():
            size_mb = self._memory.episodic_file.stat().st_size / (1024 * 1024)
            if size_mb > 8:
                issues.append({
                    "subsystem": "memory",
                    "severity": "warning",
                    "issue": f"Episodic log is {size_mb:.1f}MB — approaching rotation threshold",
                    "suggestion": "Episodic log will auto-rotate at 10MB",
                })
        malformed = 0
        for key, val in self._memory.facts.items():
            if not isinstance(val, dict):
                malformed += 1
        if malformed > 0:
            issues.append({
                "subsystem": "memory",
                "severity": "warning",
                "issue": f"{malformed} facts have non-dict values (legacy format)",
                "suggestion": "These facts may not have confidence scores",
            })
        return issues

    def _check_log_growth(self) -> List[Dict[str, Any]]:
        issues = []
        log_dir = self._base_dir / "data" / "logs"
        if log_dir.exists():
            total = sum(f.stat().st_size for f in log_dir.rglob("*") if f.is_file())
            if total > 20 * 1024 * 1024:
                issues.append({
                    "subsystem": "logging",
                    "severity": "warning",
                    "issue": f"Log directory is {total // (1024*1024)}MB",
                    "suggestion": "Consider rotating or truncating old logs",
                })
        events_file = self._base_dir / "data" / "events.jsonl"
        if events_file.exists():
            size_mb = events_file.stat().st_size / (1024 * 1024)
            if size_mb > 10:
                issues.append({
                    "subsystem": "logging",
                    "severity": "warning",
                    "issue": f"Events log is {size_mb:.1f}MB",
                    "suggestion": "Truncate events.jsonl to reduce size",
                })
        return issues

    def _check_confidence_collapse(self) -> List[Dict[str, Any]]:
        issues = []
        state_file = self._base_dir / "data" / "agent_state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                conf = state.get("confidence", 0.5)
                if conf < 0.2:
                    issues.append({
                        "subsystem": "confidence",
                        "severity": "critical",
                        "issue": f"Agent confidence collapsed to {conf:.2f}",
                        "suggestion": "Review recent failures — confidence may recover with successful actions",
                    })
                ds = state.get("decision_summary", {})
                sr = ds.get("success_rate", 0.5)
                if sr < 0.3 and ds.get("total_decisions", 0) > 10:
                    issues.append({
                        "subsystem": "execution",
                        "severity": "warning",
                        "issue": f"Success rate is {sr:.0%} over {ds.get('total_decisions', 0)} decisions",
                        "suggestion": "Many actions are failing — check tool configurations",
                    })
            except Exception:
                pass
        return issues

    def _check_generated_tools(self) -> List[Dict[str, Any]]:
        issues = []
        gen_dir = self._base_dir / "tools" / "generated"
        if gen_dir.exists():
            for f in gen_dir.iterdir():
                if f.suffix in (".py", ".sh") and f.stat().st_size == 0:
                    issues.append({
                        "subsystem": "tools",
                        "severity": "warning",
                        "issue": f"Generated tool {f.name} is empty",
                        "suggestion": f"Delete or regenerate {f.name}",
                    })
        return issues

    def get_repair_report(self) -> str:
        """Human-readable repair report with policy info."""
        report = self.run_check()
        if report["status"] == "healthy":
            return "All systems healthy. No issues found."
        lines = [f"Health check: {report['status'].upper()} ({report['issues_found']} issues)"]
        for issue in report["issues"]:
            sev = issue["severity"].upper()
            rc = issue.get("repair_class", "?")
            rsr = issue.get("repair_success_rate", 0.5)
            lines.append(f"  [{sev}] {issue['issue']}")
            lines.append(f"         Class: {rc} (repair success: {rsr:.0%})")
            if issue.get("suggestion"):
                lines.append(f"         Fix: {issue['suggestion']}")
        if report.get("past_repairs"):
            lines.append("\nRelated past repairs:")
            for r in report["past_repairs"][:3]:
                lines.append(f"  - {r.get('value', {}).get('issue', '?')}")
        return "\n".join(lines)
