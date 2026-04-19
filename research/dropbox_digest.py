"""Dropbox Digest - Automatic knowledge ingestion from drop folders.

Users can simply drop files into folders and Karma will automatically
ingest and learn from them.

Now also feeds into the unified Knowledge Spine.

Usage:
- Drop files into data/knowledge_drop/ subfolders
- Call watch_and_ingest() to process new files
- Files are moved to knowledge store after processing
- All content also goes through Knowledge Spine
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from research.ingestor import SeedIngestor, get_ingestor


SUPPORTED_EXTENSIONS = {
    ".html", ".htm",
    ".md", ".txt",
    ".pdf",
    ".py", ".js", ".ts", ".sh", ".c", ".cpp", ".go", ".rs", ".java",
    ".json", ".yaml", ".yml", ".toml",
}


@dataclass
class DigestStats:
    """Statistics from a digest run."""
    files_scanned: int = 0
    files_ingested: int = 0
    files_failed: int = 0
    chunks_to_spine: int = 0
    errors: List[str] = field(default_factory=list)


class DropboxDigest:
    """Monitors drop folders and ingests new files."""
    
    def __init__(self, base_dir: str = "data/knowledge_drop"):
        self.base_dir = Path(base_dir)
        self.ingestor = get_ingestor()
        self._seen_files: set = set()
        
        # Ensure folders exist
        for subfolder in ["raw_pages", "raw_docs", "raw_code", "raw_pdfs"]:
            (self.base_dir / subfolder).mkdir(parents=True, exist_ok=True)
    
    def watch_and_ingest(self) -> DigestStats:
        """Watch drop folders and ingest any new files."""
        stats = DigestStats()
        
        for subfolder in ["raw_pages", "raw_docs", "raw_code", "raw_pdfs"]:
            folder_path = self.base_dir / subfolder
            
            if not folder_path.exists():
                continue
            
            for file_path in folder_path.iterdir():
                if file_path.is_file():
                    stats.files_scanned += 1
                    
                    # Check if already seen
                    file_key = f"{subfolder}:{file_path.name}"
                    if file_key in self._seen_files:
                        continue
                    
                    # Process file
                    try:
                        self._ingest_file(file_path, subfolder)
                        stats.files_ingested += 1
                        self._seen_files.add(file_key)
                    except Exception as e:
                        stats.files_failed += 1
                        stats.errors.append(f"{file_path.name}: {str(e)}")
        
        return stats
    
    def _ingest_file(self, file_path: Path, subfolder: str) -> None:
        """Ingest a single file."""
        ext = file_path.suffix.lower()
        
        if ext not in SUPPORTED_EXTENSIONS:
            return
        
        # Determine topic based on subfolder
        topic = self._get_topic_from_subfolder(subfolder, file_path.stem)
        
        # Read content
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        
        # Create item for legacy ingestor
        from research.ingestor import IngestedItem, Provenance
        
        provenance = Provenance.LOCAL
        item = IngestedItem(
            topic_bucket=topic,
            title=file_path.stem[:100],
            content=content[:50_000],  # Limit size
            provenance=provenance,
            metadata={"source_file": str(file_path), "subfolder": subfolder},
        )
        
        # Add to legacy ingestor
        self.ingestor.items.append(item)
        
        # Also feed into unified Knowledge Spine
        try:
            from research.knowledge_spine import get_spine
            spine = get_spine()
            spine.ingest(
                content=content[:50_000],
                source_type="dropbox",
                provenance=f"dropbox_{subfolder}",
                topic=topic,
                source_url=str(file_path),
                title=file_path.stem[:100],
            )
        except Exception:
            pass  # Spine integration is optional
        
        # Move file to processed
        processed_dir = self.base_dir.parent / "knowledge" / topic
        processed_dir.mkdir(parents=True, exist_ok=True)
        
        dest = processed_dir / file_path.name
        try:
            file_path.rename(dest)
        except Exception:
            pass
    
    def _get_topic_from_subfolder(self, subfolder: str, filename: str) -> str:
        """Determine topic from subfolder and filename."""
        folder_topic_map = {
            "raw_pages": "web_pages",
            "raw_docs": "docs",
            "raw_code": "code",
            "raw_pdfs": "pdfs",
        }
        
        base_topic = folder_topic_map.get(subfolder, "general")
        
        # Try to extract topic from filename
        filename_lower = filename.lower()
        if "python" in filename_lower:
            return "python"
        elif "kali" in filename_lower or "linux" in filename_lower:
            return "kali_linux"
        elif "ai" in filename_lower or "ml" in filename_lower:
            return "ai_frameworks"
        elif "debug" in filename_lower:
            return "debugging"
        
        return base_topic
    
    def get_drop_folder_status(self) -> Dict[str, Any]:
        """Get status of drop folders."""
        status = {}
        
        for subfolder in ["raw_pages", "raw_docs", "raw_code", "raw_pdfs"]:
            folder_path = self.base_dir / subfolder
            if folder_path.exists():
                files = list(folder_path.iterdir())
                status[subfolder] = {
                    "count": len(files),
                    "files": [f.name for f in files[:10]],
                }
        
        return status


_digest_instance: Optional[DropboxDigest] = None


def get_digest() -> DropboxDigest:
    """Get or create digest singleton."""
    global _digest_instance
    if _digest_instance is None:
        _digest_instance = DropboxDigest()
    return _digest_instance


def run_digest() -> DigestStats:
    """Run digest and return stats."""
    digest = get_digest()
    return digest.watch_and_ingest()