from agent.agent_loop import AgentLoop, load_config
from core.conversation_state import ConversationState
from core.dialogue import command_signal_score, choose_response_goal, retrieval_mode_for_goal


def make_agent(tmp_path):
    cfg = load_config()
    cfg["observer"]["enabled"] = False
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg["memory"]["episodic_file"] = str(data_dir / "episodic.jsonl")
    cfg["memory"]["facts_file"] = str(data_dir / "facts.json")
    cfg["memory"]["tasks_file"] = str(data_dir / "tasks.json")
    cfg["memory"]["state_file"] = str(data_dir / "agent_state.json")
    return AgentLoop(cfg)


def test_command_signal_score_prefers_question_shaped_commands():
    assert command_signal_score("can you list files in tests") >= 0.32
    assert choose_response_goal("summarize that", act="summary_request") == "summarize"
    assert retrieval_mode_for_goal("continue") == "dialogue_continue"


def test_conversation_state_artifact_and_reference_resolution():
    cs = ConversationState()
    cs.current_topic = "core files"
    cs.register_artifact(type="entry", gist="planner.py", raw="planner.py", ordering=1)
    cs.register_artifact(type="entry", gist="retrieval.py", raw="retrieval.py", ordering=2)
    assert cs.resolve_reference("the second one") == "retrieval.py"
    cs.note_turn(user_input="compare shell and file", response="compare shell and file", act="brainstorming")
    assert cs.resolve_reference("the first one") == "shell"


def test_question_shaped_command_routes_to_action(tmp_path):
    agent = make_agent(tmp_path)
    out = agent.run("what files are in core")
    assert "path:" in out or "entries:" in out or "error:" not in out.lower()
    agent.stop()


def test_followup_second_one_uses_artifact_ledger(tmp_path):
    agent = make_agent(tmp_path)
    first = agent.run("what files are in core")
    second = agent.run("the second one")
    assert "mean" in second.lower() or "tracking" in second.lower() or "continuing" in second.lower()
    assert agent.conversation.artifact_ledger
    agent.stop()


def test_go_on_and_summary_use_current_thread(tmp_path):
    agent = make_agent(tmp_path)
    first = agent.run("What can you do")
    go_on = agent.run("go on")
    summary = agent.run("summarize that")
    assert "Continuing on" in go_on
    assert "Summary of" in summary or "Topic:" in summary or "Active topic" in summary
    assert agent.conversation.answer_fragments
    agent.stop()


def test_uncertainty_gate_clarifies_unresolved_reference(tmp_path):
    agent = make_agent(tmp_path)
    out = agent.run("that folder")
    assert "which" in out.lower() and ("folder" in out.lower() or "file" in out.lower() or "referring" in out.lower())
    assert "unresolved_reference" in agent.conversation.scars
    agent.stop()


def test_concept_promotion_from_repeated_pattern():
    cs = ConversationState()
    for _ in range(3):
        cs.note_turn(user_input="explain parser bug", response="parser bug details", act="question", entities={"topic": "parser bug"})
    assert cs.concepts
    concept = next(iter(cs.concepts.values()))
    assert "parser bug" in concept["name"].lower()


# ── live fixes: referent quality ─────────────────────────────────────

def test_artifact_registration_filters_junk(tmp_path):
    """__pycache__ and .git should not appear in artifact ledger."""
    agent = make_agent(tmp_path)
    agent.run("list files in core")
    gists = [a.get("gist", "") for a in agent.conversation.artifact_ledger]
    assert not any("__pycache__" in g for g in gists)
    assert not any(".git" in g and ".gitignore" not in g for g in gists)
    agent.stop()


def test_second_one_skips_junk(tmp_path):
    """'the second one' after list should resolve to a meaningful file."""
    agent = make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("the second one")
    assert "__pycache__" not in out
    agent.stop()


# ── live fixes: summary anchoring ────────────────────────────────────

def test_summarize_uses_answer_fragment(tmp_path):
    """'summarize that' should use recent answer fragment, not generic."""
    agent = make_agent(tmp_path)
    agent.run("search files *.py in tests")
    out = agent.run("summarize that")
    # Should reference the topic or have structured content, not raw file listing
    assert "summary" in out.lower() or "topic" in out.lower() or "-" in out


# ── live fixes: continuation anchoring ───────────────────────────────

def test_go_on_uses_active_thread_topic(tmp_path):
    """'go on' should continue from active thread topic."""
    agent = make_agent(tmp_path)
    agent.run("search files *.py in tests")
    out = agent.run("go on")
    assert "continuing on" in out.lower()
    assert "tests" in out.lower() or "*.py" in out.lower()
    agent.stop()


# ── live fixes: clarification ────────────────────────────────────────

def test_that_folder_asks_specific_clarification(tmp_path):
    """'that folder' with no context should ask WHICH folder."""
    agent = make_agent(tmp_path)
    out = agent.run("that folder")
    assert "which" in out.lower()
    assert "folder" in out.lower()
    agent.stop()


def test_that_file_with_context_resolves(tmp_path):
    """'that file' after a search should resolve to an artifact."""
    agent = make_agent(tmp_path)
    agent.run("search files *.py in tests")
    out = agent.run("that file")
    # Should resolve to last artifact, not ask clarification
    assert "test_" in out.lower() or "tracking" in out.lower() or ".py" in out.lower()
    agent.stop()


# ── live fixes: introspection commands ───────────────────────────────

def test_current_topic_introspection(tmp_path):
    """'what is the current topic' should return topic state."""
    from core.dialogue import classify_dialogue_act
    d = classify_dialogue_act("what is the current topic")
    assert d["act"] == "introspection"

    agent = make_agent(tmp_path)
    agent.run("search files *.py in tests")
    out = agent.run("what is the current topic")
    assert "current topic" in out.lower()
    agent.stop()


def test_show_active_artifacts_introspection(tmp_path):
    """'show active artifacts' should list artifact ledger."""
    from core.dialogue import classify_dialogue_act
    d = classify_dialogue_act("show active artifacts")
    assert d["act"] == "introspection"

    agent = make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("show active artifacts")
    assert "artifact" in out.lower()
    # Should have items listed
    assert "1." in out or "core" in out.lower()
    agent.stop()
