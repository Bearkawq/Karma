"""Tests for Karma Truth Layer (v3.5.7a)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_result_state_completed():
    """Test completed state when run finishes normally with useful results."""
    from research.truth_layer import determine_result_state, ResultState

    state, summary = determine_result_state(
        stop_reason="budget_exhausted",
        provider_code="provider_ok",
        accepted_sources_live=10,
        accepted_sources_cached=0,
        accepted_sources_local=0,
        useful_artifacts=10,
    )

    assert state == ResultState.COMPLETED
    assert "live search" in summary.lower()


def test_result_state_blocked():
    """Test blocked state when live search is blocked."""
    from research.truth_layer import determine_result_state, ResultState

    state, summary = determine_result_state(
        stop_reason="low_yield",
        provider_code="provider_exhausted",
        accepted_sources_live=0,
        accepted_sources_cached=5,
        accepted_sources_local=0,
        useful_artifacts=0,
    )

    assert state == ResultState.BLOCKED
    assert "blocked" in summary.lower() or "unavailable" in summary.lower()


def test_result_state_cache_only():
    """Test cache_only state when only cache is used."""
    from research.truth_layer import determine_result_state, ResultState

    state, summary = determine_result_state(
        stop_reason="budget_exhausted",
        provider_code="provider_exhausted",
        accepted_sources_live=0,
        accepted_sources_cached=8,
        accepted_sources_local=0,
        useful_artifacts=8,
    )

    assert state == ResultState.CACHE_ONLY
    assert "cache" in summary.lower()


def test_result_state_partial():
    """Test partial state when run stops early."""
    from research.truth_layer import determine_result_state, ResultState

    state, summary = determine_result_state(
        stop_reason="low_yield",
        provider_code="low_yield",
        accepted_sources_live=3,
        accepted_sources_cached=0,
        accepted_sources_local=0,
        useful_artifacts=3,
    )

    assert state == ResultState.PARTIAL
    assert "stopped early" in summary.lower() or "low" in summary.lower()


def test_result_state_mixed():
    """Test mixed state when using both live and cached sources."""
    from research.truth_layer import determine_result_state, ResultState

    state, summary = determine_result_state(
        stop_reason="budget_exhausted",
        provider_code="provider_ok",
        accepted_sources_live=5,
        accepted_sources_cached=5,
        accepted_sources_local=0,
        useful_artifacts=10,
    )

    assert state == ResultState.MIXED
    assert "mix" in summary.lower()


def test_followup_patterns():
    """Test that follow-up patterns match correctly."""
    from research.truth_layer import FOLLOWUP_PATTERNS

    # These should match
    assert "any errors?" in FOLLOWUP_PATTERNS["errors"]
    assert "what failed?" in FOLLOWUP_PATTERNS["failed"]
    assert "what do you need" in FOLLOWUP_PATTERNS["needs"]
    assert "what should i feed you" in FOLLOWUP_PATTERNS["feed"]
    assert "what are the blockers" in FOLLOWUP_PATTERNS["blockers"]
    assert "what happened" in FOLLOWUP_PATTERNS["happened"]


def test_handle_followup_errors():
    """Test error follow-up handling."""
    from research.truth_layer import handle_followup

    pulse_data = {
        "blockers": [{"message": "All search providers failed", "severity": "warning", "subsystem": "golearn"}],
    }

    result = handle_followup("any errors?", pulse_data, None)
    assert result is not None
    assert "search providers" in result.lower() or "blocked" in result.lower()


def test_handle_followup_needs():
    """Test needs follow-up handling."""
    from research.truth_layer import handle_followup

    pulse_data = {
        "needs": [{"topic": "python", "description": "Need more Python docs", "urgency": 2}],
    }

    result = handle_followup("what do you need?", pulse_data, None)
    assert result is not None
    assert "python" in result.lower()


def test_handle_followup_feed():
    """Test feed follow-up handling."""
    from research.truth_layer import handle_followup

    pulse_data = {
        "feed_me": [
            {"requested_topic": "python", "suggested_folder": "01_python/", "reason": "Need docs", "urgency": 2}
        ],
    }

    result = handle_followup("what should i feed you?", pulse_data, None)
    assert result is not None
    assert "python" in result.lower() or "feed" in result.lower()


def test_handle_followup_blockers():
    """Test blockers follow-up handling."""
    from research.truth_layer import handle_followup

    pulse_data = {
        "blockers": [
            {"message": "Live search blocked", "severity": "warning", "subsystem": "golearn"},
            {"message": "Low quality results", "severity": "warning", "subsystem": "golearn"},
        ],
    }

    result = handle_followup("what are the blockers?", pulse_data, None)
    assert result is not None
    assert "blocker" in result.lower()


def test_translate_result_for_display():
    """Test result translation for display."""
    from research.truth_layer import translate_result_for_display

    result = {
        "session": {
            "stop_reason": "budget_exhausted",
            "provider_code": "provider_ok",
            "accepted_sources_live": 10,
            "accepted_sources_cached": 0,
            "accepted_sources_local": 0,
            "useful_artifacts": 10,
        }
    }

    translated = translate_result_for_display(result)
    assert "[COMPLETED]" in translated
    assert "live" in translated.lower()


def test_grammar_status_query():
    """Test that status query patterns match in grammar."""
    from core.grammar import grammar_match

    tests = [
        "any errors?",
        "what failed?",
        "what do you need?",
        "what should i feed you?",
        "what are the blockers?",
    ]

    for t in tests:
        result = grammar_match(t)
        assert result is not None, f"Should match: {t}"
        assert result.get("intent") == "status_query", f"Should be status_query: {t}"


if __name__ == "__main__":
    test_result_state_completed()
    test_result_state_blocked()
    test_result_state_cache_only()
    test_result_state_partial()
    test_result_state_mixed()
    test_followup_patterns()
    test_handle_followup_errors()
    test_handle_followup_needs()
    test_handle_followup_feed()
    test_handle_followup_blockers()
    test_translate_result_for_display()
    test_grammar_status_query()
    print("All Truth Layer tests passed!")
