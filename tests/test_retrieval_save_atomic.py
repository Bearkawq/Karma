"""Tests for RetrievalBus._save_json atomic write hardening.

Covers:
- _save_json routes through atomic_write_text (no direct write_text)
- successful save produces readable, correct file contents
- save failure (os.replace failure) leaves original file intact
- no orphan temp files on failure
- each store path (workflow, failure, health, procedure, crystal) uses _save_json
- reload after save returns same data
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


class DummyMem:
    def __init__(self):
        self.facts = {}


def _bus(tmp_path):
    from core.retrieval import RetrievalBus
    return RetrievalBus(DummyMem(), data_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# _save_json uses atomic_write_text
# ---------------------------------------------------------------------------

class TestSaveJsonAtomic:

    def test_save_json_calls_atomic_write_text(self, tmp_path):
        bus = _bus(tmp_path)
        target = tmp_path / "test.json"
        calls = []

        import core.retrieval as _retrieval_mod
        original = _retrieval_mod.atomic_write_text

        def tracking(*a, **kw):
            calls.append(Path(a[0]))
            return original(*a, **kw)

        with patch("core.retrieval.atomic_write_text", side_effect=tracking):
            bus._save_json(target, {"x": 1})

        assert any(str(p) == str(target) for p in calls)

    def test_save_json_does_not_use_write_text_directly(self, tmp_path):
        """Path.write_text must not be called — atomic path only."""
        bus = _bus(tmp_path)
        target = tmp_path / "test.json"
        write_text_calls = []

        original_wt = Path.write_text
        def spy_write_text(self_path, *a, **kw):
            write_text_calls.append(str(self_path))
            return original_wt(self_path, *a, **kw)

        with patch.object(Path, "write_text", spy_write_text):
            bus._save_json(target, {"x": 1})

        assert not any(str(target) == p for p in write_text_calls)

    def test_save_json_writes_correct_content(self, tmp_path):
        bus = _bus(tmp_path)
        target = tmp_path / "out.json"
        data = [{"id": "w1", "steps": ["a", "b"]}, {"id": "w2"}]
        bus._save_json(target, data)
        loaded = json.loads(target.read_text())
        assert loaded == data

    def test_no_orphan_tmp_file_on_success(self, tmp_path):
        bus = _bus(tmp_path)
        target = tmp_path / "out.json"
        bus._save_json(target, {"k": "v"})
        tmps = list(tmp_path.glob("out.json.*.tmp"))
        assert tmps == []

    def test_original_preserved_when_replace_fails(self, tmp_path):
        bus = _bus(tmp_path)
        target = tmp_path / "out.json"
        target.write_text('{"old": true}', encoding="utf-8")
        with patch("os.replace", side_effect=OSError("replace failed")):
            try:
                bus._save_json(target, {"new": True})
            except OSError:
                pass
        assert json.loads(target.read_text()) == {"old": True}

    def test_no_orphan_tmp_file_on_failure(self, tmp_path):
        bus = _bus(tmp_path)
        target = tmp_path / "out.json"
        with patch("os.replace", side_effect=OSError("replace failed")):
            try:
                bus._save_json(target, {"k": "v"})
            except OSError:
                pass
        tmps = list(tmp_path.glob("out.json.*.tmp"))
        assert tmps == []


# ---------------------------------------------------------------------------
# Each store path uses atomic_write_text via _save_json
# ---------------------------------------------------------------------------

class TestSavePathsUseAtomicWrite:

    def _count_atomic_calls(self, bus, action):
        import core.retrieval as _retrieval_mod
        original = _retrieval_mod.atomic_write_text
        calls = []

        def tracking(*a, **kw):
            calls.append(Path(a[0]))
            return original(*a, **kw)

        with patch("core.retrieval.atomic_write_text", side_effect=tracking):
            action()

        return calls

    def test_workflow_save_uses_atomic(self, tmp_path):
        bus = _bus(tmp_path)
        calls = self._count_atomic_calls(
            bus, lambda: bus.store_workflow(
                "deploy app", ["build", "push"], ["docker", "kubectl"]
            )
        )
        assert any("workflow" in str(p).lower() for p in calls)

    def test_failure_save_uses_atomic(self, tmp_path):
        bus = _bus(tmp_path)
        calls = self._count_atomic_calls(
            bus, lambda: bus.store_failure(
                "run tests", "pytest", {}, "CalledProcessError",
                "ci environment", "check deps first"
            )
        )
        assert any("failure" in str(p).lower() for p in calls)

    def test_health_save_uses_atomic(self, tmp_path):
        bus = _bus(tmp_path)
        calls = self._count_atomic_calls(
            bus, lambda: bus.store_health_event(
                "disk near full", "warning", "prune old logs", "storage"
            )
        )
        assert any("health" in str(p).lower() for p in calls)

    def test_procedure_save_uses_atomic(self, tmp_path):
        bus = _bus(tmp_path)
        calls = self._count_atomic_calls(
            bus, lambda: bus.store_procedure(
                "migrate db", "migrate", [{"step": "backup"}, {"step": "run"}]
            )
        )
        assert any("procedure" in str(p).lower() for p in calls)

    def test_crystal_save_uses_atomic(self, tmp_path):
        from core.retrieval import RetrievalBus
        mem = DummyMem()
        # crystallize requires ≥3 related facts
        for i in range(5):
            mem.facts[f"retry:fact{i}"] = {
                "value": f"retry policy {i}", "confidence": 0.8,
                "source": "agent", "use_count": 1,
            }
        bus = RetrievalBus(mem, data_dir=str(tmp_path))
        import core.retrieval as _retrieval_mod
        original = _retrieval_mod.atomic_write_text
        calls = []

        def tracking(*a, **kw):
            calls.append(Path(a[0]))
            return original(*a, **kw)

        with patch("core.retrieval.atomic_write_text", side_effect=tracking):
            bus.crystallize("retry")

        assert any("crystal" in str(p).lower() for p in calls)


# ---------------------------------------------------------------------------
# Round-trip: save → reload recovers same data
# ---------------------------------------------------------------------------

class TestSaveReloadRoundTrip:

    def test_workflow_survives_reload(self, tmp_path):
        from core.retrieval import RetrievalBus
        bus = _bus(tmp_path)
        bus.store_workflow("deploy app", ["build", "push"], ["docker"])
        bus2 = RetrievalBus(DummyMem(), data_dir=str(tmp_path))
        assert any(w.get("signature") == "deploy app" for w in bus2._workflows)

    def test_failure_survives_reload(self, tmp_path):
        from core.retrieval import RetrievalBus
        bus = _bus(tmp_path)
        bus.store_failure("run tests", "pytest", {}, "CalledProcessError",
                          "ci", "check deps first")
        bus2 = RetrievalBus(DummyMem(), data_dir=str(tmp_path))
        assert any(f.get("error_class") == "CalledProcessError" for f in bus2._failures)

    def test_health_survives_reload(self, tmp_path):
        from core.retrieval import RetrievalBus
        bus = _bus(tmp_path)
        bus.store_health_event("disk near full", "warning", "prune old logs")
        bus2 = RetrievalBus(DummyMem(), data_dir=str(tmp_path))
        assert any(h.get("issue") == "disk near full" for h in bus2._health)

    def test_procedure_survives_reload(self, tmp_path):
        from core.retrieval import RetrievalBus
        bus = _bus(tmp_path)
        bus.store_procedure("migrate db", "migrate", [{"step": "backup"}])
        bus2 = RetrievalBus(DummyMem(), data_dir=str(tmp_path))
        assert any(p.get("name") == "migrate db" for p in bus2._procedures)

    def test_crystal_survives_reload(self, tmp_path):
        from core.retrieval import RetrievalBus
        mem = DummyMem()
        for i in range(5):
            mem.facts[f"retry:fact{i}"] = {
                "value": f"retry policy {i}", "confidence": 0.8,
                "source": "agent", "use_count": 1,
            }
        bus = RetrievalBus(mem, data_dir=str(tmp_path))
        bus.crystallize("retry")
        bus2 = RetrievalBus(DummyMem(), data_dir=str(tmp_path))
        assert any(c.get("topic") == "retry" for c in bus2._crystals)
