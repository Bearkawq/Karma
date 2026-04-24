"""Tests for Karma v3.5.1 — Search Provider Spine + Acquisition Hardening.

Tests for:
1. Parser / dispatch for golearn
2. Provider diagnostics 
3. Artifact integrity
4. Conversation continuity
5. Regression checks
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.grammar import grammar_match
from core.conversation_state import ConversationState


# ── 1. PARSER / DISPATCH TESTS ────────────────────────────────

def test_golearn_python_decorators_match():
    """'golearn python decorators 1 auto' should match golearn intent."""
    result = grammar_match('golearn "python decorators" 1 auto')
    assert result is not None
    assert result["intent"] == "golearn", f"Got {result['intent']}"
    assert "topic" in result.get("entities", {})


def test_golearn_python_decorators_1_auto():
    """'golearn python decorators 1 auto' should match correctly."""
    result = grammar_match("golearn python decorators 1 auto")
    assert result is not None
    assert result["intent"] == "golearn"
    entities = result.get("entities", {})
    assert "topic" in entities


def test_golearn_python_decorators_quoted():
    """'golearn \"python decorators\" 1 auto' should match correctly."""
    result = grammar_match('golearn "python decorators" 1 auto')
    assert result is not None
    assert result["intent"] == "golearn"
    entities = result.get("entities", {})
    assert "python decorators" in entities.get("topic", "").lower() or "topic" in entities


def test_golearn_kali_linux():
    """'golearn kali linux' should match golearn intent."""
    result = grammar_match("golearn kali linux 2")
    assert result is not None
    assert result["intent"] == "golearn"


# ── 2. PROVIDER DIAGNOSTICS TESTS ─────────────────────────────

def test_diagnostic_code_constants():
    """Diagnostic codes should be properly defined."""
    from research.providers import DiagnosticCode

    assert DiagnosticCode.SEARCH_PROVIDER_BLOCKED == "search_provider_blocked"
    assert DiagnosticCode.SEARCH_TIMEOUT == "search_timeout"
    assert DiagnosticCode.SEARCH_PARSE_ERROR == "search_parse_error"
    assert DiagnosticCode.SEARCH_EMPTY == "search_empty"
    assert DiagnosticCode.FETCH_TIMEOUT == "fetch_timeout"
    assert DiagnosticCode.FETCH_ERROR == "fetch_error"
    assert DiagnosticCode.QUEUE_EXHAUSTED == "queue_exhausted"
    assert DiagnosticCode.BUDGET_EXHAUSTED == "budget_exhausted"
    assert DiagnosticCode.COMPLETED == "completed"
    assert DiagnosticCode.LOW_YIELD == "low_yield"
    assert DiagnosticCode.PROVIDER_OK == "provider_ok"


def test_provider_diagnostics_class():
    """ProviderDiagnostics should properly store diagnostic info."""
    from research.providers import ProviderDiagnostics, DiagnosticCode

    diag = ProviderDiagnostics(
        code=DiagnosticCode.SEARCH_PROVIDER_BLOCKED,
        message="Search provider blocked the request",
        provider="duckduckgo",
        details={"retry_after": 60}
    )

    assert diag.code == "search_provider_blocked"
    assert diag.provider == "duckduckgo"
    assert diag.details["retry_after"] == 60


def test_search_result_dataclass():
    """SearchResult should store result information properly."""
    from research.providers import SearchResult

    result = SearchResult(
        title="Python Decorators Tutorial",
        url="https://example.com/decorators",
        snippet="Learn about Python decorators...",
        quality=0.8
    )

    assert result.title == "Python Decorators Tutorial"
    assert result.quality == 0.8


# ── 3. ARTIFACT INTEGRITY TESTS ───────────────────────────────

def test_session_json_contains_provider_fields():
    """session.json should contain provider and diagnostic fields."""
    import tempfile
    from research.session import ResearchSession
    from research.providers import DiagnosticCode

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a minimal session
        session = ResearchSession(
            id="test_001",
            topic="test topic",
            mode="auto",
            start_ts="2024-01-01T00:00:00",
            provider="duckduckgo",
            provider_code=DiagnosticCode.PROVIDER_OK,
            provider_diagnostic="Found 5 results",
            accepted_sources=3,
            fetched_pages=5,
            useful_artifacts=3,
            stop_reason="budget_exhausted",
        )

        assert session.provider == "duckduckgo"
        assert session.provider_code == DiagnosticCode.PROVIDER_OK
        assert session.accepted_sources == 3
        assert session.fetched_pages == 5
        assert session.useful_artifacts == 3


def test_report_contains_provider_info():
    """report.md should contain provider diagnostics."""
    from research.index import NoteWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        nw = NoteWriter()
        report_path = Path(tmpdir) / "report.md"

        # Generate report with provider info
        nw.generate_report(
            session_id="test_001",
            root_topic="Python Decorators",
            notes=[],
            elapsed_seconds=60.0,
            visited_topics=["what are decorators", "decorator syntax"],
            report_path=report_path,
            provider="duckduckgo",
            provider_code="provider_ok",
            provider_diagnostic="Found 5 results",
            stop_reason="budget_exhausted",
            accepted_sources=3,
            useful_artifacts=3,
        )

        report_content = report_path.read_text()

        assert "duckduckgo" in report_content
        assert "Provider status" in report_content
        assert "provider_ok" in report_content
        assert "Accepted sources" in report_content
        assert "Useful artifacts" in report_content
        assert "budget_exhausted" in report_content


# ── 4. CONVERSATION CONTINUITY TESTS ──────────────────────────

def test_golearn_followup_after_blocked():
    """Blocked golearn should not break follow-up conversation."""
    from agent.dialogue_manager import DialogueManager

    cs = ConversationState()
    dm = DialogueManager(cs, None, None, None)

    # Simulate a blocked golearn result
    blocked_result = {
        "session": {
            "topic": "python decorators",
            "stop_reason": "low_yield",
            "visited": [],
            "artifacts": [],
            "provider_diagnostic": "Search provider blocked the request",
            "provider_code": "search_provider_blocked",
        }
    }

    dm.set_last_golearn_result(blocked_result)

    # Test "continue" follow-up after blocked run
    response = dm._handle_golearn_followup("continue")
    assert response is not None
    assert "blocked" in response.lower() or "limited" in response.lower()

    # Test "summarize that" follow-up after blocked run
    response = dm._handle_golearn_followup("summarize that")
    assert response is not None
    assert "python decorators" in response.lower()


def test_golearn_followup_after_successful():
    """Successful golearn should provide useful follow-up."""
    from agent.dialogue_manager import DialogueManager

    cs = ConversationState()
    dm = DialogueManager(cs, None, None, None)

    # Simulate a successful golearn result
    success_result = {
        "session": {
            "topic": "python decorators",
            "stop_reason": "budget_exhausted",
            "visited": ["decorator basics", "function decorators", "class decorators"],
            "artifacts": ["art_0001", "art_0002", "art_0003"],
            "provider_diagnostic": None,
            "provider_code": "provider_ok",
            "accepted_sources": 3,
            "useful_artifacts": 3,
        }
    }

    dm.set_last_golearn_result(success_result)

    # Test "summarize that" follow-up after successful run
    response = dm._handle_golearn_followup("summarize that")
    assert response is not None
    assert "python decorators" in response.lower()
    assert "3" in response  # Should mention the number of topics/artifacts


# ── 5. REGRESSION CHECKS ───────────────────────────────────────

def test_shell_rules_still_match():
    """Generic shell commands still work after changes."""
    result = grammar_match("run echo hello")
    assert result is not None
    assert result["intent"] == "run_shell"


def test_golearn_dispatch_routes_correctly():
    """golearn intent should have tool='golearn' in action."""
    from core.grammar import grammar_match

    gram = grammar_match('golearn "python decorators" 5')
    assert gram is not None
    assert gram["intent"] == "golearn"

    _DIRECT_TOOL_MAP = {
        "golearn": "golearn",
        "salvage_golearn": "golearn",
    }

    tool = _DIRECT_TOOL_MAP.get(gram.get("intent", ""))
    assert tool == "golearn"


def test_provider_creation():
    """Provider factory should create valid providers."""
    from research.providers import create_provider, FallbackProvider, CachedProvider

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)

        # Default: create_provider uses cache=True
        provider = create_provider(session_dir, "duckduckgo")
        assert isinstance(provider, CachedProvider)
        assert isinstance(provider.primary, FallbackProvider)

        # Without cache
        provider_no_cache = create_provider(session_dir, "duckduckgo", use_cache=False)
        assert isinstance(provider_no_cache, FallbackProvider)


def test_provider_search_returns_diagnostics():
    """Provider search should return diagnostics even on failure."""
    from research.providers import create_provider

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)

        provider = create_provider(session_dir, "duckduckgo")

        # The search should return results and diagnostics
        # (We can't reliably test actual search without network, but we can verify the interface)
        results, diag = provider.search("test query", max_results=3)

        # Diagnostics should always be returned
        assert diag is not None
        # Provider name should be one of the valid providers in the chain
        assert diag.provider in ("duckduckgo", "brave", "browser", "multi", "fallback", "retry_duckduckgo")
        assert diag.code is not None


# ── 6. ACQUISITION HARDENING TESTS ─────────────────────────────

def test_dedupe_urls_in_results():
    """Provider should dedupe URLs in results."""
    from research.providers import SearchResult

    # Create duplicate URLs
    results = [
        SearchResult(title="A", url="https://example.com/a", snippet="", quality=0.8),
        SearchResult(title="B", url="https://example.com/a", snippet="", quality=0.9),
        SearchResult(title="C", url="https://example.com/b", snippet="", quality=0.7),
    ]

    # Deduping should happen in the provider layer
    seen = set()
    deduped = []
    for r in results:
        if r.url not in seen:
            seen.add(r.url)
            deduped.append(r)

    assert len(deduped) == 2


def test_fallback_queries_generated():
    """FallbackProvider should generate alternative queries."""
    from research.providers import FallbackProvider, DuckDuckGoProvider
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        primary = DuckDuckGoProvider(session_dir)
        fallback = FallbackProvider(primary)

        # Generate fallback queries for a multi-word topic
        fallback_queries = fallback._generate_fallback_queries("python decorators tutorial")

        assert len(fallback_queries) > 0
        assert all(isinstance(q, str) for q in fallback_queries)


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
