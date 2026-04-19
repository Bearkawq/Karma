import importlib
import json
import sys
import types
from pathlib import Path


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status


class FakeFlaskApp:
    def __init__(self, *args, **kwargs):
        self.routes = {}

    def route(self, path, methods=None):
        def decorator(fn):
            self.routes[(path, tuple(methods or ['GET']))] = fn
            return fn
        return decorator


def fake_jsonify(payload=None, *args, **kwargs):
    return payload if payload is not None else kwargs


class FakeRequest:
    payload = {}

    @classmethod
    def get_json(cls, silent=True):
        return cls.payload


class FakeAgent:
    def __init__(self, config=None):
        self.config = config or {}
        self.current_state = {"execution_log": [], "decision_summary": {}}
        self.memory = types.SimpleNamespace(
            facts={"alpha": {"confidence": 0.9}},
            tasks={"t1": {"goal": "ship it", "priority": 1, "status": "open"}},
            get_stats=lambda: {
                "facts_count": 1,
                "episodic_count": 0,
                "tasks_count": 1,
                "facts_file_size": 0,
                "episodic_file_size": 0,
            },
        )
        self.tool_manager = types.SimpleNamespace(list_tools=lambda: ["files", "shell"])
        self.tool_builder = types.SimpleNamespace(registry={"hello": {}})
        self.capability_map = types.SimpleNamespace(get_full_map=lambda: {"files": {"score": 0.8}})
        self.health = types.SimpleNamespace(run_check=lambda: {"issues": [], "status": "HEALTHY"})
        self._DIRECT_INTENTS = {"help", "self_check"}
        self.runs = []
        self._revision = 0
        self._safe_mode = False
        self._current_lane = "chat"

    def run(self, text):
        self.runs.append(text)
        if text == "boom":
            raise RuntimeError("kaboom")
        return f"ok:{text}"

    def _state_file(self):
        return Path("/nonexistent/state.json")

    def get_revision(self):
        return self._revision

    def get_last_mutation(self):
        return {"source": "test", "revision": self._revision, "ts": "2026-01-01T00:00:00"}

    def is_safe_mode(self):
        return self._safe_mode

    def set_safe_mode(self, enabled):
        self._safe_mode = enabled

    def get_current_lane(self):
        return self._current_lane


class FakeWidget:
    def __init__(self, *args, **kwargs):
        self.rows = []
        self.lines = []
        self.value = ""

    def add_columns(self, *args, **kwargs):
        return None

    def add_row(self, *args, **kwargs):
        self.rows.append(args)

    def clear(self):
        self.rows.clear()
        self.lines.clear()

    def write(self, text):
        self.lines.append(text)

    def focus(self):
        return None


class FakeTabs(FakeWidget):
    class TabActivated:
        def __init__(self, tab=None):
            self.tab = tab


class FakeTab:
    def __init__(self, label, id=None):
        self.label = label
        self.id = id


class FakeContainer:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeTextualApp:
    def __init__(self, *args, **kwargs):
        pass


def _install_fake_agent_module(monkeypatch):
    mod = types.ModuleType("agent.agent_loop")
    mod.AgentLoop = FakeAgent
    mod.load_config = lambda path: {"tools": {"enabled": ["files", "shell"]}, "memory": {}, "logging": {}}
    monkeypatch.setitem(sys.modules, "agent.agent_loop", mod)


