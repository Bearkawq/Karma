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


def test_web_model_ops_status_route_uses_readiness_report(monkeypatch):
    flask_mod = types.ModuleType("flask")
    flask_mod.Flask = FakeFlaskApp
    flask_mod.Response = FakeResponse
    flask_mod.jsonify = fake_jsonify
    flask_mod.render_template = lambda name: f"TEMPLATE:{name}"
    flask_mod.request = FakeRequest
    monkeypatch.setitem(sys.modules, "flask", flask_mod)
    _install_fake_agent_module(monkeypatch)

    manager_mod = types.ModuleType("core.agent_model_manager")
    fake_manager = types.SimpleNamespace(initialize=lambda: None)
    manager_mod.get_agent_model_manager = lambda: fake_manager
    monkeypatch.setitem(sys.modules, "core.agent_model_manager", manager_mod)

    slot_mod = types.ModuleType("core.slot_manager")
    fake_slot_mgr = object()
    slot_mod.get_slot_manager = lambda path: fake_slot_mgr
    monkeypatch.setitem(sys.modules, "core.slot_manager", slot_mod)

    import agent.services.model_operator_service as model_ops

    def fake_report(manager, slot_mgr):
        assert manager is fake_manager
        assert slot_mgr is fake_slot_mgr
        return {
            "status": "READY",
            "ready": True,
            "inventory": {"reachable": True},
            "small_models": [{"model": "qwen3:4b", "installed": True, "warm_now": False}],
            "roles": [{"role": "planner", "slot": "planner_slot", "assigned_model_id": "qwen3:4b"}],
        }

    monkeypatch.setattr(model_ops, "build_readiness_report", fake_report)
    sys.modules.pop("ui.web", None)
    web = importlib.import_module("ui.web")

    result = web.app.routes[("/api/model-ops/status", ("GET",))]()
    assert result["ok"] is True
    assert result["data"]["status"] == "READY"
    assert result["data"]["small_models"][0]["warm_now"] is False


def test_active_runtime_treats_persisted_task_as_last_task(monkeypatch, tmp_path):
    flask_mod = types.ModuleType("flask")
    flask_mod.Flask = FakeFlaskApp
    flask_mod.Response = FakeResponse
    flask_mod.jsonify = fake_jsonify
    flask_mod.render_template = lambda name: f"TEMPLATE:{name}"
    flask_mod.request = FakeRequest
    monkeypatch.setitem(sys.modules, "flask", flask_mod)
    _install_fake_agent_module(monkeypatch)

    slot_mod = types.ModuleType("core.slot_manager")
    slot_mod.get_slot_manager = lambda path: types.SimpleNamespace(get_all_roles=lambda: [])
    monkeypatch.setitem(sys.modules, "core.slot_manager", slot_mod)

    posture_mod = types.ModuleType("core.posture")
    posture_mod.get_system_posture = lambda: types.SimpleNamespace(
        get_posture_with_metrics=lambda: {"posture": "CALM"}
    )
    monkeypatch.setitem(sys.modules, "core.posture", posture_mod)

    receipts_mod = types.ModuleType("core.action_receipts")
    receipts_mod.get_receipt_store = lambda: types.SimpleNamespace(get_latest_receipt=lambda: None)
    monkeypatch.setitem(sys.modules, "core.action_receipts", receipts_mod)

    mutation_mod = types.ModuleType("core.mutation_log")
    mutation_mod.get_mutation_log = lambda: types.SimpleNamespace(get_latest_mutation=lambda: None)
    monkeypatch.setitem(sys.modules, "core.mutation_log", mutation_mod)

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"current_task": "stale_task"}))

    sys.modules.pop("ui.web", None)
    web = importlib.import_module("ui.web")
    fake_agent = FakeAgent()
    fake_agent._state_file = lambda: state_path
    web._agent = fake_agent

    result = web.app.routes[("/api/active_runtime", ("GET",))]()
    assert result["data"]["is_active"] is False
    assert result["data"]["current_task"] == "none"
    assert result["data"]["last_task"] == "stale_task"


