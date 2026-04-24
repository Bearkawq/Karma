"""Seed Pack Ingestion System for Karma.

Allows ingesting local knowledge from external drives and using it
in local-first/cache-first mode for GoLearn.

Knowledge drive structure:
  knowledge_drive/
    00_inbox/
    01_kali_linux/
    02_python/
    03_debugging/
    04_ai_frameworks/
    05_coding_patterns/
    06_systems/
    07_docs_reference/
    08_seed_packs/
    09_processed/
    10_rejected/
    manifest/
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import html

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    ".md", ".txt", ".json", ".py", ".rst", ".html", ".csv",
    ".yaml", ".yml", ".toml", ".sh", ".js", ".ts", ".c", ".cpp",
    ".h", ".java", ".go", ".rs", ".sql", ".xml", ".mdx",
}

# Topic bucket mapping
TOPIC_BUCKETS = {
    "kali": "kali_linux",
    "kali_linux": "kali_linux",
    "linux": "systems",
    "security": "systems",
    "penetration": "kali_linux",
    "python": "python",
    "py_": "python",
    "debugging": "debugging",
    "debug": "debugging",
    "troubleshoot": "debugging",
    "ai": "ai_frameworks",
    "ml": "ai_frameworks",
    "llm": "ai_frameworks",
    "torch": "ai_frameworks",
    "tensorflow": "ai_frameworks",
    "patterns": "coding_patterns",
    "architecture": "coding_patterns",
    "design": "coding_patterns",
    "algorithms": "coding_patterns",
    "systems": "systems",
    "os": "systems",
    "network": "systems",
    "docs": "docs_reference",
    "reference": "docs_reference",
    "manual": "docs_reference",
    "tutorial": "docs_reference",
    "guide": "docs_reference",
}

# Provenance labels
PROVENANCE_LABELS = {
    "seed_pack": "seed_pack",
    "seed": "seed_pack",
    "official_doc": "official_doc",
    "local_doc": "local_doc",
    "imported_note": "imported_note",
    "code_reference": "code_reference",
    "debug_corpus": "debug_corpus",
    "inbox": "local_doc",
    "processed": "local_doc",
}

DEFAULT_TOPIC = "misc"
DEFAULT_PROVENANCE = "local_doc"


@dataclass
class IngestedItem:
    """Single ingested knowledge item."""
    id: str
    source_path: str
    topic_bucket: str
    provenance: str
    file_type: str
    content_hash: str
    imported_ts: str
    text_length: int
    title: str
    content: str
    metadata: Dict[str, Any]

    @classmethod
    def from_content(cls, content: str, source_path: str, title: str = "",
                     topic_bucket: str = DEFAULT_TOPIC, provenance: str = DEFAULT_PROVENANCE,
                     file_type: str = "txt", metadata: Dict[str, Any] = None) -> "IngestedItem":
        """Factory constructor to create an IngestedItem from content.
        
        Automatically generates:
        - unique identifier
        - content hash
        - timestamp
        
        Args:
            content: The text content to ingest
            source_path: Path to the source file
            title: Optional title (defaults to source_path basename)
            topic_bucket: Topic/category for the content
            provenance: Source of the content
            file_type: Type of file
            metadata: Additional metadata
            
        Returns:
            A new IngestedItem instance
        """
        import hashlib
        from datetime import datetime
        from pathlib import Path

        if metadata is None:
            metadata = {}

        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
        imported_ts = datetime.now().isoformat(timespec='seconds')

        if not title:
            title = Path(source_path).stem

        return cls(
            id=f"item_{imported_ts.replace(':', '').replace('-', '')}_{content_hash}",
            source_path=source_path,
            topic_bucket=topic_bucket,
            provenance=provenance,
            file_type=file_type,
            content_hash=content_hash,
            imported_ts=imported_ts,
            text_length=len(content),
            title=title,
            content=content,
            metadata=metadata,
        )


@dataclass
class IngestStats:
    """Ingestion statistics."""
    files_scanned: int = 0
    files_accepted: int = 0
    files_rejected: int = 0
    duplicates_skipped: int = 0
    topic_counts: Dict[str, int] = None
    provenance_counts: Dict[str, int] = None
    errors: List[str] = None

    def __post_init__(self):
        if self.topic_counts is None:
            self.topic_counts = {}
        if self.provenance_counts is None:
            self.provenance_counts = {}
        if self.errors is None:
            self.errors = []


class SeedIngestor:
    """Ingests knowledge from local drives into Karma."""

    def __init__(self, base_dir: str = "data/knowledge"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Storage for ingested items
        self.items: List[IngestedItem] = []
        self.seen_hashes: Set[str] = set()

        # Stats
        self.stats = IngestStats()

        # Load existing manifest
        self.manifest_path = self.base_dir / "manifest.json"
        self._load_manifest()

    def _load_manifest(self) -> None:
        """Load existing manifest if present."""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path) as f:
                    data = json.load(f)
                    for item_data in data.get("items", []):
                        self.items.append(IngestedItem(**item_data))
                        self.seen_hashes.add(item_data["content_hash"])
            except Exception:
                pass

    def _save_manifest(self) -> None:
        """Save manifest to disk."""
        data = {
            "updated": datetime.now().isoformat(),
            "items": [vars(item) for item in self.items],
            "stats": {
                "files_scanned": self.stats.files_scanned,
                "files_accepted": self.stats.files_accepted,
                "files_rejected": self.stats.files_rejected,
                "duplicates_skipped": self.stats.duplicates_skipped,
                "topic_counts": self.stats.topic_counts,
                "provenance_counts": self.stats.provenance_counts,
            }
        }
        with open(self.manifest_path, "w") as f:
            json.dump(data, f, indent=2)

    def _compute_hash(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _extract_title(self, content: str, filename: str) -> str:
        """Extract title from content or filename."""
        # Try markdown heading
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()[:100]

        # Try first non-empty line
        for line in lines:
            line = line.strip()
            if line and len(line) > 3:
                return line[:100]

        # Fallback to filename
        return Path(filename).stem[:100]

    def _classify_topic(self, file_path: Path, content: str) -> str:
        """Classify file into topic bucket."""
        path_str = str(file_path).lower()
        content_lower = content.lower()[:5000]  # Check beginning of content

        # Check path components first
        for key, topic in TOPIC_BUCKETS.items():
            if key in path_str:
                return topic

        # Check content
        for key, topic in TOPIC_BUCKETS.items():
            if key in content_lower:
                return topic

        return DEFAULT_TOPIC

    def _detect_provenance(self, file_path: Path) -> str:
        """Detect provenance label from path."""
        path_str = str(file_path).lower()

        for key, provenance in PROVENANCE_LABELS.items():
            if key in path_str:
                return provenance

        return DEFAULT_PROVENANCE

    def _extract_text(self, file_path: Path) -> Optional[str]:
        """Extract text from file based on type."""
        suffix = file_path.suffix.lower()

        try:
            if suffix == ".html":
                return self._extract_from_html(file_path)
            elif suffix == ".md" or suffix == ".mdx":
                return self._extract_from_markdown(file_path)
            elif suffix == ".json":
                return self._extract_from_json(file_path)
            else:
                # Plain text
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()[:50000]  # Limit size
        except Exception as e:
            self.stats.errors.append(f"Error extracting {file_path}: {e}")
            return None

    def _extract_from_html(self, file_path: Path) -> str:
        """Extract text from HTML."""
        import re
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            html_content = f.read()

        # Remove scripts and styles
        text = re.sub(r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)

        # Decode HTML entities
        text = html.unescape(text)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text)

        return text[:50000]

    def _extract_from_markdown(self, file_path: Path) -> str:
        """Extract text from Markdown."""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            md_content = f.read()

        # Simple markdown to text (basic)
        # Remove code blocks
        md_content = re.sub(r"```.*?```", "", md_content, flags=re.DOTALL)
        md_content = re.sub(r"`[^`]+`", "", md_content)

        # Remove images
        md_content = re.sub(r"!\[.*?\]\([^)]+\)", "", md_content)

        # Remove links but keep text
        md_content = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md_content)

        # Headers to text
        md_content = re.sub(r"^#{1,6}\s+", "", md_content, flags=re.MULTILINE)

        # Clean up
        md_content = re.sub(r"\n{3,}", "\n\n", md_content)

        return md_content[:50000]

    def _extract_from_json(self, file_path: Path) -> str:
        """Extract text from JSON."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Extract values recursively
            def extract_values(obj):
                if isinstance(obj, str):
                    return [obj]
                elif isinstance(obj, list):
                    result = []
                    for item in obj:
                        result.extend(extract_values(item))
                    return result
                elif isinstance(obj, dict):
                    result = []
                    for key, value in obj.items():
                        if isinstance(value, str):
                            result.append(value)
                        else:
                            result.extend(extract_values(value))
                    return result
                return []

            return " ".join(extract_values(data))[:50000]
        except:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:50000]

    def ingest_path(self, source_path: str, move_processed: bool = False,
                    move_rejected: bool = False) -> IngestStats:
        """Ingest knowledge from a path.
        
        Args:
            source_path: Path to knowledge folder
            move_processed: Move accepted files to processed folder
            move_rejected: Move rejected files to rejected folder
        
        Returns:
            IngestStats with ingestion results
        """
        source = Path(source_path)

        if not source.exists():
            self.stats.errors.append(f"Source path does not exist: {source_path}")
            return self.stats

        # Create processed/rejected folders
        processed_dir = source / "09_processed"
        rejected_dir = source / "10_rejected"

        if move_processed:
            processed_dir.mkdir(parents=True, exist_ok=True)
        if move_rejected:
            rejected_dir.mkdir(parents=True, exist_ok=True)

        # Scan files
        for file_path in source.rglob("*"):
            if not file_path.is_file():
                continue

            self.stats.files_scanned += 1

            # Check extension
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                self.stats.files_rejected += 1
                if move_rejected:
                    try:
                        shutil.move(str(file_path), str(rejected_dir / file_path.name))
                    except:
                        pass
                continue

            # Extract text
            content = self._extract_text(file_path)
            if content is None or len(content.strip()) < 10:
                self.stats.files_rejected += 1
                if move_rejected:
                    try:
                        shutil.move(str(file_path), str(rejected_dir / file_path.name))
                    except:
                        pass
                continue

            # Compute hash
            content_hash = self._compute_hash(content)

            # Check for duplicates
            if content_hash in self.seen_hashes:
                self.stats.duplicates_skipped += 1
                continue

            # Classify topic
            topic = self._classify_topic(file_path, content)

            # Detect provenance
            provenance = self._detect_provenance(file_path)

            # Extract title
            title = self._extract_title(content, file_path.name)

            # Create item
            item = IngestedItem(
                id=f"ing_{len(self.items):05d}",
                source_path=str(file_path),
                topic_bucket=topic,
                provenance=provenance,
                file_type=file_path.suffix.lower(),
                content_hash=content_hash,
                imported_ts=datetime.now().isoformat(),
                text_length=len(content),
                title=title,
                content=content,
                metadata={
                    "filename": file_path.name,
                    "size_bytes": file_path.stat().st_size,
                }
            )

            # Add to items
            self.items.append(item)
            self.seen_hashes.add(content_hash)
            self.stats.files_accepted += 1

            # Update counts
            self.stats.topic_counts[topic] = self.stats.topic_counts.get(topic, 0) + 1
            self.stats.provenance_counts[provenance] = self.stats.provenance_counts.get(provenance, 0) + 1

            # Move to processed
            if move_processed:
                try:
                    dest = processed_dir / file_path.name
                    shutil.move(str(file_path), str(dest))
                except:
                    pass

        # Save manifest
        self._save_manifest()

        return self.stats

    def search_by_topic(self, topic: str) -> List[IngestedItem]:
        """Search ingested items by topic."""
        return [item for item in self.items if item.topic_bucket == topic]

    def search_local(self, query: str, topics: Optional[List[str]] = None) -> List[IngestedItem]:
        """Search local knowledge for query."""
        results = []
        query_lower = query.lower()

        for item in self.items:
            if topics and item.topic_bucket not in topics:
                continue

            if query_lower in item.content.lower() or query_lower in item.title.lower():
                results.append(item)

        return results

    def get_stats(self) -> IngestStats:
        """Get ingestion statistics."""
        return self.stats

    def get_all_items(self) -> List[IngestedItem]:
        """Get all ingested items."""
        return self.items

    def search_knowledge(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search knowledge and return as dict for browser fallback."""
        results = self.search_local(query)[:limit]
        return [
            {
                "topic": item.topic_bucket,
                "title": item.title,
                "content": item.content,
                "source": item.provenance,
            }
            for item in results
        ]


def get_ingestor(base_dir: str = "data/knowledge") -> SeedIngestor:
    """Get or create seed ingestor singleton."""
    if not hasattr(get_ingestor, "_instance"):
        get_ingestor._instance = SeedIngestor(base_dir)
    return get_ingestor._instance
