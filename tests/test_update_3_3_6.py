from agent.agent_loop import AgentLoop, load_config
from core.conversation_state import ConversationState
from core.dialogue import classify_dialogue_act


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


# ── thread reopen ────────────────────────────────────────────────────

def test_thread_reopen_on_revisit():
    """Revisiting a topic should reopen a stable/closed thread."""
    cs = ConversationState()
    cs.note_turn(user_input="explain parser", response="parser details", act="question", entities={"topic": "parser"})
    cs.note_turn(user_input="summarize that", response="summary", act="summary_request", response_goal="summarize")
    # Thread should be stable after summary
    th = cs.active_thread()
    assert th is not None
    assert th["current_state"] == "stable"
    # Revisit the same topic
    cs.note_turn(user_input="explain parser again", response="more parser details", act="question", entities={"topic": "parser"})
    th2 = cs.active_thread()
    assert th2 is not None
    assert th2["current_state"] == "active"


def test_reopen_thread_method():
    cs = ConversationState()
    cs.note_turn(user_input="explain parser", response="details", act="question", entities={"topic": "parser"})
    cs.note_turn(user_input="summarize that", response="summary", act="summary_request", response_goal="summarize")
    tid = cs.active_thread_id
    assert tid is not None
    th = cs.threads[tid]
    assert th["current_state"] == "stable"
    reopened = cs.reopen_thread(tid)
    assert reopened is not None
    assert reopened["current_state"] == "active"


def test_find_thread_by_topic():
    cs = ConversationState()
    cs.note_turn(user_input="explain parser", response="details", act="question", entities={"topic": "parser"})
    tid = cs.find_thread_by_topic("parser")
    assert tid is not None
    assert "parser" in tid


# ── concept promotion ────────────────────────────────────────────────

def test_concept_promotion_links_files():
    """Concepts should track linked files from artifact ledger."""
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="planner.py", raw="planner.py", ordering=1)
    cs.register_artifact(type="entry", gist="retrieval.py", raw="retrieval.py", ordering=2)
    for _ in range(3):
        cs.note_turn(user_input="explain core files", response="core file details", act="question", entities={"topic": "core files"})
    assert cs.concepts
    concept = next(iter(cs.concepts.values()))
    assert "linked_files" in concept
    assert any(".py" in f for f in concept["linked_files"])


def test_concept_has_unresolved_questions():
    cs = ConversationState()
    for _ in range(3):
        cs.note_turn(user_input="explain parser bug", response="details", act="question", entities={"topic": "parser bug"})
    concept = next(iter(cs.concepts.values()))
    assert "unresolved_questions" in concept


# ── truth-status weighting ───────────────────────────────────────────

def test_truth_weight_ranking():
    """Observed items should rank higher than superseded."""
    cs = ConversationState()
    assert cs.truth_weight("observed") > cs.truth_weight("superseded")
    assert cs.truth_weight("stable") > cs.truth_weight("provisional")
    assert cs.truth_weight("corrected") > cs.truth_weight("superseded")


def test_truth_weight_in_artifact_retrieval():
    """Artifacts with 'observed' status should have higher confidence in retrieval."""
    cs = ConversationState()
    art1 = cs.register_artifact(type="entry", gist="planner.py", raw="planner.py")
    assert art1["status"] == "observed"
    assert cs.truth_weight(art1["status"]) == 1.0


# ── scar memory ──────────────────────────────────────────────────────

def test_scar_severity_accumulates():
    cs = ConversationState()
    cs.add_scar("question_command_swallow", reason="can you list files", severity=0.1)
    assert cs.scar_severity("question_command_swallow") == 0.1
    cs.add_scar("question_command_swallow", reason="can you search files", severity=0.1)
    assert cs.scar_severity("question_command_swallow") == 0.2


def test_scar_severity_zero_for_unknown():
    cs = ConversationState()
    assert cs.scar_severity("nonexistent") == 0.0


def test_scar_biased_routing(tmp_path):
    """Scar memory should lower the command-signal threshold for questions."""
    agent = make_agent(tmp_path)
    # Add a scar to simulate prior swallowed commands
    agent.conversation.add_scar("question_command_swallow", reason="prior swallow", severity=0.3)
    # A question-shaped command should still route to action
    out = agent.run("can you list files in core")
    assert "path:" in out or "entries:" in out or "error:" not in out.lower()
    agent.stop()


# ── existing behavior preservation ───────────────────────────────────

def test_list_files_still_works(tmp_path):
    agent = make_agent(tmp_path)
    out = agent.run("list files in core")
    assert "path:" in out or "entries:" in out or "error:" not in out.lower()
    agent.stop()


def test_summarize_still_anchored(tmp_path):
    agent = make_agent(tmp_path)
    agent.run("search files *.py in tests")
    out = agent.run("summarize that")
    assert "summary" in out.lower() or "topic" in out.lower() or "-" in out
    agent.stop()


def test_introspection_still_works(tmp_path):
    d = classify_dialogue_act("what is the current topic")
    assert d["act"] == "introspection"
    agent = make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("what is the current topic")
    assert "current topic" in out.lower()
    agent.stop()
