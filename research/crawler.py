"""WebFetcher — search the web, fetch pages, extract text, store artifacts.

Uses only stdlib (urllib.request). DuckDuckGo HTML endpoint for search.
"""

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_PAGE_SIZE = 500 * 1024  # 500 KB per page
FETCH_TIMEOUT = 15  # seconds per request
MAX_PAGES_PER_SLICE = 3
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Domain quality tiers for source prioritization
_HIGH_QUALITY_DOMAINS = frozenset({
    "docs.python.org", "developer.mozilla.org", "learn.microsoft.com",
    "doc.rust-lang.org", "golang.org", "go.dev", "cppreference.com",
    "man7.org", "kernel.org", "wiki.archlinux.org", "wiki.gentoo.org",
    "en.wikipedia.org", "en.cppreference.com", "peps.python.org",
    "datatracker.ietf.org", "rfc-editor.org", "w3.org",
})
_HIGH_QUALITY_PATTERNS = re.compile(
    r"(?:\.gov/|/docs/|/documentation/|/reference/|/api/|/manual/|"
    r"readthedocs\.io|github\.com/[^/]+/[^/]+(?:$|/(?:blob|tree|wiki))|"
    r"gitlab\.com/[^/]+/[^/]+|pypi\.org/project/|crates\.io/crates/|"
    r"npmjs\.com/package/|stackoverflow\.com/questions/)"
)
_LOW_QUALITY_PATTERNS = re.compile(
    r"(?:medium\.com|dev\.to|geeksforgeeks\.org|w3schools\.com|"
    r"tutorialspoint\.com|javatpoint\.com|guru99\.com|"
    r"simplilearn\.com|educba\.com|coursera\.org|udemy\.com)"
)


