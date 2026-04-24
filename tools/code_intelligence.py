"""Code Intelligence Layer - Map modules, dependencies, and symbols.

Provides:
- Module and file mapping
- Import/dependency tracking
- Function/class identification
- Symbol/reference maps
- Edit target suggestions
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CodeSymbol:
    """A code symbol (function, class, etc.)."""
    name: str
    type: str  # function, class, method, constant
    file_path: str
    line: int
    end_line: int
    args: List[str] = field(default_factory=list)
    docstring: str = ""
    references: List[str] = field(default_factory=list)


@dataclass
class ModuleInfo:
    """Information about a code module."""
    file_path: str
    module_name: str
    imports: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    docstring: str = ""


@dataclass
class RepoMap:
    """Complete repository map."""
    modules: Dict[str, ModuleInfo] = field(default_factory=dict)
    symbols: List[CodeSymbol] = field(default_factory=list)
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    updated: str = ""


class CodeIntelligence:
    """Code intelligence for repository understanding."""

    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root)
        self.repo_map = RepoMap()

        self._load_map()

    def _load_map(self) -> None:
        """Load existing repo map."""
        map_file = self.repo_root / "data" / "code_intel" / "repo_map.json"

        if map_file.exists():
            try:
                with open(map_file) as f:
                    data = json.load(f)
                    for path, module_data in data.get("modules", {}).items():
                        self.repo_map.modules[path] = ModuleInfo(**module_data)

                    for symbol_data in data.get("symbols", []):
                        self.repo_map.symbols.append(CodeSymbol(**symbol_data))

                    self.repo_map.dependencies = data.get("dependencies", {})
            except Exception:
                pass

    def _save_map(self) -> None:
        """Save repo map to disk."""
        map_file = self.repo_root / "data" / "code_intel" / "repo_map.json"
        map_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "updated": datetime.now().isoformat(),
            "modules": {k: vars(v) for k, v in self.repo_map.modules.items()},
            "symbols": [vars(s) for s in self.repo_map.symbols],
            "dependencies": self.repo_map.dependencies,
        }

        with open(map_file, "w") as f:
            json.dump(data, f, indent=2)

    def scan_repo(self, extensions: List[str] = [".py"]) -> Dict[str, Any]:
        """Scan the repository and build map."""
        self.repo_map = RepoMap()
        self.repo_map.updated = datetime.now().isoformat()

        for ext in extensions:
            self._scan_extension(ext)

        self._build_dependencies()
        self._save_map()

        return {
            "modules_found": len(self.repo_map.modules),
            "symbols_found": len(self.repo_map.symbols),
            "files_scanned": len(self.repo_map.modules),
        }

    def _scan_extension(self, ext: str) -> None:
        """Scan files with a specific extension."""
        for file_path in self.repo_root.rglob(f"*{ext}"):
            if self._should_ignore(file_path):
                continue

            try:
                self._analyze_file(file_path)
            except Exception:
                pass

    def _should_ignore(self, path: Path) -> bool:
        """Check if file should be ignored."""
        ignore_dirs = {
            "__pycache__", ".git", ".pytest_cache",
            "node_modules", ".venv", "venv", "env",
            ".mypy_cache", ".ruff_cache",
        }

        for part in path.parts:
            if part in ignore_dirs:
                return True

        return False

    def _analyze_file(self, file_path: Path) -> None:
        """Analyze a single file."""
        if file_path.suffix != ".py":
            return

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content)
        except Exception:
            return

        module_name = self._get_module_name(file_path)

        imports = []
        exports = []
        classes = []
        functions = []

        docstring = ast.get_docstring(tree) or ""

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                    "methods": [
                        n.name for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ],
                }
                classes.append(node.name)

                for n in node.body:
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = [a.arg for a in n.args.args]
                        self.repo_map.symbols.append(CodeSymbol(
                            name=n.name,
                            type="method",
                            file_path=str(file_path),
                            line=n.lineno,
                            end_line=n.end_lineno or n.lineno,
                            args=args,
                            docstring=ast.get_docstring(n) or "",
                        ))

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    args = [a.arg for a in node.args.args]
                    functions.append(node.name)

                    self.repo_map.symbols.append(CodeSymbol(
                        name=node.name,
                        type="function",
                        file_path=str(file_path),
                        line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        args=args,
                        docstring=ast.get_docstring(node) or "",
                    ))

        module_info = ModuleInfo(
            file_path=str(file_path),
            module_name=module_name,
            imports=imports,
            exports=exports,
            classes=classes,
            functions=functions,
            dependencies=[],
            docstring=docstring[:200],
        )

        self.repo_map.modules[str(file_path)] = module_info

    def _get_module_name(self, file_path: Path) -> str:
        """Get module name from file path."""
        parts = file_path.parts

        if "karma" in parts:
            idx = parts.index("karma")
            return ".".join(parts[idx + 1:]).replace(".py", "")

        return file_path.stem

    def _build_dependencies(self) -> None:
        """Build dependency graph."""
        for path, module in self.repo_map.modules.items():
            deps = []

            for imp in module.imports:
                for other_path, other_module in self.repo_map.modules.items():
                    if imp in other_module.exports or imp == other_module.module_name:
                        if other_path != path:
                            deps.append(other_path)

            self.repo_map.dependencies[path] = list(set(deps))

    def find_symbol(self, name: str) -> List[CodeSymbol]:
        """Find a symbol by name."""
        results = []

        for symbol in self.repo_map.symbols:
            if name.lower() in symbol.name.lower():
                results.append(symbol)

        return results

    def find_in_file(self, file_path: str) -> ModuleInfo:
        """Get module info for a file."""
        return self.repo_map.modules.get(str(file_path))

    def find_edit_targets(
        self,
        behavior: str,
        subsystem: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find likely edit targets for a requested behavior."""
        targets = []
        behavior_lower = behavior.lower()

        keywords = behavior_lower.split()

        for symbol in self.repo_map.symbols:
            score = 0

            for kw in keywords:
                if kw in symbol.name.lower():
                    score += 2
                if kw in symbol.docstring.lower():
                    score += 1

            if score > 0:
                if subsystem:
                    module = self.repo_map.modules.get(symbol.file_path)
                    if not module or subsystem not in str(module.file_path):
                        continue

                targets.append({
                    "file": symbol.file_path,
                    "line": symbol.line,
                    "symbol": symbol.name,
                    "type": symbol.type,
                    "score": score,
                    "reason": f"matches '{behavior}'",
                })

        targets.sort(key=lambda x: x["score"], reverse=True)
        return targets[:10]

    def get_module_map(self) -> Dict[str, Any]:
        """Get file/module map."""
        result = {}

        for path, module in self.repo_map.modules.items():
            result[module.module_name] = {
                "file": path,
                "classes": module.classes,
                "functions": module.functions,
                "imports": module.imports[:10],
            }

        return result

    def get_dependency_tree(self, module_path: str) -> Dict[str, Any]:
        """Get dependency tree for a module."""
        visited = set()

        def get_deps(path: str, depth: int = 0) -> List[Dict[str, Any]]:
            if depth > 3 or path in visited:
                return []

            visited.add(path)

            deps = []
            module = self.repo_map.modules.get(path)

            if module:
                for dep_path in module.dependencies:
                    dep_info = {
                        "file": dep_path,
                        "depends_on": get_deps(dep_path, depth + 1),
                    }
                    deps.append(dep_info)

            return deps

        return {
            "module": module_path,
            "dependencies": get_deps(module_path),
        }


_intel_instance: Optional[CodeIntelligence] = None


def get_intelligence(repo_root: str = ".") -> CodeIntelligence:
    """Get or create code intelligence singleton."""
    global _intel_instance
    if _intel_instance is None:
        _intel_instance = CodeIntelligence(repo_root)
    return _intel_instance


def scan_repo(extensions: List[str] = [".py"]) -> Dict[str, Any]:
    """Scan repository and build code map."""
    intel = get_intelligence()
    return intel.scan_repo(extensions)


def find_symbol(name: str) -> List[CodeSymbol]:
    """Find a symbol in the code."""
    intel = get_intelligence()
    return intel.find_symbol(name)


def find_edit_targets(behavior: str, subsystem: Optional[str] = None) -> List[Dict[str, Any]]:
    """Find likely edit targets for a behavior."""
    intel = get_intelligence()
    return intel.find_edit_targets(behavior, subsystem)
