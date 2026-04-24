"""Tests for v3.3.8: bootstrap, extracted modules, storage split, version."""



# ── bootstrap ────────────────────────────────────────────────────────

def test_bootstrap_version():
    from agent.bootstrap import get_version, VERSION
    assert VERSION  # version string is set
    assert get_version() == VERSION


def test_bootstrap_load_config():
    from agent.bootstrap import load_config
    cfg = load_config()
    assert cfg["system"]["version"]  # version injected
    assert "memory" in cfg
    assert "tools" in cfg


def test_bootstrap_build_agent(tmp_path):
    from agent.bootstrap import load_config, build_agent
    cfg = load_config()
    cfg["observer"]["enabled"] = False
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg["memory"]["episodic_file"] = str(data_dir / "episodic.jsonl")
    cfg["memory"]["facts_file"] = str(data_dir / "facts.json")
    cfg["memory"]["tasks_file"] = str(data_dir / "tasks.json")
    cfg["memory"]["state_file"] = str(data_dir / "agent_state.json")
    agent = build_agent(cfg)
    assert agent is not None
    assert hasattr(agent, "run")
    agent.stop()


def test_bootstrap_project_root():
    from agent.bootstrap import get_project_root
    root = get_project_root()
    assert (root / "config.json").exists()
    assert (root / "agent" / "agent_loop.py").exists()


# ── dialogue_manager extraction ──────────────────────────────────────

def test_dialogue_manager_introspection():
    from agent.dialogue_manager import DialogueManager
    from core.conversation_state import ConversationState
    cs = ConversationState()
    cs.current_topic = "test topic"
    dm = DialogueManager(cs, retrieval=None, responder=None, memory=None)
    out = dm._handle_introspection("what is the current topic")
    assert "test topic" in out


def test_dialogue_manager_clarification():
    from agent.dialogue_manager import DialogueManager
    from core.conversation_state import ConversationState
    cs = ConversationState()
    dm = DialogueManager(cs, retrieval=None, responder=None, memory=None)
    out = dm.clarification_prompt("that folder")
    assert "folder" in out.lower()


def test_dialogue_manager_clarification_with_artifacts():
    from agent.dialogue_manager import DialogueManager
    from core.conversation_state import ConversationState
    cs = ConversationState()
    cs.register_artifact(type="entry", gist="planner.py", raw="planner.py")
    dm = DialogueManager(cs, retrieval=None, responder=None, memory=None)
    out = dm.clarification_prompt("that file")
    assert "planner.py" in out


# ── reflection_engine extraction ─────────────────────────────────────

def test_reflection_engine_confidence():
    from agent.reflection_engine import ReflectionEngine
    re = ReflectionEngine(memory=None, retrieval=None, governor=None, current_state={})
    conf = re.calculate_confidence(
        {"confidence": 0.8}, {"confidence": 0.6}
    )
    assert 0.6 <= conf <= 0.8


def test_reflection_engine_success_rate():
    from agent.reflection_engine import ReflectionEngine
    state = {"execution_log": [
        {"success": True, "confidence": 0.9},
        {"success": False, "confidence": 0.3},
        {"success": True, "confidence": 0.7},
    ]}
    re = ReflectionEngine(memory=None, retrieval=None, governor=None, current_state=state)
    rate = re._calculate_success_rate()
    assert abs(rate - 2/3) < 0.01


# ── storage split ────────────────────────────────────────────────────

def test_persistence_atomic_write(tmp_path):
    from storage.persistence import atomic_write_text
    p = tmp_path / "test.txt"
    atomic_write_text(p, "hello world")
    assert p.read_text() == "hello world"


def test_persistence_quarantine(tmp_path):
    from storage.persistence import quarantine_file
    p = tmp_path / "bad.json"
    p.write_text("corrupt")
    bak = quarantine_file(p, "corrupt")
    assert bak is not None
    assert not p.exists()
    assert bak.exists()


def test_episodic_store(tmp_path):
    from storage.episodic import EpisodicStore
    store = EpisodicStore(tmp_path / "ep.jsonl")
    store.save("test_event", {"key": "val"}, outcome="success")
    assert len(store.log) == 1
    assert store.log[0]["event"] == "test_event"
    events = store.get_events("test_event")
    assert len(events) == 1


def test_fact_store(tmp_path):
    from storage.facts import FactStore
    store = FactStore(tmp_path / "facts.json")
    store.save_fact("test:key", "test_value", source="test")
    assert store.get_value("test:key") == "test_value"
    assert store.get_confidence("test:key") == 1.0
    store.mark_used("test:key", influenced=True)
    assert store.facts["test:key"]["use_count"] == 1


def test_memory_system_facade(tmp_path):
    """MemorySystem should still work as before after split."""
    from storage.memory import MemorySystem
    mem = MemorySystem(
        episodic_file=str(tmp_path / "ep.jsonl"),
        facts_file=str(tmp_path / "facts.json"),
        tasks_file=str(tmp_path / "tasks.json"),
    )
    mem.save_fact("key1", "val1")
    assert mem.get_fact_value("key1") == "val1"
    mem.save_episodic("test", {"x": 1})
    assert len(mem.episodic_log) == 1
    mem.save_task({"id": "t1", "status": "pending", "name": "test"})
    assert mem.get_task("t1")["name"] == "test"
    stats = mem.get_stats()
    assert stats["episodic_count"] == 1
    assert stats["facts_count"] == 1
    assert stats["tasks_count"] == 1


# ── version consistency ──────────────────────────────────────────────

def test_config_version_matches_bootstrap():
    from agent.bootstrap import VERSION, load_config
    cfg = load_config()
    assert cfg["system"]["version"] == VERSION


# ── conversation behavior preserved ──────────────────────────────────

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


def test_live_list_files(tmp_path):
    agent = _make_agent(tmp_path)
    out = agent.run("list files in core")
    assert "path:" in out or "entries:" in out or "error:" not in out.lower()
    agent.stop()


def test_live_introspection(tmp_path):
    agent = _make_agent(tmp_path)
    agent.run("list files in core")
    out = agent.run("what is the current topic")
    assert "current topic" in out.lower()
    agent.stop()


def test_live_that_folder_clarification(tmp_path):
    agent = _make_agent(tmp_path)
    out = agent.run("that folder")
    assert "which" in out.lower()
    agent.stop()
