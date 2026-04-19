"""DuckDuckGo HTML search provider.

This provider uses DuckDuckGo's lite HTML interface for search results.
Falls back gracefully when blocked or rate-limited.
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from research.crawler import (
    MAX_PAGE_SIZE,
    FETCH_TIMEOUT,
    USER_AGENT,
    _HIGH_QUALITY_DOMAINS,
    _HIGH_QUALITY_PATTERNS,
    _LOW_QUALITY_PATTERNS,
)

from .base import DiagnosticCode, ProviderDiagnostics, SearchProvider, SearchResult


class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo HTML search provider."""

    def __init__(self, session_dir: Path):
        super().__init__("duckduckgo")
        self.session_dir = session_dir
        self.web_dir = session_dir / "web"
        self.web_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_counter = 0
        self.last_diagnostic: Optional[ProviderDiagnostics] = None

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        """Search DuckDuckGo HTML and return results with diagnostics."""
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                raw = resp.read(MAX_PAGE_SIZE).decode("utf-8", errors="replace")
        except urllib.error.URLError:
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_TIMEOUT,
                message="Search request timed out",
                provider=self.name,
            )
        except Exception:
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message="Search provider blocked the request (likely bot detection)",
                provider=self.name,
            )

        if self._is_blocked(raw):
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message="Search provider blocked the request (likely bot detection)",
                provider=self.name,
            )

        results = self._parse_results(raw, max_results + 3)
        if not results:
            if len(raw) < 500:
                return [], ProviderDiagnostics(
                    code=DiagnosticCode.SEARCH_EMPTY,
                    message="Search returned empty or near-empty results",
                    provider=self.name,
                )
            else:
                return [], ProviderDiagnostics(
                    code=DiagnosticCode.SEARCH_PARSE_ERROR,
                    message="Search results could not be parsed (provider may have changed format)",
                    provider=self.name,
                )

        for r in results:
            r.quality = self._score_domain(r.url)
        results.sort(key=lambda r: r.quality, reverse=True)

        return results[:max_results], ProviderDiagnostics(
            code=DiagnosticCode.PROVIDER_OK,
            message=f"Found {len(results)} results",
            provider=self.name,
        )

    def _is_blocked(self, raw_html: str) -> bool:
        """Detect if the search provider blocked us."""
        block_signals = [
            "captcha", "robot", "bot detection", "blocked",
            "access denied", "forbidden", "too many requests",
            "DDG does not share", "not a robot", "human verification",
        ]
        html_lower = raw_html.lower()
        if any(signal in html_lower for signal in block_signals):
            if "duckduckgo" in html_lower and ("captcha" in html_lower or "blocked" in html_lower):
                return True
            if len(raw_html) < 10000 and any(s in html_lower for s in ["access denied", "forbidden", "too many requests"]):
                return True
        if "/?e=" in raw_html or "uddg=" in raw_html:
            if "result" not in html_lower and "link" not in html_lower:
                return True
        return False

    def _parse_results(self, html_text: str, max_results: int) -> List[SearchResult]:
        """Parse DuckDuckGo HTML results."""
        link_patterns = [
            re.compile(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL),
            re.compile(r'class="[^"]*result[^"]*link[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL),
            re.compile(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL),
        ]
        snippet_patterns = [
            re.compile(r'class="result__snippet"[^>]*>(.*?)</(?:a|div|span|p)>', re.DOTALL),
            re.compile(r'class="[^"]*result[^"]*snippet[^"]*"[^>]*>(.*?)</(?:a|div|span|p)>', re.DOTALL),
        ]

        links = []
        for pat in link_patterns:
            links = pat.findall(html_text)
            if links:
                break

        snippets = []
        for pat in snippet_patterns:
            snippets = pat.findall(html_text)
            if snippets:
                break

        results: List[SearchResult] = []
        for i, (raw_url, raw_title) in enumerate(links[:max_results + 5]):
            try:
                actual_url = self._extract_url(raw_url)
                if not actual_url:
                    continue
                if "duckduckgo.com/y.js" in actual_url or "duckduckgo.com/l/" not in raw_url and not actual_url.startswith("http"):
                    continue
                title = self._strip_html(raw_title).strip()
                snippet = self._strip_html(snippets[i]).strip() if i < len(snippets) else ""
                results.append(SearchResult(title=title, url=actual_url, snippet=snippet))
                if len(results) >= max_results:
                    break
            except Exception:
                continue
        return results

    def _extract_url(self, raw_url: str) -> Optional[str]:
        """Extract actual URL from DuckDuckGo redirect."""
        raw_url = html.unescape(raw_url)
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        if "uddg=" in raw_url:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
            urls = parsed.get("uddg", [])
            if urls:
                return urllib.parse.unquote(urls[0])
        if raw_url.startswith("http"):
            return raw_url
        return None

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
