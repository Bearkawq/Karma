"""CodeTool — AST-aware code reading, editing, and analysis.

Supports: read with structure, search/replace edits, function listing,
error parsing, and knowledge-backed code generation from learned facts.
"""

import ast
import difflib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from research.pulse import get_pulse
    from research.pulse_words import translate_error
    PULSE_AVAILABLE = True
except ImportError:
    PULSE_AVAILABLE = False
    def get_pulse():
        class _:
            def emit_action(self, *a, **kw): pass
            def emit_success(self, *a, **kw): pass
            def emit_warning(self, *a, **kw): pass
            def emit_error(self, *a, **kw): pass
        return _()
    def translate_error(x): return x


class CodeTool:
    """AST-aware code operations."""

    def __init__(self, memory=None):
        self.memory = memory

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        op = params.get("operation", "")
        try:
            if op == "read":
                return self._read(params)
            elif op == "edit":
                return self._edit(params)
            elif op == "structure":
                return self._structure(params)
            elif op == "run":
                return self._run(params)
            elif op == "debug":
                return self._debug(params)
            elif op == "test":
                return self._test(params)
            elif op == "recall":
                return self._recall_code_knowledge(params)
            else:
                return {"success": False, "error": f"Unknown code operation: {op}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── read with line numbers ────────────────────────────────

    def _read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path", "")
        if not path or not os.path.isfile(path):
            return {"success": False, "error": f"File not found: {path}"}
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(0, int(params.get("start_line", 1)) - 1)
        end = int(params.get("end_line", len(lines)))
        numbered = [f"{i+1:4d} | {line}" for i, line in enumerate(lines[start:end], start=start)]
        return {
            "success": True,
            "content": "\n".join(numbered),
            "total_lines": len(lines),
            "path": path,
        }

    # ── search/replace edit ───────────────────────────────────

    def _edit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path", "")
        old = params.get("old_string", "")
        new = params.get("new_string", "")
        if not path or not os.path.isfile(path):
            return {"success": False, "error": f"File not found: {path}"}
        if not old:
            return {"success": False, "error": "old_string required"}

        text = Path(path).read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            return {"success": False, "error": "old_string not found in file"}

        replace_all = params.get("replace_all", False)
        if replace_all:
            result = text.replace(old, new)
        else:
            if count > 1:
                return {"success": False, "error": f"old_string found {count} times — use replace_all or provide more context"}
            result = text.replace(old, new, 1)

        Path(path).write_text(result, encoding="utf-8")
        return {"success": True, "output": f"Edited {path} ({count} replacement{'s' if count > 1 else ''})"}

    # ── AST structure ─────────────────────────────────────────

    def _structure(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path", "")
        if not path or not os.path.isfile(path):
            return {"success": False, "error": f"File not found: {path}"}

        text = Path(path).read_text(encoding="utf-8", errors="replace")

        if path.endswith(".py"):
            return self._python_structure(text, path)
        else:
            # Generic: just show line count + imports/includes
            lines = text.splitlines()
            return {
                "success": True,
                "path": path,
                "lines": len(lines),
                "type": "generic",
            }

    def _python_structure(self, text: str, path: str) -> Dict[str, Any]:
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return {"success": False, "error": f"SyntaxError: {e}"}

        imports = []
        classes = []
        functions = []
        constants = []

        # Build set of method nodes (inside classes) for filtering
        method_nodes: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_nodes.add(id(item))

        # Collect imports from anywhere in the file
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in imports:
                        imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                name = f"from {node.module or '?'}"
                if name not in imports:
                    imports.append(name)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                classes.append({"name": node.name, "line": node.lineno, "methods": methods})
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if id(node) not in method_nodes:
                    args = [a.arg for a in node.args.args]
                    functions.append({"name": node.name, "line": node.lineno, "args": args})

        lines = []
        lines.append(f"File: {path} ({len(text.splitlines())} lines)")
        if imports:
            lines.append(f"Imports: {', '.join(imports[:15])}")
        for cls in classes:
            lines.append(f"class {cls['name']} (line {cls['line']}): {', '.join(cls['methods'][:10])}")
        for fn in functions:
            lines.append(f"def {fn['name']}({', '.join(fn['args'])}) [line {fn['line']}]")

        return {
            "success": True,
            "structure": "\n".join(lines),
            "imports": imports,
            "classes": classes,
            "functions": functions,
            "path": path,
        }

    # ── run code ──────────────────────────────────────────────

    def _run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path", "")
        if not path or not os.path.isfile(path):
            return {"success": False, "error": f"File not found: {path}"}

        if path.endswith(".py"):
            cmd = ["python3", path]
        elif path.endswith(".sh"):
            cmd = ["bash", path]
        else:
            return {"success": False, "error": "Only .py and .sh supported"}

        if PULSE_AVAILABLE:
            get_pulse().emit_action(f"Running {path}", "code")

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                               cwd=str(Path(path).parent))
            if PULSE_AVAILABLE:
                if r.returncode == 0:
                    get_pulse().emit_success(f"Ran {path} successfully", "code")
                else:
                    get_pulse().emit_warning(f"Ran {path} but had errors", "code")
            return {
                "success": r.returncode == 0,
                "stdout": r.stdout.strip()[:2000],
                "stderr": r.stderr.strip()[:2000],
                "returncode": r.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timed out (30s)"}

    # ── debug: run → parse error → suggest fix ────────────────

    def _debug(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path", "")
        max_attempts = int(params.get("max_attempts", 3))

        if not path or not os.path.isfile(path):
            return {"success": False, "error": f"File not found: {path}"}

        if PULSE_AVAILABLE:
            get_pulse().emit_action(f"Debugging {path}", "debug")

        attempts = []
        for attempt in range(max_attempts):
            run_result = self._run({"path": path})
            if run_result.get("success"):
                if PULSE_AVAILABLE:
                    msg = f"Fixed {path} after {attempt} fix(es)" if attempt > 0 else f"Debugging {path} - no issues found"
                    get_pulse().emit_success(msg, "debug")
                return {
                    "success": True,
                    "output": f"Code runs clean after {attempt} fix(es)." if attempt > 0 else "Code runs clean.",
                    "attempts": attempts,
                }

            stderr = run_result.get("stderr", "")
            error_info = self._parse_python_error(stderr, path)
            if not error_info:
                if PULSE_AVAILABLE:
                    get_pulse().emit_warning(f"Could not parse error in {path}", "debug")
                return {
                    "success": False,
                    "error": f"Could not parse error:\n{stderr[:500]}",
                    "attempts": attempts,
                }

            fix = self._auto_fix(error_info, path)
            attempts.append({
                "error": error_info,
                "fix_applied": fix.get("applied", False),
                "fix_description": fix.get("description", "none"),
            })

            if not fix.get("applied"):
                # Check for missing main guard hint
                hint = ""
                if error_info.get("type") == "NameError" and path.endswith(".py"):
                    src = Path(path).read_text(encoding="utf-8", errors="replace")
                    if 'if __name__' not in src and re.search(r'^[a-zA-Z]', src.splitlines()[-1] if src.splitlines() else '', re.MULTILINE):
                        hint = "\nHint: Consider wrapping top-level code in 'if __name__ == \"__main__\":'"
                if PULSE_AVAILABLE:
                    err_type = translate_error(error_info.get("type", "error"))
                    get_pulse().emit_warning(f"Cannot auto-fix: {err_type}", "debug")
                    get_pulse().add_need(f"fix for {error_info.get('type', 'error')}", f"Need example of fixing {error_info.get('type', 'error')}", "code")
                return {
                    "success": False,
                    "error": f"Cannot auto-fix: {error_info['type']}: {error_info['message']}{hint}",
                    "suggestion": fix.get("description", ""),
                    "line": error_info.get("line"),
                    "attempts": attempts,
                }

        if PULSE_AVAILABLE:
            get_pulse().emit_warning(f"Could not fix {path} after {max_attempts} attempts", "debug")
        return {
            "success": False,
            "error": f"Still failing after {max_attempts} fix attempts",
            "attempts": attempts,
        }

    def _parse_python_error(self, stderr: str, path: str) -> Optional[Dict[str, Any]]:
        """Parse Python traceback into structured error info."""
        lines = stderr.strip().splitlines()
        if not lines:
            return None

        # Last line is usually the error
        error_line = lines[-1]
        m = re.match(r"(\w+(?:Error|Exception|Warning))\s*:\s*(.*)", error_line)
        if not m:
            return {"type": "Unknown", "message": error_line, "line": None, "code": None}

        error_type = m.group(1)
        message = m.group(2).strip()

        # Find line number from traceback
        lineno = None
        code_line = None
        for i, l in enumerate(lines):
            fm = re.search(r'File "([^"]+)", line (\d+)', l)
            if fm and (fm.group(1) == path or fm.group(1).endswith(os.path.basename(path))):
                lineno = int(fm.group(2))
                if i + 1 < len(lines) and not lines[i + 1].startswith("  File"):
                    code_line = lines[i + 1].strip()

        return {
            "type": error_type,
            "message": message,
            "line": lineno,
            "code": code_line,
        }

    def _auto_fix(self, error: Dict[str, Any], path: str) -> Dict[str, Any]:
        """Try to auto-fix common Python errors."""
        etype = error.get("type", "")
        msg = error.get("message", "")
        lineno = error.get("line")

        text = Path(path).read_text(encoding="utf-8")
        lines = text.splitlines()

        # NameError: name 'X' is not defined → check for typo or missing import
        if etype == "NameError":
            m = re.match(r"name '(\w+)' is not defined", msg)
            if m:
                name = m.group(1)
                # Common missing imports
                COMMON_IMPORTS = {
                    "json": "import json", "os": "import os", "sys": "import sys",
                    "re": "import re", "math": "import math", "Path": "from pathlib import Path",
                    "datetime": "from datetime import datetime", "subprocess": "import subprocess",
                    "time": "import time", "random": "import random", "typing": "import typing",
                    "Dict": "from typing import Dict", "List": "from typing import List",
                    "Optional": "from typing import Optional", "Any": "from typing import Any",
                }
                if name in COMMON_IMPORTS:
                    imp = COMMON_IMPORTS[name]
                    new_text = imp + "\n" + text
                    Path(path).write_text(new_text, encoding="utf-8")
                    return {"applied": True, "description": f"Added '{imp}'"}

                # Typo detection: find similar names defined in the file
                defined_names = set(re.findall(r'\b(?:def|class)\s+(\w+)', text))
                defined_names.update(re.findall(r'^(\w+)\s*=', text, re.MULTILINE))
                defined_names.update(re.findall(r'import\s+(\w+)', text))
                close = difflib.get_close_matches(name, defined_names, n=1, cutoff=0.7)
                if close and lineno:
                    idx = lineno - 1
                    if 0 <= idx < len(lines):
                        old_line = lines[idx]
                        new_line = old_line.replace(name, close[0])
                        if new_line != old_line:
                            lines[idx] = new_line
                            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
                            return {"applied": True, "description": f"Fixed typo: '{name}' -> '{close[0]}' on line {lineno}"}

        # ImportError / ModuleNotFoundError
        if etype in ("ImportError", "ModuleNotFoundError"):
            m = re.match(r"No module named '(\w+)'", msg)
            if m:
                return {"applied": False, "description": f"Missing module: {m.group(1)} — install it"}

        # IndentationError
        if etype == "IndentationError" and lineno:
            idx = lineno - 1
            if 0 <= idx < len(lines):
                line = lines[idx]
                # Try fixing mixed tabs/spaces
                fixed = line.expandtabs(4)
                if fixed != line:
                    lines[idx] = fixed
                    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
                    return {"applied": True, "description": f"Fixed indentation on line {lineno}"}

        # SyntaxError: missing colon, paren, etc
        if etype == "SyntaxError" and lineno:
            idx = lineno - 1
            if 0 <= idx < len(lines):
                line = lines[idx]
                # Missing colon after def/class/if/for/while/else/elif/try/except/finally/with
                if re.match(r"\s*(def |class |if |for |while |else|elif |try|except|finally|with )", line):
                    if not line.rstrip().endswith(":"):
                        lines[idx] = line.rstrip() + ":"
                        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
                        return {"applied": True, "description": f"Added missing colon on line {lineno}"}

        # TypeError: missing positional argument
        if etype == "TypeError" and "missing" in msg and "required positional argument" in msg:
            return {"applied": False, "description": f"Function call missing argument: {msg}"}

        return {"applied": False, "description": f"No auto-fix for {etype}"}

    # ── test: generate + run basic tests ──────────────────────

    def _test(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path", "")
        function = params.get("function", "")
        if not path or not os.path.isfile(path):
            return {"success": False, "error": f"File not found: {path}"}

        text = Path(path).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return {"success": False, "error": f"SyntaxError: {e}"}

        # Find functions to test
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if function and node.name != function:
                    continue
                if node.name.startswith("_"):
                    continue
                args = [a.arg for a in node.args.args if a.arg != "self"]
                targets.append({"name": node.name, "args": args, "line": node.lineno})

        if not targets:
            return {"success": False, "error": f"No testable functions found{' matching ' + function if function else ''}"}

        # Generate test file
        module_name = Path(path).stem
        test_lines = [
            f"# Auto-generated tests for {path}",
            f"import sys",
            f"sys.path.insert(0, '{str(Path(path).parent)}')",
            f"from {module_name} import *",
            "",
            "passed = 0",
            "failed = 0",
            "",
        ]

        for fn in targets:
            test_lines.append(f"# Test {fn['name']}")
            test_lines.append("try:")
            # Generate basic call with default args
            default_args = []
            for arg in fn["args"]:
                if "path" in arg or "file" in arg or "name" in arg or "dir" in arg:
                    default_args.append('"/tmp/test"')
                elif "num" in arg or "count" in arg or "n" in arg or "size" in arg:
                    default_args.append("1")
                elif "text" in arg or "string" in arg or "msg" in arg or "s" in arg:
                    default_args.append('"test"')
                elif "flag" in arg or "enabled" in arg or "verbose" in arg:
                    default_args.append("False")
                elif "items" in arg or "data" in arg or "lst" in arg:
                    default_args.append("[]")
                else:
                    default_args.append("None")
            call = f"    result = {fn['name']}({', '.join(default_args)})"
            test_lines.append(call)
            test_lines.append(f"    print(f'  PASS: {fn['name']} returned {{type(result).__name__}}')")
            test_lines.append("    passed += 1")
            test_lines.append("except Exception as e:")
            test_lines.append(f"    print(f'  FAIL: {fn['name']} — {{e}}')")
            test_lines.append("    failed += 1")
            test_lines.append("")

        test_lines.append("print(f'\\nResults: {passed} passed, {failed} failed')")
        test_lines.append("sys.exit(1 if failed else 0)")

        test_path = f"/tmp/karma_test_{module_name}.py"
        Path(test_path).write_text("\n".join(test_lines), encoding="utf-8")

        # Run tests
        try:
            r = subprocess.run(["python3", test_path], capture_output=True, text=True,
                               timeout=30, cwd=str(Path(path).parent))
            return {
                "success": r.returncode == 0,
                "output": r.stdout.strip()[:2000],
                "stderr": r.stderr.strip()[:1000] if r.returncode != 0 else "",
                "test_file": test_path,
                "functions_tested": len(targets),
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Tests timed out (30s)"}

    # ── recall learned code knowledge ─────────────────────────

    def _recall_code_knowledge(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search memory for code patterns, solutions, snippets related to a topic."""
        if not self.memory:
            return {"success": False, "error": "No memory system"}

        topic = params.get("topic", "").lower()
        if not topic:
            return {"success": False, "error": "No topic provided"}

        matches = []
        topic_words = set(topic.split())

        for key, val in self.memory.facts.items():
            key_low = key.lower()
            # Match learn facts, code patterns, solutions
            if any(prefix in key_low for prefix in ["learn:", "code:", "pattern:", "solution:", "error:"]):
                key_words = set(key_low.replace(":", " ").replace("_", " ").split())
                overlap = len(topic_words & key_words)
                if overlap > 0 or topic in key_low:
                    value = val.get("value", val) if isinstance(val, dict) else val
                    confidence = float(val.get("confidence", 0.5)) if isinstance(val, dict) else 0.5
                    matches.append((key, str(value)[:500], confidence, overlap))

        if not matches:
            return {"success": True, "output": f"No code knowledge found for '{topic}'. Try: golearn \"{topic}\" 3"}

        matches.sort(key=lambda x: (x[3], x[2]), reverse=True)
        lines = [f"Code knowledge for '{topic}':"]
        for key, value, conf, _ in matches[:10]:
            display = key.split(":")[-1].replace("_", " ")
            lines.append(f"  [{display}] {value[:200]}")

        return {"success": True, "output": "\n".join(lines)}
