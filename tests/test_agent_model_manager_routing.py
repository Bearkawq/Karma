"""Tests for AgentModelManager.execute model-routing fix.

Before fix: force_no_model defaulted to config.default_to_deterministic (always True),
so available_models was always [], even when _no_model_mode=False (Ollama present).

After fix: force_no_model defaults to _no_model_mode, which reflects real availability.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def _stub_route(captured: dict):
    """Return a route spy that records kwargs and short-circuits via role='none'."""
    from core.role_router import RouteDecision
    from core.role_router import InvocationMode

    def _spy(**kwargs):
        captured["available_models"] = kwargs.get("available_models")
        captured["force_no_model"] = kwargs.get("force_no_model")
        return RouteDecision(role="none", mode=InvocationMode.NONE)

    return _spy


def _make_manager(no_model_mode: bool, loaded_models: dict = None):
    from core.agent_model_manager import AgentModelManager, ManagerConfig

    mgr = AgentModelManager(config=ManagerConfig())
    mgr._initialized = True
    mgr._no_model_mode = no_model_mode
    if loaded_models:
        mgr._models = loaded_models
        mgr._model_enabled = {k: True for k in loaded_models}
    return mgr


def _loaded_model(model_id="llama3:8b"):
    m = MagicMock()
    m.is_loaded = True
    return {model_id: m}


class TestForceNoModelDefaultResolution:

    def test_no_model_mode_true_passes_empty_models(self):
        mgr = _make_manager(no_model_mode=True, loaded_models=_loaded_model())
        captured = {}
        mgr.role_router.route = _stub_route(captured)
        mgr.execute("do something")
        assert captured["available_models"] == []
        assert captured["force_no_model"] is True

    def test_no_model_mode_false_passes_loaded_models(self):
        mgr = _make_manager(no_model_mode=False, loaded_models=_loaded_model("llama3:8b"))
        captured = {}
        mgr.role_router.route = _stub_route(captured)
        mgr.execute("do something")
        assert captured["force_no_model"] is False
        assert "llama3:8b" in captured["available_models"]

    def test_explicit_force_no_model_true_overrides_no_model_mode_false(self):
        mgr = _make_manager(no_model_mode=False, loaded_models=_loaded_model())
        captured = {}
        mgr.role_router.route = _stub_route(captured)
        mgr.execute("do something", force_no_model=True)
        assert captured["available_models"] == []
        assert captured["force_no_model"] is True

    def test_explicit_force_no_model_false_overrides_no_model_mode_true(self):
        mgr = _make_manager(no_model_mode=True, loaded_models=_loaded_model("phi3:mini"))
        captured = {}
        mgr.role_router.route = _stub_route(captured)
        mgr.execute("do something", force_no_model=False)
        assert captured["force_no_model"] is False
        assert "phi3:mini" in captured["available_models"]

    def test_default_to_deterministic_config_no_longer_gates_models(self):
        """config.default_to_deterministic=True must NOT block models when _no_model_mode=False."""
        from core.agent_model_manager import AgentModelManager, ManagerConfig

        mgr = AgentModelManager(config=ManagerConfig(default_to_deterministic=True))
        mgr._initialized = True
        mgr._no_model_mode = False
        mgr._models = _loaded_model("phi3:mini")
        mgr._model_enabled = {"phi3:mini": True}

        captured = {}
        mgr.role_router.route = _stub_route(captured)
        mgr.execute("do something")

        assert captured["force_no_model"] is False
        assert "phi3:mini" in captured["available_models"]

    def test_no_loaded_models_returns_empty_even_when_no_model_mode_false(self):
        """If no models are loaded, available_models is still [] even with _no_model_mode=False."""
        m = MagicMock()
        m.is_loaded = False
        mgr = _make_manager(no_model_mode=False, loaded_models={"stale": m})
        captured = {}
        mgr.role_router.route = _stub_route(captured)
        mgr.execute("do something")
        assert captured["force_no_model"] is False
        assert captured["available_models"] == []
