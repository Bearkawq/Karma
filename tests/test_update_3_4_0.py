"""Tests for v3.4.0: current subject, truth-status recall, contrastive, crown-jewel introspection."""

from core.conversation_state import ConversationState, _TRUTH_STATUS_ORDER
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


# ── current_subject structure ────────────────────────────────────────

def test_current_subject_default_none():
    cs = ConversationState()
    assert cs.current_subject is None


def test_set_current_subject_creates_dict():
    cs = ConversationState()
    cs.set_current_subject(kind="file", label="planner.py", id="a1", confidence=0.9)
    subj = cs.current_subject
    assert subj is not None
    assert subj["kind"] == "file"
    assert subj["human_label"] == "planner.py"
    assert subj["id"] == "a1"
    assert subj["confidence"] == 0.9
    assert "source_turn" in subj
    assert "related_artifacts" in subj


def test_set_current_subject_updates_last_subject():
    cs = ConversationState()
    cs.set_current_subject(kind="file", label="retrieval.py")
    assert cs.last_subject == "retrieval.py"


def test_current_subject_bound_to_thread():
    cs = ConversationState()
    cs.note_turn(user_input="list files", response="core, tests", act="command",
                 entities={"topic": "core files"})
    cs.set_current_subject(kind="folder", label="core", confidence=0.8)
    th = cs.active_thread()
    assert th is not None
    assert th.get("current_subject") is not None
    assert th["current_subject"]["human_label"] == "core"


def test_register_artifact_sets_current_subject():
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="planner.py", raw="planner.py")
    assert cs.current_subject is not None
    assert cs.current_subject["kind"] == "file"
    assert cs.current_subject["human_label"] == "planner.py"


def test_note_turn_sets_current_subject():
    cs = ConversationState()
    cs.note_turn(user_input="show planner", response="planner details", act="command",
                 entities={"name": "planner.py"})
    assert cs.current_subject is not None
    assert cs.current_subject["human_label"] == "planner.py"


def test_subject_kind_detection():
    assert ConversationState._infer_subject_kind("planner.py") == "file"
    assert ConversationState._infer_subject_kind("tests/test_foo.py") == "file"
    assert ConversationState._infer_subject_kind("core") == "folder"
    assert ConversationState._infer_subject_kind("core/") == "folder"
    assert ConversationState._infer_subject_kind("the meaning of life and everything in it forever and ever") == "topic"


# ── truth-status-aware recall ────────────────────────────────────────

def test_truth_status_rank_ordering():
    cs = ConversationState()
    ranks = [cs.truth_status_rank(s) for s in _TRUTH_STATUS_ORDER]
    assert ranks == sorted(ranks), f"Expected monotonic ordering, got {ranks}"
    assert cs.truth_status_rank("observed") < cs.truth_status_rank("superseded")


def test_truth_status_rank_unknown_defaults():
    cs = ConversationState()
    assert cs.truth_status_rank("unknown_status") == 4  # provisional-level


def test_truth_weight_still_works():
    cs = ConversationState()
    assert cs.truth_weight("observed") == 1.0
    assert cs.truth_weight("superseded") == 0.2


# ── contrastive recall ───────────────────────────────────────────────

def test_contrastive_surfaces_corrected_artifacts():
    cs = ConversationState()
    cs.note_turn(user_input="list files", response="core, tests", act="command",
                 entities={"topic": "files"})
    art = cs.register_artifact(type="entry", gist="old_file.py", raw="old_file.py")
    art["status"] = "corrected"
    corrected = cs.corrected_artifacts()
    assert len(corrected) >= 1
    assert corrected[0]["gist"] == "old_file.py"


def test_contrastive_alternatives_still_works():
    cs = ConversationState()
    alts = cs.contrastive_alternatives()
    assert isinstance(alts, list)


# ── crown-jewel introspection (classify) ─────────────────────────────

def test_classify_current_subject_introspection():
    d = classify_dialogue_act("what is the current subject")
    assert d["act"] == "introspection"


def test_classify_why_talking_introspection():
    d = classify_dialogue_act("why are we talking about this")
    assert d["act"] == "introspection"


def test_classify_what_evidence_introspection():
    d = classify_dialogue_act("what evidence supports that")
    assert d["act"] == "introspection"


def test_classify_what_else_introspection():
    d = classify_dialogue_act("what else did you think it might be")
    assert d["act"] == "introspection"


def test_classify_what_changed_introspection():
    d = classify_dialogue_act("what changed")
    assert d["act"] == "introspection"


def test_classify_what_was_corrected_introspection():
    d = classify_dialogue_act("what was corrected")
    assert d["act"] == "introspection"


# ── crown-jewel introspection (responses) ────────────────────────────

def test_introspection_current_subject_response(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("what is the current subject")
    assert "subject" in out.lower() or "kind" in out.lower()
    agent.stop()


def test_introspection_why_talking_response(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("why are we talking about this")
    assert "topic" in out.lower() or "thread" in out.lower() or "subject" in out.lower()
    agent.stop()


def test_introspection_what_evidence_response(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("what evidence supports that")
    assert "evidence" in out.lower() or "artifact" in out.lower() or "fragment" in out.lower() or "subject" in out.lower()
    agent.stop()


def test_introspection_what_else_response(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("what else did you think it might be")
    assert len(out) > 5  # should have some response
    agent.stop()


def test_introspection_what_changed_response(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("what changed")
    assert len(out) > 5
    agent.stop()


# ── backward compat ──────────────────────────────────────────────────

def test_existing_last_subject_still_works():
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="planner.py", raw="planner.py")
    cs.register_artifact(type="entry", gist="retrieval.py", raw="retrieval.py")
    assert cs.resolve_reference("the second one") == "retrieval.py"
    assert cs.last_subject is not None


def test_existing_introspection_still_works():
    d = classify_dialogue_act("show active artifacts")
    assert d["act"] == "introspection"
    d = classify_dialogue_act("what is the current topic")
    assert d["act"] == "introspection"
