"""Tests for Ollama adapter loading during AgentModelManager.initialize().

Covers:
- adapters are loaded (not just registered) after initialize()
- get_loaded_models() is populated when Ollama is available
- a single model load failure does not abort remaining registrations
- slot assignments only happen for successfully loaded models
- no regression in execute() / routing when models are loaded
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Detect live Ollama once at module level
_OLLAMA_AVAILABLE = False
try:
    import urllib.request
    with urllib.request.urlopen(
        urllib.request.Request("http://localhost:11434/api/tags"), timeout=2
    ) as _r:
        _OLLAMA_AVAILABLE = _r.status == 200
except Exception:
    pass


# ---------------------------------------------------------------------------
# Deterministic tests — do not require live Ollama
# ---------------------------------------------------------------------------


def _fresh_mgr():
    """Return an uninitialized manager with a clean global state."""
    from core.agent_model_manager import AgentModelManager, ManagerConfig
    return AgentModelManager(config=ManagerConfig())


class TestAdapterLoadCalledOnRegistration:

    def test_load_called_for_each_ollama_llm_adapter(self):
        """Each LLM seat adapter must have load() called after register_model()."""
        from core.agent_model_manager import AgentModelManager

        mgr = _fresh_mgr()
        loaded_ids = []

        real_register = mgr.register_model

        def tracking_register(model_id, adapter):
            original_load = adapter.load

            def load_and_track():
                loaded_ids.append(model_id)
                return original_load()

            adapter.load = load_and_track
            return real_register(model_id, adapter)

        mgr.register_model = tracking_register

        with patch("models.local_llm_adapter._ollama_available", return_value=True), \
             patch("models.local_llm_adapter._ollama_model_present", return_value=True):
            mgr.initialize()

        # At least the LLM seats should have been loaded
        llm_seat_ids = [s[0] for s in AgentModelManager._OLLAMA_LLM_SEATS]
        for mid in llm_seat_ids:
            assert mid in loaded_ids, f"{mid} was registered but load() was not called"

    def test_model_load_failure_does_not_crash_initialization(self):
        """If one model fails to load, initialization must still complete."""
        mgr = _fresh_mgr()

        with patch("models.local_llm_adapter._ollama_available", return_value=True), \
             patch("models.local_llm_adapter._ollama_model_present", return_value=True), \
             patch("models.local_llm_adapter.LocalLLMAdapter.load", return_value=False):
            # Must not raise
            mgr.initialize()

        # Manager should still be initialized
        assert mgr._initialized is True

    def test_slot_assignment_skipped_when_load_fails(self):
        """assign_role must not be called for models whose load() returns False."""
        mgr = _fresh_mgr()
        assigned_calls = []

        # Intercept get_slot_manager to return a spy slot manager
        mock_slot_mgr = MagicMock()
        mock_slot_mgr.assign_role.side_effect = lambda role, mid: assigned_calls.append((role, mid))

        with patch("models.local_llm_adapter._ollama_available", return_value=True), \
             patch("models.local_llm_adapter._ollama_model_present", return_value=True), \
             patch("models.local_llm_adapter.LocalLLMAdapter.load", return_value=False), \
             patch("core.slot_manager.get_slot_manager", return_value=mock_slot_mgr):
            # Only patch LLM adapter load — embedding adapter is separate
            mgr.initialize()

        # No LLM role assignments should have been made since all LLM loads failed
        from core.agent_model_manager import AgentModelManager
        llm_seat_roles = {role for _, roles, _, _ in AgentModelManager._OLLAMA_LLM_SEATS for role in roles}
        actually_assigned_roles = {role for role, _ in assigned_calls}
        overlap = llm_seat_roles & actually_assigned_roles
        assert overlap == set(), f"LLM roles assigned despite load failure: {overlap}"

    def test_registered_but_unloaded_model_not_in_get_loaded_models(self):
        """A model that is registered but fails load() must not appear in get_loaded_models()."""
        from core.agent_model_manager import AgentModelManager, ManagerConfig
        from models.local_llm_adapter import create_llm_adapter

        mgr = AgentModelManager(config=ManagerConfig())
        mgr._initialized = True
        mgr._no_model_mode = False

        adapter = create_llm_adapter("test_model", backend="mock")
        # Mock load failure
        adapter._status = __import__(
            "models.base_model_adapter", fromlist=["ModelStatus"]
        ).ModelStatus.ERROR
        mgr.register_model("test_model", adapter)

        assert "test_model" not in mgr.get_loaded_models()

    def test_successfully_loaded_model_appears_in_get_loaded_models(self):
        """A model that passes load() must appear in get_loaded_models()."""
        from core.agent_model_manager import AgentModelManager, ManagerConfig
        from models.local_llm_adapter import create_llm_adapter

        mgr = AgentModelManager(config=ManagerConfig())
        mgr._initialized = True
        mgr._no_model_mode = False

        adapter = create_llm_adapter("mock_ready", backend="mock")
        adapter.load()  # sets status to READY
        mgr.register_model("mock_ready", adapter)

        assert "mock_ready" in mgr.get_loaded_models()

    def test_partial_load_failure_leaves_successful_models_loaded(self):
        """If one model fails and another succeeds, the successful one stays in get_loaded_models()."""
        from core.agent_model_manager import AgentModelManager, ManagerConfig
        from models.local_llm_adapter import create_llm_adapter
        from models.base_model_adapter import ModelStatus

        mgr = AgentModelManager(config=ManagerConfig())
        mgr._initialized = True
        mgr._no_model_mode = False

        good = create_llm_adapter("good_model", backend="mock")
        good.load()
        mgr.register_model("good_model", good)

        bad = create_llm_adapter("bad_model", backend="mock")
        bad._status = ModelStatus.ERROR
        mgr.register_model("bad_model", bad)

        loaded = mgr.get_loaded_models()
        assert "good_model" in loaded
        assert "bad_model" not in loaded

    def test_execute_uses_loaded_models_not_registered_models(self):
        """execute() must pass only is_loaded=True models to the router."""
        from core.agent_model_manager import AgentModelManager, ManagerConfig
        from models.local_llm_adapter import create_llm_adapter
        from models.base_model_adapter import ModelStatus
        from core.role_router import RouteDecision, InvocationMode

        mgr = AgentModelManager(config=ManagerConfig())
        mgr._initialized = True
        mgr._no_model_mode = False

        good = create_llm_adapter("loaded_model", backend="mock")
        good.load()
        mgr.register_model("loaded_model", good)

        bad = create_llm_adapter("unloaded_model", backend="mock")
        bad._status = ModelStatus.ERROR
        mgr.register_model("unloaded_model", bad)

        captured = {}

        def spy(**kw):
            captured["available_models"] = kw.get("available_models", [])
            return RouteDecision(role="none", mode=InvocationMode.NONE)

        mgr.role_router.route = spy
        mgr.execute("do something")

        assert "loaded_model" in captured["available_models"]
        assert "unloaded_model" not in captured["available_models"]


# ---------------------------------------------------------------------------
# Live tests — require Ollama at localhost:11434
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _OLLAMA_AVAILABLE, reason="Ollama not reachable at localhost:11434")
class TestOllamaModelLoadingLive:

    def test_get_loaded_models_populated_after_initialize(self):
        from core.agent_model_manager import AgentModelManager
        mgr = AgentModelManager()
        mgr.initialize()
        loaded = mgr.get_loaded_models()
        assert len(loaded) > 0, "Expected loaded models but got none"

    def test_all_registered_models_are_loaded(self):
        from core.agent_model_manager import AgentModelManager
        mgr = AgentModelManager()
        mgr.initialize()
        for mid, adapter in mgr._models.items():
            assert adapter.is_loaded, f"Model '{mid}' was registered but is_loaded=False"

    def test_execute_receives_loaded_models_from_real_init(self):
        from core.agent_model_manager import AgentModelManager
        from core.role_router import RouteDecision, InvocationMode

        mgr = AgentModelManager()
        mgr.initialize()

        captured = {}
        original = mgr.role_router.route

        def spy(**kw):
            captured["available_models"] = kw.get("available_models", [])
            captured["force_no_model"] = kw.get("force_no_model")
            return original(**kw)

        mgr.role_router.route = spy
        result = mgr.execute("list items", explicit_role="summarizer")

        assert captured.get("force_no_model") is False
        assert len(captured.get("available_models", [])) > 0
        assert result is not None

    def test_no_model_mode_false_after_init_with_ollama(self):
        from core.agent_model_manager import AgentModelManager
        mgr = AgentModelManager()
        mgr.initialize()
        assert mgr._no_model_mode is False

    def test_slot_assignments_wired_for_loaded_models(self):
        """Loaded models should be assigned to their declared roles in the slot manager."""
        from core.agent_model_manager import AgentModelManager
        import core.slot_manager as _sm_mod

        orig = _sm_mod._global_manager
        _sm_mod._global_manager = None
        try:
            mgr = AgentModelManager()
            mgr.initialize()
            slot_mgr = _sm_mod._global_manager
            if slot_mgr is None:
                pytest.skip("Global slot manager not set — skipping slot wiring check")
            loaded = set(mgr.get_loaded_models())
            for slot in slot_mgr._slots.values():
                if slot.assigned_model_id is not None:
                    assert slot.assigned_model_id in loaded, (
                        f"Slot '{slot.slot_name}' assigned to '{slot.assigned_model_id}' "
                        f"but that model is not in get_loaded_models()"
                    )
        finally:
            _sm_mod._global_manager = orig
