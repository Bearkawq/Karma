"""Saved Page Digest - Handle saved pages including MHT/MHTML formats.

Supports:
- .mht (MHTML - MIME HTML)
- .mhtml (MIME HTML)
- .html saved pages

Features:
- Extract HTML from MHT containers
- Clean boilerplate
- Preserve title/headings
- Quarantine bad extractions
- Store provenance as saved_page / dropbox_import
"""

from __future__ import annotations

import base64
import hashlib
import html as html_module
import re
import email
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SavedPage:
    """A parsed saved page."""
    url: str
    title: str
    content: str
    content_type: str
    source_file: str
    provenance: str
    timestamp: str
    content_hash: str
    success: bool
    error: Optional[str] = None


MHT_BOUNDARY_RE = re.compile(r'--([^"\s]+)')


class SavedPageDigester:
    """Extract content from saved pages (MHT, MHTML, HTML)."""
    
    def __init__(self, output_dir: str = "data/knowledge/saved_pages"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._emit_pulse("init", "Initialized saved page digester")
    
    def digest_file(self, file_path: str) -> SavedPage:
        """Digest a saved page file."""
        path = Path(file_path)
        
        if not path.exists():
            return SavedPage(
                url="",
                title="",
                content="",
                content_type="",
                source_file=str(path),
                provenance="saved_page",
                timestamp=datetime.now().isoformat(),
                content_hash="",
                success=False,
                error="File not found",
            )
        
        suffix = path.suffix.lower()
        
        try:
            if suffix == ".mht" or suffix == ".mhtml":
                return self._parse_mht(path)
            elif suffix in (".html", ".htm"):
                return self._parse_html(path)
            else:
                return SavedPage(
                    url="",
                    title="",
                    content="",
                    content_type="",
                    source_file=str(path),
                    provenance="saved_page",
                    timestamp=datetime.now().isoformat(),
                    content_hash="",
                    success=False,
                    error=f"Unsupported format: {suffix}",
                )
        except Exception as e:
            return SavedPage(
                url="",
                title="",
                content="",
                content_type="",
                source_file=str(path),
                provenance="saved_page",
                timestamp=datetime.now().isoformat(),
                content_hash="",
                success=False,
                error=f"Parse error: {str(e)}",
            )
    
    def digest_directory(self, dir_path: str) -> List[SavedPage]:
        """Digest all saved pages in a directory."""
        results = []
        
        path = Path(dir_path)
        if not path.exists():
            return results
        
        for file_path in path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in (".mht", ".mhtml", ".html", ".htm"):
                result = self.digest_file(str(file_path))
                results.append(result)
                
                if result.success:
                    self._save_to_knowledge(result)
        
        return results
    
    def _parse_mht(self, path: Path) -> SavedPage:
        """Parse MHT/MHTML file."""
        content = path.read_bytes()
        
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            text = content.decode("latin-1", errors="replace")
        
        msg = email.message_from_string(text)
        
        url = msg.get("X-WebKitURL", "") or msg.get("X-Url", "") or ""
        title = msg.get("Subject", "") or "Untitled"
        
        html_content = ""
        content_type = "text/html"
        
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/html":
                    html_content = part.get_payload(decode=True)
                    if isinstance(html_content, bytes):
                        html_content = html_content.decode("utf-8", errors="replace")
                    content_type = ct
                    break
                elif ct == "text/plain" and not html_content:
                    plain = part.get_payload(decode=True)
                    if isinstance(plain, bytes):
                        plain = plain.decode("utf-8", errors="replace")
        else:
            html_content = msg.get_payload(decode=True)
            if isinstance(html_content, bytes):
                html_content = html_content.decode("utf-8", errors="replace")
        
        if not html_content:
            content_bytes = path.read_bytes()
            html_content = self._extract_html_from_mht_raw(content_bytes)
        
        if not html_content:
            return SavedPage(
                url=url,
                title=title,
                content="",
                content_type=content_type,
                source_file=str(path),
                provenance="saved_page",
                timestamp=datetime.now().isoformat(),
                content_hash="",
                success=False,
                error="No HTML content found in MHT",
            )
        
        cleaned = self._clean_html(html_content)
        content_hash = hashlib.sha256(cleaned.encode()).hexdigest()[:16]
        
        return SavedPage(
            url=url,
            title=title[:100],
            content=cleaned,
            content_type=content_type,
            source_file=str(path),
            provenance="saved_page",
            timestamp=datetime.now().isoformat(),
            content_hash=content_hash,
            success=True,
        )
    
    def _extract_html_from_mht_raw(self, content: bytes) -> str:
        """Extract HTML from raw MHT content as fallback."""
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            return ""
        
        boundary_match = MHT_BOUNDARY_RE.search(text)
        if boundary_match:
            boundary = boundary_match.group(1)
            parts = text.split(f"--{boundary}")
            
            for part in parts:
                if "text/html" in part:
                    match = re.search(r'<html.*?</html>', part, re.DOTALL | re.IGNORECASE)
                    if match:
                        return match.group(0)
        
        return ""
    
    def _parse_html(self, path: Path) -> SavedPage:
        """Parse regular HTML file."""
        content = path.read_text(encoding="utf-8", errors="replace")
        
        title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
        title = html_module.unescape(title_match.group(1).strip()) if title_match else path.stem
        
        url_match = re.search(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?\d+;[\s]*url=([^"\']+)', content, re.IGNORECASE)
        url = url_match.group(1).strip() if url_match else ""
        
        cleaned = self._clean_html(content)
        content_hash = hashlib.sha256(cleaned.encode()).hexdigest()[:16]
        
        return SavedPage(
            url=url,
            title=title[:100],
            content=cleaned,
            content_type="text/html",
            source_file=str(path),
            provenance="saved_page",
            timestamp=datetime.now().isoformat(),
            content_hash=content_hash,
            success=True,
        )
    
    def _clean_html(self, html: str) -> str:
        """Clean HTML content, removing boilerplate."""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<aside[^>]*>.*?</aside>", "", text, flags=re.DOTALL | re.IGNORECASE)
        
        text = re.sub(r"<h1[^>]*>", "\n# ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h2[^>]*>", "\n## ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h3[^>]*>", "\n### ", text, flags=re.IGNORECASE)
        
        text = re.sub(r"<pre[^>]*>", "\n```\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</pre>", "\n```\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<code[^>]*>", "`", text, flags=re.IGNORECASE)
        text = re.sub(r"</code>", "`", text, flags=re.IGNORECASE)
        
        text = re.sub(r"<p[^>]*>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
        
        text = re.sub(r"<[^>]+>", " ", text)
        
        text = html_module.unescape(text)
        
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        
        lines = text.split("\n")
        cleaned = [l.strip() for l in lines if len(l.strip()) > 15]
        
        return "\n".join(cleaned)[:30_000]
    
    def _save_to_knowledge(self, page: SavedPage) -> None:
        """Save parsed page to knowledge store."""
        import json
        
        import uuid
        
        title_slug = re.sub(r'[^a-z0-9]', '_', page.title.lower())[:30]
        if not title_slug:
            title_slug = "untitled"
        
        filename = f"{page.content_hash}_{title_slug}.json"
        
        topic = self._classify_topic(page)
        
        data = {
            "url": page.url,
            "title": page.title,
            "content": page.content,
            "content_type": page.content_type,
            "source_file": page.source_file,
            "provenance": page.provenance,
            "timestamp": page.timestamp,
            "content_hash": page.content_hash,
            "topic_bucket": topic,
        }
        
        with open(self.output_dir / filename, "w") as f:
            json.dump(data, f, indent=2)
        
        self._emit_pulse("success", f"Saved: {page.title[:30]}")
    
    def _classify_topic(self, page: SavedPage) -> str:
        """Classify topic from page content."""
        content_lower = page.content.lower()[:5000]
        title_lower = page.title.lower()
        
        if "python" in content_lower or "python" in title_lower:
            return "python"
        elif "kali" in content_lower or "linux" in content_lower:
            return "kali_linux"
        elif "debug" in content_lower or "error" in content_lower:
            return "debugging"
        elif "api" in content_lower or "reference" in content_lower:
            return "docs_reference"
        
        return "saved_pages"
    
    def _emit_pulse(self, event_type: str, message: str):
        """Emit pulse event."""
        try:
            from research.pulse import get_pulse
            pulse = get_pulse()
            pulse.emit_action(message, "saved_page_digest")
        except Exception:
            pass


_digester_instance: Optional[SavedPageDigester] = None


def get_digester() -> SavedPageDigester:
    """Get or create digester singleton."""
    global _digester_instance
    if _digester_instance is None:
        _digester_instance = SavedPageDigester()
    return _digester_instance


def digest_saved_page(file_path: str) -> SavedPage:
    """Digest a single saved page."""
    digester = get_digester()
    result = digester.digest_file(file_path)
    if result.success:
        digester._save_to_knowledge(result)
    return result


def digest_saved_pages(dir_path: str) -> List[SavedPage]:
    """Digest all saved pages in a directory."""
    digester = get_digester()
    return digester.digest_directory(dir_path)
