
from agent.agent_loop import AgentLoop, load_config
from tools.tool_interface import ShellTool


def test_optional_ui_modules_import_without_deps():
    import ui.web as web
    import ui.cockpit as cockpit
    assert hasattr(web, "main")
    assert hasattr(cockpit, "KarmaCockpit")


def test_self_check_has_no_stale_pt_warning():
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    out = agent.run("self check")
    assert "_pt" not in str(out)


def test_shell_tool_rejects_chaining():
    tool = ShellTool("shell", {"allowed_commands": ["ls", "echo"], "timeout": 5})
    result = tool.execute({"command": "ls; pwd"})
    assert result["success"] is False
    assert "not allowed" in result["error"].lower() or "chaining" in result["error"].lower()
