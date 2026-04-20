from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import os

KARMA_ROOT = Path(__file__).resolve().parent.parent
if str(KARMA_ROOT) not in sys.path:
    sys.path.insert(0, str(KARMA_ROOT))

from core.slot_manager import SlotManager
import agent.services.model_operator_service as model_ops
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


def _fake_ollama(monkeypatch, models, loaded=None):
    loaded = loaded or []

    def fake_request(path, timeout=3.0):
        if path == "/api/tags":
            return {"models": [{"name": model} for model in models]}
        if path == "/api/ps":
            return {"models": [{"name": model} for model in loaded]}
        return None

    monkeypatch.setattr(model_ops, "_request_json", fake_request)


def test_build_model_status_text_shows_roles_and_inventory(monkeypatch, tmp_path):
    _fake_ollama(monkeypatch, ["m1", "qwen3:4b"], loaded=["m1"])
    sm = SlotManager(storage_path=None)
    sm.assign_model('planner_slot', 'm1')
    mgr = FakeManager(['m1','m2'], loaded=['m1'])
    txt = build_model_status_text(mgr, sm)
    assert 'role: planner' in txt
    assert 'slot: planner_slot' in txt
    assert 'assigned: m1' in txt
    assert 'exists: True' in txt
    assert 'loaded: True' in txt
    assert 'deterministic_only: False' in txt
    assert 'Small model pool:' in txt


def test_assign_role_and_persist(monkeypatch, tmp_path):
    _fake_ollama(monkeypatch, ["mmodel"])
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager(['mmodel'])
    ok, msg = assign_model_to_role(mgr, sm, 'planner', 'mmodel')
    assert ok
    assert "resolved as mmodel" in msg
    sm2 = SlotManager(storage_path=path)
    assert sm2.get_slot('planner_slot').assigned_model_id == 'mmodel'


def test_assign_slot_and_persist(monkeypatch, tmp_path):
    _fake_ollama(monkeypatch, ["slotmodel"])
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager(['slotmodel'])
    ok, msg = assign_model_to_slot(mgr, sm, 'planner_slot', 'slotmodel')
    assert ok
    sm2 = SlotManager(storage_path=path)
    assert sm2.get_slot('planner_slot').assigned_model_id == 'slotmodel'


def test_tagless_assignment_validates_against_latest_tag(monkeypatch, tmp_path):
    _fake_ollama(monkeypatch, ["phi4-mini:latest"])
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager([])
    ok, msg = assign_model_to_slot(mgr, sm, 'planner_slot', 'phi4-mini')
    assert ok
    assert "resolved as phi4-mini:latest" in msg
    assert SlotManager(storage_path=path).get_slot('planner_slot').assigned_model_id == 'phi4-mini'


def test_invalid_model_assignment_fails(monkeypatch, tmp_path):
    _fake_ollama(monkeypatch, ["good"])
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager(['good'])
    ok, msg = assign_model_to_role(mgr, sm, 'planner', 'bad')
    assert not ok
    assert "Model not found" in msg


def test_bootstrap_layout_assigns_preferred_available_models(monkeypatch, tmp_path):
    _fake_ollama(
        monkeypatch,
        ["qwen3:4b", "granite3.3:2b", "nomic-embed-text:latest", "gemma3:4b", "phi4-mini:latest"],
    )
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    mgr = FakeManager([])
    report = bootstrap_layout(mgr, sm)
    assert len(report['assigned']) == 6

    reloaded = SlotManager(storage_path=path)
    assert reloaded.get_role_assignment('planner').assigned_model_id == 'qwen3:4b'
    assert reloaded.get_role_assignment('executor').assigned_model_id == 'qwen3:4b'
    assert reloaded.get_role_assignment('critic').assigned_model_id == 'qwen3:4b'
    assert reloaded.get_role_assignment('summarizer').assigned_model_id == 'granite3.3:2b'
    assert reloaded.get_role_assignment('navigator').assigned_model_id == 'granite3.3:2b'
    assert reloaded.get_role_assignment('retriever').assigned_model_id == 'nomic-embed-text'


def test_bootstrap_layout_skips_role_without_suitable_model(monkeypatch, tmp_path):
    _fake_ollama(monkeypatch, ["qwen3:4b"])
    sm = SlotManager(storage_path=str(tmp_path / 'slots.json'))
    report = bootstrap_layout(FakeManager([]), sm)
    skipped_roles = {item["role"] for item in report["skipped"]}
    assert "retriever" in skipped_roles


def test_slot_manager_role_assignment_regression(tmp_path):
    path = str(tmp_path / 'slots.json')
    sm = SlotManager(storage_path=path)
    assert sm.assign_role('planner', 'qwen3:4b', deterministic=True)
    reloaded = SlotManager(storage_path=path)
    assert reloaded.get_role_assignment('planner').assigned_model_id == 'qwen3:4b'
    assert reloaded.get_role_assignment('planner').deterministic_only is True


def test_cli_model_status_runs(tmp_path):
    # run agent/agent_loop.py --models (uses build_agent, then live Ollama inventory)
    karma_root = str(Path(__file__).resolve().parent.parent)
    env = {**os.environ, 'PYTHONPATH': karma_root}
    res = subprocess.run([sys.executable, 'agent/agent_loop.py', '--models'], cwd=karma_root, env=env, capture_output=True, text=True, timeout=30)
    assert 'Model status:' in res.stdout
    assert 'Small model pool:' in res.stdout
