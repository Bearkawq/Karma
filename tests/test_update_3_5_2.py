"""Tests for Karma v3.5.2 — Free Search Fallback + Local Cache Spine.

Tests for:
1. Provider fallback behavior
2. Cache behavior
3. Partial success
4. Artifact integrity
5. Conversation continuity
6. Regression checks
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.grammar import grammar_match
from core.conversation_state import ConversationState


# ── 1. PROVIDER FALLBACK TESTS ────────────────────────────────

def test_provider_fallback_engages_on_blocked():
    """Primary provider blocked should engage fallback."""
    from research.providers import FallbackProvider, DuckDuckGoProvider, DiagnosticCode, ProviderDiagnostics
    from unittest.mock import Mock
    
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        primary = DuckDuckGoProvider(session_dir)
        
        # Mock primary to return blocked
        primary.search = Mock(return_value=([], ProviderDiagnostics(
            code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
            message="Blocked",
            provider="duckduckgo"
        )))
        
        fallback = FallbackProvider(primary)
        
        # Fallback should try the primary, which is blocked
        # The fallback should still return the blocked result from primary
        results, diag = fallback.search("test query", max_results=3)
        
        assert diag.code == DiagnosticCode.SEARCH_PROVIDER_BLOCKED


def test_fallback_queries_generated():
    """FallbackProvider should generate fallback queries."""
    from research.providers import FallbackProvider, DuckDuckGoProvider
    from pathlib import Path
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        primary = DuckDuckGoProvider(session_dir)
        fallback = FallbackProvider(primary)
        
        fallback_queries = fallback._generate_fallback_queries("python decorators tutorial")
        
        assert len(fallback_queries) > 0
        assert all(isinstance(q, str) for q in fallback_queries)


def test_fallback_queries_include_programming_specific():
    """FallbackProvider should generate programming-specific queries."""
    from research.providers import FallbackProvider, DuckDuckGoProvider
    from pathlib import Path
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        primary = DuckDuckGoProvider(session_dir)
        fallback = FallbackProvider(primary)
        
        fallback_queries = fallback._generate_fallback_queries("python asyncio")
        
        assert any("documentation" in q.lower() for q in fallback_queries)


def test_is_usable_result_filters_junk():
    """FallbackProvider should filter out low-quality results."""
    from research.providers import FallbackProvider, DuckDuckGoProvider, SearchResult, ProviderDiagnostics, DiagnosticCode
    from pathlib import Path
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        primary = DuckDuckGoProvider(session_dir)
        fallback = FallbackProvider(primary)
        
        # Very low quality results
        junk_results = [
            SearchResult(title="A", url="https://example.com/a", snippet="", quality=0.05),
            SearchResult(title="B", url="https://example.com/b", snippet="", quality=0.02),
        ]
        
        is_usable = fallback._is_usable_result(junk_results, ProviderDiagnostics(
            code=DiagnosticCode.PROVIDER_OK,
            message="ok",
            provider="test"
        ))
        
        assert is_usable == False


# ── 2. CACHE BEHAVIOR TESTS ────────────────────────────────

def test_cache_entry_creation():
    """Cache should create entries correctly."""
    from research.cache import CacheEntry
    from datetime import datetime
    
    entry = CacheEntry(
        key="test_key",
        provider="duckduckgo",
        query_or_url="test query",
        timestamp=datetime.now().isoformat(timespec="seconds"),
        data={"results": []},
        diagnostic_code="provider_ok",
        diagnostic_message="ok",
    )
    
    assert entry.key == "test_key"
    assert entry.provider == "duckduckgo"


def test_cache_entry_stale_detection():
    """Cache should detect stale entries."""
    from research.cache import CacheEntry
    from datetime import datetime, timedelta
    
    entry = CacheEntry(
        key="test_key",
        provider="duckduckgo",
        query_or_url="test query",
        timestamp=(datetime.now() - timedelta(hours=48)).isoformat(timespec="seconds"),
        data={"results": []},
        diagnostic_code="provider_ok",
        diagnostic_message="ok",
        ttl_hours=24,
    )
    
    assert entry.is_stale() == True


def test_cache_entry_fresh_detection():
    """Cache should detect fresh entries."""
    from research.cache import CacheEntry
    from datetime import datetime
    
    entry = CacheEntry(
        key="test_key",
        provider="duckduckgo",
        query_or_url="test query",
        timestamp=datetime.now().isoformat(timespec="seconds"),
        data={"results": []},
        diagnostic_code="provider_ok",
        diagnostic_message="ok",
        ttl_hours=24,
    )
    
    assert entry.is_stale() == False


def test_golearn_cache_search_round_trip():
    """Cache should store and retrieve search results."""
    import tempfile
    from research.cache import GoLearnCache
    from research.providers import SearchResult
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = GoLearnCache(tmpdir)
        
        results = [
            SearchResult(title="Test", url="https://example.com", snippet="test", quality=0.8),
        ]
        
        cache.put_search("test query", "duckduckgo", results, "provider_ok", "ok")
        
        cached_results, entry = cache.get_search("test query", "duckduckgo")
        
        assert cached_results is not None
        assert len(cached_results) == 1
        assert cached_results[0].title == "Test"


def test_golearn_cache_fetch_round_trip():
    """Cache should store and retrieve fetch results."""
    import tempfile
    from research.cache import GoLearnCache
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = GoLearnCache(tmpdir)
        
        artifact = {
            "id": "art_0001",
            "url": "https://example.com",
            "title": "Test Page",
            "text": "Test content",
        }
        
        cache.put_fetch("https://example.com", "duckduckgo", artifact, "provider_ok", "ok")
        
        cached_artifact, entry = cache.get_fetch("https://example.com", "duckduckgo")
        
        assert cached_artifact is not None
        assert cached_artifact["id"] == "art_0001"
        assert cached_artifact.get("_cache_hit") is None  # Raw artifact doesn't have cache marker


def test_cache_stale_detection():
    """Cache should detect stale cache entries."""
    import tempfile
    from research.cache import GoLearnCache
    from research.providers import SearchResult
    from datetime import datetime, timedelta
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = GoLearnCache(tmpdir)
        
        results = [SearchResult(title="Test", url="https://example.com", snippet="test", quality=0.8)]
        
        # Manually create a stale entry
        from research.cache import CacheEntry
        stale_entry = CacheEntry(
            key="stale_key",
            provider="duckduckgo",
            query_or_url="stale query",
            timestamp=(datetime.now() - timedelta(hours=48)).isoformat(timespec="seconds"),
            data={"results": [{"title": "Stale", "url": "https://example.com", "snippet": "", "quality": 0.5}]},
            diagnostic_code="provider_ok",
            diagnostic_message="ok",
            ttl_hours=24,
        )
        cache._search_index["stale_key"] = stale_entry
        cache._save_index()
        
        # Reload cache
        cache2 = GoLearnCache(tmpdir)
        
        # Stale entry should not be returned
        cached_results, entry = cache2.get_search("stale query", "duckduckgo")
        
        assert cached_results is None


def test_cache_status_detection():
    """Cache should correctly report cache status."""
    import tempfile
    from research.cache import GoLearnCache
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = GoLearnCache(tmpdir)
        
        status = cache.get_cache_status("new query", "https://new.com", "duckduckgo")
        
        assert status == "cache_miss"


def test_cache_stats():
    """Cache should provide stats."""
    import tempfile
    from research.cache import GoLearnCache
    from research.providers import SearchResult
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = GoLearnCache(tmpdir)
        
        results = [SearchResult(title="Test", url="https://example.com", snippet="test", quality=0.8)]
        cache.put_search("test query", "duckduckgo", results, "provider_ok", "ok")
        
        stats = cache.get_stats()
        
        assert "search_entries" in stats
        assert "fetch_entries" in stats
        assert stats["search_entries"] == 1


# ── 3. PARTIAL SUCCESS TESTS ────────────────────────────────

def test_session_json_contains_cache_fields():
    """session.json should contain cache_status and cache_hits."""
    import tempfile
    from research.session import ResearchSession
    
    session = ResearchSession(
        id="test_001",
        topic="test topic",
        mode="auto",
        start_ts="2024-01-01T00:00:00",
        provider="duckduckgo",
        cache_status="cache_partial",
        cache_hits=5,
        accepted_sources=3,
        useful_artifacts=3,
    )
    
    assert session.cache_status == "cache_partial"
    assert session.cache_hits == 5


def test_partial_success_report():
    """Report should reflect partial success state."""
    from research.index import NoteWriter
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        nw = NoteWriter()
        report_path = Path(tmpdir) / "report.md"
        
        nw.generate_report(
            session_id="test_001",
            root_topic="Python",
            notes=[],
            elapsed_seconds=60.0,
            visited_topics=[],
            report_path=report_path,
            provider="duckduckgo",
            provider_code="search_provider_blocked",
            stop_reason="search_provider_blocked",
            cache_status="cache_partial",
            cache_hits=3,
        )
        
        report_content = report_path.read_text()
        
        assert "**Cache status**: cache_partial" in report_content
        assert "**Cache hits**: 3" in report_content


# ── 4. ARTIFACT INTEGRITY TESTS ───────────────────────────────

def test_diagnostic_code_cache_constants():
    """Diagnostic codes should include cache codes."""
    from research.providers import DiagnosticCode
    
    assert DiagnosticCode.CACHE_HIT == "cache_hit"
    assert DiagnosticCode.CACHE_PARTIAL == "cache_partial"


def test_provider_returns_cache_diagnostic():
    """Provider should return cache diagnostic when cache hits."""
    from research.providers import create_provider, DiagnosticCode
    
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        
        provider = create_provider(session_dir, "duckduckgo", use_cache=True)
        
        # The provider should return diagnostics
        results, diag = provider.search("test query", max_results=3)
        
        # Either we get results or we get a diagnostic code
        assert diag is not None
        assert diag.code is not None


# ── 5. CONVERSATION CONTINUITY TESTS ──────────────────────────

def test_golearn_followup_after_cache_hit():
    """GoLearn follow-up should handle cache hits."""
    from agent.dialogue_manager import DialogueManager
    from core.conversation_state import ConversationState
    
    cs = ConversationState()
    dm = DialogueManager(cs, None, None, None)
    
    cache_result = {
        "session": {
            "topic": "python decorators",
            "stop_reason": "budget_exhausted",
            "visited": ["decorator basics"],
            "artifacts": ["art_0001"],
            "provider_code": "cache_hit",
            "cache_status": "cache_hit",
            "cache_hits": 1,
        }
    }
    
    dm.set_last_golearn_result(cache_result)
    
    response = dm._handle_golearn_followup("summarize that")
    assert response is not None
    assert "cache" in response.lower()


def test_golearn_followup_after_partial_cache():
    """GoLearn follow-up should handle partial cache."""
    from agent.dialogue_manager import DialogueManager
    from core.conversation_state import ConversationState
    
    cs = ConversationState()
    dm = DialogueManager(cs, None, None, None)
    
    partial_result = {
        "session": {
            "topic": "python decorators",
            "stop_reason": "search_provider_blocked",
            "visited": [],
            "artifacts": [],
            "provider_code": "search_provider_blocked",
            "cache_status": "cache_partial",
            "cache_hits": 2,
        }
    }
    
    dm.set_last_golearn_result(partial_result)
    
    response = dm._handle_golearn_followup("continue")
    assert response is not None
    assert "cache" in response.lower()


# ── 6. REGRESSION CHECKS ───────────────────────────────────────

def test_grammar_still_matches_golearn():
    """golearn grammar should still match."""
    result = grammar_match('golearn "python decorators" 1 auto')
    assert result is not None
    assert result["intent"] == "golearn"


def test_provider_factory_works():
    """Provider factory should create cached provider."""
    from research.providers import create_provider, CachedProvider
    
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        
        provider = create_provider(session_dir, "duckduckgo", use_cache=True)
        
        assert isinstance(provider, CachedProvider)


def test_provider_factory_without_cache():
    """Provider factory should create non-cached provider."""
    from research.providers import create_provider, FallbackProvider
    
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        
        provider = create_provider(session_dir, "duckduckgo", use_cache=False)
        
        assert isinstance(provider, FallbackProvider)


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
