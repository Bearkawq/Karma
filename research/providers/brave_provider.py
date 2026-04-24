"""Brave Search HTML provider.

This provider uses Brave Search's web interface for search results.
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from research.crawler import (
    MAX_PAGE_SIZE,
    FETCH_TIMEOUT,
    USER_AGENT,
    _HIGH_QUALITY_DOMAINS,
    _HIGH_QUALITY_PATTERNS,
    _LOW_QUALITY_PATTERNS,
)

from .base import DiagnosticCode, ProviderDiagnostics, SearchProvider, SearchResult


class BraveSearchProvider(SearchProvider):
    """Brave Search HTML provider."""

    def __init__(self, session_dir: Path, api_key: Optional[str] = None):
        super().__init__("brave")
        self.session_dir = session_dir
        self.web_dir = session_dir / "web"
        self.web_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_counter = 0
        self.api_key = api_key
        self.last_diagnostic: Optional[ProviderDiagnostics] = None

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        """Search Brave Search HTML and return results with diagnostics."""
        encoded = urllib.parse.quote_plus(query)
        url = f"https://search.brave.com/reserve?q={encoded}&count={max_results}"

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
            })
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                raw = resp.read(MAX_PAGE_SIZE).decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_TIMEOUT,
                message=f"Search request timed out: {e}",
                provider=self.name,
            )
        except Exception as e:
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message=f"Brave Search blocked or unavailable: {e}",
                provider=self.name,
            )

        if self._is_blocked(raw):
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message="Brave Search blocked the request (likely bot detection)",
                provider=self.name,
            )

        results = self._parse_results(raw, max_results)
        if not results:
            if len(raw) < 500:
                return [], ProviderDiagnostics(
                    code=DiagnosticCode.SEARCH_EMPTY,
                    message="Brave Search returned empty results",
                    provider=self.name,
                )
            else:
                return [], ProviderDiagnostics(
                    code=DiagnosticCode.SEARCH_PARSE_ERROR,
                    message="Brave Search results could not be parsed",
                    provider=self.name,
                )

        for r in results:
            r.quality = self._score_domain(r.url)

        return results[:max_results], ProviderDiagnostics(
            code=DiagnosticCode.PROVIDER_OK,
            message=f"Found {len(results)} results from Brave Search",
            provider=self.name,
        )

    def _is_blocked(self, raw_html: str) -> bool:
        """Detect if Brave Search blocked us."""
        block_signals = ["captcha", "robot", "blocked", "access denied", "forbidden"]
        html_lower = raw_html.lower()
        if any(signal in html_lower for signal in block_signals):
            if len(raw_html) < 10000:
                return True
        return False

    def _parse_results(self, html_text: str, max_results: int) -> List[SearchResult]:
        """Parse Brave Search results."""
        results: List[SearchResult] = []

        link_patterns = [
            re.compile(r'class="result[^"]*"[^>]*href="([^"]+)"', re.DOTALL),
            re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>', re.DOTALL),
        ]

        title_patterns = [
            re.compile(r'class="title[^"]*"[^>]*>(.*?)</a>', re.DOTALL),
            re.compile(r'<h3[^>]*>(.*?)</h3>', re.DOTALL),
        ]

        snippet_patterns = [
            re.compile(r'class="snippet[^"]*"[^>]*>(.*?)</div>', re.DOTALL),
            re.compile(r'class="description[^"]*"[^>]*>(.*?)</', re.DOTALL),
        ]

        links = []
        for pat in link_patterns:
            links = pat.findall(html_text)
            if links:
                break

        titles = []
        for pat in title_patterns:
            titles = pat.findall(html_text)
            if titles:
                break

        snippets = []
        for pat in snippet_patterns:
            snippets = pat.findall(html_text)
            if snippets:
                break

        for i, url in enumerate(links[:max_results]):
            if not url.startswith("http"):
                continue
            title = self._strip_html(titles[i]) if i < len(titles) else "Untitled"
            snippet = self._strip_html(snippets[i]) if i < len(snippets) else ""
            results.append(SearchResult(title=title, url=url, snippet=snippet))

        return results

    def _score_domain(self, url: str) -> float:
        """Score a URL by domain quality."""
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            return 0.5
        if host.startswith("www."):
            host = host[4:]
        if host in _HIGH_QUALITY_DOMAINS:
            return 1.0
        if _HIGH_QUALITY_PATTERNS.search(url):
            return 0.8
        if _LOW_QUALITY_PATTERNS.search(url):
            return 0.2
        return 0.5

    def _strip_html(self, text: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", text))

    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single page."""
        timeout = timeout or FETCH_TIMEOUT
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return None
                raw_bytes = resp.read(MAX_PAGE_SIZE)
        except Exception:
            return None

        raw_html = raw_bytes.decode("utf-8", errors="replace")

        self._artifact_counter += 1
        art_id = f"art_{self._artifact_counter:04d}"

        title = self._extract_title(raw_html)
        text = self._html_to_text(raw_html)

        html_path = self.web_dir / f"{art_id}.html"
        text_path = self.web_dir / f"{art_id}.txt"
        meta_path = self.web_dir / f"{art_id}_meta.json"

        html_path.write_text(raw_html, encoding="utf-8")
        text_path.write_text(text, encoding="utf-8")

        artifact = {
            "id": art_id,
            "url": url,
            "title": title,
            "html_path": str(html_path),
            "text_path": str(text_path),
            "text": text[:8000],
            "fetch_ts": datetime.now().isoformat(timespec="seconds"),
            "size_bytes": len(raw_bytes),
        }
        import json
        meta_path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
        return artifact

    def _extract_title(self, html_text: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.DOTALL | re.IGNORECASE)
        return self._strip_html(m.group(1)).strip() if m else "Untitled"

    def _html_to_text(self, html_text: str) -> str:
        text = re.sub(
            r"<(script|style|nav|header|footer|aside|noscript)[^>]*>.*?</\1>",
            "", html_text, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(
            r"<[^>]+(class|id)=\"[^\"]*(?:nav|menu|sidebar|footer|header|breadcrumb|cookie)[^\"]*\"[^>]*>.*?</(?:div|ul|section|aside)>",
            "", text, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
