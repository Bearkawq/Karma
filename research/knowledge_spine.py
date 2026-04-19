"""Unified Knowledge Spine - Central knowledge ingestion, storage, and retrieval.

This module provides a unified pipeline for all knowledge sources:
- seed packs
- raw drop ingestion  
- docs harvester
- navigator
- self-patch corpus
- Context7 (future)

Architecture:
  source -> extract -> clean -> chunk -> tag -> store -> index -> retrieve -> reason
"""

from __future__ import annotations

import hashlib
import json
import re
import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


SOURCE_TYPES = {
    "seed_pack": 0.9,
    "docs_harvest": 0.85,
    "navigator": 0.7,
    "saved_page": 0.75,
    "dropbox": 0.8,
    "raw_drop": 0.7,
    "context7": 0.9,
    "patch": 0.6,
    "local": 0.5,
}

DEFAULT_TRUST_SCORE = 0.7


@dataclass
class KnowledgeChunk:
    """A unified knowledge chunk."""
    id: str
    topic: str
    subtopic: str
    source_type: str
    provenance: str
    trust_score: float
    timestamp: str
    content: str
    tags: List[str] = field(default_factory=list)
    embedding: Optional[List[float]] = None
    content_hash: str = ""
    source_url: str = ""
    title: str = ""
    chunk_index: int = 0
    total_chunks: int = 1


@dataclass
class RetrievalResult:
    """A retrieval result with ranking info."""
    chunk: KnowledgeChunk
    score: float
    rank: int
    match_reason: str


@dataclass  
class IngestStats:
    """Statistics from ingestion."""
    items_processed: int = 0
    items_stored: int = 0
    duplicates_skipped: int = 0
    failed: int = 0
    topics_found: Dict[str, int] = field(default_factory=dict)


