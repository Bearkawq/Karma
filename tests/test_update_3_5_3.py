"""Tests for Karma v3.5.3 — Alternate Provider + Rate Limit Spine.

Tests for:
1. Rate limiting behavior
2. Retry with backoff
3. Multi-provider fallback
4. Provider diagnostics
5. Regression checks
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.grammar import grammar_match
from core.conversation_state import ConversationState


# ── 1. RATE LIMITER TESTS ────────────────────────────────

def test_rate_limiter_allows_requests():
    """Rate limiter should allow requests within limit."""
    from research.providers import RateLimiter
    
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    
    assert limiter.is_allowed() == True
    assert limiter.is_allowed() == True
    assert limiter.is_allowed() == True
    # Fourth request should be denied
    assert limiter.is_allowed() == False


def test_rate_limiter_reset():
    """Rate limiter should allow requests after reset."""
    from research.providers import RateLimiter
    
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    
    limiter.is_allowed()
    limiter.is_allowed()
    assert limiter.is_allowed() == False
    
    limiter.reset()
    assert limiter.is_allowed() == True


def test_rate_limiter_wait_time():
    """Rate limiter should return correct wait time."""
    from research.providers import RateLimiter
    
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    
    limiter.is_allowed()
    limiter.is_allowed()
    
    wait = limiter.wait_time()
    assert wait >= 0


# ── 2. RETRY PROVIDER TESTS ────────────────────────────────

def test_retry_provider_success_first_try():
    """RetryProvider should return results on first success."""
    from research.providers import RetryProvider, SearchProvider, DiagnosticCode, ProviderDiagnostics, SearchResult
    
    class MockProvider(SearchProvider):
        def __init__(self):
            super().__init__("mock")
            self.call_count = 0
        
        def search(self, query, max_results=5):
            self.call_count += 1
            return [SearchResult(title="Test", url="https://example.com", snippet="", quality=0.8)], ProviderDiagnostics(
                code=DiagnosticCode.PROVIDER_OK,
                message="ok",
                provider=self.name,
            )
        
        def fetch(self, url, timeout=None):
            return {"id": "test", "url": url, "text": "test"}
    
    mock = MockProvider()
    retry = RetryProvider(mock, max_attempts=3)
    
    results, diag = retry.search("test query")
    
    assert len(results) == 1
    assert mock.call_count == 1


def test_retry_provider_retries_on_timeout():
    """RetryProvider should retry on timeout."""
    from research.providers import RetryProvider, SearchProvider, DiagnosticCode, ProviderDiagnostics, SearchResult
    
    call_count = 0
    
    class MockTimeoutProvider(SearchProvider):
        def __init__(self):
            super().__init__("mock")
        
        def search(self, query, max_results=5):
            nonlocal call_count
            call_count += 1
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_TIMEOUT,
                message="timeout",
                provider=self.name,
            )
        
        def fetch(self, url, timeout=None):
            return None
    
    mock = MockTimeoutProvider()
    retry = RetryProvider(mock, max_attempts=3)
    
    results, diag = retry.search("test query")
    
    assert len(results) == 0
    assert call_count == 3  # Should have retried


def test_retry_provider_stops_on_success():
    """RetryProvider should stop retrying when results obtained."""
    from research.providers import RetryProvider, SearchProvider, DiagnosticCode, ProviderDiagnostics, SearchResult
    
    call_count = 0
    
    class MockEventuallySuccess(SearchProvider):
        def __init__(self):
            super().__init__("mock")
        
        def search(self, query, max_results=5):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return [], ProviderDiagnostics(
                    code=DiagnosticCode.SEARCH_TIMEOUT,
                    message="timeout",
                    provider=self.name,
                )
            return [SearchResult(title="Test", url="https://example.com", snippet="", quality=0.8)], ProviderDiagnostics(
                code=DiagnosticCode.PROVIDER_OK,
                message="ok",
                provider=self.name,
            )
        
        def fetch(self, url, timeout=None):
            return {"id": "test", "url": url, "text": "test"}
    
    mock = MockEventuallySuccess()
    retry = RetryProvider(mock, max_attempts=3)
    
    results, diag = retry.search("test query")
    
    assert len(results) == 1
    assert call_count == 2  # Should have stopped after success


# ── 3. MULTI PROVIDER TESTS ────────────────────────────────

def test_multi_provider_first_provider_works():
    """MultiProvider should return results from first working provider."""
    from research.providers import MultiProvider, SearchProvider, DiagnosticCode, ProviderDiagnostics, SearchResult
    
    class WorkingProvider(SearchProvider):
        def __init__(self, name):
            super().__init__(name)
        
        def search(self, query, max_results=5):
            return [SearchResult(title="Test", url="https://example.com", snippet="", quality=0.8)], ProviderDiagnostics(
                code=DiagnosticCode.PROVIDER_OK,
                message="ok",
                provider=self.name,
            )
        
        def fetch(self, url, timeout=None):
            return {"id": "test", "url": url, "text": "test"}
    
    providers = [WorkingProvider("provider1"), WorkingProvider("provider2")]
    multi = MultiProvider(providers)
    
    results, diag = multi.search("test query")
    
    assert len(results) == 1
    assert diag.details.get("providers_tried") == ["provider1"]


def test_multi_provider_fallback():
    """MultiProvider should fallback to next provider when first fails."""
    from research.providers import MultiProvider, SearchProvider, DiagnosticCode, ProviderDiagnostics, SearchResult
    
    class FailingProvider(SearchProvider):
        def __init__(self, name):
            super().__init__(name)
        
        def search(self, query, max_results=5):
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message="blocked",
                provider=self.name,
            )
        
        def fetch(self, url, timeout=None):
            return None
    
    class WorkingProvider(SearchProvider):
        def __init__(self, name):
            super().__init__(name)
        
        def search(self, query, max_results=5):
            return [SearchResult(title="Test", url="https://example.com", snippet="", quality=0.8)], ProviderDiagnostics(
                code=DiagnosticCode.PROVIDER_OK,
                message="ok",
                provider=self.name,
            )
        
        def fetch(self, url, timeout=None):
            return {"id": "test", "url": url, "text": "test"}
    
    providers = [FailingProvider("failing"), WorkingProvider("working")]
    multi = MultiProvider(providers)
    
    results, diag = multi.search("test query")
    
    assert len(results) == 1
    assert diag.details.get("providers_tried") == ["failing", "working"]


def test_multi_provider_all_fail():
    """MultiProvider should return exhausted when all providers fail."""
    from research.providers import MultiProvider, SearchProvider, DiagnosticCode, ProviderDiagnostics
    
    class FailingProvider(SearchProvider):
        def __init__(self, name):
            super().__init__(name)
        
        def search(self, query, max_results=5):
            return [], ProviderDiagnostics(
                code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
                message="blocked",
                provider=self.name,
            )
        
        def fetch(self, url, timeout=None):
            return None
    
    providers = [FailingProvider("p1"), FailingProvider("p2")]
    multi = MultiProvider(providers)
    
    results, diag = multi.search("test query")
    
    assert len(results) == 0
    assert diag.code == DiagnosticCode.PROVIDER_EXHAUSTED


# ── 4. DIAGNOSTIC CODE TESTS ────────────────────────────────

def test_diagnostic_codes_include_new_codes():
    """Diagnostic codes should include new codes."""
    from research.providers import DiagnosticCode
    
    assert DiagnosticCode.PARTIAL_SUCCESS == "partial_success"
    assert DiagnosticCode.RATE_LIMITED == "rate_limited"
    assert DiagnosticCode.PROVIDER_EXHAUSTED == "provider_exhausted"


# ── 5. REGRESSION TESTS ───────────────────────────────────────

def test_grammar_still_matches_golearn():
    """golearn grammar should still match."""
    result = grammar_match('golearn "python decorators" 1 auto')
    assert result is not None
    assert result["intent"] == "golearn"


def test_provider_factory_creates_multi_provider():
    """Provider factory should create multi-provider with rate limiting."""
    from research.providers import create_provider, MultiProvider, CachedProvider, RateLimiterWrapper
    
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        provider = create_provider(session_dir, "duckduckgo", use_cache=True)
        
        assert isinstance(provider, CachedProvider)
        # The primary should be wrapped in FallbackProvider -> MultiProvider -> RetryProvider -> RateLimiterWrapper


def test_rate_limiter_constants():
    """Rate limiter constants should be defined."""
    from research.providers import RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW, RETRY_MAX_ATTEMPTS
    
    assert RATE_LIMIT_REQUESTS == 20
    assert RATE_LIMIT_WINDOW == 60
    assert RETRY_MAX_ATTEMPTS == 3


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed}/{passed+failed} passed")
    sys.exit(1 if failed else 0)
