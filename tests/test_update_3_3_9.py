"""Tests for v3.3.9: referent typing, summary anchoring, continuation, introspection scoping."""

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


# ── referent typing ──────────────────────────────────────────────────

def test_that_folder_cannot_resolve_to_file():
    """'that folder' must not resolve to a .py file."""
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="health.py", raw="health.py")
    cs.register_artifact(type="entry", gist="planner.py", raw="planner.py")
    result = cs.resolve_reference("that folder")
    assert result is None  # no folders in ledger


def test_that_file_cannot_resolve_to_directory():
    """'that file' must not resolve to a bare directory name."""
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="core", raw="core")
    cs.register_artifact(type="entry", gist="tests", raw="tests")
    result = cs.resolve_reference("that file")
    assert result is None  # no files in ledger


def test_that_folder_resolves_to_folder():
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="health.py", raw="health.py")
    cs.register_artifact(type="entry", gist="core", raw="core")
    result = cs.resolve_reference("that folder")
    assert result == "core"


def test_that_file_resolves_to_file():
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="core", raw="core")
    cs.register_artifact(type="entry", gist="health.py", raw="health.py")
    result = cs.resolve_reference("that file")
    assert result == "health.py"


# ── topic/subject consistency ────────────────────────────────────────

def test_subject_syncs_on_correction_resolve():
    """When correction resolves, last_subject should update."""
    from agent.dialogue_manager import DialogueManager
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="planner.py", raw="planner.py")
    cs.register_artifact(type="entry", gist="retrieval.py", raw="retrieval.py")
    dm = DialogueManager(cs, retrieval=None, responder=None, memory=None)
    # Simulate "the second one" correction
    response = dm.handle_turn("the second one", {"act": "correction", "route": "ask_clarification"})
    assert cs.last_subject == "retrieval.py"


def test_introspection_current_subject(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    out = agent.run("what is the current topic")
    # Should mention a concrete subject, not generic
    assert out and len(out) > 5
    agent.stop()


# ── summarize that ───────────────────────────────────────────────────

def test_summarize_does_not_return_wrapper_text(tmp_path):
    """'summarize that' should not summarize 'Got it. You mean: ...' wrapper."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    out = agent.run("summarize that")
    assert "Got it" not in out
    assert "summary" in out.lower() or "topic" in out.lower() or "-" in out
    agent.stop()


# ── go on ────────────────────────────────────────────────────────────

def test_go_on_uses_selected_subject(tmp_path):
    """'go on' after selecting an artifact should continue that subject."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    out = agent.run("go on")
    # Should reference the selected subject, not the original list
    assert "continuing on" in out.lower()
    assert "Got it" not in out
    agent.stop()


# ── introspection scoping ───────────────────────────────────────────

def test_what_are_you_referring_to_is_introspection():
    d = classify_dialogue_act("what are you referring to")
    assert d["act"] == "introspection"


def test_what_do_you_think_i_mean_is_introspection():
    d = classify_dialogue_act("what do you think I mean")
    assert d["act"] == "introspection"


def test_referring_to_scoped_to_local_state(tmp_path):
    """'what are you referring to' should show local state, not global memory."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    out = agent.run("what are you referring to")
    # Should show current subject/artifacts/thread, not broad memory
    assert "subject" in out.lower() or "artifact" in out.lower() or "topic" in out.lower()
    agent.stop()


def test_current_subject_introspection():
    d = classify_dialogue_act("what is the current subject")
    assert d["act"] == "introspection"


# ── existing behavior preserved ──────────────────────────────────────

def test_that_folder_no_context_clarifies(tmp_path):
    agent = _make_agent(tmp_path)
    out = agent.run("that folder")
    assert "which" in out.lower()
    agent.stop()


def test_list_files_still_works(tmp_path):
    agent = _make_agent(tmp_path)
    out = agent.run("list files in core")
    assert "path:" in out or "entries:" in out or "error:" not in out.lower()
    agent.stop()