class KnowledgeSpine:
    """Unified Knowledge Spine - central knowledge management."""
    
    def __init__(self, storage_dir: str = "data/knowledge_spine"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.chunks: List[KnowledgeChunk] = []
        self.seen_hashes: Set[str] = set()
        
        self._load_index()
    
    def _load_index(self) -> None:
        """Load existing knowledge index."""
        index_file = self.storage_dir / "spine_index.json"
        
        if index_file.exists():
            try:
                with open(index_file) as f:
                    data = json.load(f)
                    for chunk_data in data.get("chunks", []):
                        chunk = KnowledgeChunk(**chunk_data)
                        self.chunks.append(chunk)
                        self.seen_hashes.add(chunk.content_hash)
            except Exception:
                pass
    
    def _save_index(self) -> None:
        """Save knowledge index to disk."""
        data = {
            "updated": datetime.now().isoformat(),
            "total_chunks": len(self.chunks),
            "chunks": [vars(c) for c in self.chunks],
        }
        
        with open(self.storage_dir / "spine_index.json", "w") as f:
            json.dump(data, f, indent=2)
    
    def ingest(
        self,
        content: str,
        source_type: str,
        provenance: str,
        topic: str = "general",
        subtopic: str = "",
        source_url: str = "",
        title: str = "",
        tags: Optional[List[str]] = None,
        trust_score: Optional[float] = None,
    ) -> Optional[KnowledgeChunk]:
        """Ingest knowledge through the unified pipeline."""
        
        cleaned = self._clean_content(content)
        
        if not cleaned or len(cleaned.strip()) < 20:
            return None
        
        chunks = self._chunk_content(cleaned)
        
        trust = trust_score if trust_score is not None else SOURCE_TYPES.get(source_type, DEFAULT_TRUST_SCORE)
        
        stored_chunks = []
        for i, chunk_text in enumerate(chunks):
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:16]
            
            if content_hash in self.seen_hashes:
                continue
            
            chunk = KnowledgeChunk(
                id=f"kc_{len(self.chunks) + len(stored_chunks):08d}",
                topic=topic,
                subtopic=subtopic,
                source_type=source_type,
                provenance=provenance,
                trust_score=trust,
                timestamp=datetime.now().isoformat(),
                content=chunk_text,
                tags=tags or [],
                content_hash=content_hash,
                source_url=source_url,
                title=title,
                chunk_index=i,
                total_chunks=len(chunks),
            )
            
            self.chunks.append(chunk)
            self.seen_hashes.add(content_hash)
            stored_chunks.append(chunk)
        
        if stored_chunks:
            self._save_index()
            self._emit_pulse("ingest", f"Ingested {len(stored_chunks)} chunks: {topic}")
        
        return stored_chunks[0] if stored_chunks else None
    
    def ingest_file(
        self,
        file_path: str,
        source_type: str = "raw_drop",
        provenance: str = "local",
    ) -> IngestStats:
        """Ingest a file through the unified pipeline."""
        stats = IngestStats()
        
        path = Path(file_path)
        if not path.exists():
            stats.failed = 1
            return stats
        
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            stats.failed = 1
            return stats
        
        stats.items_processed = 1
        
        topic = self._classify_topic(content, str(path))
        title = path.stem
        
        tags = self._extract_tags(content, topic)
        
        self.ingest(
            content=content,
            source_type=source_type,
            provenance=provenance,
            topic=topic,
            source_url=str(path),
            title=title,
            tags=tags,
        )
        
        stats.items_stored = 1
        stats.topics_found[topic] = stats.topics_found.get(topic, 0) + 1
        
        return stats
    
    def ingest_directory(self, dir_path: str, source_type: str = "raw_drop") -> IngestStats:
        """Ingest all supported files in a directory."""
        stats = IngestStats()
        
        path = Path(dir_path)
        if not path.exists():
            return stats
        
        supported = {".md", ".txt", ".py", ".json", ".html", ".rst", ".yaml", ".yml"}
        
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            
            if file_path.suffix.lower() not in supported:
                continue
            
            file_stats = self.ingest_file(str(file_path), source_type)
            stats.items_processed += file_stats.items_processed
            stats.items_stored += file_stats.items_stored
            stats.failed += file_stats.failed
            
            for topic, count in file_stats.topics_found.items():
                stats.topics_found[topic] = stats.topics_found.get(topic, 0) + count
        
        return stats
    
    def _clean_content(self, content: str) -> str:
        """Clean content - extract text from various formats."""
        if not content:
            return ""
        
        text = str(content)
        
        if text.strip().startswith("<") and "<html" in text[:100].lower():
            text = self._extract_from_html(text)
        
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        
        text = html.unescape(text)
        
        text = re.sub(r"\n{4,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 10]
        text = "\n".join(lines)
        
        return text.strip()
    
    def _extract_from_html(self, html_text: str) -> str:
        """Extract text from HTML."""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
        
        text = re.sub(r"<h[1-6][^>]*>", "\n## ", text, flags=re.IGNORECASE)
        text = re.sub(r"<pre[^>]*>", "\n```\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</pre>", "\n```\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
        
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        
        return text.strip()
    
    def _chunk_content(self, content: str, chunk_size: int = 2000) -> List[str]:
        """Segment content into chunks."""
        if len(content) <= chunk_size:
            return [content]
        
        chunks = []
        start = 0
        
        while start < len(content):
            end = min(start + chunk_size, len(content))
            
            if end < len(content):
                break_point = content.rfind("\n\n", start, end)
                if break_point > start + 200:
                    end = break_point
            
            chunk_text = content[start:end].strip()
            if len(chunk_text) > 100:
                chunks.append(chunk_text)
            
            start = end
        
        return chunks if chunks else [content[:chunk_size]]
    
    def _classify_topic(self, content: str, source_path: str = "") -> str:
        """Classify topic from content and source."""
        combined = f"{content} {source_path}".lower()[:5000]
        
        topic_keywords = {
            "python": ["python", "def ", "import ", "class ", ".py", "pip ", "venv"],
            "kali_linux": ["kali", "linux", "penetration", "security", "nmap", "metasploit"],
            "debugging": ["debug", "error", "exception", "traceback", "bug"],
            "ai": ["ai", "ml ", "machine learning", "tensorflow", "pytorch", "llm", "gpt"],
            "web": ["http", "html", "css", "javascript", "api", "rest"],
            "systems": ["kernel", "systemd", "network", "docker", "container"],
            "navigator": ["navigate", "browser", "fetch", "url", "wikipedia"],
            "docs": ["documentation", "docs", "reference", "manual"],
        }
        
        for topic, keywords in topic_keywords.items():
            if any(kw in combined for kw in keywords):
                return topic
        
        return "general"
    
    def _extract_tags(self, content: str, topic: str) -> List[str]:
        """Extract tags from content."""
        tags = [topic]
        
        code_blocks = len(re.findall(r"```|\bcode\b", content, re.IGNORECASE))
        if code_blocks > 0:
            tags.append("has_code")
        
        if "test" in content.lower():
            tags.append("has_tests")
        
        if "example" in content.lower():
            tags.append("has_examples")
        
        return tags[:5]
    
    def retrieve(
        self,
        topic: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 10,
        min_trust: float = 0.0,
    ) -> List[RetrievalResult]:
        """Retrieve knowledge with ranking."""
        candidates = []
        
        for chunk in self.chunks:
            if min_trust > 0 and chunk.trust_score < min_trust:
                continue
            
            if topic and topic.lower() not in chunk.topic.lower():
                continue
            
            score = chunk.trust_score
            
            if query:
                query_lower = query.lower()
                
                if query_lower in chunk.content.lower():
                    score += 0.3
                
                if query_lower in chunk.topic.lower():
                    score += 0.2
                
                if any(query_lower in tag.lower() for tag in chunk.tags):
                    score += 0.15
                
                if query_lower in chunk.title.lower():
                    score += 0.1
            else:
                score += 0.1
            
            candidates.append((chunk, score))
        
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        results = []
        for i, (chunk, score) in enumerate(candidates[:limit]):
            match_reason = "trust"
            if query:
                if query.lower() in chunk.content.lower():
                    match_reason = "content"
                elif query.lower() in chunk.topic.lower():
                    match_reason = "topic"
            
            results.append(RetrievalResult(
                chunk=chunk,
                score=score,
                rank=i + 1,
                match_reason=match_reason,
            ))
        
        return results
    
    def get_by_provenance(self, provenance: str) -> List[KnowledgeChunk]:
        """Get all chunks with a specific provenance."""
        return [c for c in self.chunks if c.provenance == provenance]
    
    def get_by_source_type(self, source_type: str) -> List[KnowledgeChunk]:
        """Get all chunks from a specific source type."""
        return [c for c in self.chunks if c.source_type == source_type]
    
    def get_topics(self) -> Dict[str, int]:
        """Get topic distribution."""
        topics: Dict[str, int] = {}
        for chunk in self.chunks:
            topics[chunk.topic] = topics.get(chunk.topic, 0) + 1
        return topics
    
    def get_stats(self) -> Dict[str, Any]:
        """Get spine statistics."""
        return {
            "total_chunks": len(self.chunks),
            "topics": self.get_topics(),
            "source_types": self._get_source_type_counts(),
            "avg_trust": sum(c.trust_score for c in self.chunks) / max(len(self.chunks), 1),
        }
    
    def _get_source_type_counts(self) -> Dict[str, int]:
        """Get source type distribution."""
        counts: Dict[str, int] = {}
        for chunk in self.chunks:
            counts[chunk.source_type] = counts.get(chunk.source_type, 0) + 1
        return counts
    
    def _emit_pulse(self, event_type: str, message: str):
        """Emit pulse event."""
        try:
            from research.pulse import get_pulse
            pulse = get_pulse()
            pulse.emit_action(message, "knowledge_spine")
        except Exception:
            pass


_spine_instance: Optional[KnowledgeSpine] = None


def get_spine() -> KnowledgeSpine:
    """Get or create knowledge spine singleton."""
    global _spine_instance
    if _spine_instance is None:
        _spine_instance = KnowledgeSpine()
    return _spine_instance


def ingest_knowledge(
    content: str,
    source_type: str,
    provenance: str,
    topic: str = "general",
    **kwargs,
) -> Optional[KnowledgeChunk]:
    """Ingest knowledge through the unified pipeline."""
    spine = get_spine()
    return spine.ingest(content, source_type, provenance, topic, **kwargs)


def retrieve_knowledge(
    topic: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 10,
) -> List[RetrievalResult]:
    """Retrieve knowledge from the spine."""
    spine = get_spine()
    return spine.retrieve(topic, query, limit)
