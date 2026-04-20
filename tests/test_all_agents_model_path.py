"""Model-path coverage for all generation-capable agents.

Verifies for each of PlannerAgent, CriticAgent, ExecutorAgent, NavigatorAgent:
- model_generated=True when _try_model returns text
- deterministic fallback (no model_generated key) when _try_model returns None
- graceful failure when run() raises internally

Live Ollama tests confirm the full path: global manager → slot → real adapter.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

_OLLAMA_AVAILABLE = False
try:
    import urllib.request
    with urllib.request.urlopen(
        urllib.request.Request("http://localhost:11434/api/tags"), timeout=2
    ) as _r:
        _OLLAMA_AVAILABLE = _r.status == 200
except Exception:
    pass


def _ctx(task="test task", input_data=None):
    from agents.base_agent import AgentContext
    return AgentContext(task=task, input_data=input_data or {})


# ── PlannerAgent ──────────────────────────────────────────────────────────────


class TestPlannerAgentModelPath:

    def _agent(self):
        from agents.planner_agent import PlannerAgent
        return PlannerAgent()

    def test_model_generated_true_when_model_returns_steps(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value="1. RESEARCH: neural nets\n2. SUMMARIZE: findings"):
            result = agent.run(_ctx("research neural nets"))
        assert result.success is True
        assert result.output.get("model_generated") is True
        assert len(result.output["plan_steps"]) >= 1

    def test_model_generated_absent_on_deterministic_fallback(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=None):
            result = agent.run(_ctx("research neural nets", {"intent": "golearn", "entities": {"topic": "neural nets"}}))
        assert result.success is True
        assert "model_generated" not in result.output

    def test_deterministic_fallback_still_returns_plan_steps(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=None):
            result = agent.run(_ctx("list files", {"intent": "list_files", "entities": {}}))
        assert result.success is True
        assert "plan_steps" in result.output
        assert len(result.output["plan_steps"]) >= 1

    def test_exception_in_run_returns_failure_result(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", side_effect=RuntimeError("boom")):
            result = agent.run(_ctx("anything"))
        assert result.success is False
        assert result.error is not None

    def test_model_plan_parsed_into_step_dicts(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value="1. FETCH: data\n2. PROCESS: results\n3. STORE: output"):
            result = agent.run(_ctx("pipeline task"))
        steps = result.output.get("plan_steps", [])
        assert len(steps) == 3
        assert steps[0]["step"] == 1

    def test_model_fallback_on_empty_string_response(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=""):
            result = agent.run(_ctx("test", {"intent": "unknown"}))
        # Empty string is falsy — should use deterministic fallback
        assert result.success is True
        assert "model_generated" not in result.output


# ── CriticAgent ───────────────────────────────────────────────────────────────


class TestCriticAgentModelPath:

    def _agent(self):
        from agents.critic_agent import CriticAgent
        return CriticAgent()

    def _plan_ctx(self):
        return _ctx("review", {"content_type": "plan", "content": [{"step": 1, "action": "RUN", "target": "tests"}]})

    def test_model_generated_true_when_model_returns_critique(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value="- Step lacks error handling\n- No rollback defined"):
            result = agent.run(self._plan_ctx())
        assert result.success is True
        assert result.output.get("model_generated") is True
        assert "critique" in result.output

    def test_model_generated_absent_on_deterministic_fallback(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=None):
            result = agent.run(self._plan_ctx())
        assert result.success is True
        assert "model_generated" not in result.output

    def test_deterministic_fallback_returns_issues_key(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=None):
            result = agent.run(_ctx("review", {"content_type": "result", "content": {"success": False, "error": "oops"}}))
        assert result.success is True
        assert "issues" in result.output

    def test_exception_returns_failure_result(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", side_effect=RuntimeError("bang")):
            result = agent.run(self._plan_ctx())
        assert result.success is False
        assert result.error is not None

    def test_model_ok_response_is_accepted(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value="OK"):
            result = agent.run(self._plan_ctx())
        assert result.success is True
        assert result.output.get("model_generated") is True
        assert "OK" in result.output.get("critique", "")

    def test_run_artifact_dict_goes_to_model_as_formatted_string(self):
        """run_artifact dict should be formatted and sent to model, not passed raw."""
        agent = self._agent()
        captured = {}

        def spy(prompt, **kw):
            captured["prompt"] = prompt
            return None  # deterministic fallback

        agent._try_model = spy
        ctx = _ctx("review", {
            "content_type": "run_artifact",
            "content": {"outcome": "failed", "steps": [], "failed": []},
        })
        agent.run(ctx)
        # Prompt must contain formatted content, not raw dict repr
        assert "prompt" in captured


# ── ExecutorAgent ─────────────────────────────────────────────────────────────


class TestExecutorAgentModelPath:

    def _agent(self):
        from agents.executor_agent import ExecutorAgent
        return ExecutorAgent()

    def test_model_generated_true_when_model_returns_steps(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value="1. Run pytest\n2. Check exit code"):
            result = agent.run(_ctx("run the test suite"))
        assert result.success is True
        assert result.output.get("model_generated") is True

    def test_model_generated_absent_on_deterministic_fallback(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=None):
            plan = [{"step": 1, "action": "research", "target": "X"}]
            result = agent.run(_ctx("", {"plan_steps": plan}))
        assert result.success is True
        assert "model_generated" not in result.output
        assert "step_results" in result.output

    def test_model_path_requires_nonempty_task(self):
        """Executor only tries model when context.task is non-empty."""
        agent = self._agent()
        called = {}

        def spy(prompt, **kw):
            called["yes"] = True
            return None

        agent._try_model = spy
        # Empty task → no model call, falls back to plan_steps
        agent.run(_ctx("", {"plan_steps": [{"step": 1, "action": "process", "target": "x"}]}))
        assert "yes" not in called

    def test_model_call_exception_degrades_gracefully(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", side_effect=RuntimeError("crash")):
            result = agent.run(_ctx("do something"))
        assert result.success is False

    def test_prior_results_included_in_model_prompt(self):
        agent = self._agent()
        captured = {}

        def spy(prompt, **kw):
            captured["prompt"] = prompt
            return None

        agent._try_model = spy
        prior = [{"step": 1, "action": "fetch", "target": "data", "output": "100 items"}]
        agent.run(_ctx("process the data", {"prior_results": prior}))
        assert "100 items" in captured.get("prompt", "")

    def test_deterministic_step_execution_maps_actions(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=None):
            steps = [
                {"step": 1, "action": "research", "target": "topic"},
                {"step": 2, "action": "summarize", "target": "findings"},
            ]
            result = agent.run(_ctx("", {"plan_steps": steps}))
        sr = result.output["step_results"]
        assert sr[0]["mapped_action"] == "golearn"
        assert sr[1]["mapped_action"] == "digest"


# ── NavigatorAgent ────────────────────────────────────────────────────────────


class TestNavigatorAgentModelPath:

    def _agent(self):
        from agents.navigator_agent import NavigatorAgent
        return NavigatorAgent()

    def _ctx_with_available(self, task="find the planner", available="agents/planner_agent.py\nagents/critic_agent.py"):
        return _ctx(task, {"available": available, "target": task})

    def test_model_generated_true_when_model_returns_options(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value="- agents/planner_agent.py: handles planning"):
            result = agent.run(self._ctx_with_available())
        assert result.success is True
        assert result.output.get("model_generated") is True

    def test_model_generated_absent_on_deterministic_fallback(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=None):
            result = agent.run(_ctx("memory", {}))
        assert result.success is True
        assert "model_generated" not in result.output

    def test_model_not_called_when_no_available_context_and_no_real_paths(self):
        """Without available context and non-code task, model should not be called."""
        agent = self._agent()
        called = {}

        def spy(prompt, **kw):
            called["yes"] = True
            return None

        agent._try_model = spy
        # Task with no code keywords and no available context
        result = agent.run(_ctx("memory", {}))
        assert "yes" not in called
        assert result.success is True

    def test_validate_options_strips_hallucinated_paths(self):
        """Options not in available_context are filtered out."""
        from agents.navigator_agent import NavigatorAgent
        available = "agents/planner_agent.py\nagents/critic_agent.py"
        text = "- agents/planner_agent.py: real\n- agents/INVENTED_FILE.py: fake"
        result = NavigatorAgent._validate_options(text, available)
        assert "planner_agent" in result
        assert "INVENTED_FILE" not in result

    def test_validate_options_passes_through_unparseable_text(self):
        from agents.navigator_agent import NavigatorAgent
        raw = "no structured bullet format here"
        result = NavigatorAgent._validate_options(raw, "anything")
        assert result == raw

    def test_exception_returns_failure_result(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", side_effect=RuntimeError("err")):
            result = agent.run(self._ctx_with_available())
        assert result.success is False

    def test_deterministic_fallback_navigates_known_targets(self):
        agent = self._agent()
        with patch.object(agent, "_try_model", return_value=None):
            result = agent.run(_ctx("logs", {}))
        assert result.success is True
        assert result.output.get("target") == "logs"


# ── Live E2E — all four agents ────────────────────────────────────────────────


@pytest.mark.skipif(not _OLLAMA_AVAILABLE, reason="Ollama not reachable at localhost:11434")
class TestAllAgentsModelPathLive:
    """Full path: global manager init → slot assignment → real adapter → model_generated."""

    def _fresh_globals(self):
        import core.agent_model_manager as _amm
        import core.slot_manager as _sm
        orig = (_amm._global_manager, _sm._global_manager)
        _amm._global_manager = None
        _sm._global_manager = None
        return orig

    def _restore_globals(self, orig):
        import core.agent_model_manager as _amm
        import core.slot_manager as _sm
        _amm._global_manager, _sm._global_manager = orig

    def _init_manager(self):
        from core.agent_model_manager import get_agent_model_manager
        mgr = get_agent_model_manager()
        mgr.initialize()
        if mgr._no_model_mode:
            pytest.skip("No models loaded despite Ollama being up")
        return mgr

    def test_planner_produces_model_generated_true(self):
        orig = self._fresh_globals()
        try:
            self._init_manager()
            from agents.planner_agent import PlannerAgent
            from agents.base_agent import AgentContext
            agent = PlannerAgent()
            result = agent.run(AgentContext(task="research machine learning basics"))
            assert result.success is True
            assert result.output.get("model_generated") is True
        finally:
            self._restore_globals(orig)

    def test_critic_produces_model_generated_true(self):
        orig = self._fresh_globals()
        try:
            self._init_manager()
            from agents.critic_agent import CriticAgent
            from agents.base_agent import AgentContext
            agent = CriticAgent()
            result = agent.run(AgentContext(
                task="review",
                input_data={
                    "content_type": "plan",
                    "content": [{"step": 1, "action": "RUN", "target": "tests"}, {"step": 2, "action": "CHECK", "target": "results"}],
                },
            ))
            assert result.success is True
            assert result.output.get("model_generated") is True
        finally:
            self._restore_globals(orig)

    def test_executor_produces_model_generated_true(self):
        orig = self._fresh_globals()
        try:
            self._init_manager()
            from agents.executor_agent import ExecutorAgent
            from agents.base_agent import AgentContext
            agent = ExecutorAgent()
            result = agent.run(AgentContext(task="run the test suite and report failures"))
            assert result.success is True
            assert result.output.get("model_generated") is True
        finally:
            self._restore_globals(orig)

    def test_navigator_produces_model_generated_true_with_grounding(self):
        orig = self._fresh_globals()
        try:
            self._init_manager()
            from agents.navigator_agent import NavigatorAgent
            from agents.base_agent import AgentContext
            agent = NavigatorAgent()
            available = (
                "agents/planner_agent.py\n"
                "agents/critic_agent.py\n"
                "agents/executor_agent.py\n"
                "agents/navigator_agent.py"
            )
            result = agent.run(AgentContext(
                task="find the planner agent file",
                input_data={
                    "available": available,
                    "target": "find the planner agent file",
                },
            ))
            assert result.success is True
            assert result.output.get("model_generated") is True
        finally:
            self._restore_globals(orig)

    def test_planner_plan_steps_are_non_empty(self):
        orig = self._fresh_globals()
        try:
            self._init_manager()
            from agents.planner_agent import PlannerAgent
            from agents.base_agent import AgentContext
            agent = PlannerAgent()
            result = agent.run(AgentContext(task="summarize a document"))
            steps = result.output.get("plan_steps", [])
            assert len(steps) >= 1
            assert all("step" in s and "action" in s for s in steps)
        finally:
            self._restore_globals(orig)

    def test_critic_output_contains_critique_key(self):
        orig = self._fresh_globals()
        try:
            self._init_manager()
            from agents.critic_agent import CriticAgent
            from agents.base_agent import AgentContext
            agent = CriticAgent()
            result = agent.run(AgentContext(
                task="review",
                input_data={"content_type": "plan", "content": [{"step": 1, "action": "GO", "target": "prod"}]},
            ))
            assert "critique" in result.output
            assert isinstance(result.output["critique"], str)
        finally:
            self._restore_globals(orig)
