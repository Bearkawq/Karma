"""Browser Agent - Handles URL fetching for navigation."""

from __future__ import annotations

import re
import urllib.request
import html
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
FETCH_TIMEOUT = 20.0
MAX_PAGE_SIZE = 800_000


@dataclass
class FetchResult:
    """Result from fetching a URL."""
    url: str
    title: str
    content: str
    internal_links: List[str]
    success: bool
    error: Optional[str] = None
    depth: int = 0


class BrowserAgent:
    """Handles fetching and basic parsing of web pages."""
    
    def __init__(self, visited: Optional[Set[str]] = None):
        self.visited: Set[str] = visited or set()
        self.session_dir: Optional[Path] = None
    
    def set_session_dir(self, path: Path):
        """Set directory for saving artifacts."""
        self.session_dir = path
        self.session_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch(self, url: str, depth: int = 0) -> FetchResult:
        """Fetch a URL and extract basic content."""
        if url in self.visited:
            return FetchResult(
                url=url,
                title="",
                content="",
                internal_links=[],
                success=False,
                error="Already visited",
                depth=depth,
            )
        
        self.visited.add(url)
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                raw = resp.read(MAX_PAGE_SIZE).decode("utf-8", errors="replace")
        except Exception as e:
            return FetchResult(
                url=url,
                title="",
                content="",
                internal_links=[],
                success=False,
                error=f"Fetch failed: {e}",
                depth=depth,
            )
        
        # Extract title
        title_match = re.search(r"<title>(.*?)</title>", raw, re.IGNORECASE)
        title = html.unescape(title_match.group(1).strip()) if title_match else ""
        
        # Extract main content
        content = self._extract_content(raw)
        
        # Extract internal links
        internal_links = self._extract_wiki_links(raw)
        
        # Save artifact
        if self.session_dir:
            self._save_artifact(url, title, content)
        
        return FetchResult(
            url=url,
            title=title,
            content=content,
            internal_links=internal_links,
            success=True,
            depth=depth,
        )
    
    def _extract_content(self, html_text: str) -> str:
        """Extract readable content from HTML."""
        # Check if this is a Wikipedia page - use special extraction
        # Check for Wikipedia-specific markers in the HTML
        if "mw-content-text" in html_text[:10000] or "wikipedia" in html_text[:5000].lower():
            return self._extract_wikipedia_content(html_text)
        
        # Remove scripts and styles
        text = re.sub(r"<script[^>]*>.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<aside[^>]*>.*?</aside>", "", text, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove remaining tags but keep structure
        text = re.sub(r"<br[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<h[1-6][^>]*>", "\n\n## ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        
        # Decode HTML entities
        text = html.unescape(text)
        
        # Clean whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        
        # Remove short noise lines
        lines = text.split("\n")
        cleaned = [l for l in lines if len(l.strip()) > 15]
        text = "\n".join(cleaned)
        
        return text.strip()[:20_000]
    
    def _extract_wikipedia_content(self, html_text: str) -> str:
        """Extract main article content from Wikipedia HTML."""
        # Find the main content div - prefer mw-content-text which is the article body
        match = re.search(r'<div[^>]+id="mw-content-text"[^>]*>(.*?)</div>\s*<div[^>]+class="[^"]*print[^"]*"', html_text, re.DOTALL | re.IGNORECASE)
        if not match:
            match = re.search(r'<div[^>]+class="[^"]*mw-body[^"]*"[^>]*>(.*?)</div>\s*<div[^>]+id="footer"', html_text, re.DOTALL | re.IGNORECASE)
        if not match:
            match = re.search(r'<div[^>]+id="bodyContent"[^>]*>(.*?)</div>\s*<div[^>]+id="footer"', html_text, re.DOTALL | re.IGNORECASE)
        if not match:
            match = re.search(r'<div[^>]+id="content"[^>]*>(.*?)</div>', html_text, re.DOTALL | re.IGNORECASE)
        
        if not match:
            content = html_text
        else:
            content = match.group(1)
        
        # Remove scripts, styles, and navigation elements
        content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<nav[^>]*>.*?</nav>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<table[^>]*class=[^>]*navbox[^>]*>.*?</table>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<div[^>]*class=[^>]*sidebar[^>]*>.*?</div>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<div[^>]*class=[^>]*printfooter[^>]*>.*?</div>", "", content, flags=re.DOTALL | re.IGNORECASE)
        
        # Convert headings
        content = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n\n## \1\n\n", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n\n### \1\n\n", content, flags=re.DOTALL | re.IGNORECASE)
        
        # Convert paragraphs and breaks
        content = re.sub(r"<br[^>]*>", "\n", content, flags=re.IGNORECASE)
        content = re.sub(r"<p[^>]*>", "\n\n", content, flags=re.IGNORECASE)
        
        # Remove remaining HTML tags
        content = re.sub(r"<[^>]+>", " ", content)
        
        # Decode HTML entities
        content = html.unescape(content)
        
        # Clean whitespace
        content = re.sub(r"[ \t]+", " ", content)
        content = re.sub(r"\n{4,}", "\n\n\n", content)
        
        # Clean up extracted content - remove Wikipedia UI noise
        lines = content.split("\n")
        cleaned = []
        skip_mode = False
        skip_remaining = 0
        
        for line in lines:
            stripped = line.strip()
            
            # Detect language bar pattern - starts with language names or UI elements
            if (stripped.startswith("العربية") or stripped.startswith("Azərbaycanca") or 
                stripped.startswith("বাংলা") or stripped.startswith("中文") or
                stripped.startswith("Donate") or
                stripped.startswith("Create account") or
                stripped.startswith("Log in") or
                (len(stripped) > 50 and "Azərbaycanca" in stripped)):
                skip_remaining = 3  # Skip this + next 2 lines
                continue
            
            if skip_remaining > 0:
                skip_remaining -= 1
                continue
            
            # Skip known noise patterns
            if stripped.startswith("From Wikipedia"):
                continue
                
            cleaned.append(line)
        
        content = "\n".join(cleaned)
        
        # Final cleanup - remove multiple spaces
        content = re.sub(r" {2,}", " ", content)
        
        return content.strip()[:20_000]
    
    def _extract_wiki_links(self, html_text: str) -> List[str]:
        """Extract Wikipedia internal article links."""
        links = []
        
        # Match /wiki/Article_Title links (excluding special pages)
        pattern = re.compile(r'<a[^>]+href="(/wiki/[^#":]+)"[^>]*>', re.IGNORECASE)
        
        for match in pattern.finditer(html_text):
            href = match.group(1)
            
            # Skip main page and special pages
            if href in ("/wiki/Main_Page", "/wiki/Wikipedia:") or ":" in href:
                continue
            
            full_url = f"https://en.wikipedia.org{href}"
            if full_url not in links:
                links.append(full_url)
        
        return links[:30]
    
    def _save_artifact(self, url: str, title: str, content: str):
        """Save fetched content to file."""
        if not self.session_dir:
            return
        
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        filename = f"nav_{url_hash}.txt"
        path = self.session_dir / filename
        
        path.write_text(
            f"URL: {url}\n"
            f"Title: {title}\n"
            f"---CONTENT---\n"
            f"{content}",
            encoding="utf-8",
        )
    
    def is_visited(self, url: str) -> bool:
        """Check if URL was already visited."""
        return url in self.visited
    
    def mark_visited(self, url: str):
        """Mark a URL as visited."""
        self.visited.add(url)
    
    def reset(self):
        """Reset visited set."""
        self.visited.clear()