"""Write-path durability tests.

Covers:
- FactStore._save: permission denied, write failure, flag tracking, recovery
- EpisodicStore.save: permission denied, append failure, flag tracking, recovery
- ToolBuilder._save_registry: now atomic, exception-safe, corrupt-load recovery
- MemorySystem.facts_save_failed / episodic_save_failed properties
- Boot doctor surfaces save-failure warnings
- AgentLoop._save_state failure sets _state_save_failed in current_state
- Post-failure recovery: next successful save clears the failure flag
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_health(status: str = "healthy"):
    h = MagicMock()
    h.run_check.return_value = {"status": status, "issues_found": 0, "issues": []}
    return h


def _mem(tmp_path):
    from storage.memory import MemorySystem
    return MemorySystem(
        episodic_file=str(tmp_path / "ep.jsonl"),
        facts_file=str(tmp_path / "facts.json"),
        tasks_file=str(tmp_path / "tasks.json"),
    )


def _svc(memory, state=None, health=None, tool_builder=None):
    from agent.services.status_query_service import StatusQueryService
    return StatusQueryService(state or {}, memory, health or _make_health(),
                              tool_builder=tool_builder)


# ---------------------------------------------------------------------------
# FactStore write failures
# ---------------------------------------------------------------------------


class TestFactStoreSaveFailure:

    def test_flag_false_on_successful_save(self, tmp_path):
        from storage.facts import FactStore
        fs = FactStore(tmp_path / "facts.json")
        fs.save_fact("k", "v")
        assert not fs._last_save_failed

    def test_flag_set_on_write_failure(self, tmp_path):
        from storage.facts import FactStore
        fs = FactStore(tmp_path / "facts.json")
        with patch("storage.facts.save_json_file", side_effect=PermissionError("denied")):
            fs.save_fact("k", "v")
        assert fs._last_save_failed

    def test_flag_cleared_on_recovery(self, tmp_path):
        from storage.facts import FactStore
        fs = FactStore(tmp_path / "facts.json")
        with patch("storage.facts.save_json_file", side_effect=OSError("disk full")):
            fs.save_fact("first", "val")
        assert fs._last_save_failed
        # Next save succeeds — flag should clear
        fs.save_fact("second", "ok")
        assert not fs._last_save_failed

    def test_in_memory_data_preserved_after_write_failure(self, tmp_path):
        from storage.facts import FactStore
        fs = FactStore(tmp_path / "facts.json")
        with patch("storage.facts.save_json_file", side_effect=OSError("disk full")):
            fs.save_fact("important", "data")
        # In-memory data is still accessible
        assert fs.get_value("important") == "data"

    def test_permission_denied_sets_flag(self, tmp_path):
        from storage.facts import FactStore
        p = tmp_path / "subdir" / "facts.json"
        p.parent.mkdir()
        fs = FactStore(p)
        fs.save_fact("seed", "value")
        # Make the parent directory read-only so temp file creation fails
        p.parent.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            if os.getuid() != 0:  # root bypasses permission checks
                fs.save_fact("new_key", "new_val")
                assert fs._last_save_failed
        finally:
            p.parent.chmod(stat.S_IRWXU)

    def test_multiple_saves_after_failure_all_in_memory(self, tmp_path):
        from storage.facts import FactStore
        import storage.facts as _facts_mod
        fs = FactStore(tmp_path / "facts.json")
        call_count = 0
        original = _facts_mod.save_json_file

        def flaky(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OSError("flaky disk")
            return original(*a, **kw)

        with patch("storage.facts.save_json_file", side_effect=flaky):
            fs.save_fact("a", 1)
            fs.save_fact("b", 2)
        # 3rd call succeeds (call_count==3 ≥ 3, doesn't raise)
        fs.save_fact("c", 3)
        assert not fs._last_save_failed
        for k, v in [("a", 1), ("b", 2), ("c", 3)]:
            assert fs.get_value(k) == v


# ---------------------------------------------------------------------------
# EpisodicStore write failures
# ---------------------------------------------------------------------------


class TestEpisodicStoreSaveFailure:

    def test_flag_false_on_successful_append(self, tmp_path):
        from storage.episodic import EpisodicStore
        es = EpisodicStore(tmp_path / "ep.jsonl")
        es.save("event", {}, "success")
        assert not es._last_save_failed

    def test_flag_set_when_open_fails(self, tmp_path):
        from storage.episodic import EpisodicStore
        es = EpisodicStore(tmp_path / "ep.jsonl")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            es.save("event", {}, "success")
        assert es._last_save_failed

    def test_flag_cleared_on_recovery(self, tmp_path):
        from storage.episodic import EpisodicStore
        es = EpisodicStore(tmp_path / "ep.jsonl")
        with patch("builtins.open", side_effect=OSError("disk full")):
            es.save("bad", {})
        assert es._last_save_failed
        es.save("ok", {}, "success")
        assert not es._last_save_failed

    def test_in_memory_log_preserved_after_write_failure(self, tmp_path):
        from storage.episodic import EpisodicStore
        es = EpisodicStore(tmp_path / "ep.jsonl")
        with patch("builtins.open", side_effect=OSError("no space")):
            es.save("lost_event", {"key": "val"})
        assert any(e["event"] == "lost_event" for e in es.log)

    def test_new_events_appended_after_failure(self, tmp_path):
        from storage.episodic import EpisodicStore
        es = EpisodicStore(tmp_path / "ep.jsonl")
        fail_count = 0

        original_open = open
        def patched_open(path, *a, **kw):
            nonlocal fail_count
            if str(path).endswith(".jsonl") and "a" in str(a):
                fail_count += 1
                if fail_count == 1:
                    raise OSError("first write fails")
            return original_open(path, *a, **kw)

        with patch("builtins.open", side_effect=patched_open):
            es.save("drop", {})
        es.save("keep", {}, "success")
        assert any(e["event"] == "keep" for e in es.log)


# ---------------------------------------------------------------------------
# ToolBuilder — atomic save + corruption recovery
# ---------------------------------------------------------------------------


class TestToolBuilderSaveRegistry:

    def _make_tb(self, tmp_path):
        from tools.tool_builder import ToolBuilder
        from tools.tool_interface import ToolManager
        tb = ToolBuilder(tmp_path, ToolManager())
        return tb

    def test_save_registry_creates_file(self, tmp_path):
        tb = self._make_tb(tmp_path)
        tb.registry = [{"name": "my_tool", "lang": "bash"}]
        tb._save_registry()
        assert tb.registry_file.exists()
        data = json.loads(tb.registry_file.read_text())
        assert data[0]["name"] == "my_tool"

    def test_save_registry_is_atomic_no_partial(self, tmp_path):
        """Registry file should not be partially written on success."""
        tb = self._make_tb(tmp_path)
        tb.registry = [{"name": "tool_a"}, {"name": "tool_b"}]
        tb._save_registry()
        # No temp files left
        tmp_files = list(tb.registry_file.parent.glob("registry.json.*.tmp"))
        assert tmp_files == []

    def test_save_registry_survives_write_failure(self, tmp_path):
        """Write failure should be caught; no unhandled exception."""
        from storage import persistence
        tb = self._make_tb(tmp_path)
        tb.registry = [{"name": "tool_x"}]
        with patch.object(persistence, "atomic_write_text", side_effect=PermissionError("denied")):
            # Should not raise
            tb._save_registry()

    def test_corrupt_registry_loads_empty(self, tmp_path):
        tb = self._make_tb(tmp_path)
        tb.registry_file.parent.mkdir(parents=True, exist_ok=True)
        tb.registry_file.write_text("{CORRUPT REGISTRY}", encoding="utf-8")
        tb.load_registry()
        assert tb.registry == []

    def test_truncated_registry_loads_empty(self, tmp_path):
        tb = self._make_tb(tmp_path)
        tb.registry_file.parent.mkdir(parents=True, exist_ok=True)
        tb.registry_file.write_text('[{"name": "partial"', encoding="utf-8")
        tb.load_registry()
        assert tb.registry == []

    def test_save_then_reload_round_trip(self, tmp_path):
        tb = self._make_tb(tmp_path)
        tb.registry = [{"name": "persistent_tool", "lang": "python", "code": "print(1)"}]
        tb._save_registry()
        tb2 = self._make_tb(tmp_path)
        tb2.load_registry()
        assert len(tb2.registry) == 1
        assert tb2.registry[0]["name"] == "persistent_tool"

    def test_registry_file_not_corrupted_by_concurrent_overwrite(self, tmp_path):
        """Atomic write: old content preserved if new write fails mid-way."""
        from storage import persistence
        tb = self._make_tb(tmp_path)
        # Write good initial registry
        tb.registry = [{"name": "existing_tool"}]
        tb._save_registry()
        assert tb.registry_file.exists()
        original_content = tb.registry_file.read_text()

        # Simulate failure on next save
        with patch.object(persistence, "atomic_write_text", side_effect=OSError("disk full")):
            tb.registry = [{"name": "new_tool"}]
            tb._save_registry()

        # Original file untouched
        assert tb.registry_file.read_text() == original_content


# ---------------------------------------------------------------------------
# MemorySystem property exposure
# ---------------------------------------------------------------------------


class TestMemorySystemWriteFlags:

    def test_facts_save_failed_initially_false(self, tmp_path):
        mem = _mem(tmp_path)
        assert not mem.facts_save_failed

    def test_episodic_save_failed_initially_false(self, tmp_path):
        mem = _mem(tmp_path)
        assert not mem.episodic_save_failed

    def test_facts_save_failed_reflects_store_flag(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("storage.facts.save_json_file", side_effect=OSError("full")):
            mem.save_fact("k", "v")
        assert mem.facts_save_failed

    def test_episodic_save_failed_reflects_store_flag(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("builtins.open", side_effect=PermissionError("no write")):
            mem.save_episodic("event", {})
        assert mem.episodic_save_failed

    def test_facts_save_failed_clears_after_recovery(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("storage.facts.save_json_file", side_effect=OSError("full")):
            mem.save_fact("k", "v")
        assert mem.facts_save_failed
        mem.save_fact("k2", "v2")
        assert not mem.facts_save_failed


# ---------------------------------------------------------------------------
# Boot doctor surfaces write-failure warnings
# ---------------------------------------------------------------------------


class TestBootDoctorWriteFailures:

    def test_facts_save_failure_surfaces_warning(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("storage.facts.save_json_file", side_effect=OSError("disk full")):
            mem.save_fact("k", "v")
        svc = _svc(mem)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] in ("warning", "critical")
        assert any("facts" in w.lower() or "save" in w.lower() for w in summary["warnings"])

    def test_episodic_save_failure_surfaces_warning(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("builtins.open", side_effect=PermissionError("denied")):
            mem.save_episodic("event", {})
        svc = _svc(mem)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] in ("warning", "critical")
        assert any("episodic" in w.lower() or "append" in w.lower() for w in summary["warnings"])

    def test_state_save_failure_surfaces_warning(self, tmp_path):
        mem = _mem(tmp_path)
        state = {"_state_save_failed": "Permission denied: /data/state.json"}
        svc = _svc(mem, state=state)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] in ("warning", "critical")
        assert any("state" in w.lower() for w in summary["warnings"])

    def test_no_warnings_when_all_saves_succeed(self, tmp_path):
        mem = _mem(tmp_path)
        mem.save_fact("k", "v")
        mem.save_episodic("e", {})
        svc = _svc(mem)
        summary = svc.build_boot_doctor_summary()
        save_warnings = [w for w in summary["warnings"]
                         if "save" in w.lower() or "failed" in w.lower()]
        assert save_warnings == []

    def test_multiple_write_failures_all_shown(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("storage.facts.save_json_file", side_effect=OSError("full")):
            mem.save_fact("k", "v")
        with patch("builtins.open", side_effect=PermissionError("no write")):
            mem.save_episodic("event", {})
        state = {"_state_save_failed": "disk error"}
        svc = _svc(mem, state=state)
        summary = svc.build_boot_doctor_summary()
        # All three failure types should be reflected
        warn_text = " ".join(summary["warnings"]).lower()
        assert "facts" in warn_text or "save" in warn_text
        assert "episodic" in warn_text or "append" in warn_text
        assert "state" in warn_text

    def test_boot_doctor_format_shows_write_failure(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("storage.facts.save_json_file", side_effect=OSError("no space")):
            mem.save_fact("x", "y")
        svc = _svc(mem)
        summary = svc.build_boot_doctor_summary()
        text = svc.format_boot_doctor_summary(summary)
        assert "warn" in text.lower() or "save" in text.lower() or "[warn]" in text


# ---------------------------------------------------------------------------
# AgentLoop._save_state failure tracking
# ---------------------------------------------------------------------------


class TestAgentLoopSaveStateFailure:

    def _make_agent(self):
        from agent.agent_loop import AgentLoop, load_config
        cfg = load_config("config.json")
        agent = AgentLoop(cfg)
        agent.memory.facts.clear()
        return agent

    def test_save_state_failure_sets_flag(self):
        agent = self._make_agent()
        with patch.object(agent, "_atomic_write_json", side_effect=PermissionError("denied")):
            agent._save_state()
        assert "_state_save_failed" in agent.current_state

    def test_save_state_success_clears_flag(self):
        agent = self._make_agent()
        # Inject a pre-existing failure flag
        agent.current_state["_state_save_failed"] = "previous error"
        agent._save_state()
        assert "_state_save_failed" not in agent.current_state

    def test_save_state_failure_flag_not_persisted_to_disk(self, tmp_path):
        from agent.agent_loop import AgentLoop, load_config
        state_file = tmp_path / "state.json"
        cfg = load_config("config.json")
        cfg = dict(cfg)
        cfg["memory"] = dict(cfg.get("memory", {}))
        cfg["memory"]["state_file"] = str(state_file)
        agent = AgentLoop(cfg)
        agent.memory.facts.clear()

        # Inject failure flag manually
        agent.current_state["_state_save_failed"] = "write error"
        agent._save_state()

        # The flag should NOT be written to disk (it's also ephemeral)
        if state_file.exists():
            saved = json.loads(state_file.read_text())
            assert "_state_save_failed" not in saved

    def test_save_state_failure_visible_in_boot_doctor(self):
        agent = self._make_agent()
        with patch.object(agent, "_atomic_write_json", side_effect=OSError("no space")):
            agent._save_state()
        agent._status_query_svc._health = _make_health()
        summary = agent.build_boot_doctor_summary()
        assert any("state" in w.lower() for w in summary.get("warnings", []))


# ---------------------------------------------------------------------------
# Atomic write correctness (persistence layer)
# ---------------------------------------------------------------------------


class TestAtomicWriteEdgeCases:

    def test_no_partial_file_on_os_replace_failure(self, tmp_path):
        """If os.replace fails, temp file should be cleaned up."""
        from storage.persistence import atomic_write_text
        p = tmp_path / "target.json"
        with patch("os.replace", side_effect=OSError("replace failed")):
            try:
                atomic_write_text(p, '{"x": 1}')
            except OSError:
                pass
        # Target should not exist (write was atomic, replace failed)
        assert not p.exists()
        # No orphan tmp files
        assert list(tmp_path.glob("target.json.*.tmp")) == []

    def test_original_preserved_when_new_write_would_fail(self, tmp_path):
        from storage.persistence import atomic_write_text
        p = tmp_path / "data.json"
        p.write_text('{"old": true}', encoding="utf-8")
        with patch("os.replace", side_effect=OSError("cannot replace")):
            try:
                atomic_write_text(p, '{"new": true}')
            except OSError:
                pass
        # Original still intact
        assert json.loads(p.read_text()) == {"old": True}


# ---------------------------------------------------------------------------
# MemorySystem.tasks_save_failed
# ---------------------------------------------------------------------------


class TestTasksSaveFailure:

    def test_flag_false_initially(self, tmp_path):
        mem = _mem(tmp_path)
        assert not mem.tasks_save_failed

    def test_flag_set_on_write_failure(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("storage.memory.save_json_file", side_effect=OSError("disk full")):
            mem.save_task({"id": "t1", "status": "pending"})
        assert mem.tasks_save_failed

    def test_flag_cleared_on_recovery(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("storage.memory.save_json_file", side_effect=OSError("disk full")):
            mem.save_task({"id": "t1", "status": "pending"})
        assert mem.tasks_save_failed
        mem.save_task({"id": "t2", "status": "pending"})
        assert not mem.tasks_save_failed

    def test_in_memory_tasks_preserved_after_write_failure(self, tmp_path):
        mem = _mem(tmp_path)
        with patch("storage.memory.save_json_file", side_effect=OSError("no space")):
            mem.save_task({"id": "t1", "status": "pending"})
        assert mem.get_task("t1") is not None

    def test_tasks_save_failed_property_reflects_flag(self, tmp_path):
        mem = _mem(tmp_path)
        mem._last_tasks_save_failed = True
        assert mem.tasks_save_failed
        mem._last_tasks_save_failed = False
        assert not mem.tasks_save_failed


# ---------------------------------------------------------------------------
# ToolBuilder._last_save_failed
# ---------------------------------------------------------------------------


class TestToolBuilderSaveFailedFlag:

    def _builder(self, tmp_path):
        from tools.tool_builder import ToolBuilder
        from tools.tool_interface import ToolManager
        tm = ToolManager()
        return ToolBuilder(tmp_path, tm)

    def test_flag_false_initially(self, tmp_path):
        b = self._builder(tmp_path)
        assert not b._last_save_failed

    def test_flag_set_on_write_failure(self, tmp_path):
        b = self._builder(tmp_path)
        with patch("storage.persistence.atomic_write_text", side_effect=OSError("denied")):
            b._save_registry()
        assert b._last_save_failed

    def test_flag_cleared_on_recovery(self, tmp_path):
        b = self._builder(tmp_path)
        with patch("storage.persistence.atomic_write_text", side_effect=OSError("denied")):
            b._save_registry()
        assert b._last_save_failed
        b._save_registry()
        assert not b._last_save_failed

    def test_registry_unchanged_in_memory_after_failure(self, tmp_path):
        b = self._builder(tmp_path)
        b.registry = [{"name": "mytool", "lang": "bash", "path": "/tmp/x.sh"}]
        with patch("storage.persistence.atomic_write_text", side_effect=OSError("denied")):
            b._save_registry()
        assert b.registry[0]["name"] == "mytool"


# ---------------------------------------------------------------------------
# Boot doctor — all 5 normalized failure signals
# ---------------------------------------------------------------------------


class TestBootDoctorAllFailureSignals:

    def _make_mem(self, tmp_path):
        return _mem(tmp_path)

    def _make_builder(self, tmp_path):
        from tools.tool_builder import ToolBuilder
        from tools.tool_interface import ToolManager
        return ToolBuilder(tmp_path, ToolManager())

    def test_tasks_save_failure_surfaces_warning(self, tmp_path):
        mem = self._make_mem(tmp_path)
        mem._last_tasks_save_failed = True
        svc = _svc(mem, state={})
        summary = svc.build_boot_doctor_summary()
        assert any("task" in w.lower() for w in summary.get("warnings", []))

    def test_registry_save_failure_surfaces_warning(self, tmp_path):
        mem = self._make_mem(tmp_path)
        mem.facts_save_failed  # touch to init
        builder = self._make_builder(tmp_path)
        builder._last_save_failed = True
        svc = _svc(mem, state={}, tool_builder=builder)
        summary = svc.build_boot_doctor_summary()
        assert any("registry" in w.lower() or "tool" in w.lower()
                   for w in summary.get("warnings", []))

    def test_all_five_signals_in_one_summary(self, tmp_path):
        mem = self._make_mem(tmp_path)
        mem._facts._last_save_failed = True
        mem._episodic._last_save_failed = True
        mem._last_tasks_save_failed = True
        builder = self._make_builder(tmp_path)
        builder._last_save_failed = True
        state = {"_state_save_failed": "no space left on device"}
        svc = _svc(mem, state=state, tool_builder=builder)
        summary = svc.build_boot_doctor_summary()
        warnings = summary.get("warnings", [])
        assert any("fact" in w.lower() for w in warnings)
        assert any("episodic" in w.lower() for w in warnings)
        assert any("task" in w.lower() for w in warnings)
        assert any("registry" in w.lower() or "tool" in w.lower() for w in warnings)
        assert any("state" in w.lower() for w in warnings)

    def test_no_warnings_when_all_saves_succeed(self, tmp_path):
        mem = self._make_mem(tmp_path)
        builder = self._make_builder(tmp_path)
        svc = _svc(mem, state={}, tool_builder=builder)
        # All flags are false by default
        summary = svc.build_boot_doctor_summary()
        write_warnings = [w for w in summary.get("warnings", [])
                          if any(k in w.lower() for k in ("fact", "episodic", "task", "registry", "state file"))]
        assert write_warnings == []

    def test_no_tool_builder_does_not_raise(self, tmp_path):
        mem = self._make_mem(tmp_path)
        svc = _svc(mem, state={}, tool_builder=None)
        summary = svc.build_boot_doctor_summary()
        assert "status" in summary


# ---------------------------------------------------------------------------
# EpisodicStore — partial-line tolerance and recovery
# ---------------------------------------------------------------------------


class TestEpisodicPartialLineRecovery:

    def test_partial_last_line_skipped_on_load(self, tmp_path):
        from storage.episodic import EpisodicStore
        ep_file = tmp_path / "ep.jsonl"
        # Write two valid lines then a truncated third
        ep_file.write_text(
            '{"timestamp":"2026-01-01T00:00:00","event":"a","context":{},"outcome":null,"confidence":1.0}\n'
            '{"timestamp":"2026-01-01T00:00:01","event":"b","context":{},"outcome":null,"confidence":1.0}\n'
            '{"timestamp":"2026-01-01T00:00:02","event"',
            encoding="utf-8",
        )
        store = EpisodicStore(ep_file)
        assert len(store.log) == 2
        assert store.log[0]["event"] == "a"
        assert store.log[1]["event"] == "b"

    def test_all_partial_lines_returns_empty(self, tmp_path):
        from storage.episodic import EpisodicStore
        ep_file = tmp_path / "ep.jsonl"
        ep_file.write_text('{"timestamp":"2026-01-01T00:00:00","event"', encoding="utf-8")
        store = EpisodicStore(ep_file)
        assert store.log == []

    def test_new_appends_work_after_partial_load(self, tmp_path):
        from storage.episodic import EpisodicStore
        ep_file = tmp_path / "ep.jsonl"
        ep_file.write_text(
            '{"timestamp":"2026-01-01T00:00:00","event":"ok","context":{},"outcome":null,"confidence":1.0}\n'
            '{"truncated"',
            encoding="utf-8",
        )
        store = EpisodicStore(ep_file)
        assert len(store.log) == 1
        store.save("new_event")
        assert len(store.log) == 2
        assert not store._last_save_failed
        # Reload confirms the good line and new append survived
        store2 = EpisodicStore(ep_file)
        events = [e["event"] for e in store2.log]
        assert "ok" in events
        assert "new_event" in events

    def test_in_memory_log_survives_disk_failure(self, tmp_path):
        from storage.episodic import EpisodicStore
        store = EpisodicStore(tmp_path / "ep.jsonl")
        store.save("before_failure")
        with patch("builtins.open", side_effect=OSError("no space")):
            store.save("during_failure")
        assert len(store.log) == 2
        assert store._last_save_failed

    def test_flag_cleared_after_recovery_from_partial(self, tmp_path):
        from storage.episodic import EpisodicStore
        store = EpisodicStore(tmp_path / "ep.jsonl")
        with patch("builtins.open", side_effect=OSError("full")):
            store.save("fail")
        assert store._last_save_failed
        store.save("recover")
        assert not store._last_save_failed
