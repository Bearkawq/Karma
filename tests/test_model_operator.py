from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from pathlib import Path
import subprocess
import sys
import os

import pytest

from core.slot_manager import SlotManager
from agent.services.model_operator_service import (
    build_model_status_text,
    assign_model_to_role,
    assign_model_to_slot,
    bootstrap_layout,
)


class FakeManager:
    def __init__(self, available, loaded=None):
        self._available = [{'model_id': m} for m in available]
        self._loaded = set(loaded or [])

    def get_available_models(self):
        return self._available

    def get_loaded_models(self):
        return list(self._loaded)


def test_build_model_status_text_shows_roles(tmp_path):
    sm = SlotManager(storage_path=None)
    # assign one model
    sm.assign_model('planner_slot', 'm1')
    mgr = FakeManager(['m1','m2'], loaded=['m1'])
    txt = build_model_status_text(mgr, sm)
    assert 'role: planner' in txt
    assert 'assigned: m1' in txt
    assert 'LOADED' in txt


def test_assign_role_and_persist(tmp_path):
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager(['mmodel'])
    ok, msg = assign_model_to_role(mgr, sm, 'planner', 'mmodel')
    assert ok
    # reload
    sm2 = SlotManager(storage_path=path)
    assert sm2.get_slot('planner_slot').assigned_model_id == 'mmodel'


def test_assign_slot_and_persist(tmp_path):
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager(['slotmodel'])
    ok, msg = assign_model_to_slot(mgr, sm, 'planner_slot', 'slotmodel')
    assert ok
    sm2 = SlotManager(storage_path=path)
    assert sm2.get_slot('planner_slot').assigned_model_id == 'slotmodel'


def test_invalid_model_assignment_fails(tmp_path):
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager(['good'])
    ok, msg = assign_model_to_role(mgr, sm, 'planner', 'bad')
    assert not ok


def test_bootstrap_layout_assigns_available(tmp_path):
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager(['a','b','c'], loaded=['a','b'])
    report = bootstrap_layout(mgr, sm)
    assert 'assigned' in report
    # assigned models count <= available models
    assert len(report['assigned']) <= 3


def test_cli_model_status_runs(tmp_path):
    # run agent/agent_loop.py --model-status (uses build_agent which will initialize)
    karma_root = str(Path(__file__).resolve().parent.parent)
    env = {**os.environ, 'PYTHONPATH': karma_root}
    res = subprocess.run([sys.executable, 'agent/agent_loop.py', '--model-status'], cwd=karma_root, env=env, capture_output=True, text=True, timeout=30)
    assert 'Model status:' in res.stdout
