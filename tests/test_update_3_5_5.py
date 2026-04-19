"""Tests for Karma v3.5.5 — Subject Flow + Yield Quality.

Tests for:
1. Branch quality scoring improvements
2. Low-value pattern penalties
3. Queue bounding
4. Novelty judgment
5. Regression checks
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.grammar import grammar_match


# ── 1. BRANCH QUALITY TESTS ────────────────────────────────

def test_low_value_patterns_defined():
    """LOW_VALUE_PATTERNS should be defined."""
    from research.brancher import LOW_VALUE_PATTERNS
    
    assert len(LOW_VALUE_PATTERNS) > 0
    assert any("click here" in p for p in LOW_VALUE_PATTERNS)


def test_min_quality_threshold_defined():
    """MIN_QUALITY_THRESHOLD should be defined."""
    from research.brancher import MIN_QUALITY_THRESHOLD
    
    assert MIN_QUALITY_THRESHOLD > 0


def test_max_queue_size_defined():
    """MAX_QUEUE_SIZE should be defined."""
    from research.brancher import MAX_QUEUE_SIZE
    
    assert MAX_QUEUE_SIZE > 0


def test_brancher_penalizes_low_value():
    """Brancher should penalize low-value patterns."""
    from research.brancher import SubtopicBrancher
    
    brancher = SubtopicBrancher("python", mode="auto")
    
    # High-value candidate
    high_value = "python decorator examples"
    # Low-value candidate  
    low_value = "python click here subscribe"
    
    # Score them
    candidates = [high_value, low_value]
    scored = brancher._score_candidates(candidates)
    
    scores = {t: s for t, s in scored}
    
    assert scores[high_value] > scores[low_value]


def test_brancher_bounded_queue():
    """Brancher should bound queue size."""
    from research.brancher import SubtopicBrancher, MAX_QUEUE_SIZE
    
    brancher = SubtopicBrancher("python", mode="auto")
    
    # Add many candidates
    texts = ["python tutorial guide " * 50]
    
    for i in range(100):
        brancher.extract_and_enqueue(texts, "python")
    
    # Queue should be bounded
    assert len(brancher.queue) <= MAX_QUEUE_SIZE


def test_brancher_filters_low_quality():
    """Brancher should filter candidates below quality threshold."""
    from research.brancher import SubtopicBrancher, MIN_QUALITY_THRESHOLD
    
    brancher = SubtopicBrancher("python", mode="auto")
    
    # Candidates with very low scores
    candidates = ["hi", "a"]  # Too short
    scored = brancher._score_candidates(candidates)
    
    # Should filter out candidates below threshold
    filtered = [(t, s) for t, s in scored if s >= MIN_QUALITY_THRESHOLD]
    
    # These should be filtered
    assert len(filtered) == 0


def test_brancher_boosts_root_overlap():
    """Brancher should boost candidates with root topic overlap."""
    from research.brancher import SubtopicBrancher
    
    brancher = SubtopicBrancher("python decorators", mode="auto")
    
    # Candidate with root overlap
    with_overlap = "python decorators tutorial"
    without_overlap = "javascript tutorial"
    
    scored = brancher._score_candidates([with_overlap, without_overlap])
    scores = {t: s for t, s in scored}
    
    assert scores[with_overlap] > scores[without_overlap]


def test_brancher_penalizes_generic():
    """Brancher should penalize generic words."""
    from research.brancher import SubtopicBrancher
    
    brancher = SubtopicBrancher("python", mode="auto")
    
    # Generic without specific
    generic = "python introduction overview"
    specific = "python decorator class"
    
    scored = brancher._score_candidates([generic, specific])
    scores = {t: s for t, s in scored}
    
    # Specific should score higher
    assert scores[specific] > scores[generic]


# ── 2. REGRESSION TESTS ───────────────────────────────────────

def test_grammar_still_matches_golearn():
    """golearn grammar should still match."""
    result = grammar_match('golearn "python decorators" 1 auto')
    assert result is not None
    assert result["intent"] == "golearn"


def test_brancher_basic_functionality():
    """Brancher should still work for basic cases."""
    from research.brancher import SubtopicBrancher
    
    brancher = SubtopicBrancher("python", mode="auto")
    
    topic = brancher.pick_next()
    assert topic is not None
    assert topic == "python"
    
    # Extract from sample text
    texts = ["Python decorators are functions that modify the behavior of other functions."]
    new_topics = brancher.extract_and_enqueue(texts, topic)
    
    assert isinstance(new_topics, list)


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
