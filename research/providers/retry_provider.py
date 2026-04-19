"""Retry provider with exponential backoff.

Wraps a provider to automatically retry failed requests.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .base import DiagnosticCode, ProviderDiagnostics, SearchProvider, SearchResult


RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 10.0
RETRY_MAX_ATTEMPTS = 3


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
            
            if results or diag.code not in (
                DiagnosticCode.SEARCH_TIMEOUT,
                DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
            ):
                return results, diag
            
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


class FallbackProvider(SearchProvider):
    """Fallback provider that tries alternative queries when primary fails."""

    def __init__(self, primary: SearchProvider):
        super().__init__("fallback")
        self.primary = primary

    def search(self, query: str, max_results: int = 5) -> tuple[List[SearchResult], ProviderDiagnostics]:
        results, diag = self.primary.search(query, max_results)
        
        if results and self._is_usable_result(results, diag):
            return results, diag
        
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
        quality_scores = [r.quality for r in results]
        if sum(quality_scores) / len(quality_scores) < 0.1:
            return False
        return True

    def _generate_fallback_queries(self, query: str) -> List[str]:
        """Generate alternative queries when primary fails."""
        words = query.lower().split()
        if len(words) <= 1:
            return []
        
        core = words[0] if len(words) == 1 else " ".join(words[:2])
        
        fallbacks = [
            f"{core} tutorial",
            f"{core} documentation",
            f"how to use {core}",
            f"{core} guide",
            f"{core} basics",
        ]
        
        if any(w in query.lower() for w in ["python", "javascript", "java", "rust", "go"]):
            fallbacks.extend([
                f"{core} official docs",
                f"{core} w3schools",
            ])
        
        return fallbacks[:5]

    def fetch(self, url: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        return self.primary.fetch(url, timeout)
