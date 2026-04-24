"""Rate limiter for search providers.

Enforces request limits to prevent provider blocking.
"""

from __future__ import annotations

import time
from typing import List


RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW = 60


class RateLimiter:
    """Rate limiter for search providers to prevent blocking."""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: List[float] = []

    def is_allowed(self) -> bool:
        """Check if a request is allowed under rate limits."""
        now = time.time()
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


class RateLimiterWrapper:
    """Wrapper that enforces rate limiting on a provider."""

    def __init__(self, provider, max_requests: int = RATE_LIMIT_REQUESTS):
        from .base import DiagnosticCode, ProviderDiagnostics
        self.provider = provider
        self.primary = provider  # expose for provider-chain traversal
        self.limiter = RateLimiter(max_requests)
        self._DiagnosticCode = DiagnosticCode
        self._ProviderDiagnostics = ProviderDiagnostics

    @property
    def name(self) -> str:
        return f"rate_limited_{self.provider.name}"

    def search(self, query: str, max_results: int = 5):
        if not self.limiter.is_allowed():
            wait = self.limiter.wait_time()
            return [], self._ProviderDiagnostics(
                code=self._DiagnosticCode.RATE_LIMITED,
                message=f"Rate limited. Wait {wait:.1f}s before next request.",
                provider=self.name,
                details={"wait_seconds": wait},
            )

        return self.provider.search(query, max_results)

    def fetch(self, url: str, timeout: float = None):
        return self.provider.fetch(url, timeout)
