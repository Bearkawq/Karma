from concurrent.futures import ThreadPoolExecutor
import json
import os
import time
from pathlib import Path

from agent.agent_loop import AgentLoop, load_config
from core.events import EventBus
from core.observer import EnvironmentObserver
from storage.memory import MemorySystem
from tools.tool_interface import FileTool


def test_corrupt_state_file_is_quarantined(tmp_path):
    cfg = load_config("config.json")
    cfg["memory"] = dict(cfg.get("memory", {}))
    cfg["memory"]["state_file"] = str(tmp_path / "agent_state.json")
    state_path = Path(cfg["memory"]["state_file"])
    state_path.write_text('{nope', encoding='utf-8')

    agent = AgentLoop(cfg)
    assert agent.current_state["execution_log"] == []
    quarantined = list(tmp_path.glob("agent_state.json.corrupt*.bak"))
    assert quarantined, "corrupt state file should be quarantined"
    assert not state_path.exists()


def test_corrupt_facts_and_tasks_are_quarantined(tmp_path):
    facts = tmp_path / "facts.json"
    tasks = tmp_path / "tasks.json"
    episodic = tmp_path / "episodic.jsonl"
    facts.write_text('{bad', encoding='utf-8')
    tasks.write_text('{worse', encoding='utf-8')

    mem = MemorySystem(str(episodic), str(facts), str(tasks))
    assert mem.facts == {}
    assert mem.tasks == {}
    assert list(tmp_path.glob("facts.json.corrupt*.bak"))
    assert list(tmp_path.glob("tasks.json.corrupt*.bak"))


def test_eventbus_concurrent_emit_keeps_jsonl_valid(tmp_path):
    log_file = tmp_path / "events.jsonl"
    bus = EventBus(str(log_file))

    def emit_one(i: int):
        bus.emit("tick", idx=i, payload={"v": i})

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(emit_one, range(200)))

    lines = log_file.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 200
    parsed = [json.loads(line) for line in lines]
    assert {p["data"]["idx"] for p in parsed} == set(range(200))


def test_observer_stop_joins_thread(tmp_path):
    mem = MemorySystem(str(tmp_path / "episodic.jsonl"), str(tmp_path / "facts.json"), str(tmp_path / "tasks.json"))
    bus = EventBus(str(tmp_path / "events.jsonl"))
    observer = EnvironmentObserver([str(tmp_path)], mem, bus, interval=0.05)
    observer.start()
    time.sleep(0.12)
    observer.stop()
    assert observer._thread is not None
    assert not observer._thread.is_alive()


def test_agent_run_concurrent_smoke():
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    cmds = ["what can you do", "self check", "list files in tests", "search files *.py in tests"] * 6

    def run_cmd(cmd: str):
        return agent.run(cmd)

    with ThreadPoolExecutor(max_workers=8) as ex:
        outputs = list(ex.map(run_cmd, cmds))

    assert len(outputs) == len(cmds)
    assert any("matches:" in out for out in outputs)
    assert any("HEALTHY" in out or "Health:" in out for out in outputs)


def test_filetool_relative_path_uses_workspace_root(tmp_path):
    workspace = tmp_path / "workspace"
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "alpha.py").write_text("print('x')\n", encoding='utf-8')
    outside = tmp_path / "outside"
    outside.mkdir()
    old = os.getcwd()
    os.chdir(outside)
    try:
        tool = FileTool("file", {
            "category": "file",
            "workspace_root": str(workspace),
            "allowed_paths": [str(workspace)],
        })
        result = tool.execute({"operation": "search", "path": "tests", "pattern": "*.py"})
    finally:
        os.chdir(old)
    assert result["success"] is True
    assert str(tests_dir) == result["result"]["path"]
    assert result["result"]["matches"] == [str(tests_dir / "alpha.py")]
