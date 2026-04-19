"""Search provider abstraction layer for GoLearn.

Provides a clean interface for multiple search backends with explicit
diagnostics for different failure modes.

Explicit diagnostics:
- search_provider_blocked: Search provider blocked the request
- search_timeout: Search request timed out
- search_parse_error: Search results could not be parsed
- search_empty: Search returned empty results
- fetch_timeout: Page fetch timed out
- fetch_error: Page could not be fetched
- queue_exhausted: Topic queue exhausted
- budget_exhausted: Time budget exhausted
- completed: Session completed normally
- partial_success: Some results obtained but not ideal
"""

from __future__ import annotations

import abc
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from research.crawler import (
    MAX_PAGE_SIZE,
    FETCH_TIMEOUT,
    USER_AGENT,
    _HIGH_QUALITY_DOMAINS,
    _HIGH_QUALITY_PATTERNS,
    _LOW_QUALITY_PATTERNS,
)

MAX_PAGES_PER_SLICE = 3

# Rate limiting configuration (tuned in 3.5.3b)
RATE_LIMIT_REQUESTS = 20  # Increased from 10 - too aggressive before
RATE_LIMIT_WINDOW = 60    # Time window in seconds
RETRY_BASE_DELAY = 1.0    # Base delay for exponential backoff
RETRY_MAX_DELAY = 10.0    # Max delay between retries
RETRY_MAX_ATTEMPTS = 3    # Max retry attempts


class DiagnosticCode:
    """Explicit diagnostic codes for provider failures."""
    SEARCH_PROVIDER_BLOCKED = "search_provider_blocked"
    SEARCH_TIMEOUT = "search_timeout"
    SEARCH_PARSE_ERROR = "search_parse_error"
    SEARCH_EMPTY = "search_empty"
    FETCH_TIMEOUT = "fetch_timeout"
    FETCH_ERROR = "fetch_error"
    QUEUE_EXHAUSTED = "queue_exhausted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    COMPLETED = "completed"
    LOW_YIELD = "low_yield"
    PROVIDER_OK = "provider_ok"
    CACHE_HIT = "cache_hit"
    CACHE_PARTIAL = "cache_partial"
    PARTIAL_SUCCESS = "partial_success"
    RATE_LIMITED = "rate_limited"
    PROVIDER_EXHAUSTED = "provider_exhausted"


@dataclass
class SearchResult:
    """Single search result from a provider."""
    title: str
    url: str
    snippet: str
    quality: float = 0.5


@dataclass
class ProviderDiagnostics:
    """Container for provider diagnostic information."""
    code: str
    message: str
    provider: str
    details: Dict[str, Any] = field(default_factory=dict)