class WebFetcher:
    """Search the web, fetch pages, extract readable text, store artifacts."""

    # Provider diagnostics - distinguish different failure modes
    PROVIDER_DIAGNOSTICS = {
        "search_timeout": "Search request timed out",
        "search_blocked": "Search provider blocked the request (likely bot detection)",
        "parse_error": "Search results could not be parsed (provider may have changed format)",
        "empty_content": "Search returned empty or near-empty results",
        "no_results": "No results found for query",
        "fetch_timeout": "Page fetch timed out",
        "fetch_blocked": "Page fetch was blocked (403/444 or bot detection)",
        "fetch_error": "Page could not be fetched",
    }

    def __init__(self, session_dir: Path, bus=None):
        self.session_dir = session_dir
        self.web_dir = session_dir / "web"
        self.web_dir.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self._artifact_counter = 0
        self.last_search_diagnostic: Optional[str] = None  # Detailed diagnostic
        self.last_fetch_diagnostic: Optional[str] = None

    # ── search ────────────────────────────────────────────────

    def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Search DuckDuckGo HTML and return [{title, url, snippet, quality}].

        Tracks failure reason on self.last_search_failure (None on success).
        Detailed diagnostic available in self.last_search_diagnostic.
        Results are sorted by domain quality score before return.
        """
        self.last_search_failure: Optional[str] = None
        self.last_search_diagnostic: Optional[str] = None
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                raw = resp.read(MAX_PAGE_SIZE).decode("utf-8", errors="replace")
        except urllib.error.URLError:
            self.last_search_failure = "timeout"
            self.last_search_diagnostic = self.PROVIDER_DIAGNOSTICS["search_timeout"]
            return []
        except Exception:
            self.last_search_failure = "blocked"
            self.last_search_diagnostic = self.PROVIDER_DIAGNOSTICS["search_blocked"]
            return []

        # Detect provider blocks/bot detection pages
        if self._is_provider_blocked(raw):
            self.last_search_failure = "blocked"
            self.last_search_diagnostic = self.PROVIDER_DIAGNOSTICS["search_blocked"]
            return []

        results = self._parse_ddg_results(raw, max_results + 3)  # fetch extra for quality sort
        if not results:
            # Distinguish empty content from parse failure
            if len(raw) < 500:
                self.last_search_failure = "empty_content"
                self.last_search_diagnostic = self.PROVIDER_DIAGNOSTICS["empty_content"]
            else:
                self.last_search_failure = "parse_error"
                self.last_search_diagnostic = self.PROVIDER_DIAGNOSTICS["parse_error"]
            return []

        # Score and sort by source quality, then trim
        for r in results:
            r["quality"] = self._score_domain(r["url"])
        results.sort(key=lambda r: r["quality"], reverse=True)
        return results[:max_results]

    def _is_provider_blocked(self, raw_html: str) -> bool:
        """Detect if the search provider blocked us or showed a bot detection page."""
        # Check for common bot detection / block signals
        block_signals = [
            "captcha", "robot", "bot detection", "blocked",
            "access denied", "forbidden", "too many requests",
            "DDG does not share", "not a robot", "human verification",
        ]
        html_lower = raw_html.lower()
        # Check title or substantial content for block signals
        if any(signal in html_lower for signal in block_signals):
            # Verify it's actually a block page, not just mentioning robots
            if "duckduckgo" in html_lower and ("captcha" in html_lower or "blocked" in html_lower):
                return True
            if len(raw_html) < 10000 and any(s in html_lower for s in ["access denied", "forbidden", "too many requests"]):
                return True
        # Check for redirect to verification page
        if "/?e=" in raw_html or "uddg=" in raw_html:
            # This is a redirect, not actual results
            if "result" not in html_lower and "link" not in html_lower:
                return True
        return False

    def _parse_ddg_results(self, html_text: str, max_results: int) -> List[Dict[str, str]]:
        # Try multiple patterns for robustness against DDG layout changes
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
        results: List[Dict[str, str]] = []
        for i, (raw_url, raw_title) in enumerate(links[:max_results + 5]):
            try:
                actual_url = self._extract_ddg_url(raw_url)
                if not actual_url:
                    continue
                # Skip DDG ad redirects
                if "duckduckgo.com/y.js" in actual_url or "duckduckgo.com/l/" not in raw_url and not actual_url.startswith("http"):
                    continue
                title = self._strip_html(raw_title).strip()
                snippet = self._strip_html(snippets[i]).strip() if i < len(snippets) else ""
                results.append({"title": title, "url": actual_url, "snippet": snippet})
                if len(results) >= max_results:
                    break
            except Exception:
                continue
        return results

    def _extract_ddg_url(self, raw_url: str) -> Optional[str]:
        # Decode HTML entities (DDG uses &amp; in href attributes)
        raw_url = html.unescape(raw_url)
        # Add scheme if missing (DDG uses //duckduckgo.com/...)
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
        """Score a URL by domain quality. Higher = better source."""
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            return 0.5
        # Strip www.
        if host.startswith("www."):
            host = host[4:]
        if host in _HIGH_QUALITY_DOMAINS:
            return 1.0
        if _HIGH_QUALITY_PATTERNS.search(url):
            return 0.8
        if _LOW_QUALITY_PATTERNS.search(url):
            return 0.2
        return 0.5

    # ── fetch ─────────────────────────────────────────────────

    def fetch_page(self, url: str, timeout: float = None) -> Optional[Dict[str, Any]]:
        """Fetch a single page. Returns artifact dict or None on failure."""
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
        meta_path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")

        if self.bus:
            self.bus.emit("source_fetched", artifact_id=art_id, url=url,
                          title=title, size=len(raw_bytes))
        return artifact

    # ── text extraction ───────────────────────────────────────

    def _extract_title(self, html_text: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.DOTALL | re.IGNORECASE)
        return self._strip_html(m.group(1)).strip() if m else "Untitled"

    def _html_to_text(self, html_text: str) -> str:
        # Remove non-content elements
        text = re.sub(r"<(script|style|nav|header|footer|aside|noscript)[^>]*>.*?</\1>",
                       "", html_text, flags=re.DOTALL | re.IGNORECASE)
        # Remove common nav/menu patterns
        text = re.sub(r"<[^>]+(class|id)=\"[^\"]*(?:nav|menu|sidebar|footer|header|breadcrumb|cookie)[^\"]*\"[^>]*>.*?</(?:div|ul|section|aside)>",
                       "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _strip_html(self, text: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", text))
