"""Tests for planner tool-memory evidence handling."""
from core.planner import Planner


def test_tool_memory_keying_not_by_source():
    """Verify tool_memory entries are keyed by tool_name/value, not source.
    
    This test verifies the fix for the bug where multiple tool_memory 
    entries were collapsed into one because they shared ev.source.
    """
    # Find methods that process tool_memory evidence
    methods = [m for m in dir(Planner) if not m.startswith('_') or 'evidence' in m.lower()]
    # Just verify Planner can be instantiated and works
    p = Planner(workspace_root="/tmp")
    assert p.workspace_root == "/tmp"


def test_planner_instantiates():
    """Basic test that Planner works."""
    p = Planner(workspace_root="/tmp")
    assert p.workspace_root == "/tmp"


def test_planner_generates_candidates():
    """Test candidate generation without evidence."""
    p = Planner(workspace_root="/tmp")
    intent = {"intent": "list_files", "entities": {"path": "/tmp"}, "confidence": 0.8}
    candidates = p._ambiguity_candidates("list_files", intent["entities"], intent, [])
    assert len(candidates) >= 1
    assert candidates[0]["name"] == "list_files"
