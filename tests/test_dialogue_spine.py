from core.dialogue import classify_dialogue_act
from core.conversation_state import ConversationState
from agent.agent_loop import AgentLoop, load_config


def make_agent(tmp_path):
    cfg = load_config()
    cfg["observer"]["enabled"] = False
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for key in ("episodic_file", "facts_file", "tasks_file", "state_file"):
        cfg["memory"][key] = str(data_dir / key.replace('_file', ''))
    return AgentLoop(cfg)


def test_dialogue_act_classification():
    assert classify_dialogue_act("go on")["act"] == "continuation"
    assert classify_dialogue_act("What is memory?")["act"] == "question"
    assert classify_dialogue_act("search files *.py in tests")["route"] == "act_and_report"


def test_conversation_state_tracks_topic_and_summary():
    state = ConversationState()
    state.note_turn(user_input="what can you do", response="Tools: shell, file", act="question", intent=None, entities={})
    assert state.current_topic
    assert "Topic:" in state.summary()


def test_go_on_uses_previous_topic(tmp_path):
    agent = make_agent(tmp_path)
    first = agent.run("what can you do")
    second = agent.run("go on")
    assert "Tools:" in first or "Here's what" in first
    assert "Continuing on" in second
    assert agent.conversation.current_topic is not None
    agent.stop()


def test_second_option_reference_resolution(tmp_path):
    agent = make_agent(tmp_path)
    agent.conversation.active_options = ["shell", "file"]
    out = agent.run("the second one")
    assert "file" in out.lower()
    agent.stop()


def test_normal_question_does_not_trigger_tool_execution(tmp_path):
    agent = make_agent(tmp_path)
    out = agent.run("What is this system?")
    assert not out.startswith("Error:")
    assert "path:" not in out
    agent.stop()
