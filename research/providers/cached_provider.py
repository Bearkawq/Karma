"""Cached provider wrapper.

Adds caching to any search provider with explicit provenance tracking.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import DiagnosticCode, ProviderDiagnostics, SearchProvider, SearchResult


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
