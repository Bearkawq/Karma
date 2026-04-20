"""Tests: Karma identity, chat sanity, health indicator, and title cleanliness.

Covers the contamination fixes introduced to resolve:
  - Garbage responses to simple prompts like "are you functioning"
  - Council/BranchBoard name leaking into the Karma UI
  - Health indicator reflecting real backend state vs. just SSE connection
"""
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Responder unit tests
# ---------------------------------------------------------------------------

class FakeRetrieval:
    """Retrieval bus stub that returns high-relevance garbage for any query."""

    def retrieve_context_bundle(self, query, mode):
        # Simulate contaminated retrieval returning Python decorator text
        from core.retrieval import EvidenceItem
        return [
            EvidenceItem(
                type="answer_fragment",
                value="@app.route('/foo') def foo(): pass  # decorator garbage",
                confidence=0.9,
                relevance=0.8,
                source="contaminated_memory",
                effect_hint="answer_fact",
            )
        ]


def _make_responder(with_retrieval=False):
    from core.responder import Responder
    r = Responder(base_dir=str(ROOT), config={"system": {"version": "test"}})
    if with_retrieval:
        r._retrieval = FakeRetrieval()
    return r


@pytest.mark.parametrize("query", [
    "are you functioning",
    "are you functioning?",
    "are you working",
    "are you operational",
    "are you online",
    "are you active",
    "are you running",
    "is karma functioning",
    "is karma working",
    "is karma running",
    "functioning",
    "operational",
])
def test_functioning_queries_return_status_not_garbage(query):
    """Status queries must return the _status() answer, never retrieved garbage."""
    r = _make_responder(with_retrieval=True)
    response = r.respond(query)
    # Must NOT contain Python decorator artifacts
    assert "decorator" not in response.lower()
    assert "@app.route" not in response
    assert "def foo" not in response
    # Must be a real status message
    assert any(kw in response.lower() for kw in ["running", "local", "systems", "karma", "functioning"]), \
        f"Unexpected response for '{query}': {response!r}"


@pytest.mark.parametrize("query", [
    "how are you",
    "status",
    "you up",
    "you good",
    "you alive",
    "ping",
    "alive",
])
def test_existing_status_patterns_still_work(query):
    """Existing base-template patterns must continue to fire."""
    r = _make_responder(with_retrieval=True)
    response = r.respond(query)
    assert "@app.route" not in response, f"Retrieval garbage leaked for '{query}'"
    assert "I don't understand" not in response, f"Base template missed '{query}'"


def test_base_templates_take_priority_over_retrieval():
    """Base templates must fire even when retrieval returns high-relevance results."""
    r = _make_responder(with_retrieval=True)
    # "hello" is a greeting — retrieval must not override it
    response = r.respond("hello")
    assert "decorator" not in response.lower()
    assert "Hey" in response or "Karma" in response


def test_identity_not_overridden_by_retrieval():
    r = _make_responder(with_retrieval=True)
    response = r.respond("who are you")
    assert "Karma" in response
    assert "decorator" not in response.lower()


def test_unknown_query_still_falls_to_retrieval():
    """Unknown queries (not matching any base template) should reach retrieval."""
    r = _make_responder(with_retrieval=True)
    # "explain the Fibonacci sequence" — won't match any base template
    response = r.respond("explain the fibonacci sequence in detail please")
    # Retrieval is allowed to respond here (it has the only knowledge)
    # We just verify it doesn't crash and returns something
    assert isinstance(response, str)
    assert len(response) > 0


# ---------------------------------------------------------------------------
# Page title / identity string tests
# ---------------------------------------------------------------------------

def test_dashboard_title_is_karma():
    """dashboard.html must have <title>Karma</title>, never Council or BranchBoard."""
    html = (ROOT / "ui" / "templates" / "dashboard.html").read_text()
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    assert title_match, "No <title> tag found in dashboard.html"
    title = title_match.group(1)
    assert title == "Karma", f"Title is {title!r}, expected 'Karma'"


def test_dashboard_has_no_council_reference():
    html = (ROOT / "ui" / "templates" / "dashboard.html").read_text()
    assert "council" not in html.lower(), "Council reference found in dashboard.html"
    assert "branchboard" not in html.lower(), "BranchBoard reference found in dashboard.html"


def test_appjs_has_no_council_reference():
    js = (ROOT / "ui" / "static" / "app.js").read_text()
    assert "council" not in js.lower(), "Council reference found in app.js"


def test_appjs_karma_online_message():
    """The startup message must identify as Karma."""
    js = (ROOT / "ui" / "static" / "app.js").read_text()
    assert "Karma online" in js, "Expected 'Karma online' startup message in app.js"


# ---------------------------------------------------------------------------
# Health indicator test
# ---------------------------------------------------------------------------

def test_appjs_polls_health_endpoint():
    """app.js must call /api/health periodically, not only rely on SSE."""
    js = (ROOT / "ui" / "static" / "app.js").read_text()
    assert "/api/health" in js, "/api/health not referenced in app.js"
    assert "pollHealth" in js or "poll_health" in js or "setInterval" in js, \
        "No periodic health polling found in app.js"


def test_status_dot_has_degraded_class():
    """CSS must define the 'degraded' dot state for partial health failures."""
    css = (ROOT / "ui" / "static" / "style.css").read_text()
    assert "degraded" in css, "No 'degraded' CSS class found for status dot"


# ---------------------------------------------------------------------------
# Launch guard test
# ---------------------------------------------------------------------------

def test_web_main_has_port_guard():
    """web.py main() must check for port-in-use before binding."""
    source = (ROOT / "ui" / "web.py").read_text()
    assert "connect_ex" in source or "already in use" in source, \
        "No port-in-use guard found in web.py main()"
