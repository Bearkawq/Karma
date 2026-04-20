"""Tests for agent internal generate path — model-first with deterministic fallback.

Covers:
- _try_model() returns None when no slot assignment exists
- _try_model() returns None when adapter not in model manager
- _try_model() returns None when adapter fails to load
- _try_model() returns text when adapter generates successfully
- SummarizerAgent uses model path (model_generated=True) when model returns text
- SummarizerAgent falls back deterministically when model returns None
- Live E2E: model_generated=True when Ollama is available
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
# _try_model() unit tests
# ---------------------------------------------------------------------------


class TestTryModelLogic:

    def _make_agent(self):
        from agents.summarizer_agent import SummarizerAgent
        return SummarizerAgent()

    def test_returns_none_when_no_slot_assignment(self):
        agent = self._make_agent()

        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = None

        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=MagicMock()):
            result = agent._try_model("test prompt")

        assert result is None

    def test_returns_none_when_assignment_has_no_model_id(self):
        agent = self._make_agent()

        mock_assignment = MagicMock()
        mock_assignment.assigned_model_id = None
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = mock_assignment

        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=MagicMock()):
            result = agent._try_model("test prompt")

        assert result is None

    def test_returns_none_when_adapter_not_in_manager(self):
        agent = self._make_agent()

        mock_assignment = MagicMock()
        mock_assignment.assigned_model_id = "some_model"
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = mock_assignment

        mock_mgr = MagicMock()
        mock_mgr._models = {}  # Adapter not registered

        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=mock_mgr):
            result = agent._try_model("test prompt")

        assert result is None

    def test_returns_none_when_adapter_load_fails(self):
        agent = self._make_agent()

        mock_assignment = MagicMock()
        mock_assignment.assigned_model_id = "some_model"
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = mock_assignment

        mock_adapter = MagicMock()
        mock_adapter.is_loaded = False
        mock_adapter.load.return_value = False

        mock_mgr = MagicMock()
        mock_mgr._models = {"some_model": mock_adapter}

        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=mock_mgr):
            result = agent._try_model("test prompt")

        assert result is None

    def test_returns_text_when_adapter_generates_successfully(self):
        agent = self._make_agent()

        mock_assignment = MagicMock()
        mock_assignment.assigned_model_id = "some_model"
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = mock_assignment

        mock_adapter = MagicMock()
        mock_adapter.is_loaded = True
        mock_adapter.generate.return_value = "Generated summary text."

        mock_mgr = MagicMock()
        mock_mgr._models = {"some_model": mock_adapter}

        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=mock_mgr):
            result = agent._try_model("test prompt")

        assert result == "Generated summary text."

    def test_returns_none_when_generate_raises(self):
        agent = self._make_agent()

        mock_assignment = MagicMock()
        mock_assignment.assigned_model_id = "some_model"
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = mock_assignment

        mock_adapter = MagicMock()
        mock_adapter.is_loaded = True
        mock_adapter.generate.side_effect = RuntimeError("connection reset")

        mock_mgr = MagicMock()
        mock_mgr._models = {"some_model": mock_adapter}

        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=mock_mgr):
            result = agent._try_model("test prompt")

        assert result is None


# ---------------------------------------------------------------------------
# SummarizerAgent model-first behavior
# ---------------------------------------------------------------------------


class TestSummarizerAgentModelPath:

    def _make_ctx(self, content="Test content for summarization."):
        from agents.base_agent import AgentContext
        return AgentContext(
            task="summarize",
            input_data={"content_type": "general", "content": content},
        )

    def test_model_generated_true_when_model_returns_text(self):
        from agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent()

        with patch.object(agent, "_try_model", return_value="A short summary."):
            result = agent.run(self._make_ctx())

        assert result.success is True
        assert result.output.get("model_generated") is True

    def test_model_generated_absent_when_model_returns_none(self):
        from agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent()

        with patch.object(agent, "_try_model", return_value=None):
            result = agent.run(self._make_ctx())

        assert result.success is True
        assert "model_generated" not in result.output

    def test_deterministic_fallback_still_succeeds_without_model(self):
        from agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent()

        with patch.object(agent, "_try_model", return_value=None):
            result = agent.run(self._make_ctx("hello world"))

        assert result.success is True
        assert "summary" in result.output

    def test_model_path_uses_model_role_name_for_slot_lookup(self):
        """_try_model is called with the right agent role for slot lookup."""
        from agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent()
        assert agent.role_name == "summarizer"

        captured = {}

        original_try_model = agent._try_model

        def spy(prompt, **kw):
            captured["called"] = True
            return None  # force deterministic

        agent._try_model = spy
        agent.run(self._make_ctx())

        assert captured.get("called") is True


# ---------------------------------------------------------------------------
# Live E2E — requires Ollama
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _OLLAMA_AVAILABLE, reason="Ollama not reachable at localhost:11434")
class TestAgentGenerateLive:

    def test_summarizer_produces_model_generated_true(self):
        """Full path: global manager → slot assignment → real adapter → model_generated."""
        import core.agent_model_manager as _amm_mod
        import core.slot_manager as _sm_mod

        orig_mgr = _amm_mod._global_manager
        orig_sm = _sm_mod._global_manager
        _amm_mod._global_manager = None
        _sm_mod._global_manager = None

        try:
            from core.agent_model_manager import get_agent_model_manager
            mgr = get_agent_model_manager()
            mgr.initialize()

            assert len(mgr.get_loaded_models()) > 0, "No models loaded despite Ollama being up"

            from agents.summarizer_agent import SummarizerAgent
            from agents.base_agent import AgentContext

            agent = SummarizerAgent()
            ctx = AgentContext(
                task="summarize",
                input_data={
                    "content_type": "general",
                    "content": "The sky is blue. Water is wet. Fire is hot. Ice is cold.",
                },
            )
            result = agent.run(ctx)

            assert result.success is True
            assert result.output.get("model_generated") is True, (
                f"Expected model_generated=True but got: {result.output}"
            )
        finally:
            _amm_mod._global_manager = orig_mgr
            _sm_mod._global_manager = orig_sm

    def test_summarizer_output_contains_summary_key(self):
        """Model path always returns a 'summary' key in output."""
        import core.agent_model_manager as _amm_mod
        import core.slot_manager as _sm_mod

        orig_mgr = _amm_mod._global_manager
        orig_sm = _sm_mod._global_manager
        _amm_mod._global_manager = None
        _sm_mod._global_manager = None

        try:
            from core.agent_model_manager import get_agent_model_manager
            mgr = get_agent_model_manager()
            mgr.initialize()

            if mgr._no_model_mode:
                pytest.skip("No models loaded despite Ollama being up")

            from agents.summarizer_agent import SummarizerAgent
            from agents.base_agent import AgentContext

            agent = SummarizerAgent()
            ctx = AgentContext(
                task="summarize",
                input_data={"content_type": "general", "content": "Short test."},
            )
            result = agent.run(ctx)

            assert "summary" in result.output
            assert isinstance(result.output["summary"], str)
            assert len(result.output["summary"]) > 0
        finally:
            _amm_mod._global_manager = orig_mgr
            _sm_mod._global_manager = orig_sm
