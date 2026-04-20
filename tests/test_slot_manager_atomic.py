"""Tests for SlotManager._save atomic write hardening.

Covers:
- _save routes through atomic_write_text (no bare open/write)
- saved assignments survive a reload
- original file preserved when os.replace fails
- no orphan temp files on failure
- no-storage-path case does not raise
- _load corrupt-file silence preserved (no new crashes)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _manager(tmp_path, storage=True):
    from core.slot_manager import SlotManager
    path = str(tmp_path / "slots.json") if storage else None
    return SlotManager(storage_path=path)


class TestSlotManagerSaveAtomic:

    def test_save_calls_atomic_write_text(self, tmp_path):
        import core.slot_manager as _mod
        original = _mod.atomic_write_text
        calls = []

        def tracking(path, text):
            calls.append(Path(path))
            return original(path, text)

        with patch("core.slot_manager.atomic_write_text", side_effect=tracking):
            sm = _manager(tmp_path)
            sm.assign_model("planner_slot", "mistral:7b")

        assert any("slots.json" in str(p) for p in calls)

    def test_save_does_not_use_bare_open_write(self, tmp_path):
        """Bare open(..., 'w') must not be called on the slots file."""
        target = str(tmp_path / "slots.json")
        open_calls = []
        real_open = open

        def spy_open(file, mode="r", *a, **kw):
            if str(file) == target and "w" in str(mode):
                open_calls.append((str(file), mode))
            return real_open(file, mode, *a, **kw)

        with patch("builtins.open", side_effect=spy_open):
            sm = _manager(tmp_path)
            sm.assign_model("planner_slot", "mistral:7b")

        assert open_calls == [], f"bare open for write called: {open_calls}"

    def test_no_orphan_tmp_file_on_success(self, tmp_path):
        sm = _manager(tmp_path)
        sm.assign_model("planner_slot", "mistral:7b")
        tmps = list(tmp_path.glob("slots.json.*.tmp"))
        assert tmps == []

    def test_original_preserved_when_replace_fails(self, tmp_path):
        sm = _manager(tmp_path)
        sm.assign_model("planner_slot", "original-model")
        original_text = (tmp_path / "slots.json").read_text()

        with patch("os.replace", side_effect=OSError("replace failed")):
            try:
                sm.assign_model("planner_slot", "new-model")
            except OSError:
                pass

        assert (tmp_path / "slots.json").read_text() == original_text

    def test_no_orphan_tmp_on_replace_failure(self, tmp_path):
        sm = _manager(tmp_path)
        sm.assign_model("planner_slot", "original-model")

        with patch("os.replace", side_effect=OSError("replace failed")):
            try:
                sm.assign_model("planner_slot", "new-model")
            except OSError:
                pass

        tmps = list(tmp_path.glob("slots.json.*.tmp"))
        assert tmps == []

    def test_no_storage_path_does_not_raise(self):
        sm = _manager(None, storage=False)
        sm.assign_model("planner_slot", "any-model")  # must not raise


class TestSlotManagerRoundTrip:

    def test_assignment_survives_reload(self, tmp_path):
        from core.slot_manager import SlotManager
        path = str(tmp_path / "slots.json")
        sm = SlotManager(storage_path=path)
        sm.assign_model("planner_slot", "mistral:7b")
        sm.assign_model("summarizer_slot", "phi3:mini")

        sm2 = SlotManager(storage_path=path)
        assert sm2.get_slot("planner_slot").assigned_model_id == "mistral:7b"
        assert sm2.get_slot("summarizer_slot").assigned_model_id == "phi3:mini"

    def test_role_assignment_survives_reload(self, tmp_path):
        from core.slot_manager import SlotManager
        path = str(tmp_path / "slots.json")
        sm = SlotManager(storage_path=path)
        sm.assign_role("planner", "llama3:8b")

        sm2 = SlotManager(storage_path=path)
        assert sm2.get_role_assignment("planner").assigned_model_id == "llama3:8b"

    def test_deterministic_flag_survives_reload(self, tmp_path):
        from core.slot_manager import SlotManager
        path = str(tmp_path / "slots.json")
        sm = SlotManager(storage_path=path)
        sm.assign_model("coder_slot", "codellama:7b", deterministic=True)

        sm2 = SlotManager(storage_path=path)
        assert sm2.get_slot("coder_slot").deterministic_only is True

    def test_clear_assignment_survives_reload(self, tmp_path):
        from core.slot_manager import SlotManager
        path = str(tmp_path / "slots.json")
        sm = SlotManager(storage_path=path)
        sm.assign_model("planner_slot", "mistral:7b")
        sm.assign_model("planner_slot", None)  # clear

        sm2 = SlotManager(storage_path=path)
        assert sm2.get_slot("planner_slot").assigned_model_id is None

    def test_corrupt_slots_file_loads_defaults(self, tmp_path):
        """Corrupt file on load must not crash — defaults survive."""
        from core.slot_manager import SlotManager
        path = tmp_path / "slots.json"
        path.write_text("{CORRUPT", encoding="utf-8")
        sm = SlotManager(storage_path=str(path))
        # All default slots present, no assignment
        assert sm.get_slot("planner_slot") is not None
        assert sm.get_slot("planner_slot").assigned_model_id is None

    def test_missing_slots_file_loads_defaults(self, tmp_path):
        from core.slot_manager import SlotManager
        path = str(tmp_path / "slots.json")
        sm = SlotManager(storage_path=path)
        assert sm.get_slot("planner_slot") is not None

    def test_written_json_is_valid(self, tmp_path):
        sm = _manager(tmp_path)
        sm.assign_model("planner_slot", "mistral:7b")
        data = json.loads((tmp_path / "slots.json").read_text())
        assert "planner_slot" in data
        assert data["planner_slot"]["assigned_model_id"] == "mistral:7b"
