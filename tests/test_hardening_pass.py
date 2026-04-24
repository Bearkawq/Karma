from concurrent.futures import ThreadPoolExecutor


from agent.agent_loop import AgentLoop, load_config
from tools.tool_interface import ShellTool, ToolManager, InvalidTool


def test_parse_cache_stores_none_for_conversation():
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    text = "hello there"
    out1 = agent.run(text)
    out2 = agent.run(text)
    assert isinstance(out1, str) and isinstance(out2, str)
    snap = agent.governor.snapshot()
    assert snap["parse_cache_entries"] >= 1
    assert snap["parse_cache_hits"] >= 1


def test_shell_nonzero_is_failure():
    tool = ShellTool("shell", {"allowed_commands": ["ls"], "timeout": 5})
    result = tool.execute({"command": "ls /definitely/not/here"})
    assert result["success"] is False
    assert result["result"]["returncode"] != 0


def test_unknown_tool_category_becomes_invalid_tool():
    tm = ToolManager()
    tm.register_tool("weird", {"category": "eldritch"})
    tool = tm.get_tool("weird")
    assert isinstance(tool, InvalidTool)
    result = tm.execute_tool("weird", {})
    assert result["success"] is False
    assert "Unknown tool category" in result["error"]


def test_agent_run_is_thread_safe_for_simple_calls():
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    cmds = ["what can you do", "self check", "list files", "again"]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(agent.run, cmds))
    assert all(isinstance(r, str) and r.strip() for r in results)


def test_agent_uses_base_dir_for_default_file_listing():
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    out = agent.run("list files")
    assert "path:" in out
    # Root dir has many files; verify listing shows the project root path and entries
    assert "/karma" in out or "karma" in out
    assert "entries:" in out
