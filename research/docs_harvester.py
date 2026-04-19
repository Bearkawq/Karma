"""Documentation Harvester - Harvest documentation from structured sites.

Supports harvesting from:
- docs.python.org
- kali.org/docs
- debian.org/doc
- readthedocs-style sites

Usage:
- harvest docs <url>
- harvest python docs
- harvest kali docs
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
import html
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FETCH_TIMEOUT = 20.0
MAX_PAGE_SIZE = 500_000


DOCS_SOURCES = {
    "python": {
        "base_url": "https://docs.python.org/3/",
        "name": "Python Documentation",
        "link_patterns": [r"/3/[a-z_/]+$", r"/3/library/[a-z_]+\.html$"],
        "ignore_patterns": [r"/3/genindex", r"/3/py-modindex", r"/3/whatsnew"],
    },
    "kali": {
        "base_url": "https://www.kali.org/docs/",
        "name": "Kali Linux Documentation",
        "link_patterns": [r"/docs/[a-z\-/]+/$", r"/docs/[a-z\-/]+#[a-z\-]+$"],
        "ignore_patterns": [r"/docs/search", r"/docs/atom", r"/docsTags"],
    },
    "debian": {
        "base_url": "https://www.debian.org/doc/",
        "name": "Debian Documentation",
        "link_patterns": [r"/doc/[a-z\-/]+", r"/distrib/notes"],
        "ignore_patterns": [r"/search", r"/CD/"],
    },
}


@dataclass
class HarvestedDoc:
    """A single harvested documentation page."""
    url: str
    title: str
    content: str
    headings: List[str]
    code_blocks: int
    provenance: str
    source_type: str
    topic_bucket: str
    timestamp: str
    content_hash: str


@dataclass
class HarvestStats:
    """Statistics from a harvest run."""
    pages_visited: int = 0
    pages_harvested: int = 0
    duplicates_skipped: int = 0
    pages_failed: int = 0
    code_blocks_total: int = 0
    stop_reason: str = ""
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class DocsHarvester:
    """Harvest documentation from structured sites."""
    
    def __init__(self, output_dir: str = "data/knowledge/docs_harvest"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.visited: Set[str] = set()
        self.seen_hashes: Set[str] = set()
        
        self._emit_pulse("init", f"Initialized docs harvester")
    
    def harvest(self, source: str = "python", max_pages: int = 10, 
                max_depth: int = 2) -> HarvestStats:
        """Harvest documentation from a source."""
        stats = HarvestStats()
        
        source_config = DOCS_SOURCES.get(source.lower())
        if not source_config:
            stats.stop_reason = f"Unknown source: {source}"
            stats.errors.append(stats.stop_reason)
            return stats
        
        self._emit_pulse("start", f"Harvesting {source_config['name']}")
        
        start_url = source_config["base_url"]
        topic_bucket = source.lower()
        
        queue: List[tuple] = [(start_url, 0)]
        
        while queue and stats.pages_harvested < max_pages:
            url, depth = queue.pop(0)
            
            if url in self.visited or depth > max_depth:
                continue
            
            self._emit_pulse("fetch", f"Fetching: {url}")
            stats.pages_visited += 1
            
            try:
                doc = self._fetch_page(url, source, topic_bucket)
                
                if not doc:
                    stats.pages_failed += 1
                    continue
                
                content_hash = doc.content_hash
                if content_hash in self.seen_hashes:
                    stats.duplicates_skipped += 1
                    continue
                
                self._save_doc(doc)
                self.seen_hashes.add(content_hash)
                stats.pages_harvested += 1
                stats.code_blocks_total += doc.code_blocks
                
                self._emit_pulse("success", f"Harvested: {doc.title[:40]}")
                
                if depth < max_depth:
                    links = self._extract_doc_links(doc.content, url, source_config)
                    for link in links[:5]:
                        if link not in self.visited:
                            queue.append((link, depth + 1))
                            
            except Exception as e:
                stats.pages_failed += 1
                stats.errors.append(f"{url}: {str(e)}")
                self._emit_pulse("error", f"Failed: {url}")
        
        if stats.pages_harvested >= max_pages:
            stats.stop_reason = "max_pages"
        elif not queue:
            stats.stop_reason = "completed"
        else:
            stats.stop_reason = "queue_empty"
        
        self._emit_pulse("stop", f"Harvest complete: {stats.stop_reason}")
        
        return stats
    
    def harvest_url(self, url: str, max_pages: int = 5) -> HarvestStats:
        """Harvest from a specific URL."""
        stats = HarvestStats()
        
        self._emit_pulse("start", f"Harvesting {url}")
        
        source_type = self._detect_source_type(url)
        topic_bucket = source_type if source_type else "docs"
        
        queue = [(url, 0)]
        
        while queue and stats.pages_harvested < max_pages:
            page_url, depth = queue.pop(0)
            
            if page_url in self.visited:
                continue
            
            stats.pages_visited += 1
            
            try:
                doc = self._fetch_page(page_url, source_type or "generic", topic_bucket)
                
                if not doc:
                    stats.pages_failed += 1
                    continue
                
                if doc.content_hash in self.seen_hashes:
                    stats.duplicates_skipped += 1
                    continue
                
                self._save_doc(doc)
                self.seen_hashes.add(doc.content_hash)
                stats.pages_harvested += 1
                stats.code_blocks_total += doc.code_blocks
                
                self._emit_pulse("success", f"Harvested: {doc.title[:40]}")
                
                if depth < 2:
                    links = self._extract_generic_links(doc.content, page_url)
                    for link in links[:5]:
                        if link not in self.visited:
                            queue.append((link, depth + 1))
                            
            except Exception as e:
                stats.pages_failed += 1
                stats.errors.append(f"{page_url}: {str(e)}")
        
        stats.stop_reason = "completed" if stats.pages_harvested >= max_pages else "done"
        return stats
    
    def _detect_source_type(self, url: str) -> Optional[str]:
        """Detect source type from URL."""
        url_lower = url.lower()
        if "python.org" in url_lower:
            return "python"
        elif "kali.org" in url_lower:
            return "kali"
        elif "debian.org" in url_lower:
            return "debian"
        elif "readthedocs" in url_lower or "rtfd" in url_lower:
            return "readthedocs"
        return None
    
    def _fetch_page(self, url: str, source_type: str, topic_bucket: str) -> Optional[HarvestedDoc]:
        """Fetch a single documentation page."""
        if url in self.visited:
            return None
        self.visited.add(url)
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                raw = resp.read(MAX_PAGE_SIZE).decode("utf-8", errors="replace")
        except Exception as e:
            self._emit_pulse("error", f"Fetch error: {e}")
            return None
        
        title = self._extract_title(raw)
        content = self._extract_doc_content(raw)
        headings = self._extract_headings(raw)
        code_blocks = self._count_code_blocks(raw)
        
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        
        return HarvestedDoc(
            url=url,
            title=title,
            content=content,
            headings=headings,
            code_blocks=code_blocks,
            provenance="docs_harvest",
            source_type=source_type,
            topic_bucket=topic_bucket,
            timestamp=datetime.now().isoformat(),
            content_hash=content_hash,
        )
    
    def _extract_title(self, html_text: str) -> str:
        """Extract page title."""
        match = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE)
        if match:
            title = html.unescape(match.group(1).strip())
            title = title.replace(" — ", " - ").replace("  ", " ")
            return title[:100]
        return "Untitled"
    
    def _extract_doc_content(self, html_text: str) -> str:
        """Extract readable content from documentation HTML."""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<aside[^>]*>.*?</aside>", "", text, flags=re.DOTALL | re.IGNORECASE)
        
        text = re.sub(r"<h1[^>]*>", "\n\n# ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h2[^>]*>", "\n\n## ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h3[^>]*>", "\n\n### ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h4[^>]*>", "\n\n#### ", text, flags=re.IGNORECASE)
        
        text = re.sub(r"<pre[^>]*>", "\n```\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</pre>", "\n```\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<code[^>]*>", "`", text, flags=re.IGNORECASE)
        text = re.sub(r"</code>", "`", text, flags=re.IGNORECASE)
        
        text = re.sub(r"<p[^>]*>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
        
        text = re.sub(r"<[^>]+>", " ", text)
        
        text = html.unescape(text)
        
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        
        lines = text.split("\n")
        cleaned = [l.strip() for l in lines if len(l.strip()) > 10]
        text = "\n".join(cleaned)
        
        return text.strip()[:30_000]
    
    def _extract_headings(self, html_text: str) -> List[str]:
        """Extract headings from HTML."""
        headings = []
        for level in [1, 2, 3, 4]:
            pattern = re.compile(rf"<h{level}[^>]*>(.*?)</h{level}>", re.IGNORECASE | re.DOTALL)
            for match in pattern.finditer(html_text):
                heading = html.unescape(match.group(1).strip())
                heading = re.sub(r"<[^>]+>", "", heading)
                if heading and len(heading) < 100:
                    headings.append(heading)
        return headings[:20]
    
    def _count_code_blocks(self, html_text: str) -> int:
        """Count code blocks in HTML."""
        pre_count = len(re.findall(r"<pre[^>]*>", html_text, re.IGNORECASE))
        code_count = len(re.findall(r"<code[^>]*>", html_text, re.IGNORECASE))
        return max(pre_count, code_count // 2)
    
    def _extract_doc_links(self, html_text: str, base_url: str, source_config: Dict) -> List[str]:
        """Extract valid documentation links."""
        links = []
        
        pattern = re.compile(r'<a[^>]+href="([^"#:]+)"[^>]*>', re.IGNORECASE)
        
        for match in pattern.finditer(html_text):
            href = match.group(1)
            
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            
            if href.startswith("/"):
                href = urllib.parse.urljoin(base_url, href)
            
            if href.startswith("http") and base_url.split("/")[2] not in href:
                continue
            
            valid = True
            for ignore in source_config.get("ignore_patterns", []):
                if re.search(ignore, href, re.IGNORECASE):
                    valid = False
                    break
            
            if valid:
                links.append(href)
        
        return list(set(links))[:20]
    
    def _extract_generic_links(self, html_text: str, base_url: str) -> List[str]:
        """Extract links generically."""
        links = []
        
        pattern = re.compile(r'<a[^>]+href="([^"#:]+)"[^>]*>', re.IGNORECASE)
        
        for match in pattern.finditer(html_text):
            href = match.group(1)
            
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            
            if href.startswith("/"):
                href = urllib.parse.urljoin(base_url, href)
            
            if href.startswith("http") and base_url.split("/")[2] in href:
                links.append(href)
        
        return list(set(links))[:15]
    
    def _save_doc(self, doc: HarvestedDoc) -> None:
        """Save harvested document to disk."""
        import json
        
        topic_dir = self.output_dir / doc.topic_bucket
        topic_dir.mkdir(parents=True, exist_ok=True)
        
        url_hash = hashlib.md5(doc.url.encode()).hexdigest()[:8]
        filename = f"{url_hash}_{doc.timestamp.replace(':', '-')}.json"
        
        data = {
            "url": doc.url,
            "title": doc.title,
            "content": doc.content,
            "headings": doc.headings,
            "code_blocks": doc.code_blocks,
            "provenance": doc.provenance,
            "source_type": doc.source_type,
            "topic_bucket": doc.topic_bucket,
            "timestamp": doc.timestamp,
            "content_hash": doc.content_hash,
        }
        
        with open(topic_dir / filename, "w") as f:
            json.dump(data, f, indent=2)
    
    def _emit_pulse(self, event_type: str, message: str):
        """Emit pulse event."""
        try:
            from research.pulse import get_pulse
            pulse = get_pulse()
            pulse.emit_action(message, "harvester")
        except Exception:
            pass


_harvester_instance: Optional[DocsHarvester] = None


def get_harvester() -> DocsHarvester:
    """Get or create harvester singleton."""
    global _harvester_instance
    if _harvester_instance is None:
        _harvester_instance = DocsHarvester()
    return _harvester_instance


def harvest_docs(source: str = "python", max_pages: int = 10) -> HarvestStats:
    """Harvest documentation from a source."""
    harvester = get_harvester()
    return harvester.harvest(source, max_pages)


def harvest_url(url: str, max_pages: int = 5) -> HarvestStats:
    """Harvest from a specific URL."""
    harvester = get_harvester()
    return harvester.harvest_url(url, max_pages)
