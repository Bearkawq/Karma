"""Self-Patch Learning - Learn from Karma's own patches and fixes.

Stores and retrieves knowledge about:
- Bug diagnoses
- Applied fixes
- Patch relationships
- Test results

Supports searching patch knowledge by topic and subsystem.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class PatchCase:
    """A bug fix case."""
    id: str
    bug_description: str
    diagnosis: str
    fix_applied: str
    file_path: str
    subsystem: str
    topic: str
    timestamp: str
    test_result: str
    success: bool


@dataclass
class PatchStats:
    """Statistics for patch learning."""
    total_cases: int = 0
    successful_fixes: int = 0
    failed_fixes: int = 0
    subsystems: Dict[str, int] = field(default_factory=dict)


class PatchLearner:
    """Learn from patches and fixes."""
    
    def __init__(self, storage_dir: str = "data/patch_learning"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.cases: List[PatchCase] = []
        self.seen_hashes: Set[str] = set()
        
        self._load_cases()
    
    def _load_cases(self) -> None:
        """Load existing patch cases."""
        cases_file = self.storage_dir / "cases.json"
        
        if cases_file.exists():
            try:
                with open(cases_file) as f:
                    data = json.load(f)
                    for case_data in data.get("cases", []):
                        self.cases.append(PatchCase(**case_data))
                        self.seen_hashes.add(case_data.get("content_hash", ""))
            except Exception:
                pass
    
    def _save_cases(self) -> None:
        """Save patch cases to disk."""
        data = {
            "updated": datetime.now().isoformat(),
            "cases": [vars(c) for c in self.cases],
        }
        
        with open(self.storage_dir / "cases.json", "w") as f:
            json.dump(data, f, indent=2)
    
    def record_patch(
        self,
        bug_description: str,
        diagnosis: str,
        fix_applied: str,
        file_path: str,
        subsystem: str = "general",
        test_result: str = "unknown",
        success: bool = True,
    ) -> PatchCase:
        """Record a patch case."""
        topic = self._extract_topic(bug_description, file_path)
        
        content_hash = hashlib.sha256(
            f"{bug_description}{diagnosis}{fix_applied}".encode()
        ).hexdigest()[:16]
        
        case = PatchCase(
            id=f"patch_{len(self.cases):05d}",
            bug_description=bug_description[:500],
            diagnosis=diagnosis[:1000],
            fix_applied=fix_applied[:2000],
            file_path=file_path,
            subsystem=subsystem,
            topic=topic,
            timestamp=datetime.now().isoformat(),
            test_result=test_result,
            success=success,
        )
        
        self.cases.append(case)
        self._save_cases()
        
        self._emit_pulse(
            "success" if success else "warning",
            f"Recorded patch: {topic}"
        )
        
        return case
    
    def record_unified_diff(
        self,
        diff_content: str,
        context: Dict[str, Any],
    ) -> Optional[PatchCase]:
        """Record knowledge from a unified diff."""
        if not diff_content:
            return None
        
        lines = diff_content.split("\n")
        
        added_lines = [l for l in lines if l.startswith("+") and not l.startswith("+++")]
        removed_lines = [l for l in lines if l.startswith("-") and not l.startswith("---")]
        
        if not added_lines and not removed_lines:
            return None
        
        bug_description = context.get("description", "Code change")
        file_path = context.get("file", "unknown")
        subsystem = context.get("subsystem", "general")
        
        diagnosis = "; ".join(removed_lines[:3]) if removed_lines else "Code modification"
        fix_applied = "; ".join(added_lines[:5]) if added_lines else "Code added"
        
        return self.record_patch(
            bug_description=bug_description,
            diagnosis=diagnosis,
            fix_applied=fix_applied,
            file_path=file_path,
            subsystem=subsystem,
            test_result=context.get("test_result", "unknown"),
            success=context.get("success", True),
        )
    
    def record_test_log(
        self,
        test_output: str,
        test_name: str,
        file_path: str,
        subsystem: str = "tests",
    ) -> None:
        """Record knowledge from test logs."""
        success = "PASSED" in test_output.upper() or "OK" in test_output.upper()
        failed = "FAILED" in test_output.upper() or "ERROR" in test_output.upper()
        
        if failed:
            error_match = re.search(r"(Error|Failed):(.+?)(?:\n|$)", test_output, re.IGNORECASE)
            diagnosis = error_match.group(2).strip()[:500] if error_match else "Test failed"
            
            self.record_patch(
                bug_description=f"Test failure: {test_name}",
                diagnosis=diagnosis,
                fix_applied="Not yet fixed",
                file_path=file_path,
                subsystem=subsystem,
                test_result="failed",
                success=False,
            )
    
    def _extract_topic(self, description: str, file_path: str) -> str:
        """Extract topic from description and file path."""
        combined = f"{description} {file_path}".lower()
        
        topics = {
            "python": ["python", "def ", "import ", "class ", ".py"],
            "navigator": ["navigate", "browser", "fetch", "url"],
            "ingestor": ["ingest", "knowledge", "seed"],
            "pulse": ["pulse", "event", "status"],
            "code_tool": ["code", "ast", "parse", "edit"],
            "debug": ["debug", "error", "fix", "exception"],
            "tests": ["test", "pytest", "assert"],
        }
        
        for topic, keywords in topics.items():
            if any(kw in combined for kw in keywords):
                return topic
        
        if file_path:
            path_parts = Path(file_path).parts
            if path_parts:
                return path_parts[0].lower()
        
        return "general"
    
    def search_patches(
        self,
        query: str,
        subsystem: Optional[str] = None,
        limit: int = 10,
    ) -> List[PatchCase]:
        """Search patch cases by topic or subsystem."""
        results = []
        query_lower = query.lower()
        
        for case in self.cases:
            if subsystem and case.subsystem != subsystem:
                continue
            
            if (query_lower in case.bug_description.lower() or
                query_lower in case.diagnosis.lower() or
                query_lower in case.topic.lower() or
                query_lower in case.file_path.lower()):
                results.append(case)
        
        return results[:limit]
    
    def get_cases_by_subsystem(self, subsystem: str) -> List[PatchCase]:
        """Get all cases for a subsystem."""
        return [c for c in self.cases if c.subsystem == subsystem]
    
    def get_stats(self) -> PatchStats:
        """Get patch learning statistics."""
        stats = PatchStats()
        stats.total_cases = len(self.cases)
        
        for case in self.cases:
            if case.success:
                stats.successful_fixes += 1
            else:
                stats.failed_fixes += 1
            
            stats.subsystems[case.subsystem] = stats.subsystems.get(case.subsystem, 0) + 1
        
        return stats
    
    def get_fix_for_error(self, error_type: str) -> Optional[PatchCase]:
        """Get a known fix for an error type."""
        error_lower = error_type.lower()
        
        for case in reversed(self.cases):
            if not case.success:
                continue
            
            if error_lower in case.bug_description.lower():
                return case
            
            if error_lower in case.diagnosis.lower():
                return case
        
        return None
    
    def _emit_pulse(self, event_type: str, message: str):
        """Emit pulse event."""
        try:
            from research.pulse import get_pulse
            pulse = get_pulse()
            if event_type == "success":
                pulse.emit_success(message, "patching")
            else:
                pulse.emit_warning(message, "patching")
        except Exception:
            pass


_learner_instance: Optional[PatchLearner] = None


def get_learner() -> PatchLearner:
    """Get or create patch learner singleton."""
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = PatchLearner()
    return _learner_instance


def record_patch(
    bug_description: str,
    diagnosis: str,
    fix_applied: str,
    file_path: str,
    subsystem: str = "general",
    test_result: str = "unknown",
    success: bool = True,
) -> PatchCase:
    """Record a patch case."""
    learner = get_learner()
    return learner.record_patch(
        bug_description, diagnosis, fix_applied, file_path,
        subsystem, test_result, success,
    )


def search_patches(query: str, subsystem: Optional[str] = None) -> List[PatchCase]:
    """Search patch cases."""
    learner = get_learner()
    return learner.search_patches(query, subsystem)
