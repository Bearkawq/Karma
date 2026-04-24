"""Self-Upgrade Tool — analyzes Karma's own codebase and suggests improvements.

Scans Python files for common patterns, generates patch suggestions in data/upgrades/.
"""

import ast
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class SelfUpgrade:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.upgrades_dir = self.base_dir / "data" / "upgrades"
        self.upgrades_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self) -> Dict[str, Any]:
        """Scan codebase and return improvement suggestions."""
        issues: List[Dict[str, str]] = []

        py_files = []
        for subdir in ("agent", "core", "ml", "research", "storage", "tools", "ui"):
            d = self.base_dir / subdir
            if d.exists():
                py_files.extend(d.glob("*.py"))

        for path in py_files:
            rel = str(path.relative_to(self.base_dir))
            try:
                source = path.read_text(errors="replace")
            except Exception:
                continue

            # Check for bare excepts
            for i, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if stripped == "except:" or stripped == "except Exception:":
                    if "pass" in (source.splitlines()[i] if i < len(source.splitlines()) else ""):
                        issues.append({
                            "file": rel, "line": i, "type": "silent_except",
                            "detail": "Silent exception swallowed — consider logging",
                        })

            # Check for TODO/FIXME/HACK
            for i, line in enumerate(source.splitlines(), 1):
                for tag in ("TODO", "FIXME", "HACK", "XXX"):
                    if tag in line:
                        issues.append({
                            "file": rel, "line": i, "type": "todo",
                            "detail": line.strip()[:120],
                        })

            # Check for long functions (>60 lines)
            try:
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        end = getattr(node, "end_lineno", node.lineno)
                        length = end - node.lineno
                        if length > 60:
                            issues.append({
                                "file": rel, "line": node.lineno, "type": "long_function",
                                "detail": f"{node.name}() is {length} lines — consider splitting",
                            })
            except SyntaxError:
                pass

            # Check for hardcoded paths
            for i, line in enumerate(source.splitlines(), 1):
                if re.search(r'["\']\/home\/\w+', line) and "# noqa" not in line:
                    issues.append({
                        "file": rel, "line": i, "type": "hardcoded_path",
                        "detail": "Hardcoded home path — use Path or config",
                    })

        # Save report
        report = {
            "timestamp": datetime.now().isoformat(),
            "files_scanned": len(py_files),
            "issues_found": len(issues),
            "issues": issues,
        }

        report_path = self.upgrades_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        lines = [
            f"Karma Self-Upgrade Report — {report['timestamp']}",
            f"Files scanned: {report['files_scanned']}",
            f"Issues found: {report['issues_found']}",
            "",
        ]
        for issue in issues:
            lines.append(f"  [{issue['type']}] {issue['file']}:{issue['line']} — {issue['detail']}")

        report_path.write_text("\n".join(lines) + "\n")

        return report