class SearchProvider(abc.ABC):
    """Abstract base class for search providers."""

    def __init__(self, name: str):
        self.name = name

    @abc.abstractmethod
    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        """Execute search and return results with diagnostics."""
        pass

    @abc.abstractmethod
    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single page and return artifact dict."""
        pass


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
        meta_path.write_text(
            __import__("json").dumps(artifact, indent=2, default=str), encoding="utf-8"
        )
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


class BraveSearchProvider(SearchProvider):
    """Brave Search API provider - free tier available, different from DuckDuckGo."""

    def __init__(self, session_dir: Path, api_key: Optional[str] = None):
        super().__init__("brave")
        self.session_dir = session_dir
        self.web_dir = session_dir / "web"
        self.web_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_counter = 0
        self.api_key = api_key
        self.last_diagnostic: Optional[ProviderDiagnostics] = None

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        """Search Brave Search API and return results with diagnostics."""
        encoded = urllib.parse.quote_plus(query)
        
        # Brave Search API endpoint (free tier doesn't require API key for web search)
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
        
        # Brave Search result patterns
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
        
        # Extract links
        links = []
        for pat in link_patterns:
            links = pat.findall(html_text)
            if links:
                break
        
        # Extract titles
        titles = []
        for pat in title_patterns:
            titles = pat.findall(html_text)
            if titles:
                break
        
        # Extract snippets
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
        meta_path.write_text(
            __import__("json").dumps(artifact, indent=2, default=str), encoding="utf-8"
        )
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


class BingProvider(SearchProvider):
    """Bing HTML search provider - tested working in audit."""

    def __init__(self, session_dir: Path):
        super().__init__("bing")
        self.session_dir = session_dir
        self.web_dir = session_dir / "web"
        self.web_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_counter = 0
        self.last_diagnostic: Optional[ProviderDiagnostics] = None

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        """Search Bing HTML and return results with diagnostics."""
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.bing.com/search?q={encoded}&count={max_results}"

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html",
                "Accept-Language": "en-US,en;q=0.9",
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
                message=f"Bing blocked or unavailable: {e}",
                provider=self.name,
            )

        if self._is_blocked(raw):
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message="Bing blocked the request (likely bot detection)",
                provider=self.name,
            )

        results = self._parse_results(raw, max_results)
        if not results:
            if len(raw) < 500:
                return [], ProviderDiagnostics(
                    code=DiagnosticCode.SEARCH_EMPTY,
                    message="Bing returned empty results",
                    provider=self.name,
                )
            else:
                return [], ProviderDiagnostics(
                    code=DiagnosticCode.SEARCH_PARSE_ERROR,
                    message="Bing results could not be parsed",
                    provider=self.name,
                )

        for r in results:
            r.quality = self._score_domain(r.url)

        return results[:max_results], ProviderDiagnostics(
            code=DiagnosticCode.PROVIDER_OK,
            message=f"Found {len(results)} results from Bing",
            provider=self.name,
        )

    def _is_blocked(self, raw_html: str) -> bool:
        """Detect if Bing blocked us."""
        block_signals = ["captcha", "blocked", "access denied", "forbidden", "unusual traffic"]
        html_lower = raw_html.lower()
        if any(signal in html_lower for signal in block_signals):
            if len(raw_html) < 15000:
                return True
        return False

    def _parse_results(self, html_text: str, max_results: int) -> List[SearchResult]:
        """Parse Bing search results with robust fallback patterns."""
        results: List[SearchResult] = []
        
        # Try specific Bing patterns first
        link_patterns = [
            re.compile(r'href="(https?://[^"]+)"[^>]*><h2', re.DOTALL),
            re.compile(r'<a[^>]+class="b_title"[^>]*href="(https?://[^"]+)"', re.DOTALL),
            re.compile(r'class="b_algo"[^>]*>.*?href="(https?://[^"]+)"', re.DOTALL),
        ]
        
        # Generic fallback: extract all http links and filter
        generic_pattern = re.compile(r'href="(https?://[^"]+)"')
        
        # Get all links
        all_links = generic_pattern.findall(html_text)
        
        # Filter to external URLs (exclude Bing internal resources)
        external_links = []
        for link in all_links:
            # Skip internal Bing resources, CSS, images
            if any(ex in link for ex in ["r.bing.com", "th.bing.com", ".css", ".ico", ".png", ".jpg", "javascript:", "/sa/simg"]):
                continue
            # Skip self-referential bing.com links (like /search)
            if "bing.com" in link and "/search" in link:
                continue
            if link.startswith("http") and "bing.com" not in link:
                external_links.append(link)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_links = []
        for link in external_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)
        
        # If specific patterns failed but we have external links, use those
        links = unique_links[:max_results + 5]
        
        # For titles, use a generic approach
        title_patterns = [
            re.compile(r'<h2[^>]*>(.*?)</h2>', re.DOTALL),
            re.compile(r'class="b_title"[^>]*>(.*?)</', re.DOTALL),
            re.compile(r'<title>(.*?)</title>', re.DOTALL),
        ]
        
        titles = []
        for pat in title_patterns:
            titles = pat.findall(html_text)
            if titles:
                break
        
        # Snippets - generic fallback
        snippet_patterns = [
            re.compile(r'class="b_caption"[^>]*>(.*?)</p>', re.DOTALL),
            re.compile(r'class="b_desc"[^>]*>(.*?)</div>', re.DOTALL),
            re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL),
        ]
        
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
        meta_path.write_text(
            __import__("json").dumps(artifact, indent=2, default=str), encoding="utf-8"
        )
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


class FallbackProvider(SearchProvider):
    """Fallback provider that tries alternative queries when primary fails."""

    def __init__(self, primary: SearchProvider):
        super().__init__("fallback")
        self.primary = primary

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        """Try primary, then try fallback queries if primary fails or returns blocked."""
        results, diag = self.primary.search(query, max_results)
        
        # Check if results are usable
        if results and self._is_usable_result(results, diag):
            return results, diag
        
        # Try fallback queries for blocked or empty results
        if diag.code in (DiagnosticCode.SEARCH_PROVIDER_BLOCKED, DiagnosticCode.SEARCH_EMPTY, 
                        DiagnosticCode.SEARCH_PARSE_ERROR, DiagnosticCode.SEARCH_TIMEOUT):
            fallback_queries = self._generate_fallback_queries(query)
            for fallback_q in fallback_queries:
                results, diag = self.primary.search(fallback_q, max_results)
                if results and self._is_usable_result(results, diag):
                    diag.details["fallback_from"] = query
                    diag.details["fallback_to"] = fallback_q
                    return results, diag

        return results, diag

    def _is_usable_result(self, results: List[SearchResult], diag: ProviderDiagnostics) -> bool:
        """Check if results are actually usable (not just junk)."""
        if not results:
            return False
        # Check for suspiciously low-quality results
        quality_scores = [r.quality for r in results]
        if sum(quality_scores) / len(quality_scores) < 0.1:
            return False
        return True

    def _generate_fallback_queries(self, query: str) -> List[str]:
        """Generate alternative queries when primary fails."""
        words = query.lower().split()
        if len(words) <= 1:
            return []
        
        # Extract core topic
        core = words[0] if len(words) == 1 else " ".join(words[:2])
        
        fallbacks = [
            f"{core} tutorial",
            f"{core} documentation",
            f"how to use {core}",
            f"{core} guide",
            f"{core} basics",
        ]
        
        # Add more specific fallbacks for programming topics
        if any(w in query.lower() for w in ["python", "javascript", "java", "rust", "go"]):
            fallbacks.extend([
                f"{core} official docs",
                f"{core} w3schools",
            ])
        
        return fallbacks[:5]  # Limit to 5 fallback queries

    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        return self.primary.fetch(url, timeout)


class CachedProvider(SearchProvider):
    """Wrapper that adds caching to any search provider with explicit provenance tracking."""

    def __init__(self, primary: SearchProvider, cache=None):
        super().__init__(f"cached_{primary.name}")
        self.primary = primary
        self.cache = cache

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        provider_name = self.primary.name
        cached_results, cache_entry = self.cache.get_search(query, provider_name) if self.cache else (None, None)
        
        if cached_results is not None:
            return cached_results, ProviderDiagnostics(
                code=DiagnosticCode.CACHE_HIT,
                message=f"Cache hit for query: {query[:50]}",
                provider=provider_name,
                details={
                    "cache_key": cache_entry.key if cache_entry else None,
                    "cache_status": "cache_replay_only",
                    "result_origin": "cache",
                },
            )
        
        results, diag = self.primary.search(query, max_results)
        
        if results and self.cache:
            self.cache.put_search(query, provider_name, results, diag.code, diag.message)
        
        if cached_results is None and results:
            diag.details["cache_status"] = "cache_miss"
            diag.details["result_origin"] = "live"
        
        return results, diag

    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        provider_name = self.primary.name
        
        cached_artifact, cache_entry = self.cache.get_fetch(url, provider_name) if self.cache else (None, None)
        if cached_artifact is not None:
            cached_artifact["_cache_hit"] = True
            cached_artifact["result_origin"] = "cache"
            cached_artifact["cache_status"] = "cache_replay_only"
            return cached_artifact
        
        artifact = self.primary.fetch(url, timeout)
        
        if artifact and self.cache:
            self.cache.put_fetch(url, provider_name, artifact, DiagnosticCode.PROVIDER_OK, "fetched live")
            artifact["_cache_hit"] = False
            artifact["result_origin"] = "live"
            artifact["cache_status"] = "live_fetch"
        
        return artifact


class RateLimiter:
    """Rate limiter for search providers to prevent blocking."""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: List[float] = []

    def is_allowed(self) -> bool:
        """Check if a request is allowed under rate limits."""
        now = time.time()
        # Remove requests outside the window
        self.requests = [t for t in self.requests if now - t < self.window_seconds]
        
        if len(self.requests) >= self.max_requests:
            return False
        
        self.requests.append(now)
        return True

    def wait_time(self) -> float:
        """Return seconds to wait before next request is allowed."""
        if not self.requests:
            return 0.0
        now = time.time()
        oldest = min(self.requests)
        return max(0.0, self.window_seconds - (now - oldest))

    def reset(self) -> None:
        """Reset the rate limiter."""
        self.requests = []


class RetryProvider(SearchProvider):
    """Wrapper that adds retry with exponential backoff."""

    def __init__(self, primary: SearchProvider, max_attempts: int = RETRY_MAX_ATTEMPTS):
        super().__init__(f"retry_{primary.name}")
        self.primary = primary
        self.max_attempts = max_attempts

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        last_diag: Optional[ProviderDiagnostics] = None
        
        for attempt in range(self.max_attempts):
            results, diag = self.primary.search(query, max_results)
            last_diag = diag
            
            # Success or non-retryable error
            if results or diag.code not in (
                DiagnosticCode.SEARCH_TIMEOUT,
                DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
            ):
                return results, diag
            
            # Retry with backoff
            if attempt < self.max_attempts - 1:
                delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                time.sleep(delay)
                diag.details["retry_attempt"] = attempt + 1
                diag.details["retry_delay"] = delay

        return [], last_diag if last_diag else ProviderDiagnostics(
            code=DiagnosticCode.PROVIDER_EXHAUSTED,
            message=f"Provider exhausted after {self.max_attempts} attempts",
            provider=self.name,
        )

    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        return self.primary.fetch(url, timeout)


class MultiProvider(SearchProvider):
    """Tries multiple providers in order until one works."""

    def __init__(self, providers: List[SearchProvider]):
        super().__init__("multi")
        self.providers = providers

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        tried_providers: List[str] = []
        provider_failures: Dict[str, str] = {}
        
        for provider in self.providers:
            tried_providers.append(provider.name)
            results, diag = provider.search(query, max_results)
            
            if results:
                diag.details["providers_tried"] = tried_providers
                diag.details["provider_used"] = provider.name
                diag.details["provider_failures"] = provider_failures
                return results, diag
            
            # Record failure
            provider_failures[provider.name] = f"{diag.code}: {diag.message}"
            
            # If this provider is blocked or timed out, try next
            if diag.code in (
                DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                DiagnosticCode.SEARCH_TIMEOUT,
                DiagnosticCode.SEARCH_PARSE_ERROR,
            ):
                continue
        
        return [], ProviderDiagnostics(
            code=DiagnosticCode.PROVIDER_EXHAUSTED,
            message="All providers failed",
            provider=self.name,
            details={
                "providers_tried": tried_providers,
                "provider_used": None,
                "provider_failures": provider_failures,
            },
        )

    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        # Try each provider's fetch
        for provider in self.providers:
            artifact = provider.fetch(url, timeout)
            if artifact:
                return artifact
        return None


def create_provider(session_dir: Path, provider_name: str = "duckduckgo", use_cache: bool = True) -> SearchProvider:
    """Factory function to create search provider with rate limiting and fallback.
    
    Provider order (v3.6):
    1. DuckDuckGo HTML
    2. Brave Search (fallback)
    3. Browser-based fallback (tries multiple engines)
    4. Local knowledge
    
    Cache is essential for replaying previous successful sessions.
    """
    providers: List[SearchProvider] = []
    
    # Primary: DuckDuckGo
    ddg = DuckDuckGoProvider(session_dir)
    ddg_rate_limited = RateLimiterWrapper(ddg)
    providers.append(RetryProvider(ddg_rate_limited))
    
    # Secondary: Brave Search
    brave = BraveSearchProvider(session_dir)
    brave_rate_limited = RateLimiterWrapper(brave)
    providers.append(RetryProvider(brave_rate_limited))
    
    # Add browser-based fallback as last resort
    browser = BrowserSearchProvider(session_dir)
    providers.append(browser)
    
    # Create multi-provider
    multi = MultiProvider(providers)
    
    # Wrap with fallback for query variations
    wrapped = FallbackProvider(multi)
    
    # Wrap with cache
    if use_cache:
        from research.cache import get_cache
        cache = get_cache()
        wrapped = CachedProvider(wrapped, cache)
    
    return wrapped


class RateLimiterWrapper(SearchProvider):
    """Wrapper that enforces rate limiting on a provider."""

    def __init__(self, primary: SearchProvider, max_requests: int = RATE_LIMIT_REQUESTS):
        super().__init__(primary.name)
        self.primary = primary
        self.limiter = RateLimiter(max_requests)

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        if not self.limiter.is_allowed():
            wait = self.limiter.wait_time()
            return [], ProviderDiagnostics(
                code=DiagnosticCode.RATE_LIMITED,
                message=f"Rate limited. Wait {wait:.1f}s before next request.",
                provider=self.name,
                details={"wait_seconds": wait},
            )
        
        return self.primary.search(query, max_results)

    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        return self.primary.fetch(url, timeout)


class BrowserSearchProvider(SearchProvider):
    """Browser-based fallback search - tries multiple engines then local knowledge."""

    def __init__(self, session_dir: Path):
        super().__init__("browser_fallback")
        self.session_dir = session_dir
        self.web_dir = session_dir / "web"
        self.web_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_counter = 0

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        # Try DDG Lite first
        results, diag = self._search_ddg_lite(query, max_results)
        if results:
            return results, diag
        
        # Try Brave
        results, diag = self._search_brave(query, max_results)
        if results:
            return results, diag
        
        # Try local knowledge
        return self._search_local(query, max_results)

    def _search_ddg_lite(self, query: str, max_results: int) -> tuple[List[SearchResult], ProviderDiagnostics]:
        import urllib.parse
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
        import urllib.parse
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
            from research.ingestor import get_ingestor
            ingestor = get_ingestor()
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
        import re
        import html
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
        import re
        import html
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
            
            import re
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
