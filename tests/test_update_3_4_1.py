"""Tests for v3.4.1: subject commitment, subject-first summary/continuation, local introspection."""

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


# ── subject commitment after selection ───────────────────────────────

def test_subject_sticks_after_second_one(tmp_path):
    """current_subject must be the selected artifact, not the parent list."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    subj = agent.conversation.current_subject
    assert subj is not None
    assert subj["human_label"] != "core"  # not the parent list topic
    # second non-pycache artifact may be a file or folder; just verify it's a concrete item
    assert subj["kind"] in ("file", "folder") or "." in subj["human_label"]
    agent.stop()


def test_subject_survives_introspection(tmp_path):
    """Introspection must not overwrite current_subject."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    before = agent.conversation.current_subject
    agent.run("what is the current subject")
    after = agent.conversation.current_subject
    assert before == after
    agent.stop()


# ── subject-first summary ───────────────────────────────────────────

def test_summarize_uses_selected_subject(tmp_path):
    """'summarize that' after selection must reference the selected subject."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    out = agent.run("summarize that")
    subj_label = agent.conversation.current_subject["human_label"]
    assert subj_label in out
    assert "Got it" not in out
    agent.stop()


def test_summarize_no_wrapper_text(tmp_path):
    """Summary must not contain wrapper phrases."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    out = agent.run("summarize that")
    assert "Got it. You mean:" not in out
    assert "I'm tracking" not in out
    agent.stop()


# ── subject-first continuation ───────────────────────────────────────

def test_go_on_uses_selected_subject(tmp_path):
    """'go on' after selection must continue the selected subject."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    out = agent.run("go on")
    subj_label = agent.conversation.current_subject["human_label"]
    assert "continuing on" in out.lower()
    assert subj_label.lower() in out.lower()
    agent.stop()


# ── topic pollution prevention ───────────────────────────────────────

def test_introspection_does_not_pollute_topic(tmp_path):
    """Introspection commands must not set topic to meta phrases."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    topic_before = agent.conversation.current_topic
    agent.run("what is the current subject")
    topic_after = agent.conversation.current_topic
    assert "current subject" not in (topic_after or "").lower()
    assert topic_after == topic_before
    agent.stop()


def test_summarize_that_does_not_set_topic_that():
    """'summarize that' must not set topic to 'that'."""
    cs = ConversationState()
    cs.current_topic = "core files"
    cs.note_turn(user_input="summarize that", response="Summary of core files:\n- items",
                 act="summary_request")
    assert cs.current_topic == "core files"


def test_the_second_one_does_not_set_topic():
    """'the second one' must not change the topic."""
    cs = ConversationState()
    cs.current_topic = "core files"
    cs.note_turn(user_input="the second one", response="Got it. You mean: planner.py",
                 act="correction")
    assert cs.current_topic == "core files"


# ── typed referents ──────────────────────────────────────────────────

def test_that_folder_only_folders():
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="health.py", raw="health.py")
    cs.register_artifact(type="entry", gist="core", raw="core")
    assert cs.resolve_reference("that folder") == "core"


def test_that_file_only_files():
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="core", raw="core")
    cs.register_artifact(type="entry", gist="health.py", raw="health.py")
    assert cs.resolve_reference("that file") == "health.py"


def test_that_folder_no_match_returns_none():
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="health.py", raw="health.py")
    assert cs.resolve_reference("that folder") is None


# ── local-only introspection ─────────────────────────────────────────

def test_what_are_you_referring_to_is_local(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    agent.run("the second one")
    out = agent.run("what are you referring to")
    assert "subject" in out.lower() or "artifact" in out.lower() or "topic" in out.lower()
    agent.stop()


def test_why_are_you_talking_is_introspection():
    d = classify_dialogue_act("why are you talking about this")
    assert d["act"] == "introspection"


def test_why_are_we_talking_is_introspection():
    d = classify_dialogue_act("why are we talking about this")
    assert d["act"] == "introspection"


def test_what_changed_is_local(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("what changed")
    assert len(out) > 3
    agent.stop()


def test_what_else_is_local(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("what else did you think it might be")
    assert len(out) > 3
    agent.stop()


# ── answer fragment filtering ────────────────────────────────────────

def test_introspection_not_registered_as_answer_fragment(tmp_path):
    """Introspection responses must not pollute answer fragments."""
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    frags_before = len(agent.conversation.answer_fragments)
    agent.run("what is the current subject")
    frags_after = len(agent.conversation.answer_fragments)
    assert frags_after == frags_before  # no new fragment from introspection
    agent.stop()
