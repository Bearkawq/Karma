"""Artifact Management - Track generated artifacts.

Artifacts include:
- summaries
- research results
- generated files
- exports

Artifact fields:
- artifact_id
- source_action
- timestamp
- file_reference
- content_type
- metadata
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from threading import Lock
from collections import deque


CONTENT_TYPES = frozenset([
    "summary",
    "research_result",
    "generated_file",
    "export",
    "note",
    "code",
    "document",
])


@dataclass
class Artifact:
    """Generated artifact."""
    artifact_id: str
    source_action: str
    timestamp: str
    file_reference: Optional[str] = None
    content_type: str = "note"
    title: str = ""
    content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ArtifactStore:
    """Stores generated artifacts."""
    
    def __init__(self, max_artifacts: int = 500, storage_dir: Optional[str] = None):
        self._artifacts: deque = deque(maxlen=max_artifacts)
        self._by_id: Dict[str, Artifact] = {}
        self._lock = Lock()
        self._storage_dir = Path(storage_dir) if storage_dir else None
    
    def create_artifact(
        self,
        source_action: str,
        content_type: str = "note",
        title: str = "",
        content: Optional[str] = None,
        file_reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Artifact:
        """Create a new artifact."""
        if content_type not in CONTENT_TYPES:
            content_type = "note"
        
        artifact = Artifact(
            artifact_id=str(uuid.uuid4())[:12],
            source_action=source_action,
            timestamp=datetime.now().isoformat(),
            content_type=content_type,
            title=title,
            content=content,
            file_reference=file_reference,
            metadata=metadata or {},
        )
        
        with self._lock:
            self._artifacts.append(artifact)
            self._by_id[artifact.artifact_id] = artifact
        
        if self._storage_dir and content:
            self._save_to_disk(artifact)
        
        return artifact
    
    def _save_to_disk(self, artifact: Artifact) -> None:
        """Save artifact content to disk."""
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            file_path = self._storage_dir / f"{artifact.artifact_id}.json"
            with open(file_path, "w") as f:
                json.dump(artifact.to_dict(), f, indent=2)
        except Exception:
            pass
    
    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Get artifact by ID."""
        with self._lock:
            return self._by_id.get(artifact_id)
    
    def get_recent_artifacts(self, limit: int = 20) -> List[Artifact]:
        """Get recent artifacts."""
        with self._lock:
            return list(self._artifacts)[-limit:]
    
    def get_artifacts_by_action(self, source_action: str) -> List[Artifact]:
        """Get artifacts from a specific action."""
        with self._lock:
            return [a for a in self._artifacts if a.source_action == source_action]
    
    def get_artifacts_by_type(self, content_type: str) -> List[Artifact]:
        """Get artifacts of a specific type."""
        with self._lock:
            return [a for a in self._artifacts if a.content_type == content_type]
    
    def search_artifacts(self, query: str) -> List[Artifact]:
        """Search artifacts by title or content."""
        with self._lock:
            results = []
            query_lower = query.lower()
            for a in self._artifacts:
                if query_lower in a.title.lower():
                    results.append(a)
                elif a.content and query_lower in a.content.lower():
                    results.append(a)
            return results
    
    def delete_artifact(self, artifact_id: str) -> bool:
        """Delete an artifact."""
        with self._lock:
            if artifact_id in self._by_id:
                artifact = self._by_id[artifact_id]
                self._by_id.pop(artifact_id)
                try:
                    self._artifacts.remove(artifact)
                except ValueError:
                    pass
                return True
        return False
    
    def get_summary(self) -> Dict[str, Any]:
        """Get artifact statistics."""
        with self._lock:
            total = len(self._artifacts)
            if total == 0:
                return {"total": 0, "by_type": {}}
            
            by_type: Dict[str, int] = {}
            by_action: Dict[str, int] = {}
            
            for a in self._artifacts:
                by_type[a.content_type] = by_type.get(a.content_type, 0) + 1
                by_action[a.source_action] = by_action.get(a.source_action, 0) + 1
            
            return {
                "total": total,
                "by_type": by_type,
                "by_action": by_action,
            }
    
    def save_artifacts(self, path: str) -> None:
        """Persist artifacts to file."""
        with self._lock:
            artifacts = [a.to_dict() for a in self._artifacts]
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(artifacts, f, indent=2)
    
    def clear(self) -> None:
        """Clear all artifacts (for testing)."""
        with self._lock:
            self._artifacts.clear()
            self._by_id.clear()


_global_store: Optional[ArtifactStore] = None


def get_artifact_store() -> ArtifactStore:
    """Get global artifact store."""
    global _global_store
    if _global_store is None:
        _global_store = ArtifactStore()
    return _global_store
