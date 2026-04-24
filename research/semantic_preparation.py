"""Semantic Retrieval Preparation - Prepare knowledge for semantic search.

This module prepares the knowledge library for future vector search:
- Chunking strategies
- Metadata extraction  
- Embedding preparation (stub for future)
- Semantic search index structure
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
class Chunk:
    """A knowledge chunk ready for embedding."""
    id: str
    content: str
    source_file: str
    topic_bucket: str
    provenance: str
    chunk_index: int
    total_chunks: int
    headings: List[str] = field(default_factory=list)
    code_block_count: int = 0
    content_hash: str = ""


@dataclass
class SemanticIndex:
    """Index structure for semantic retrieval."""
    chunks: List[Chunk] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    updated: str = ""


class SemanticPreparer:
    """Prepare knowledge for semantic retrieval."""

    def __init__(self, knowledge_dir: str = "data/knowledge"):
        self.knowledge_dir = Path(knowledge_dir)
        self.index_dir = self.knowledge_dir / ".semantic_index"
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self.chunks: List[Chunk] = []
        self.seen_hashes: Set[str] = set()

        self._load_index()

    def _load_index(self) -> None:
        """Load existing semantic index."""
        index_file = self.index_dir / "index.json"

        if index_file.exists():
            try:
                with open(index_file) as f:
                    data = json.load(f)
                    for chunk_data in data.get("chunks", []):
                        self.chunks.append(Chunk(**chunk_data))
                        self.seen_hashes.add(chunk_data.get("content_hash", ""))
            except Exception:
                pass

    def _save_index(self) -> None:
        """Save semantic index to disk."""
        data = {
            "updated": datetime.now().isoformat(),
            "total_chunks": len(self.chunks),
            "chunks": [vars(c) for c in self.chunks],
        }

        with open(self.index_dir / "index.json", "w") as f:
            json.dump(data, f, indent=2)

    def chunk_file(self, file_path: str) -> List[Chunk]:
        """Chunk a single file for semantic retrieval."""
        path = Path(file_path)

        if not path.exists():
            return []

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        topic = self._extract_topic(path)
        provenance = self._extract_provenance(path)

        headings = self._extract_headings(content)
        code_count = self._count_code_blocks(content)

        chunks = self._create_chunks(
            content=content,
            source_file=str(path),
            topic_bucket=topic,
            provenance=provenance,
            headings=headings,
            code_block_count=code_count,
        )

        for chunk in chunks:
            if chunk.content_hash not in self.seen_hashes:
                self.chunks.append(chunk)
                self.seen_hashes.add(chunk.content_hash)

        if chunks:
            self._save_index()

        return chunks

    def chunk_directory(self, dir_path: str) -> int:
        """Chunk all files in a directory."""
        path = Path(dir_path)

        if not path.exists():
            return 0

        total_chunks = 0

        for file_path in path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in (
                ".md", ".txt", ".py", ".json", ".html", ".rst"
            ):
                chunks = self.chunk_file(str(file_path))
                total_chunks += len(chunks)

        return total_chunks

    def _extract_topic(self, path: Path) -> str:
        """Extract topic from file path."""
        path_str = str(path).lower()

        topics = {
            "python": ["python", "py_", "/python/"],
            "kali": ["kali", "linux", "/linux/"],
            "debugging": ["debug", "error", "/debug/"],
            "ai": ["ai", "ml", "llm", "/ai/"],
            "docs": ["docs", "/docs/"],
            "navigator": ["navigator", "/navigator/"],
            "ingestor": ["ingestor", "/ingestor/"],
            "pulse": ["pulse", "/pulse/"],
        }

        for topic, keywords in topics.items():
            if any(kw in path_str for kw in keywords):
                return topic

        return "general"

    def _extract_provenance(self, path: Path) -> str:
        """Extract provenance from file path."""
        path_str = str(path).lower()

        provenances = {
            "seed_pack": ["seed", "pack"],
            "docs_harvest": ["docs_harvest", "harvest"],
            "saved_page": ["saved_pages", "saved_page"],
            "dropbox": ["knowledge_drop", "dropbox"],
            "repo_explainer": ["repo_explanations", "explainer"],
            "patch": ["patch", "fix"],
            "navigator": ["nav", "navigator"],
        }

        for prov, keywords in provenances.items():
            if any(kw in path_str for kw in keywords):
                return prov

        return "local"

    def _extract_headings(self, content: str) -> List[str]:
        """Extract headings from content."""
        headings = []

        md_headings = re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE)
        headings.extend(md_headings[:10])

        if not headings:
            html_headings = re.findall(r"<h[1-6][^>]*>(.+?)</h[1-6]>", content, re.IGNORECASE)
            headings.extend(html_headings[:10])

        return headings[:10]

    def _count_code_blocks(self, content: str) -> int:
        """Count code blocks in content."""
        md_blocks = len(re.findall(r"```", content))
        html_blocks = len(re.findall(r"<pre[^>]*>|<code[^>]*>", content, re.IGNORECASE))

        return max(md_blocks // 2, html_blocks)

    def _create_chunks(
        self,
        content: str,
        source_file: str,
        topic_bucket: str,
        provenance: str,
        headings: List[str],
        code_block_count: int,
        chunk_size: int = 2000,
    ) -> List[Chunk]:
        """Create chunks from content."""
        if len(content) <= chunk_size:
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            return [
                Chunk(
                    id=f"chunk_{len(self.chunks):06d}",
                    content=content[:chunk_size],
                    source_file=source_file,
                    topic_bucket=topic_bucket,
                    provenance=provenance,
                    chunk_index=0,
                    total_chunks=1,
                    headings=headings[:5],
                    code_block_count=code_block_count,
                    content_hash=content_hash,
                )
            ]

        chunks = []
        start = 0
        index = 0

        while start < len(content):
            end = start + chunk_size

            if end < len(content):
                break_point = content.rfind("\n\n", start, end)
                if break_point > start:
                    end = break_point

            chunk_text = content[start:end].strip()

            if len(chunk_text) > 100:
                content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:16]

                chunk_headings = []
                for h in headings:
                    if h.lower() in chunk_text.lower():
                        chunk_headings.append(h)

                chunk = Chunk(
                    id=f"chunk_{len(self.chunks) + index:06d}",
                    content=chunk_text,
                    source_file=source_file,
                    topic_bucket=topic_bucket,
                    provenance=provenance,
                    chunk_index=index,
                    total_chunks=0,
                    headings=chunk_headings[:3],
                    code_block_count=code_block_count,
                    content_hash=content_hash,
                )
                chunks.append(chunk)
                index += 1

            start = end

        total = len(chunks)
        for i, chunk in enumerate(chunks):
            chunk.total_chunks = total

        return chunks

    def search_chunks(
        self,
        query: str,
        topic: Optional[str] = None,
        provenance: Optional[str] = None,
        limit: int = 10,
    ) -> List[Chunk]:
        """Search chunks (simple text search for now)."""
        results = []
        query_lower = query.lower()

        for chunk in self.chunks:
            if topic and chunk.topic_bucket != topic:
                continue

            if provenance and chunk.provenance != provenance:
                continue

            if query_lower in chunk.content.lower():
                results.append(chunk)

        return results[:limit]

    def get_topics(self) -> Dict[str, int]:
        """Get topic distribution."""
        topics: Dict[str, int] = {}

        for chunk in self.chunks:
            topics[chunk.topic_bucket] = topics.get(chunk.topic_bucket, 0) + 1

        return topics

    def get_stats(self) -> Dict[str, Any]:
        """Get semantic index statistics."""
        return {
            "total_chunks": len(self.chunks),
            "topics": self.get_topics(),
            "provenances": self._get_provenance_counts(),
            "indexed_files": len(set(c.source_file for c in self.chunks)),
        }

    def _get_provenance_counts(self) -> Dict[str, int]:
        """Get provenance distribution."""
        counts: Dict[str, int] = {}

        for chunk in self.chunks:
            counts[chunk.provenance] = counts.get(chunk.provenance, 0) + 1

        return counts

    def prepare_for_embedding(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Prepare a chunk for embedding generation (stub)."""
        for chunk in self.chunks:
            if chunk.id == chunk_id:
                return {
                    "id": chunk.id,
                    "text": chunk.content,
                    "metadata": {
                        "topic": chunk.topic_bucket,
                        "provenance": chunk.provenance,
                        "source": chunk.source_file,
                        "headings": chunk.headings,
                    },
                }

        return None


_preparer_instance: Optional[SemanticPreparer] = None


def get_preparer() -> SemanticPreparer:
    """Get or create semantic preparer singleton."""
    global _preparer_instance
    if _preparer_instance is None:
        _preparer_instance = SemanticPreparer()
    return _preparer_instance


def chunk_file(file_path: str) -> List[Chunk]:
    """Chunk a file for semantic retrieval."""
    preparer = get_preparer()
    return preparer.chunk_file(file_path)


def search_knowledge(query: str, topic: Optional[str] = None) -> List[Chunk]:
    """Search knowledge chunks."""
    preparer = get_preparer()
    return preparer.search_chunks(query, topic)
