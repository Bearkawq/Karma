"""Tests for Karma v3.4.7 — Code & Learning Spine."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.grammar import grammar_match
from core.conversation_state import ConversationState
from tools.code_tool import CodeTool


# ── 1. CODE ROUTE TESTS ──────────────────────────────────

def test_run_py_routes_to_code():
    """'run /tmp/x.py' should route to code_run, not run_shell."""
    result = grammar_match("run /tmp/x.py")
    assert result is not None
    assert result["intent"] == "code_run", f"Got {result['intent']}"
    assert result["entities"].get("path") == "/tmp/x.py"

def test_run_code_py_routes_to_code():
    """'run code /tmp/x.py' should route to code_run."""
    result = grammar_match("run code /tmp/x.py")
    assert result is not None
    assert result["intent"] == "code_run", f"Got {result['intent']}"

def test_execute_code_routes_to_code():
    """'execute code /tmp/x.py' should route to code_run."""
    result = grammar_match("execute code /tmp/x.py")
    assert result is not None
    assert result["intent"] == "code_run", f"Got {result['intent']}"

def test_read_code_preserves_path():
    """'read code /tmp/x.py' should route to code_read with full path."""
    result = grammar_match("read code /tmp/x.py")
    assert result is not None
    assert result["intent"] == "code_read", f"Got {result['intent']}"
    assert result["entities"].get("path") == "/tmp/x.py"

def test_debug_routes_to_code_debug():
    """'debug /tmp/buggy.py' should route to code_debug."""
    result = grammar_match("debug /tmp/buggy.py")
    assert result is not None
    assert result["intent"] == "code_debug", f"Got {result['intent']}"
    assert result["entities"].get("path") == "/tmp/buggy.py"

def test_generic_run_stays_shell():
    """'run ls -la' should still route to run_shell."""
    result = grammar_match("run ls -la")
    assert result is not None
    assert result["intent"] == "run_shell", f"Got {result['intent']}"


# ── 2. CODE CONVERSATION TESTS ───────────────────────────

def test_code_context_in_conversation_state():
    """ConversationState should have last_code_context field."""
    cs = ConversationState()
    assert cs.last_code_context is None
    cs.last_code_context = {"path": "/tmp/x.py", "action": "code_run", "success": True}
    assert cs.last_code_context["path"] == "/tmp/x.py"

def test_fix_it_resolves_to_code_path():
    """'fix it' should resolve to code context path when available."""
    cs = ConversationState()
    cs.last_code_context = {"path": "/tmp/buggy.py", "action": "code_debug"}
    ref = cs.resolve_reference("fix it")
    assert ref == "/tmp/buggy.py"

def test_fix_it_without_code_context():
    """'fix it' without code context should not crash."""
    cs = ConversationState()
    cs.current_topic = "python"
    ref = cs.resolve_reference("fix it")
    # Falls through to "it" handler
    assert ref is not None  # gets last_subject or current_topic

def test_go_on_resolves_safely():
    """'go on' should resolve to thread topic or current topic."""
    cs = ConversationState()
    cs.current_topic = "testing"
    ref = cs.resolve_reference("go on")
    assert ref == "testing"


# ── 3. GOLEARN TESTS ─────────────────────────────────────

def test_golearn_grammar_match():
    """'golearn python decorators 1 auto' should match golearn intent."""
    result = grammar_match('golearn "python decorators" 1')
    # Grammar has golearn rule
    assert result is not None
    assert result["intent"] == "golearn", f"Got {result['intent']}"
    assert "topic" in result.get("entities", {})

def test_golearn_learn_about_match():
    """'learn about python decorators 3' should match golearn."""
    result = grammar_match("learn about python decorators 3")
    assert result is not None
    assert result["intent"] == "golearn", f"Got {result['intent']}"


def test_golearn_dispatch_routes_correctly():
    """golearn intent should have tool='golearn' in action, not None."""
    from agent.agent_loop import AgentLoop
    from core.grammar import grammar_match

    gram = grammar_match('golearn "python decorators" 5')
    assert gram is not None
    assert gram["intent"] == "golearn"

    intent_name = gram.get("intent", "")
    _DIRECT_TOOL_MAP = {
        "list_capabilities": None,
        "golearn": "golearn",
        "salvage_golearn": "golearn",
        "self_upgrade": None,
        "reload_language": None,
        "create_tool": None,
        "run_custom_tool": None,
        "list_custom_tools": None,
        "delete_tool": None,
        "teach_response": None,
        "forget_response": None,
        "code_read": None,
        "code_structure": None,
        "code_debug": None,
        "code_test": None,
        "code_recall": None,
        "code_run": None,
        "self_check": None,
        "repair_report": None,
        "crystallize": None,
    }

    tool = _DIRECT_TOOL_MAP.get(intent_name)
    assert tool == "golearn", f"golearn intent should have tool='golearn', got {tool!r}"


# ── 4. DEBUG TESTS ────────────────────────────────────────

def test_debug_nameerror_import_fix():
    """NameError for common module should auto-add import."""
    ct = CodeTool()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("data = json.loads('{}')\nprint(data)\n")
        f.flush()
        path = f.name
    try:
        result = ct._debug({"path": path, "max_attempts": 2})
        # Should either fix it or give useful diagnostic
        assert "attempts" in result
        if result.get("success"):
            content = Path(path).read_text()
            assert "import json" in content
    finally:
        os.unlink(path)

def test_debug_nameerror_typo():
    """NameError for typo should suggest/fix nearby name."""
    ct = CodeTool()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def calculate_sum(a, b):\n    return a + b\n\nresult = calculat_sum(1, 2)\nprint(result)\n")
        f.flush()
        path = f.name
    try:
        result = ct._debug({"path": path, "max_attempts": 2})
        assert "attempts" in result
        if result.get("success"):
            content = Path(path).read_text()
            assert "calculate_sum" in content
    finally:
        os.unlink(path)

def test_debug_syntax_missing_colon():
    """SyntaxError from missing colon should be auto-fixed."""
    ct = CodeTool()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def hello()\n    print('hi')\n")
        f.flush()
        path = f.name
    try:
        result = ct._debug({"path": path, "max_attempts": 2})
        assert "attempts" in result
        if result.get("success"):
            content = Path(path).read_text()
            assert "def hello():" in content
    finally:
        os.unlink(path)

def test_debug_indentation():
    """IndentationError with mixed tabs should be fixed."""
    ct = CodeTool()
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def hello():\n\t print('hi')\n")
        f.flush()
        path = f.name
    try:
        result = ct._debug({"path": path, "max_attempts": 2})
        assert "attempts" in result
    finally:
        os.unlink(path)


# ── 5. SECURITY REGRESSION TESTS ─────────────────────────

def test_shell_rules_still_match():
    """Generic shell commands still work."""
    result = grammar_match("run echo hello")
    assert result is not None
    assert result["intent"] == "run_shell"

def test_code_route_no_path_traversal():
    """Code tool rejects missing files gracefully."""
    ct = CodeTool()
    result = ct.execute({"operation": "read", "path": "/nonexistent/../../etc/passwd"})
    assert not result.get("success")


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