def test_web_routes_register_and_command_flow(monkeypatch):
    flask_mod = types.ModuleType("flask")
    flask_mod.Flask = FakeFlaskApp
    flask_mod.Response = FakeResponse
    flask_mod.jsonify = fake_jsonify
    flask_mod.render_template = lambda name: f"TEMPLATE:{name}"
    flask_mod.request = FakeRequest
    monkeypatch.setitem(sys.modules, "flask", flask_mod)
    _install_fake_agent_module(monkeypatch)
    sys.modules.pop("ui.web", None)
    web = importlib.import_module("ui.web")

    assert web.app is not None
    assert ("/", ("GET",)) in web.app.routes
    assert ("/api/command", ("POST",)) in web.app.routes

    FakeRequest.payload = {"command": "status"}
    result = web.app.routes[("/api/command", ("POST",))]()
    assert result["ok"] is True
    assert result["data"]["result"] == "ok:status"
    assert result["data"]["lane"] == "command"

    FakeRequest.payload = {}
    empty_resp = web.app.routes[("/api/command", ("POST",))]()
    empty, empty_status = (empty_resp if isinstance(empty_resp, tuple) else (empty_resp, 200))
    assert empty_status == 400
    assert empty["error"]["code"] == "EMPTY_INPUT"

    FakeRequest.payload = {"command": "boom"}
    error_resp = web.app.routes[("/api/command", ("POST",))]()
    error, error_status = (error_resp if isinstance(error_resp, tuple) else (error_resp, 200))
    assert error_status == 500
    assert error["ok"] is False


def test_web_data_routes(monkeypatch):
    flask_mod = types.ModuleType("flask")
    flask_mod.Flask = FakeFlaskApp
    flask_mod.Response = FakeResponse
    flask_mod.jsonify = fake_jsonify
    flask_mod.render_template = lambda name: f"TEMPLATE:{name}"
    flask_mod.request = FakeRequest
    monkeypatch.setitem(sys.modules, "flask", flask_mod)
    _install_fake_agent_module(monkeypatch)
    sys.modules.pop("ui.web", None)
    web = importlib.import_module("ui.web")

    tools = web.app.routes[("/api/tools", ("GET",))]()
    assert tools["registered"] == ["files", "shell"]
    assert "hello" in tools["custom"]

    caps = web.app.routes[("/api/capabilities", ("GET",))]()
    assert any(c["name"] == "files" for c in caps)
    assert any(c["type"] == "intent" for c in caps)

    health = web.app.routes[("/api/health", ("GET",))]()
    assert health["data"]["status"] == "HEALTHY"


def test_cockpit_instantiates_with_fake_textual(monkeypatch, tmp_path):
    textual_app = types.ModuleType("textual.app")
    textual_app.App = FakeTextualApp
    textual_app.ComposeResult = object
    monkeypatch.setitem(sys.modules, "textual.app", textual_app)

    textual_containers = types.ModuleType("textual.containers")
    textual_containers.Horizontal = FakeContainer
    textual_containers.Vertical = FakeContainer
    monkeypatch.setitem(sys.modules, "textual.containers", textual_containers)

    textual_widgets = types.ModuleType("textual.widgets")
    textual_widgets.Header = FakeWidget
    textual_widgets.Footer = FakeWidget
    class FakeInput(FakeWidget):
        class Submitted:
            value = ""
    textual_widgets.Input = FakeInput
    textual_widgets.Static = FakeWidget
    textual_widgets.RichLog = FakeWidget
    textual_widgets.DataTable = FakeWidget
    textual_widgets.Tabs = FakeTabs
    textual_widgets.Tab = FakeTab
    monkeypatch.setitem(sys.modules, "textual.widgets", textual_widgets)

    _install_fake_agent_module(monkeypatch)
    sys.modules.pop("ui.cockpit", None)
    cockpit = importlib.import_module("ui.cockpit")

    app = cockpit.KarmaCockpit()
    app.telemetry = FakeWidget()
    app.task_table = FakeWidget()
    app.facts_table = FakeWidget()
    app.console_log = FakeWidget()
    app.thoughtlog = FakeWidget()
    app._active_tab = "Tools"
    app.refresh_panels()
    assert any("files" in line for line in app.telemetry.lines)

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "last_run": "now",
        "current_task": "demo",
        "decision_summary": {"total_decisions": 3, "success_rate": 1.0, "average_confidence": 0.8},
        "execution_log": [{"intent": {"intent": "help"}, "success": True}],
    }))
    app.state_file = state_path
    app.telemetry = FakeWidget()
    app._active_tab = "State"
    app._refresh_telemetry()
    assert any("Last run" in line for line in app.telemetry.lines)
    assert any("help" in line for line in app.telemetry.lines)
