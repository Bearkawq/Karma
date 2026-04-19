"""Multi-provider orchestration.

Tries multiple providers in order until one works.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import DiagnosticCode, ProviderDiagnostics, SearchProvider, SearchResult


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
            
            provider_failures[provider.name] = f"{diag.code}: {diag.message}"
            
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
        for provider in self.providers:
            artifact = provider.fetch(url, timeout)
            if artifact:
                return artifact
        return None
