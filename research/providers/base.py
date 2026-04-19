"""Search provider base classes and shared types.

This module defines the abstract base class for all search providers
and the common data structures used across providers.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    """Abstract base class for search providers.
    
    All search providers must implement the search and fetch methods.
    This ensures a consistent interface across different provider implementations.
    """

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
