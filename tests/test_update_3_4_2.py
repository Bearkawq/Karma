"""Tests for v3.4.2: enriched subject content, file-role summaries, natural introspection."""

from core.conversation_state import ConversationState
from core.dialogue import classify_dialogue_act


def _make_agent(tmp_path):
    from agent.bootstrap import load_config, build_agent
    cfg = load_config()
    cfg["observer"]["enabled"] = False
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg["memory"]["episodic_file"] = str(data_dir / "episodic.jsonl")
    cfg["memory"]["facts_file"] = str(data_dir / "facts.json")
    cfg["memory"]["tasks_file"] = str(data_dir / "tasks.json")
    cfg["memory"]["state_file"] = str(data_dir / "agent_state.json")
    return build_agent(cfg)


# ── enriched file summary ────────────────────────────────────────────

def test_summary_includes_file_role(tmp_path):
    """'summarize that' on a .py file must include role/purpose, not just filename."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the third one")
    out = agent.run("summarize that")
    # Should have file path and role/symbols, not just the filename
    assert "File:" in out or "Role:" in out or "Symbols:" in out
    agent.stop()


def test_summary_no_wrapper_content(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the third one")
    out = agent.run("summarize that")
    assert "Got it" not in out
    assert "I'm tracking" not in out
    agent.stop()


# ── enriched continuation ────────────────────────────────────────────

def test_continuation_includes_file_info(tmp_path):
    """'go on' on a file must include role/symbols, not stale list."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the third one")
    out = agent.run("go on")
    assert "continuing on" in out.lower()
    assert "File:" in out or "Role:" in out or "Symbols:" in out
    agent.stop()


# ── enriched introspection ───────────────────────────────────────────

def test_current_subject_shows_role(tmp_path):
    """'what is the current subject' must include file role if file selected."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the third one")
    out = agent.run("what is the current subject")
    assert "file" in out.lower()
    assert "Role:" in out or "Symbols:" in out or "Thread:" in out
    agent.stop()


def test_why_talking_natural_wording(tmp_path):
    """'why are you talking about this' must include selection context."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the third one")
    out = agent.run("why are you talking about this")
    assert "selected" in out.lower() or "thread" in out.lower()
    assert "list files" in out.lower() or "core" in out.lower()
    agent.stop()


def test_evidence_includes_file_info(tmp_path):
    """'what evidence' must include file-level evidence."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the third one")
    out = agent.run("what evidence supports that")
    assert "evidence" in out.lower()
    assert "File:" in out or "Role:" in out or "Selected" in out
    agent.stop()


def test_what_else_shows_nearby_artifacts(tmp_path):
    """'what else' must show other items from the same result set."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the third one")
    out = agent.run("what else did you think it might be")
    # Should list sibling files from the core listing
    assert "result set" in out.lower() or ".py" in out
    agent.stop()


def test_what_changed_mentions_selection(tmp_path):
    """'what changed' must mention subject selection."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the third one")
    out = agent.run("what changed")
    assert "selected" in out.lower() or "moved" in out.lower() or "subject" in out.lower()
    agent.stop()


# ── file enrichment unit tests ───────────────────────────────────────

def test_enrich_file_finds_real_file():
    from agent.dialogue_manager import DialogueManager
    cs = ConversationState()
    dm = DialogueManager(cs, retrieval=None, responder=None, memory=None)
    result = dm._enrich_file("dialogue.py")
    assert "File:" in result
    assert "dialogue" in result.lower()


def test_enrich_file_missing_returns_empty():
    from agent.dialogue_manager import DialogueManager
    cs = ConversationState()
    dm = DialogueManager(cs, retrieval=None, responder=None, memory=None)
    result = dm._enrich_file("nonexistent_xyz_file.py")
    assert result == ""


def test_extract_docstring():
    from agent.dialogue_manager import DialogueManager
    src = '"""Module docstring here."""\n\nclass Foo:\n    pass'
    assert "Module docstring here" in DialogueManager._extract_docstring(src)
