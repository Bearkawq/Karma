"""Chaos / corruption recovery integration tests.

Proves that Karma's persistence layer handles every bad-file scenario
gracefully and that the boot doctor surfaces quarantine events truthfully.

Scenarios covered:
  - Malformed JSON state file → quarantined, clean state returned
  - Truncated JSON state file → quarantined, clean state returned
  - Missing state file → clean state created (no quarantine)
  - Malformed JSON facts file → quarantined, empty facts returned
  - Truncated JSON facts file → quarantined, empty facts returned
  - Missing facts file → empty facts (no quarantine)
  - Partially-corrupt JSONL episodic file → valid lines preserved, bad skipped
  - Malformed tasks file → empty tasks dict returned
  - Write failure safety (atomic write uses temp + rename)
  - Boot doctor after state quarantine → reports warning
  - Boot doctor after facts quarantine → reports warning
  - Boot doctor after both → escalates to warning status
  - Quarantine does not overwrite existing .bak files (collision handling)
  - Startup warnings not persisted to disk (ephemeral)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: str | Path, content: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def _make_health(status: str = "healthy"):
    h = MagicMock()
    h.run_check.return_value = {"status": status, "issues_found": 0, "issues": []}
    return h


class _TempDir:
    """Context manager giving a temp directory cleaned up on exit."""
    def __enter__(self):
        self._d = tempfile.mkdtemp()
        return self._d

    def __exit__(self, *_):
        import shutil
        shutil.rmtree(self._d, ignore_errors=True)


# ---------------------------------------------------------------------------
# persistence.load_json_file — the base layer
# ---------------------------------------------------------------------------


class TestLoadJsonFile:

    def test_missing_file_returns_default(self, tmp_path):
        from storage.persistence import load_json_file
        result = load_json_file(tmp_path / "ghost.json", {"x": 1})
        assert result == {"x": 1}

    def test_valid_file_loads_correctly(self, tmp_path):
        from storage.persistence import load_json_file
        p = tmp_path / "ok.json"
        p.write_text('{"a": 42}', encoding="utf-8")
        assert load_json_file(p, {}) == {"a": 42}

    def test_malformed_json_quarantined_returns_default(self, tmp_path):
        from storage.persistence import load_json_file
        p = tmp_path / "bad.json"
        p.write_text("{not valid json,,}", encoding="utf-8")
        result = load_json_file(p, {"fallback": True})
        assert result == {"fallback": True}
        # Original file must not exist anymore
        assert not p.exists(), "corrupt file should have been quarantined"

    def test_truncated_json_quarantined(self, tmp_path):
        from storage.persistence import load_json_file
        p = tmp_path / "trunc.json"
        p.write_text('{"key": "val', encoding="utf-8")  # truncated
        load_json_file(p, {})
        assert not p.exists()

    def test_quarantine_file_gets_bak_suffix(self, tmp_path):
        from storage.persistence import load_json_file
        p = tmp_path / "corrupt.json"
        p.write_text("!!!bad!!!", encoding="utf-8")
        load_json_file(p, {})
        bak_files = list(tmp_path.glob("*.bak"))
        assert len(bak_files) == 1

    def test_empty_file_quarantined(self, tmp_path):
        from storage.persistence import load_json_file
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        result = load_json_file(p, [])
        assert result == []
        assert not p.exists()


# ---------------------------------------------------------------------------
# storage.persistence.quarantine_file — collision handling
# ---------------------------------------------------------------------------


class TestQuarantineFile:

    def test_quarantine_moves_file(self, tmp_path):
        from storage.persistence import quarantine_file
        p = tmp_path / "data.json"
        p.write_text("{}", encoding="utf-8")
        bak = quarantine_file(p)
        assert bak is not None
        assert not p.exists()
        assert bak.exists()

    def test_quarantine_missing_file_returns_none(self, tmp_path):
        from storage.persistence import quarantine_file
        result = quarantine_file(tmp_path / "nonexistent.json")
        assert result is None

    def test_quarantine_collision_increments_suffix(self, tmp_path):
        from storage.persistence import quarantine_file
        p = tmp_path / "data.json"
        # Create first bak manually
        first_bak = tmp_path / "data.json.corrupt.bak"
        first_bak.write_text("{}", encoding="utf-8")
        p.write_text("{}", encoding="utf-8")
        bak2 = quarantine_file(p)
        # Should have gotten a .1.bak suffix
        assert bak2 is not None
        assert "1" in bak2.name or bak2 != first_bak


# ---------------------------------------------------------------------------
# storage.persistence.atomic_write_text — crash-safe writes
# ---------------------------------------------------------------------------


class TestAtomicWrite:

    def test_atomic_write_creates_file(self, tmp_path):
        from storage.persistence import atomic_write_text
        p = tmp_path / "out.json"
        atomic_write_text(p, '{"ok": true}')
        assert p.exists()
        assert json.loads(p.read_text()) == {"ok": True}

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        from storage.persistence import atomic_write_text
        p = tmp_path / "deep" / "nested" / "file.json"
        atomic_write_text(p, "{}")
        assert p.exists()

    def test_atomic_write_no_partial_file_on_success(self, tmp_path):
        from storage.persistence import atomic_write_text
        p = tmp_path / "target.json"
        atomic_write_text(p, '{"val": 99}')
        # No .tmp files should be left
        assert list(tmp_path.glob("*.tmp")) == []

    def test_atomic_write_overwrites_existing(self, tmp_path):
        from storage.persistence import atomic_write_text
        p = tmp_path / "overwrite.json"
        p.write_text('{"old": 1}', encoding="utf-8")
        atomic_write_text(p, '{"new": 2}')
        assert json.loads(p.read_text()) == {"new": 2}


# ---------------------------------------------------------------------------
# FactStore — load/quarantine tracking
# ---------------------------------------------------------------------------


class TestFactStore:

    def test_missing_file_loads_empty(self, tmp_path):
        from storage.facts import FactStore
        fs = FactStore(tmp_path / "facts.json")
        assert fs.facts == {}
        assert not fs._load_quarantined

    def test_valid_file_loads_correctly(self, tmp_path):
        from storage.facts import FactStore
        p = tmp_path / "facts.json"
        p.write_text(json.dumps({"k": {"value": "v", "source": "test"}}), encoding="utf-8")
        fs = FactStore(p)
        assert "k" in fs.facts
        assert not fs._load_quarantined

    def test_malformed_file_quarantined(self, tmp_path):
        from storage.facts import FactStore
        p = tmp_path / "facts.json"
        p.write_text("{broken json", encoding="utf-8")
        fs = FactStore(p)
        assert fs.facts == {}
        assert fs._load_quarantined
        assert not p.exists()

    def test_truncated_file_quarantined(self, tmp_path):
        from storage.facts import FactStore
        p = tmp_path / "facts.json"
        p.write_text('{"key": "val', encoding="utf-8")
        fs = FactStore(p)
        assert fs._load_quarantined
        assert fs.facts == {}

    def test_reload_clears_quarantine_flag(self, tmp_path):
        from storage.facts import FactStore
        p = tmp_path / "facts.json"
        p.write_text("{broken", encoding="utf-8")
        fs = FactStore(p)
        assert fs._load_quarantined
        # Write a good file and reload
        p.write_text("{}", encoding="utf-8")
        fs.load()
        assert not fs._load_quarantined

    def test_save_fact_persists_to_disk(self, tmp_path):
        from storage.facts import FactStore
        p = tmp_path / "facts.json"
        fs = FactStore(p)
        fs.save_fact("hello", "world", source="test")
        # Reload from disk
        fs2 = FactStore(p)
        assert fs2.get_value("hello") == "world"

    def test_facts_empty_after_quarantine_does_not_block_writes(self, tmp_path):
        from storage.facts import FactStore
        p = tmp_path / "facts.json"
        p.write_text("GARBAGE", encoding="utf-8")
        fs = FactStore(p)
        assert fs._load_quarantined
        # Should still be able to write new facts
        fs.save_fact("new_key", "new_value")
        assert fs.get_value("new_key") == "new_value"
        assert p.exists()


# ---------------------------------------------------------------------------
# MemorySystem — facts_quarantined property + tasks fallback
# ---------------------------------------------------------------------------


class TestMemorySystem:

    def test_facts_quarantined_false_when_clean(self, tmp_path):
        from storage.memory import MemorySystem
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "facts.json"),
            tasks_file=str(tmp_path / "tasks.json"),
        )
        assert not mem.facts_quarantined

    def test_facts_quarantined_true_when_corrupt(self, tmp_path):
        from storage.memory import MemorySystem
        facts_path = tmp_path / "facts.json"
        facts_path.write_text("{CORRUPT}", encoding="utf-8")
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(facts_path),
            tasks_file=str(tmp_path / "tasks.json"),
        )
        assert mem.facts_quarantined
        assert mem.facts == {}

    def test_corrupt_tasks_file_returns_empty_tasks(self, tmp_path):
        from storage.memory import MemorySystem
        tasks_path = tmp_path / "tasks.json"
        tasks_path.write_text("NOT JSON", encoding="utf-8")
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "facts.json"),
            tasks_file=str(tasks_path),
        )
        assert mem.tasks == {}

    def test_missing_all_files_initialises_cleanly(self, tmp_path):
        from storage.memory import MemorySystem
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "facts.json"),
            tasks_file=str(tmp_path / "tasks.json"),
        )
        assert mem.facts == {}
        assert mem.tasks == {}
        assert not mem.facts_quarantined


# ---------------------------------------------------------------------------
# MemorySystem — tasks_quarantined flag
# ---------------------------------------------------------------------------


class TestTasksQuarantine:

    def _mem(self, tmp_path, tasks_content=None):
        from storage.memory import MemorySystem
        tasks_path = tmp_path / "tasks.json"
        if tasks_content is not None:
            tasks_path.write_text(tasks_content, encoding="utf-8")
        return MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "facts.json"),
            tasks_file=str(tasks_path),
        )

    def test_flag_false_when_tasks_file_missing(self, tmp_path):
        mem = self._mem(tmp_path)
        assert not mem.tasks_quarantined

    def test_flag_false_when_tasks_file_valid(self, tmp_path):
        import json
        mem = self._mem(tmp_path, json.dumps({"t1": {"id": "t1", "status": "pending"}}))
        assert not mem.tasks_quarantined
        assert mem.tasks["t1"]["status"] == "pending"

    def test_flag_true_when_tasks_file_corrupt(self, tmp_path):
        mem = self._mem(tmp_path, "NOT JSON {{{")
        assert mem.tasks_quarantined
        assert mem.tasks == {}

    def test_flag_true_when_tasks_file_truncated(self, tmp_path):
        mem = self._mem(tmp_path, '{"t1": {"id": "t1"')
        assert mem.tasks_quarantined
        assert mem.tasks == {}

    def test_corrupt_file_is_quarantined_on_disk(self, tmp_path):
        tasks_path = tmp_path / "tasks.json"
        tasks_path.write_text("NOT JSON", encoding="utf-8")
        self._mem(tmp_path)
        # Original tasks.json should be gone (renamed to .bak)
        assert not tasks_path.exists()
        baks = list(tmp_path.glob("tasks.json.*.bak"))
        assert baks, "corrupt tasks file should have been quarantined to a .bak"

    def test_flag_clears_on_reload_with_valid_file(self, tmp_path):
        import json
        from storage.memory import MemorySystem
        tasks_path = tmp_path / "tasks.json"
        tasks_path.write_text("BAD", encoding="utf-8")
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "facts.json"),
            tasks_file=str(tasks_path),
        )
        assert mem.tasks_quarantined
        # Write a valid file and reload
        tasks_path.write_text(json.dumps({}), encoding="utf-8")
        mem.load_tasks()
        assert not mem.tasks_quarantined

    def test_safe_fallback_no_crash(self, tmp_path):
        """Corrupt tasks file must not raise — system still boots."""
        mem = self._mem(tmp_path, "{GARBAGE}")
        # System is usable after corrupt tasks load
        mem.save_task({"id": "new_task", "status": "pending"})
        assert mem.get_task("new_task") is not None

    def test_tasks_quarantined_property_exposed(self, tmp_path):
        mem = self._mem(tmp_path, "bad")
        assert hasattr(mem, "tasks_quarantined")
        assert mem.tasks_quarantined is True


class TestTasksQuarantineBootDoctor:

    def _make_mem(self, tmp_path, tasks_content=None):
        from storage.memory import MemorySystem
        tasks_path = tmp_path / "tasks.json"
        if tasks_content is not None:
            tasks_path.write_text(tasks_content, encoding="utf-8")
        return MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "facts.json"),
            tasks_file=str(tasks_path),
        )

    def _make_health(self):
        from unittest.mock import MagicMock
        h = MagicMock()
        h.run_check.return_value = {"status": "healthy", "issues_found": 0, "issues": []}
        return h

    def _svc(self, mem, startup_warnings=None):
        from agent.services.status_query_service import StatusQueryService
        state = {}
        if startup_warnings:
            state["_startup_warnings"] = startup_warnings
        return StatusQueryService(state, mem, self._make_health())

    def test_tasks_quarantine_warning_in_boot_doctor(self, tmp_path):
        mem = self._make_mem(tmp_path, "CORRUPT")
        startup_warnings = []
        if mem.tasks_quarantined:
            startup_warnings.append(
                "Tasks file was corrupted and quarantined at startup — all pending tasks lost."
            )
        svc = self._svc(mem, startup_warnings)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] in ("warning", "critical")
        assert any("task" in w.lower() for w in summary.get("warnings", []))

    def test_clean_tasks_no_quarantine_warning(self, tmp_path):
        import json
        mem = self._make_mem(tmp_path, json.dumps({}))
        svc = self._svc(mem)
        summary = svc.build_boot_doctor_summary()
        task_quarantine_warnings = [
            w for w in summary.get("warnings", [])
            if "task" in w.lower() and "quarantine" in w.lower()
        ]
        assert task_quarantine_warnings == []

    def test_facts_and_tasks_quarantine_both_shown(self, tmp_path):
        from storage.memory import MemorySystem
        facts_path = tmp_path / "facts.json"
        tasks_path = tmp_path / "tasks.json"
        facts_path.write_text("BAD FACTS", encoding="utf-8")
        tasks_path.write_text("BAD TASKS", encoding="utf-8")
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(facts_path),
            tasks_file=str(tasks_path),
        )
        startup_warnings = []
        if mem.facts_quarantined:
            startup_warnings.append(
                "Facts file was corrupted and quarantined at startup — memory is empty. All stored facts lost."
            )
        if mem.tasks_quarantined:
            startup_warnings.append(
                "Tasks file was corrupted and quarantined at startup — all pending tasks lost."
            )
        svc = self._svc(mem, startup_warnings)
        summary = svc.build_boot_doctor_summary()
        warn_text = " ".join(summary.get("warnings", [])).lower()
        assert "facts" in warn_text or "fact" in warn_text
        assert "task" in warn_text


# ---------------------------------------------------------------------------
# EpisodicStore — partial / corrupt JSONL tolerance
# ---------------------------------------------------------------------------


class TestEpisodicStore:

    def test_missing_file_loads_empty(self, tmp_path):
        from storage.episodic import EpisodicStore
        es = EpisodicStore(tmp_path / "ep.jsonl")
        assert es.log == []

    def test_valid_jsonl_loads_all_lines(self, tmp_path):
        from storage.episodic import EpisodicStore
        p = tmp_path / "ep.jsonl"
        p.write_text(
            '{"event":"a"}\n{"event":"b"}\n',
            encoding="utf-8",
        )
        es = EpisodicStore(p)
        assert len(es.log) == 2

    def test_corrupt_line_skipped(self, tmp_path):
        from storage.episodic import EpisodicStore
        p = tmp_path / "ep.jsonl"
        p.write_text(
            '{"event":"ok1"}\n{CORRUPT\n{"event":"ok2"}\n',
            encoding="utf-8",
        )
        es = EpisodicStore(p)
        assert len(es.log) == 2
        events = {e["event"] for e in es.log}
        assert events == {"ok1", "ok2"}

    def test_all_corrupt_lines_returns_empty(self, tmp_path):
        from storage.episodic import EpisodicStore
        p = tmp_path / "ep.jsonl"
        p.write_text("JUNK\nNOT JSON\n!!!\n", encoding="utf-8")
        es = EpisodicStore(p)
        assert es.log == []

    def test_truncated_last_line_skipped(self, tmp_path):
        from storage.episodic import EpisodicStore
        p = tmp_path / "ep.jsonl"
        p.write_text('{"event":"good"}\n{"event":"tru', encoding="utf-8")
        es = EpisodicStore(p)
        assert len(es.log) == 1
        assert es.log[0]["event"] == "good"

    def test_new_events_append_after_corrupt_load(self, tmp_path):
        from storage.episodic import EpisodicStore
        p = tmp_path / "ep.jsonl"
        p.write_text('{"event":"ok"}\n{CORRUPT\n', encoding="utf-8")
        es = EpisodicStore(p)
        es.save("new_event", {}, "success")
        assert any(e["event"] == "new_event" for e in es.log)


# ---------------------------------------------------------------------------
# AgentLoop._load_state — state file corruption paths
# ---------------------------------------------------------------------------


class TestAgentLoopStateRecovery:
    """Test _load_state and _startup_warnings in isolation via minimal agent construction."""

    def _make_agent(self):
        from agent.agent_loop import AgentLoop, load_config
        cfg = load_config("config.json")
        return AgentLoop(cfg)

    def test_malformed_state_file_returns_clean_state(self, tmp_path):
        from agent.agent_loop import AgentLoop, load_config
        state_file = tmp_path / "agent_state.json"
        state_file.write_text("{CORRUPT STATE FILE}", encoding="utf-8")
        cfg = load_config("config.json")
        cfg = dict(cfg)
        cfg["memory"] = dict(cfg.get("memory", {}))
        cfg["memory"]["state_file"] = str(state_file)
        agent = AgentLoop(cfg)
        agent.memory.facts.clear()
        # State should be clean initial state (no prior task_history etc.)
        state = agent.current_state
        assert isinstance(state, dict)
        assert "execution_log" in state
        assert isinstance(state.get("task_history", []), list)

    def test_malformed_state_file_sets_startup_warning(self, tmp_path):
        from agent.agent_loop import AgentLoop, load_config
        state_file = tmp_path / "agent_state.json"
        state_file.write_text("{BAD JSON", encoding="utf-8")
        cfg = load_config("config.json")
        cfg = dict(cfg)
        cfg["memory"] = dict(cfg.get("memory", {}))
        cfg["memory"]["state_file"] = str(state_file)
        agent = AgentLoop(cfg)
        agent.memory.facts.clear()
        warnings = agent.current_state.get("_startup_warnings", [])
        assert len(warnings) >= 1
        assert any("state" in w.lower() or "quarantine" in w.lower() for w in warnings)

    def test_malformed_state_quarantined_on_disk(self, tmp_path):
        from agent.agent_loop import AgentLoop, load_config
        state_file = tmp_path / "agent_state.json"
        state_file.write_text("GARBAGE DATA", encoding="utf-8")
        cfg = load_config("config.json")
        cfg = dict(cfg)
        cfg["memory"] = dict(cfg.get("memory", {}))
        cfg["memory"]["state_file"] = str(state_file)
        AgentLoop(cfg)
        assert not state_file.exists(), "corrupt state file should be quarantined"
        bak_files = list(tmp_path.glob("*.bak"))
        assert len(bak_files) >= 1

    def test_missing_state_file_no_warning(self, tmp_path):
        from agent.agent_loop import AgentLoop, load_config
        state_file = tmp_path / "nonexistent_state.json"
        cfg = load_config("config.json")
        cfg = dict(cfg)
        cfg["memory"] = dict(cfg.get("memory", {}))
        cfg["memory"]["state_file"] = str(state_file)
        agent = AgentLoop(cfg)
        agent.memory.facts.clear()
        warnings = agent.current_state.get("_startup_warnings", [])
        state_warnings = [w for w in warnings if "state" in w.lower() and "quarantine" in w.lower()]
        assert len(state_warnings) == 0

    def test_startup_warnings_not_persisted_to_disk(self, tmp_path):
        from agent.agent_loop import AgentLoop, load_config
        state_file = tmp_path / "state.json"
        state_file.write_text("{CORRUPT}", encoding="utf-8")
        cfg = load_config("config.json")
        cfg = dict(cfg)
        cfg["memory"] = dict(cfg.get("memory", {}))
        cfg["memory"]["state_file"] = str(state_file)
        agent = AgentLoop(cfg)
        agent.memory.facts.clear()
        assert "_startup_warnings" in agent.current_state, "warnings should be in live state"
        agent._save_state()
        # Read what was saved
        saved = json.loads(state_file.read_text(encoding="utf-8"))
        assert "_startup_warnings" not in saved, "warnings must not be persisted to disk"


# ---------------------------------------------------------------------------
# Boot doctor after corruption
# ---------------------------------------------------------------------------


class TestBootDoctorAfterCorruption:

    def _make_svc(self, state: dict, memory=None, health=None):
        from agent.services.status_query_service import StatusQueryService
        if memory is None:
            memory = MagicMock()
            memory.facts = {}
            memory.get_fact_value.return_value = None
            memory.get_fact_value.side_effect = lambda k, d=None: None
            memory.facts_save_failed = False
            memory.episodic_save_failed = False
            memory.tasks_save_failed = False
        if health is None:
            health = _make_health("healthy")
        return StatusQueryService(state, memory, health)

    def test_state_quarantine_warning_in_boot_doctor(self):
        state = {
            "_startup_warnings": [
                "Agent state file was corrupted and quarantined at startup — prior task history lost."
            ]
        }
        svc = self._make_svc(state)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] in ("warning", "critical")
        all_warnings = summary.get("warnings", [])
        assert any("quarantine" in w.lower() or "state" in w.lower() for w in all_warnings)

    def test_facts_quarantine_warning_in_boot_doctor(self):
        state = {
            "_startup_warnings": [
                "Facts file was corrupted and quarantined at startup — memory is empty."
            ]
        }
        svc = self._make_svc(state)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] in ("warning", "critical")
        all_warnings = summary.get("warnings", [])
        assert any("facts" in w.lower() or "quarantine" in w.lower() for w in all_warnings)

    def test_both_quarantines_both_warnings(self):
        state = {
            "_startup_warnings": [
                "Agent state file was corrupted and quarantined at startup — prior task history lost.",
                "Facts file was corrupted and quarantined at startup — memory is empty.",
            ]
        }
        svc = self._make_svc(state)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] in ("warning", "critical")
        all_warnings = summary.get("warnings", [])
        assert len(all_warnings) >= 2

    def test_boot_doctor_format_shows_quarantine_text(self):
        state = {
            "_startup_warnings": [
                "Agent state file was corrupted and quarantined at startup — prior task history lost."
            ]
        }
        svc = self._make_svc(state)
        summary = svc.build_boot_doctor_summary()
        text = svc.format_boot_doctor_summary(summary)
        assert "quarantine" in text.lower() or "state" in text.lower() or "warn" in text.lower()

    def test_clean_start_no_startup_warnings(self):
        state = {}  # No _startup_warnings key
        svc = self._make_svc(state)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] == "healthy"

    def test_boot_doctor_healthy_when_warnings_absent(self):
        state = {"_startup_warnings": []}
        svc = self._make_svc(state)
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] == "healthy"

    def test_boot_doctor_no_recommend_recovery_after_state_quarantine_only(self):
        state = {
            "_startup_warnings": [
                "Agent state file was corrupted and quarantined at startup."
            ]
        }
        svc = self._make_svc(state)
        summary = svc.build_boot_doctor_summary()
        # State quarantine alone doesn't mean there's a failed task to recover
        assert summary["recommend_recovery"] is False

    def test_boot_doctor_recommend_recovery_when_failed_last_run_after_quarantine(self, tmp_path):
        from storage.memory import MemorySystem
        from agent.services.run_history_service import RunHistoryService
        from agent.services.status_query_service import StatusQueryService

        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(tmp_path / "facts.json"),
            tasks_file=str(tmp_path / "tasks.json"),
        )
        svc_rh = RunHistoryService(mem)
        svc_rh.persist_run_digest({
            "task": "deploy", "outcome": "failed",
            "steps": [{"step": 1, "status": "failed", "action": "run_shell", "target": "deploy.sh", "error": "timeout"}],
            "failed": [{"step": 1, "status": "failed", "action": "run_shell", "target": "deploy.sh", "error": "timeout"}],
            "outputs": [], "recovery": None, "run_kind": "primary",
        }, "")

        state = {
            "_startup_warnings": [
                "Facts file was corrupted and quarantined at startup — memory is empty."
            ]
        }
        query_svc = StatusQueryService(state, mem, _make_health("healthy"))
        summary = query_svc.build_boot_doctor_summary()
        assert summary["recommend_recovery"] is True
        assert summary["status"] in ("warning", "critical")


# ---------------------------------------------------------------------------
# Full round-trip: corrupt, quarantine, recover, write, reload
# ---------------------------------------------------------------------------


class TestChaosRoundTrip:
    """Write corrupt files, verify clean boot, write good data, verify persistence."""

    def test_facts_corrupt_recover_write_reload(self, tmp_path):
        from storage.memory import MemorySystem
        from agent.services.run_history_service import RunHistoryService

        facts_path = tmp_path / "facts.json"
        facts_path.write_text("{CORRUPT FACTS}", encoding="utf-8")

        # Boot with corrupt facts — should quarantine and start clean
        mem = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(facts_path),
            tasks_file=str(tmp_path / "tasks.json"),
        )
        assert mem.facts_quarantined
        assert mem.facts == {}

        # Now write new facts (should work despite quarantine)
        svc = RunHistoryService(mem)
        svc.persist_run_digest({
            "task": "recovery task", "outcome": "success",
            "steps": [{"step": 1, "status": "done", "action": "run_shell", "target": "fix.sh"}],
            "failed": [], "outputs": [], "recovery": None, "run_kind": "primary",
        }, "")

        # Reload from disk — should have the new data
        mem2 = MemorySystem(
            episodic_file=str(tmp_path / "ep.jsonl"),
            facts_file=str(facts_path),
            tasks_file=str(tmp_path / "tasks.json"),
        )
        assert not mem2.facts_quarantined
        val = mem2.get_fact_value("run:last")
        assert val is not None
        assert val["task"] == "recovery task"

    def test_state_corrupt_recover_continue_normally(self, tmp_path):
        from agent.agent_loop import AgentLoop, load_config
        state_path = tmp_path / "state.json"
        state_path.write_text("{bad state}", encoding="utf-8")

        cfg = load_config("config.json")
        cfg = dict(cfg)
        cfg["memory"] = dict(cfg.get("memory", {}))
        cfg["memory"]["state_file"] = str(state_path)
        agent = AgentLoop(cfg)
        agent.memory.facts.clear()

        # Should have clean state + startup warning
        assert agent.current_state.get("execution_log") is not None
        warnings = agent.current_state.get("_startup_warnings", [])
        assert len(warnings) >= 1

        # Should be able to save state normally
        agent._save_state()
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert "execution_log" in saved
        assert "_startup_warnings" not in saved

    def test_episodic_partial_corruption_then_new_events(self, tmp_path):
        from storage.episodic import EpisodicStore
        ep_path = tmp_path / "episodic.jsonl"
        # 3 good, 2 corrupt, 2 good
        lines = [
            '{"event":"e1","timestamp":"2026-01-01T00:00:00"}',
            '{"event":"e2","timestamp":"2026-01-01T00:00:01"}',
            '{"event":"e3","timestamp":"2026-01-01T00:00:02"}',
            '{CORRUPT LINE}',
            'NOT JSON AT ALL',
            '{"event":"e6","timestamp":"2026-01-01T00:00:05"}',
            '{"event":"e7","timestamp":"2026-01-01T00:00:06"}',
        ]
        ep_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        es = EpisodicStore(ep_path)
        assert len(es.log) == 5  # 3 + 2 good after the corrupt ones
        event_names = {e["event"] for e in es.log}
        assert event_names == {"e1", "e2", "e3", "e6", "e7"}

        # Write new event — should work
        es.save("e8", {}, "success")
        assert any(e["event"] == "e8" for e in es.log)
