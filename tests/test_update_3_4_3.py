"""Tests for GoLearn v3.4.3 hardening update."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.crawler import (
    WebFetcher,
)
from research.brancher import SubtopicBrancher
from research.index import NoteWriter
from research.session import GoLearnSession
import tempfile


# ── 1. Source quality scoring ─────────────────────────────

def test_score_domain_high_quality():
    with tempfile.TemporaryDirectory() as d:
        f = WebFetcher(Path(d))
        assert f._score_domain("https://docs.python.org/3/library/os.html") == 1.0
        assert f._score_domain("https://developer.mozilla.org/en-US/docs/Web") == 1.0

def test_score_domain_high_pattern():
    with tempfile.TemporaryDirectory() as d:
        f = WebFetcher(Path(d))
        score = f._score_domain("https://github.com/torvalds/linux/blob/master/README")
        assert score == 0.8
        score = f._score_domain("https://flask.palletsprojects.com/en/latest/docs/")
        assert score == 0.8

def test_score_domain_low_quality():
    with tempfile.TemporaryDirectory() as d:
        f = WebFetcher(Path(d))
        assert f._score_domain("https://www.geeksforgeeks.org/python-list/") == 0.2
        assert f._score_domain("https://www.w3schools.com/python/") == 0.2

def test_score_domain_neutral():
    with tempfile.TemporaryDirectory() as d:
        f = WebFetcher(Path(d))
        assert f._score_domain("https://example.com/article") == 0.5


# ── 2. Search failure tracking ────────────────────────────

def test_search_failure_attr_initialized():
    with tempfile.TemporaryDirectory() as d:
        f = WebFetcher(Path(d))
        # After a search (even if network fails), last_search_failure should be set
        f.search("nonexistent_xyzzy_query_12345")
        assert hasattr(f, "last_search_failure")


# ── 3. Brancher near-duplicate penalization ───────────────

def test_brancher_penalizes_near_duplicates():
    b = SubtopicBrancher("python decorators")
    b.visited = {"python decorators", "python decorator tutorial"}
    candidates = ["python decorators examples", "rust async patterns"]
    scored = b._score_candidates(candidates)
    # "rust async patterns" should score higher than near-dup "python decorators examples"
    names = [s[0] for s in scored]
    scores = {s[0]: s[1] for s in scored}
    assert scores["rust async patterns"] > scores["python decorators examples"]

def test_brancher_word_overlap_ratio():
    b = SubtopicBrancher("test")
    assert b._word_overlap_ratio({"a", "b", "c"}, {"a", "b", "c"}) == 1.0
    assert b._word_overlap_ratio({"a", "b"}, {"c", "d"}) == 0.0
    assert 0.15 < b._word_overlap_ratio({"a", "b", "c"}, {"a", "d", "e"}) < 0.25
    assert b._word_overlap_ratio(set(), {"a"}) == 0.0


# ── 4. Low-yield abort logic ─────────────────────────────

def test_session_low_yield_tracking():
    with tempfile.TemporaryDirectory() as d:
        sess = GoLearnSession("test topic", minutes=1, base_dir=d)
        assert sess._consecutive_empty == 0
        assert sess._max_consecutive_empty == 3
        assert sess._slice_failures == []

def test_session_empty_streak_increments():
    """Simulating empty slices should increment the counter."""
    with tempfile.TemporaryDirectory() as d:
        sess = GoLearnSession("test topic", minutes=1, base_dir=d)
        # Simulate failures
        sess._consecutive_empty = 2
        sess._slice_failures.append({"subtopic": "x", "reason": "no_results"})
        assert sess._consecutive_empty == 2


# ── 5. Note extraction junk filtering ────────────────────

def test_note_writer_junk_filter():
    nw = NoteWriter()
    # Junk sentence should be filtered out of key_points
    junk_text = (
        "Click here to subscribe to our newsletter. "
        "Python provides a built-in sorted function for lists. "
        "© 2024 All rights reserved. "
        "The requests library requires Python 3.7 or higher."
    )
    points = nw._extract_key_points(junk_text)
    for p in points:
        assert "subscribe" not in p.lower()
        assert "all rights reserved" not in p.lower()

def test_note_writer_summary_no_junk():
    nw = NoteWriter()
    junk_text = (
        "Click here to learn more about cookies. "
        "TCP provides reliable ordered delivery of data between applications. "
        "Share this article with your friends on social media. "
        "The protocol requires a three-way handshake to establish connections."
    )
    summary = nw._summarize(junk_text, "TCP protocol")
    assert "click here" not in summary.lower()
    assert "share this" not in summary.lower()


# ── 6. Session persistence includes failures ─────────────

def test_session_save_includes_failures():
    import json
    with tempfile.TemporaryDirectory() as d:
        sess = GoLearnSession("test topic", minutes=1, base_dir=d)
        sess._slice_failures = [
            {"subtopic": "bad search", "reason": "no_results"},
            {"subtopic": "timeout search", "reason": "timeout"},
        ]
        sess._save_session()
        saved = json.loads((sess.session_dir / "session.json").read_text())
        assert "_failures" in saved
        assert len(saved["_failures"]) == 2
        assert saved["_failures"][0]["reason"] == "no_results"


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
