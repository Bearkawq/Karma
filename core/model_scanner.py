"""Model Scanner - Local model discovery for Karma.

Scans local drives/folders for compatible model files.
Supported formats: GGUF, safetensors, model directories with manifests.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class DiscoveredModel:
    """A model discovered during scanning."""
    path: str
    name: str
    model_type: str  # "gguf", "safetensors", "directory"
    size_bytes: int = 0
    guessed_capability: str = "unknown"  # "llm", "embedding", "unknown"
    runtime_hint: str = "unknown"  # "llama.cpp", "transformers", "unknown"
    manifest: Optional[Dict] = None
    scan_time: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ScanReceipt:
    """Receipt from a model scan operation."""
    scan_path: str
    scan_time: str
    models_found: int
    models_registered: List[str] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class ModelScanner:
    """Scans local paths for compatible model files."""
    
    # File patterns that indicate models
    GGUF_PATTERNS = ["*.gguf", "*.GGUF"]
    SAFETENSORS_PATTERNS = ["*.safetensors", "*.bin"]
    MANIFEST_FILES = ["config.json", "model.safetensors.index.json", "manifest.json"]
    
    def __init__(self):
        self._last_scan: Optional[ScanReceipt] = None
    
    def scan(
        self,
        path: str,
        recursive: bool = True,
        max_depth: int = 3,
    ) -> ScanReceipt:
        """Scan a path for model files.
        
        Args:
            path: Path to scan
            recursive: Whether to scan recursively
            max_depth: Maximum directory depth
            
        Returns:
            ScanReceipt with discovered models
        """
        scan_path = Path(path).expanduser().resolve()
        
        if not scan_path.exists():
            return ScanReceipt(
                scan_path=path,
                scan_time=datetime.now().isoformat(),
                models_found=0,
                errors=[f"Path does not exist: {path}"],
            )
        
        if not os.access(scan_path, os.R_OK):
            return ScanReceipt(
                scan_path=path,
                scan_time=datetime.now().isoformat(),
                models_found=0,
                errors=[f"Path not readable: {path}"],
            )
        
        candidates = []
        errors = []
        
        try:
            if scan_path.is_file():
                # Single file
                model = self._identify_file(scan_path)
                if model:
                    candidates.append(model)
            elif scan_path.is_dir():
                # Directory
                candidates = self._scan_directory(scan_path, recursive, max_depth)
        
        except Exception as e:
            errors.append(f"Scan error: {str(e)}")
        
        receipt = ScanReceipt(
            scan_path=path,
            scan_time=datetime.now().isoformat(),
            models_found=len(candidates),
            candidates=candidates,
            errors=errors,
        )
        
        self._last_scan = receipt
        return receipt
    
    def _scan_directory(
        self,
        path: Path,
        recursive: bool,
        max_depth: int,
    ) -> List[Dict[str, Any]]:
        """Scan a directory for models."""
        candidates = []
        
        try:
            for entry in path.iterdir():
                if entry.is_file():
                    model = self._identify_file(entry)
                    if model:
                        candidates.append(model)
                elif entry.is_dir() and recursive and max_depth > 0:
                    # Check if this is a model directory
                    model = self._identify_directory(entry)
                    if model:
                        candidates.append(model)
                    else:
                        # Recurse
                        candidates.extend(
                            self._scan_directory(entry, recursive, max_depth - 1)
                        )
        except PermissionError:
            pass
        
        return candidates
    
    def _identify_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """Identify a model file."""
        name = path.stem
        suffix = path.suffix.lower()
        
        # GGUF files
        if suffix == ".gguf":
            return {
                "path": str(path),
                "name": name,
                "model_type": "gguf",
                "size_bytes": path.stat().st_size,
                "guessed_capability": self._guess_capability_from_name(name),
                "runtime_hint": "llama.cpp",
            }
        
        # Check for model directory markers
        return None
    
    def _identify_directory(self, path: Path) -> Optional[Dict[str, Any]]:
        """Identify a model directory."""
        name = path.name
        
        # Check for manifest
        manifest = None
        for mf in self.MANIFEST_FILES:
            manifest_path = path / mf
            if manifest_path.exists():
                try:
                    with open(manifest_path) as f:
                        manifest = json.load(f)
                    break
                except Exception:
                    pass
        
        if manifest:
            # This looks like a model directory
            model_type = "directory"
            runtime = "transformers"
            capability = "unknown"
            
            # Try to determine capability from manifest
            if "architectures" in manifest:
                capability = "llm"
            elif "model_type" in manifest:
                capability = "llm"
            
            # Calculate size
            total_size = self._directory_size(path)
            
            return {
                "path": str(path),
                "name": name,
                "model_type": model_type,
                "size_bytes": total_size,
                "guessed_capability": capability,
                "runtime_hint": runtime,
                "manifest": manifest,
            }
        
        # Check for safetensors files
        safetensors = list(path.glob("*.safetensors"))
        if safetensors:
            total_size = sum(f.stat().st_size for f in safetensors)
            return {
                "path": str(path),
                "name": name,
                "model_type": "safetensors",
                "size_bytes": total_size,
                "guessed_capability": self._guess_capability_from_name(name),
                "runtime_hint": "transformers",
            }
        
        return None
    
    def _guess_capability_from_name(self, name: str) -> str:
        """Guess model capability from filename."""
        name_lower = name.lower()
        
        if any(w in name_lower for w in ["embed", "embedding", "dense", "rerank"]):
            return "embedding"
        elif any(w in name_lower for w in ["code", "coder", "codex"]):
            return "llm"
        elif any(w in name_lower for w in ["summar", "sum"]):
            return "llm"
        else:
            return "llm"  # Default assumption
    
    def _directory_size(self, path: Path) -> int:
        """Calculate total size of directory."""
        total = 0
        try:
            for entry in path.rglob("*"):
                if entry.is_file():
                    total += entry.stat().st_size
        except PermissionError:
            pass
        return total
    
    def get_last_scan(self) -> Optional[ScanReceipt]:
        """Get the last scan receipt."""
        return self._last_scan
    
    def format_size(self, bytes: int) -> str:
        """Format bytes as human-readable string."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes < 1024:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024
        return f"{bytes:.1f} PB"


_global_scanner: Optional[ModelScanner] = None


def get_model_scanner() -> ModelScanner:
    """Get global model scanner."""
    global _global_scanner
    if _global_scanner is None:
        _global_scanner = ModelScanner()
    return _global_scanner