def test_dashboard_uses_operator_model_status_and_pipeline_counts():
    root = Path(__file__).resolve().parent.parent
    dashboard = (root / "ui" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    app_js = (root / "ui" / "static" / "app.js").read_text(encoding="utf-8")

    assert '<link rel="icon" href="/static/icon-192.png">' in dashboard
    assert "/api/model-ops/status" in app_js
    assert "installed, idle" in app_js
    assert "warm now" in app_js
    assert 'agentCount + " agents / " + modelCount + " models"' in app_js


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


# ── Mobile UI surface tests ────────────────────────────────────────────────────


def test_mobile_route_exists(monkeypatch):
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

    assert ("/mobile", ("GET",)) in web.app.routes
    result = web.app.routes[("/mobile", ("GET",))]()
    assert "mobile.html" in result


def test_mobile_template_has_required_structure():
    root = Path(__file__).resolve().parent.parent
    tmpl = (root / "ui" / "templates" / "mobile.html").read_text(encoding="utf-8")

    # PWA meta tags
    assert 'viewport-fit=cover' in tmpl
    assert 'apple-mobile-web-app-capable' in tmpl
    assert 'manifest.json' in tmpl

    # All 5 tabs present
    for tab in ("chat", "models", "system", "memory", "learn"):
        assert f'data-tab="{tab}"' in tmpl

    # Key panel elements
    assert 'id="panel-models"' in tmpl
    assert 'id="ready-badge"' in tmpl
    assert 'id="role-list"' in tmpl
    assert 'id="sys-runtime"' in tmpl  # new Runtime section in system tab
    assert 'id="panel-chat"' in tmpl
    assert 'id="cmdinput"' in tmpl

    # Mobile JS and CSS linked
    assert 'mobile.css' in tmpl
    assert 'mobile.js' in tmpl


def test_mobile_css_has_readiness_and_role_styles():
    root = Path(__file__).resolve().parent.parent
    css = (root / "ui" / "static" / "mobile.css").read_text(encoding="utf-8")

    assert '.ready-badge' in css
    assert '.ready-badge.ready' in css
    assert '.ready-badge.not-ready' in css
    assert '.role-row' in css
    assert '.model-pill' in css
    assert '.model-pill.warm' in css
    assert '.posture-pill' in css


def test_mobile_js_calls_model_ops_and_active_runtime():
    root = Path(__file__).resolve().parent.parent
    js = (root / "ui" / "static" / "mobile.js").read_text(encoding="utf-8")

    # Models tab fetches readiness report
    assert '/api/model-ops/status' in js
    assert 'refreshModels' in js
    assert 'ready-badge' in js
    assert 'role-list' in js

    # System tab now fetches active_runtime
    assert '/api/active_runtime' in js
    assert 'sys-runtime' in js
    assert 'posture' in js.lower()

    # Offline queue intact
    assert 'karma_queue' in js
    assert 'cmdQueue' in js


def test_dashboard_mobile_redirect_on_mobile_ua(monkeypatch):
    """/ redirects mobile User-Agents to /mobile."""
    flask_mod = types.ModuleType("flask")
    flask_mod.Flask = FakeFlaskApp
    flask_mod.Response = FakeResponse
    flask_mod.jsonify = fake_jsonify

    redirected_to = []

    def fake_redirect(url):
        redirected_to.append(url)
        return f"REDIRECT:{url}"

    flask_mod.redirect = fake_redirect
    flask_mod.render_template = lambda name: f"TEMPLATE:{name}"

    class MobileRequest:
        headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"}
        payload = {}

        @classmethod
        def get_json(cls, silent=True):
            return cls.payload

    flask_mod.request = MobileRequest
    monkeypatch.setitem(sys.modules, "flask", flask_mod)
    _install_fake_agent_module(monkeypatch)
    sys.modules.pop("ui.web", None)
    web = importlib.import_module("ui.web")

    result = web.app.routes[("/", ("GET",))]()
    assert "REDIRECT:/mobile" in result
    assert "/mobile" in redirected_to


def test_dashboard_no_redirect_on_desktop_ua(monkeypatch):
    """/ serves dashboard.html for desktop User-Agents."""
    flask_mod = types.ModuleType("flask")
    flask_mod.Flask = FakeFlaskApp
    flask_mod.Response = FakeResponse
    flask_mod.jsonify = fake_jsonify
    flask_mod.redirect = lambda url: f"REDIRECT:{url}"
    flask_mod.render_template = lambda name: f"TEMPLATE:{name}"

    class DesktopRequest:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
        payload = {}

        @classmethod
        def get_json(cls, silent=True):
            return cls.payload

    flask_mod.request = DesktopRequest
    monkeypatch.setitem(sys.modules, "flask", flask_mod)
    _install_fake_agent_module(monkeypatch)
    sys.modules.pop("ui.web", None)
    web = importlib.import_module("ui.web")

    result = web.app.routes[("/", ("GET",))]()
    assert "dashboard.html" in result
    assert "REDIRECT" not in result
    assert "mobile" not in result
