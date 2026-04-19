"""Search providers package.

Modular provider architecture for resilient search functionality.
Supports multiple backends with graceful degradation.

Example usage:
    from research.providers import create_provider
    provider = create_provider(session_dir)
    results, diagnostics = provider.search("python tutorial")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import DiagnosticCode, ProviderDiagnostics, SearchProvider, SearchResult
from .duckduckgo_provider import DuckDuckGoProvider
from .brave_provider import BraveSearchProvider
from .bing_provider import BingProvider
from .browser_provider import BrowserSearchProvider
from .cached_provider import CachedProvider
from .retry_provider import FallbackProvider, RetryProvider, RETRY_MAX_ATTEMPTS
from .rate_limiter import RateLimiter, RateLimiterWrapper, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW
from .multi_provider import MultiProvider

# Re-export MAX_PAGES_PER_SLICE from crawler for backwards compatibility
from research.crawler import MAX_PAGES_PER_SLICE


__all__ = [
    "SearchProvider",
    "SearchResult",
    "ProviderDiagnostics",
    "DiagnosticCode",
    "DuckDuckGoProvider",
    "BraveSearchProvider",
    "BingProvider",
    "BrowserSearchProvider",
    "CachedProvider",
    "RetryProvider",
    "FallbackProvider",
    "RateLimiter",
    "RateLimiterWrapper",
    "MultiProvider",
    "RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_WINDOW",
    "RETRY_MAX_ATTEMPTS",
    "create_provider",
    "MAX_PAGES_PER_SLICE",
]


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
    
    ddg = DuckDuckGoProvider(session_dir)
    ddg_rate_limited = RateLimiterWrapper(ddg)
    providers.append(RetryProvider(ddg_rate_limited))
    
    brave = BraveSearchProvider(session_dir)
    brave_rate_limited = RateLimiterWrapper(brave)
    providers.append(RetryProvider(brave_rate_limited))
    
    browser = BrowserSearchProvider(session_dir)
    providers.append(browser)
    
    multi = MultiProvider(providers)
    
    wrapped = FallbackProvider(multi)
    
    if use_cache:
        from research.cache import get_cache
        cache = get_cache()
        wrapped = CachedProvider(wrapped, cache)
    
    return wrapped
