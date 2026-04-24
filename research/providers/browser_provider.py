"""Browser-based fallback search provider.

This provider tries multiple search engines as fallback when primary providers fail.
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from research.crawler import (
    MAX_PAGE_SIZE,
    FETCH_TIMEOUT,
    USER_AGENT,
)

from .base import DiagnosticCode, ProviderDiagnostics, SearchProvider, SearchResult


class BrowserSearchProvider(SearchProvider):
    """Browser-based fallback search - tries multiple engines then local knowledge."""

    def __init__(self, session_dir: Path):
        super().__init__("browser_fallback")
        self.session_dir = session_dir
        self.web_dir = session_dir / "web"
        self.web_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_counter = 0

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        results, diag = self._search_ddg_lite(query, max_results)
        if results:
            return results, diag

        results, diag = self._search_brave(query, max_results)
        if results:
            return results, diag

        return self._search_local(query, max_results)

    def _search_ddg_lite(self, query: str, max_results: int) -> tuple[List[SearchResult], ProviderDiagnostics]:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://lite.duckduckgo.com/lite/?q={encoded}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read(MAX_PAGE_SIZE).decode("utf-8", errors="replace")
        except Exception:
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message="DDG Lite failed",
                provider=self.name,
            )

        results = self._parse_ddg(raw, max_results)
        if results:
            for r in results:
                r.quality = self._score_domain(r.url)
            return results[:max_results], ProviderDiagnostics(
                code=DiagnosticCode.PROVIDER_OK,
                message=f"Found {len(results)} from DDG Lite",
                provider=self.name,
            )
        return [], ProviderDiagnostics(code=DiagnosticCode.SEARCH_EMPTY, message="No results", provider=self.name)

    def _search_brave(self, query: str, max_results: int) -> tuple[List[SearchResult], ProviderDiagnostics]:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://search.brave.com/search?q={encoded}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read(MAX_PAGE_SIZE).decode("utf-8", errors="replace")
        except Exception:
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message="Brave failed",
                provider=self.name,
            )

        results = self._parse_brave(raw, max_results)
        if results:
            for r in results:
                r.quality = self._score_domain(r.url)
            return results[:max_results], ProviderDiagnostics(
                code=DiagnosticCode.PROVIDER_OK,
                message=f"Found {len(results)} from Brave",
                provider=self.name,
            )
        return [], ProviderDiagnostics(code=DiagnosticCode.SEARCH_EMPTY, message="No results", provider=self.name)

    def _search_local(self, query: str, max_results: int) -> tuple[List[SearchResult], ProviderDiagnostics]:
        try:
            from research.ingestor import SeedIngestor
            ingestor = SeedIngestor()
            items = ingestor.search_knowledge(query, limit=max_results)

            results = []
            for item in items:
                content = item.get("content", "") or item.get("text", "")
                if content:
                    results.append(SearchResult(
                        url=f"local://{item.get('topic', 'knowledge')}",
                        title=item.get("topic", "Local"),
                        snippet=content[:200].replace("\n", " "),
                        quality=0.8,
                    ))

            if results:
                return results, ProviderDiagnostics(
                    code=DiagnosticCode.CACHE_HIT,
                    message=f"Found {len(results)} from local",
                    provider=self.name,
                )
        except Exception:
            pass

        return [], ProviderDiagnostics(
            code=DiagnosticCode.PROVIDER_EXHAUSTED,
            message="All methods failed",
            provider=self.name,
        )

    def _parse_ddg(self, html: str, max_results: int) -> List[SearchResult]:
        results = []
        pattern = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>.*?result__snippet[^>]*>(.*?)</a>', re.DOTALL)
        for m in pattern.finditer(html):
            url = m.group(1).strip()
            if url and not url.startswith("#"):
                results.append(SearchResult(
                    url=url,
                    title=html.unescape(m.group(2).strip())[:200],
                    snippet=html.unescape(m.group(3).strip())[:300] if m.group(3) else "",
                    quality=0.5,
                ))
        return results[:max_results]

    def _parse_brave(self, html: str, max_results: int) -> List[SearchResult]:
        results = []
        pattern = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]+class="[^"]*result[^"]*"[^>]*>.*?<span[^>]*class="title[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
        seen = set()
        for m in pattern.finditer(html):
            url = m.group(1).strip()
            if url and url not in seen and url.startswith("http"):
                seen.add(url)
                results.append(SearchResult(
                    url=url,
                    title=html.unescape(m.group(2).strip())[:200] if m.group(2) else "",
                    snippet="",
                    quality=0.5,
                ))
        return results[:max_results]

    def _score_domain(self, url: str) -> float:
        high = ["github.com", "stackoverflow.com", "docs.python.org"]
        med = ["medium.com", "blog", "tutorial"]
        url_lower = url.lower()
        for d in high:
            if d in url_lower: return 0.9
        for d in med:
            if d in url_lower: return 0.6
        return 0.4

    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout or FETCH_TIMEOUT) as resp:
                raw = resp.read(MAX_PAGE_SIZE).decode("utf-8", errors="replace")

            text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
            text = re.sub(r"[ \t]+", " ", text)

            self._artifact_counter += 1
            path = self.web_dir / f"artifact_{self._artifact_counter}.txt"
            path.write_text(text[:10000], encoding="utf-8")

            return {"url": url, "content": text[:10000], "path": str(path), "size": len(text)}
        except Exception:
            return None
