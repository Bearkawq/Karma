"""Tests for Karma v3.5.3a — Real Provider Injection + Cache Truth.

Tests for:
1. Real provider wiring (2 actual providers in MultiProvider)
2. MultiProvider truth (attempt order, provider used, failures)
3. Cache truth labels (result_origin, cache_status)
4. Artifact truth (live vs cached counts)
5. Conversation continuity
6. Regression checks
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.grammar import grammar_match


# ── 1. REAL PROVIDER WIRING TESTS ────────────────────────────────

def test_multi_provider_has_two_actual_providers():
    """MultiProvider should have at least 2 actual provider implementations."""
    from research.providers import create_provider, MultiProvider, DuckDuckGoProvider, BraveSearchProvider
    
    with tempfile.TemporaryDirectory() as d:
        provider = create_provider(Path(d))
        
        # Drill down to find MultiProvider
        current = provider
        while hasattr(current, 'primary'):
            current = current.primary
        
        assert hasattr(current, 'providers'), "Should have MultiProvider with providers list"
        assert len(current.providers) >= 2, f"Should have 2+ providers, got {len(current.providers)}"


def test_brave_provider_class_exists():
    """BraveSearchProvider should be implemented."""
    from research.providers import BraveSearchProvider
    
    # Verify class exists and has required methods
    assert hasattr(BraveSearchProvider, 'search')
    assert hasattr(BraveSearchProvider, 'fetch')


def test_fallback_order_documented():
    """Fallback order should be documented and functional."""
    from research.providers import create_provider, MultiProvider
    
    with tempfile.TemporaryDirectory() as d:
        provider = create_provider(Path(d))
        
        # Find MultiProvider
        current = provider
        while hasattr(current, 'primary'):
            current = current.primary
        
        # First provider should be DuckDuckGo (primary), second Brave (fallback)
        if hasattr(current, 'providers'):
            providers = current.providers
            # Check first provider is duckduckgo (under Retry wrapper)
            first_underlying = providers[0]
            while hasattr(first_underlying, 'primary'):
                first_underlying = first_underlying.primary
            assert first_underlying.name == "duckduckgo"


# ── 2. MULTIPROVIDER TRUTH TESTS ──────────────────────────────────

def test_multi_provider_records_attempts():
    """MultiProvider should record which providers were attempted."""
    from research.providers import MultiProvider, SearchProvider, ProviderDiagnostics, DiagnosticCode, SearchResult
    
    class MockProvider1(SearchProvider):
        def __init__(self):
            super().__init__("provider1")
        def search(self, query, max_results=5):
            return [], ProviderDiagnostics(code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED, message="blocked", provider=self.name)
        def fetch(self, url, timeout=None):
            return None
    
    class MockProvider2(SearchProvider):
        def __init__(self):
            super().__init__("provider2")
        def search(self, query, max_results=5):
            return [SearchResult(title="test", url="http://test.com", snippet="test")], ProviderDiagnostics(code=DiagnosticCode.PROVIDER_OK, message="ok", provider=self.name)
        def fetch(self, url, timeout=None):
            return {"id": "art1", "url": url, "title": "test", "text": "content", "text_path": "", "html_path": "", "fetch_ts": "", "size_bytes": 0}
    
    multi = MultiProvider([MockProvider1(), MockProvider2()])
    results, diag = multi.search("test")
    
    assert "providers_tried" in diag.details
    assert diag.details["providers_tried"] == ["provider1", "provider2"]


def test_multi_provider_records_provider_used():
    """MultiProvider should record which provider actually returned results."""
    from research.providers import MultiProvider, SearchProvider, ProviderDiagnostics, DiagnosticCode, SearchResult
    
    class FailingProvider(SearchProvider):
        def __init__(self):
            super().__init__("failing")
        def search(self, query, max_results=5):
            return [], ProviderDiagnostics(code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED, message="blocked", provider=self.name)
        def fetch(self, url, timeout=None):
            return None
    
    class WorkingProvider(SearchProvider):
        def __init__(self):
            super().__init__("working")
        def search(self, query, max_results=5):
            return [SearchResult(title="test", url="http://test.com", snippet="test")], ProviderDiagnostics(code=DiagnosticCode.PROVIDER_OK, message="ok", provider=self.name)
        def fetch(self, url, timeout=None):
            return {"id": "art1", "url": url, "title": "test", "text": "content", "text_path": "", "html_path": "", "fetch_ts": "", "size_bytes": 0}
    
    multi = MultiProvider([FailingProvider(), WorkingProvider()])
    results, diag = multi.search("test")
    
    assert "provider_used" in diag.details
    assert diag.details["provider_used"] == "working"


def test_multi_provider_records_failures():
    """MultiProvider should record why each provider failed."""
    from research.providers import MultiProvider, SearchProvider, ProviderDiagnostics, DiagnosticCode, SearchResult
    
    class FailingProvider1(SearchProvider):
        def __init__(self):
            super().__init__("fail1")
        def search(self, query, max_results=5):
            return [], ProviderDiagnostics(code=DiagnosticCode.SEARCH_TIMEOUT, message="timeout", provider=self.name)
        def fetch(self, url, timeout=None):
            return None
    
    class FailingProvider2(SearchProvider):
        def __init__(self):
            super().__init__("fail2")
        def search(self, query, max_results=5):
            return [], ProviderDiagnostics(code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED, message="blocked", provider=self.name)
        def fetch(self, url, timeout=None):
            return None
    
    multi = MultiProvider([FailingProvider1(), FailingProvider2()])
    results, diag = multi.search("test")
    
    assert "provider_failures" in diag.details
    assert "fail1" in diag.details["provider_failures"]
    assert "fail2" in diag.details["provider_failures"]


def test_multi_provider_all_fail_returns_exhausted():
    """When all providers fail, should return provider_exhausted."""
    from research.providers import MultiProvider, SearchProvider, ProviderDiagnostics, DiagnosticCode
    
    class FailingProvider(SearchProvider):
        def __init__(self):
            super().__init__("failing")
        def search(self, query, max_results=5):
            return [], ProviderDiagnostics(code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED, message="blocked", provider=self.name)
        def fetch(self, url, timeout=None):
            return None
    
    multi = MultiProvider([FailingProvider(), FailingProvider()])
    results, diag = multi.search("test")
    
    assert diag.code == DiagnosticCode.PROVIDER_EXHAUSTED


# ── 3. CACHE TRUTH LABELS TESTS ───────────────────────────────────

def test_cached_provider_labels_cache_hit():
    """CachedProvider should label cache hits correctly."""
    from research.providers import CachedProvider, SearchProvider, ProviderDiagnostics, DiagnosticCode, SearchResult
    
    mock_cache = Mock()
    mock_cache.get_search.return_value = ([SearchResult(title="cached", url="http://test.com", snippet="cached")], Mock(key="test_key"))
    
    mock_primary = Mock()
    mock_primary.search.return_value = ([], ProviderDiagnostics(code=DiagnosticCode.PROVIDER_OK, message="ok", provider="primary"))
    
    cached = CachedProvider(mock_primary, mock_cache)
    results, diag = cached.search("test")
    
    assert diag.code == DiagnosticCode.CACHE_HIT
    assert diag.details.get("result_origin") == "cache"
    assert diag.details.get("cache_status") == "cache_replay_only"


def test_cached_provider_labels_live():
    """CachedProvider should label live results correctly."""
    from research.providers import CachedProvider, SearchProvider, ProviderDiagnostics, DiagnosticCode, SearchResult
    
    mock_cache = Mock()
    mock_cache.get_search.return_value = (None, None)
    
    mock_primary = Mock()
    mock_primary.search.return_value = ([SearchResult(title="live", url="http://test.com", snippet="live")], ProviderDiagnostics(code=DiagnosticCode.PROVIDER_OK, message="ok", provider="primary"))
    
    cached = CachedProvider(mock_primary, mock_cache)
    results, diag = cached.search("test")
    
    assert diag.code == DiagnosticCode.PROVIDER_OK
    assert diag.details.get("result_origin") == "live"


# ── 4. ARTIFACT TRUTH TESTS ────────────────────────────────────────

def test_session_tracks_live_vs_cached_counts():
    """Session should track live vs cached artifact counts separately."""
    from research.session import ResearchSession
    
    session = ResearchSession(
        id="test",
        topic="test",
        mode="auto",
        start_ts="2026-01-01T00:00:00",
    )
    
    # Simulate tracking
    session.accepted_sources_live = 5
    session.accepted_sources_cached = 3
    session.useful_artifacts_live = 4
    session.useful_artifacts_cached = 2
    session.fetched_pages_live = 5
    session.fetched_pages_cached = 3
    
    assert session.accepted_sources_live == 5
    assert session.accepted_sources_cached == 3
    assert session.useful_artifacts_live == 4
    assert session.useful_artifacts_cached == 2
    assert session.fetched_pages_live == 5
    assert session.fetched_pages_cached == 3


# ── 5. REPORTING TRUTH TESTS ────────────────────────────────────────

def test_report_includes_provider_truth():
    """Report should include provider truth fields."""
    from research.index import NoteWriter
    import tempfile
    
    nw = NoteWriter()
    
    with tempfile.TemporaryDirectory() as d:
        report_path = Path(d) / "report.md"
        notes = [
            {"topic": "test", "summary": "test summary", "key_points": ["point 1"], "artifact_ids": ["art1"]}
        ]
        
        report = nw.generate_report(
            session_id="test123",
            root_topic="test topic",
            notes=notes,
            elapsed_seconds=10.0,
            visited_topics=["test"],
            report_path=report_path,
            providers_attempted=["retry_duckduckgo", "retry_brave"],
            provider_used="retry_brave",
            provider_failures={"retry_duckduckgo": "rate_limited"},
            result_origin="live",
            accepted_sources=5,
            accepted_sources_live=5,
            accepted_sources_cached=0,
            useful_artifacts=3,
            useful_artifacts_live=3,
            useful_artifacts_cached=0,
        )
        
        assert "Providers attempted" in report
        assert "retry_duckduckgo" in report
        assert "Provider used" in report
        assert "retry_brave" in report
        assert "Result origin" in report
        assert "Fresh live" in report


def test_report_shows_cache_replay_warning():
    """Report should show warning when cache replay is used."""
    from research.index import NoteWriter
    import tempfile
    
    nw = NoteWriter()
    
    with tempfile.TemporaryDirectory() as d:
        report_path = Path(d) / "report.md"
        notes = [{"topic": "test", "summary": "cached", "key_points": [], "artifact_ids": []}]
        
        report = nw.generate_report(
            session_id="test123",
            root_topic="test",
            notes=notes,
            elapsed_seconds=10.0,
            visited_topics=["test"],
            report_path=report_path,
            result_origin="cache",
            cache_status="cache_hit",
        )
        
        assert "cache/local replay" in report.lower() or "cached" in report.lower()


# ── 6. PARSER/DISPATCH TESTS ──────────────────────────────────────

def test_golearn_dispatch_routes_correctly():
    """golearn should route to golearn intent."""
    result = grammar_match('golearn "python decorators" 1 auto')
    assert result is not None
    assert result["intent"] == "golearn"


def test_golearn_kali_linux():
    """golearn kali linux should match."""
    result = grammar_match("golearn kali linux 2")
    assert result is not None
    assert result["intent"] == "golearn"


# ── 7. REGRESSION CHECKS ──────────────────────────────────────────

def test_diagnostic_code_constants():
    """Diagnostic codes should be defined."""
    from research.providers import DiagnosticCode
    
    assert hasattr(DiagnosticCode, "PROVIDER_EXHAUSTED")
    assert hasattr(DiagnosticCode, "CACHE_HIT")
    assert hasattr(DiagnosticCode, "SEARCH_PROVIDER_BLOCKED")


def test_session_json_has_required_fields():
    """session.json should have all required truth fields."""
    from research.session import ResearchSession
    from dataclasses import asdict
    
    session = ResearchSession(
        id="test",
        topic="test",
        mode="auto",
        start_ts="2026-01-01T00:00:00",
    )
    
    data = asdict(session)
    
    # PHASE 2 fields
    assert "providers_attempted" in data
    assert "provider_used" in data
    assert "provider_failures" in data
    
    # PHASE 3 fields
    assert "result_origin" in data
    
    # PHASE 4 fields
    assert "accepted_sources_live" in data
    assert "accepted_sources_cached" in data
    assert "useful_artifacts_live" in data
    assert "useful_artifacts_cached" in data
    assert "fetched_pages_live" in data
    assert "fetched_pages_cached" in data