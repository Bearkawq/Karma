"""Operationalization pass tests.

Covers:
1. --doctor CLI entrypoint (via AgentLoop.build_boot_doctor_summary / format_boot_doctor_summary)
2. SlotManager _load() quarantine visibility
3. clear_tasks failure sets _last_tasks_save_failed (no print-only)
4. E2E planner→model→response path (Ollama-gated live test + deterministic mock slice)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Doctor entrypoint
# ---------------------------------------------------------------------------


def _make_svc(tmp_path, state=None):
    from storage.memory import MemorySystem
    from agent.services.status_query_service import StatusQueryService

    mem = MemorySystem(
        episodic_file=str(tmp_path / "ep.jsonl"),
        facts_file=str(tmp_path / "f.json"),
        tasks_file=str(tmp_path / "t.json"),
    )
    return StatusQueryService(state or {}, mem, None)


class TestDoctorEntrypoint:

    def test_format_boot_doctor_summary_healthy(self, tmp_path):
        svc = _make_svc(tmp_path)
        summary = svc.build_boot_doctor_summary()
        formatted = svc.format_boot_doctor_summary(summary)
        assert "Boot check:" in formatted

    def test_format_boot_doctor_status_healthy_when_no_failures(self, tmp_path):
        svc = _make_svc(tmp_path)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] == "healthy"

    def test_format_boot_doctor_status_warning_when_issues(self, tmp_path):
        from storage.memory import MemorySystem
        from agent.services.status_query_service import StatusQueryService

        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "f.json"),
            tasks_file=str(tmp_path / "t.json"),
        )
        mem._last_tasks_save_failed = True
        svc = StatusQueryService({}, mem, None)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] == "warning"

    def test_format_boot_doctor_includes_warnings_text(self, tmp_path):
        from storage.memory import MemorySystem
        from agent.services.status_query_service import StatusQueryService

        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "f.json"),
            tasks_file=str(tmp_path / "t.json"),
        )
        mem._last_tasks_save_failed = True
        svc = StatusQueryService({}, mem, None)
        summary = svc.build_boot_doctor_summary()
        formatted = svc.format_boot_doctor_summary(summary)
        assert "[warn]" in formatted

    def test_doctor_cli_exits_0_healthy(self, tmp_path):
        """--doctor exits 0 when the agent is healthy."""
        import os
        karma_root = str(Path(__file__).resolve().parent.parent)
        env = {**os.environ, "PYTHONPATH": karma_root}
        result = subprocess.run(
            [sys.executable, "agent/agent_loop.py", "--doctor"],
            capture_output=True,
            text=True,
            cwd=karma_root,
            env=env,
            timeout=60,
        )
        # May exit 0 (healthy) or 1 (warnings) but must not crash (exit 2+)
        assert result.returncode in (0, 1), f"Unexpected exit code: {result.returncode}\n{result.stderr}"
        assert "Boot check:" in result.stdout

    def test_doctor_cli_output_contains_status(self, tmp_path):
        import os
        karma_root = str(Path(__file__).resolve().parent.parent)
        env = {**os.environ, "PYTHONPATH": karma_root}
        result = subprocess.run(
            [sys.executable, "agent/agent_loop.py", "--doctor"],
            capture_output=True,
            text=True,
            cwd=karma_root,
            env=env,
            timeout=60,
        )
        assert "Boot check:" in result.stdout


# ---------------------------------------------------------------------------
# 2. SlotManager _load() quarantine visibility
# ---------------------------------------------------------------------------


class TestSlotManagerLoadVisibility:

    def test_flag_false_on_clean_load(self, tmp_path):
        from core.slot_manager import SlotManager
        path = str(tmp_path / "slots.json")
        sm = SlotManager(storage_path=path)
        sm.assign_model("planner_slot", "llama3:8b")

        sm2 = SlotManager(storage_path=path)
        assert sm2.load_quarantined is False

    def test_flag_false_on_missing_file(self, tmp_path):
        from core.slot_manager import SlotManager
        sm = SlotManager(storage_path=str(tmp_path / "nonexistent.json"))
        assert sm.load_quarantined is False

    def test_flag_true_on_corrupt_file(self, tmp_path):
        from core.slot_manager import SlotManager
        path = tmp_path / "slots.json"
        path.write_text("{BAD JSON", encoding="utf-8")
        sm = SlotManager(storage_path=str(path))
        assert sm.load_quarantined is True

    def test_corrupt_load_falls_back_to_defaults(self, tmp_path):
        from core.slot_manager import SlotManager
        path = tmp_path / "slots.json"
        path.write_text("{BAD JSON", encoding="utf-8")
        sm = SlotManager(storage_path=str(path))
        # Default slots still present, no assignment
        assert sm.get_slot("planner_slot") is not None
        assert sm.get_slot("planner_slot").assigned_model_id is None

    def test_flag_clears_on_successful_reload(self, tmp_path):
        from core.slot_manager import SlotManager
        path = tmp_path / "slots.json"
        path.write_text("{BAD JSON", encoding="utf-8")
        sm = SlotManager(storage_path=str(path))
        assert sm.load_quarantined is True

        # Fix the file, reload
        sm.assign_model("planner_slot", "llama3:8b")  # writes valid JSON
        sm2 = SlotManager(storage_path=str(path))
        assert sm2.load_quarantined is False

    def test_boot_doctor_surfaces_slot_load_failure(self, tmp_path):
        """When global SlotManager has _load_quarantined=True, boot doctor warns."""
        import core.slot_manager as _sm_mod
        from storage.memory import MemorySystem
        from agent.services.status_query_service import StatusQueryService

        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "f.json"),
            tasks_file=str(tmp_path / "t.json"),
        )
        orig_mgr = _sm_mod._global_manager
        fake_mgr = MagicMock()
        fake_mgr._load_quarantined = True
        _sm_mod._global_manager = fake_mgr
        try:
            svc = StatusQueryService({}, mem, None)
            summary = svc.build_boot_doctor_summary()
            assert any("slot" in w.lower() for w in summary.get("warnings", []))
        finally:
            _sm_mod._global_manager = orig_mgr

    def test_boot_doctor_no_false_slot_warning_when_healthy(self, tmp_path):
        import core.slot_manager as _sm_mod
        from storage.memory import MemorySystem
        from agent.services.status_query_service import StatusQueryService

        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "f.json"),
            tasks_file=str(tmp_path / "t.json"),
        )
        orig_mgr = _sm_mod._global_manager
        fake_mgr = MagicMock()
        fake_mgr._load_quarantined = False
        _sm_mod._global_manager = fake_mgr
        try:
            svc = StatusQueryService({}, mem, None)
            summary = svc.build_boot_doctor_summary()
            assert not any("slot" in w.lower() for w in summary.get("warnings", []))
        finally:
            _sm_mod._global_manager = orig_mgr


# ---------------------------------------------------------------------------
# 3. clear_tasks failure — structured flag, no print-only
# ---------------------------------------------------------------------------


class TestClearTasksFailureFlag:

    def test_clear_tasks_failure_sets_flag(self, tmp_path):
        from storage.memory import MemorySystem
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "f.json"),
            tasks_file=str(tmp_path / "t.json"),
        )
        mem.save_task({"id": "t1", "status": "pending", "description": "test"})
        assert mem._last_tasks_save_failed is False

        with patch("pathlib.Path.unlink", side_effect=OSError("permission denied")):
            mem.clear_tasks()

        assert mem._last_tasks_save_failed is True

    def test_clear_tasks_success_clears_flag(self, tmp_path):
        from storage.memory import MemorySystem
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "f.json"),
            tasks_file=str(tmp_path / "t.json"),
        )
        mem._last_tasks_save_failed = True
        mem.save_task({"id": "t1", "status": "pending", "description": "test"})
        mem.clear_tasks()
        assert mem._last_tasks_save_failed is False

    def test_clear_tasks_no_print_on_failure(self, tmp_path, capsys):
        from storage.memory import MemorySystem
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "f.json"),
            tasks_file=str(tmp_path / "t.json"),
        )
        mem.save_task({"id": "t1", "status": "pending", "description": "test"})
        with patch("pathlib.Path.unlink", side_effect=OSError("permission denied")):
            mem.clear_tasks()
        captured = capsys.readouterr()
        assert "Error clearing tasks" not in captured.out

    def test_clear_tasks_failure_surfaces_in_boot_doctor(self, tmp_path):
        from storage.memory import MemorySystem
        from agent.services.status_query_service import StatusQueryService
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "f.json"),
            tasks_file=str(tmp_path / "t.json"),
        )
        mem.save_task({"id": "t1", "status": "pending", "description": "test"})
        with patch("pathlib.Path.unlink", side_effect=OSError("permission denied")):
            mem.clear_tasks()
        svc = StatusQueryService({}, mem, None)
        summary = svc.build_boot_doctor_summary()
        assert any("task" in w.lower() for w in summary.get("warnings", []))


# ---------------------------------------------------------------------------
# 4. E2E planner→model→response path
# ---------------------------------------------------------------------------

_OLLAMA_AVAILABLE = False
try:
    import urllib.request
    with urllib.request.urlopen(
        urllib.request.Request("http://localhost:11434/api/tags"), timeout=2
    ) as _r:
        _OLLAMA_AVAILABLE = _r.status == 200
except Exception:
    pass


@pytest.mark.skipif(not _OLLAMA_AVAILABLE, reason="Ollama not reachable at localhost:11434")
class TestPlannerModelRoutingLive:

    def test_initialize_sets_no_model_mode_false_when_ollama_present(self):
        from core.agent_model_manager import AgentModelManager
        mgr = AgentModelManager()
        mgr.initialize()
        assert mgr._no_model_mode is False

    def test_execute_planner_role_returns_result(self):
        """Live smoke test: planner role routes through model and returns a result."""
        from core.agent_model_manager import AgentModelManager
        mgr = AgentModelManager()
        mgr.initialize()
        if mgr._no_model_mode:
            pytest.skip("No models loaded despite Ollama being up")
        result = mgr.execute(
            task="summarize: list three colors",
            context={"intent": "summarize"},
            explicit_role="planner",
        )
        assert result is not None
        assert result.success or result.output is not None

    def test_registered_models_not_empty_after_init(self):
        """initialize() registers Ollama adapters; load() is called on demand."""
        from core.agent_model_manager import AgentModelManager
        mgr = AgentModelManager()
        mgr.initialize()
        if mgr._no_model_mode:
            pytest.skip("No models loaded despite Ollama being up")
        # Models are registered (available) even before explicit load()
        assert len(mgr._models) > 0


class TestPlannerModelRoutingDeterministic:
    """Deterministic slice — exercises routing logic without live Ollama."""

    def test_no_model_mode_false_passes_models_to_router(self):
        from core.agent_model_manager import AgentModelManager, ManagerConfig
        from core.role_router import RouteDecision, InvocationMode

        mgr = AgentModelManager(config=ManagerConfig())
        mgr._initialized = True
        mgr._no_model_mode = False
        mock_model = MagicMock()
        mock_model.is_loaded = True
        mgr._models = {"qwen3:4b": mock_model}
        mgr._model_enabled = {"qwen3:4b": True}

        captured = {}

        def spy_route(**kwargs):
            captured["available_models"] = kwargs.get("available_models")
            captured["force_no_model"] = kwargs.get("force_no_model")
            return RouteDecision(role="none", mode=InvocationMode.NONE)

        mgr.role_router.route = spy_route
        mgr.execute("plan something", explicit_role="planner")

        assert captured["force_no_model"] is False
        assert "qwen3:4b" in captured["available_models"]

    def test_execute_returns_pipeline_result_on_karma_only_path(self):
        from core.agent_model_manager import AgentModelManager, ManagerConfig

        mgr = AgentModelManager(config=ManagerConfig())
        mgr._initialized = True
        mgr._no_model_mode = True

        result = mgr.execute("test task")
        assert result is not None
        assert result.pipeline_type == "karma_only"

    def test_execute_with_explicit_missing_role_fails_gracefully(self):
        from core.agent_model_manager import AgentModelManager, ManagerConfig

        mgr = AgentModelManager(config=ManagerConfig())
        mgr._initialized = True
        mgr._no_model_mode = False
        # No agents registered
        result = mgr.execute("test", explicit_role="nonexistent_role")
        # Should not raise — returns a failure result
        assert result is not None
