#!/usr/bin/env python3
"""Tests for weak-point tightening + IFO utilization upgrades.

Covers: evidence_score, post_execute, maintenance, retrieval shape-aware,
capability_map v2, memory usefulness, health repair classes, planner evidence,
bundle limits, EvidenceItem recency, procedure memory, reflect mode, parse rewrite.

Compatible with both pytest and direct execution.
"""

import sys
import os
import tempfile
import json
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ── 1. evidence_score ────────────────────────────────────

def test_score_evidence_range():
    from core.evidence_score import score_evidence
    item = {"intent": "list_files", "tool": "file", "timestamp": "2026-03-10T12:00:00", "confidence": 0.8}
    s = score_evidence(item, {"list", "files"}, query_intent="list_files", query_domain="filesystem", query_tool="file")
    assert 0.0 <= s <= 1.0
    assert s > 0.2

def test_extract_shape():
    from core.evidence_score import extract_shape
    shape = extract_shape("list_files", {"path": "/tmp"}, "file")
    assert shape["intent"] == "list_files"
    assert shape["entity_types"] == ["path"]
    assert shape["domain"] == "filesystem"
    assert shape["tool_family"] == "filesystem"
    assert "list_files(path)" in shape["action_shape"]

def test_shape_similarity():
    from core.evidence_score import extract_shape, shape_similarity
    shape = extract_shape("list_files", {"path": "/tmp"}, "file")
    shape2 = extract_shape("read_file", {"path": "/tmp", "filename": "x"}, "file")
    sim = shape_similarity(shape, shape2)
    assert 0.0 <= sim <= 1.0
    assert sim > 0.1
    identical_sim = shape_similarity(shape, shape)
    assert identical_sim > 0.5

def test_rank_evidence():
    from core.evidence_score import rank_evidence
    items = [{"intent": "a"}, {"intent": "list_files", "tool": "file"}]
    ranked = rank_evidence(items, {"list", "files"}, query_intent="list_files")
    assert isinstance(ranked, list)


# ── 2. post_execute ──────────────────────────────────────

def test_post_executor():
    from core.post_execute import PostExecutor

    class FakeMeta:
        def end_action(self, name): self._ended = name
    class FakeCapMap:
        def __init__(self): self._recorded = []
        def record(self, *a, **kw): self._recorded.append((a, kw))
    class FakeRetrieval:
        def __init__(self): self._wf = []; self._fail = []
        def store_workflow(self, *a, **kw): self._wf.append(a)
        def store_failure(self, **kw): self._fail.append(kw)

    fm, fc, fr = FakeMeta(), FakeCapMap(), FakeRetrieval()
    pe = PostExecutor(fm, fc, fr)
    pe.run({"name": "list_files", "tool": "file", "parameters": {"path": "/"}}, {"success": True})
    assert fm._ended == "list_files"
    assert len(fc._recorded) == 1
    assert len(fr._wf) == 1
    assert len(fr._fail) == 0

    pe.run({"name": "bad", "tool": "x", "parameters": {}}, {"success": False, "error": "oops"})
    assert len(fr._fail) == 1


# ── 3. maintenance ───────────────────────────────────────

def test_maintenance_tick():
    from core.maintenance import MaintenanceScheduler

    class FakeMeta2:
        _cycle_count = 0
        def tick(self, log):
            self._cycle_count += 1
            return None
    class FakeCapMap2:
        def detect_pressure(self): return []
    class FakeMemory:
        facts = {}
        def compress(self): return {"removed_dupes": 0}
        def save_episodic(self, *a, **kw): pass
    class FakeHealth:
        def run_check(self): return {"issues_found": 0}
    class FakeBus:
        def emit(self, *a, **kw): pass
    class FakeRetrieval2:
        def crystallize(self, t): pass

    ms = MaintenanceScheduler(FakeMeta2(), FakeCapMap2(), FakeMemory(), FakeHealth(), FakeRetrieval2(), FakeBus())
    ms.tick([])  # should not raise


# ── 4. retrieval shape-aware ─────────────────────────────

def test_retrieval_shape_aware():
    from storage.memory import MemorySystem
    from core.retrieval import RetrievalBus

    with tempfile.TemporaryDirectory() as td:
        mem = MemorySystem(
            episodic_file=os.path.join(td, "ep.jsonl"),
            facts_file=os.path.join(td, "facts.json"),
            tasks_file=os.path.join(td, "tasks.json"),
        )
        mem.save_fact("learn:python:decorators", "functions that wrap functions", source="golearn")
        rb = RetrievalBus(mem, data_dir=td)

        rb.store_workflow("file.list_files", ["list_files"], ["file"],
                          intent="list_files", entities={"path": "/tmp"})
        assert rb._workflows[0].get("shape") is not None

        evidence = rb.retrieve_context_bundle("list_files", "plan",
                                              intent="list_files", entities={"path": "/"}, tool="file")
        assert isinstance(evidence, list)

        evidence2 = rb.retrieve_context_bundle("python decorators", "respond")
        assert any(e.type == "golearn" for e in evidence2)


# ── 5. capability_map v2 ─────────────────────────────────

def test_capability_map_v2():
    from core.capability_map import CapabilityMap

    with tempfile.TemporaryDirectory() as td:
        cm = CapabilityMap(persist_path=os.path.join(td, "cap.json"))
        cm.record("file", "list_files", True, context="list_files")
        cm.record("file", "list_files", True, context="list_files")
        cm.record("file", "read_file", False, context="read_file")

        assert cm.success_rate("file") > 0.5
        assert 0 <= cm.recent_success_rate("file") <= 1.0

        ts = cm.tool_score("file", context="list_files", intent="list_files")
        assert ts > 0
        assert ts <= 1.0

        cluster = cm.get_capability_cluster("list_files")
        assert len(cluster["tools"]) > 0
        assert cluster["intent"] == "list_files"

        full = cm.get_full_map()
        assert "best_contexts" in full.get("file", {})
        assert "recent_success_rate" in full.get("file", {})

        basic = cm.get_map()
        assert "success_rate" in basic.get("file", {})


# ── 6. memory usefulness ─────────────────────────────────

def test_memory_usefulness():
    from storage.memory import MemorySystem

    with tempfile.TemporaryDirectory() as td:
        mem = MemorySystem(
            episodic_file=os.path.join(td, "ep.jsonl"),
            facts_file=os.path.join(td, "facts.json"),
            tasks_file=os.path.join(td, "tasks.json"),
        )
        mem.save_fact("test:key", "value", topic="test", stratum="world")
        assert mem.facts["test:key"].get("use_count") == 0
        assert mem.facts["test:key"].get("topic") == "test"

        mem.mark_used("test:key", influenced=True)
        assert mem.facts["test:key"]["use_count"] == 1
        assert mem.facts["test:key"]["influence_count"] == 1
        assert mem.facts["test:key"]["last_used"] != ""

def test_memory_compression():
    from storage.memory import MemorySystem

    with tempfile.TemporaryDirectory() as td:
        mem = MemorySystem(
            episodic_file=os.path.join(td, "ep.jsonl"),
            facts_file=os.path.join(td, "facts.json"),
            tasks_file=os.path.join(td, "tasks.json"),
        )
        mem.save_fact("stale:unused", "junk")
        mem.facts["stale:unused"]["last_updated"] = "2025-01-01T00:00:00"
        mem.facts["stale:unused"]["confidence"] = 0.05
        mem.facts["stale:unused"]["use_count"] = 0
        mem.facts["stale:unused"]["influence_count"] = 0

        report = mem.compress()
        assert report.get("pruned_dead", 0) >= 1
        assert "stale:unused" not in mem.facts

        mem.save_fact("old:useful", "important")
        mem.facts["old:useful"]["last_updated"] = "2025-01-01T00:00:00"
        mem.facts["old:useful"]["use_count"] = 10
        mem.facts["old:useful"]["influence_count"] = 5
        mem.facts["old:useful"]["confidence"] = 0.5

        mem.compress()
        assert "old:useful" in mem.facts
        assert mem.facts["old:useful"]["confidence"] > 0.45


# ── 7. health repair classes ─────────────────────────────

def test_health_repair_classes():
    from core.health import HealthMonitor, REPAIR_CLASSES
    from storage.memory import MemorySystem

    assert len(REPAIR_CLASSES) >= 7

    with tempfile.TemporaryDirectory() as td:
        mem = MemorySystem(
            episodic_file=os.path.join(td, "ep.jsonl"),
            facts_file=os.path.join(td, "facts.json"),
            tasks_file=os.path.join(td, "tasks.json"),
        )
        (Path(td) / "data").mkdir(exist_ok=True)
        (Path(td) / "data" / "agent_state.json").write_text(json.dumps({"confidence": 0.5}))
        (Path(td) / "config.json").write_text("{}")

        hm = HealthMonitor(td, mem)

        hm.record_repair_outcome("import_error", "fixed syntax", True)
        hm.record_repair_outcome("import_error", "wrong fix", False)
        assert hm.get_repair_success_rate("import_error") == 0.5

        assert hm._classify_issue({"subsystem": "imports", "issue": "Cannot import core.foo: SyntaxError", "severity": "critical"}) == "import_error"
        assert hm._classify_issue({"subsystem": "memory", "issue": "Facts file is 6.0MB (large)", "severity": "warning"}) == "memory_bloat"
        assert hm._classify_issue({"subsystem": "storage", "issue": "Missing expected file: data/facts.json", "severity": "warning"}) == "missing_file"

        report = hm.run_check()
        assert "repair_policy" in report


# ── 8. planner evidence conditioning ─────────────────────

def test_planner_evidence():
    from core.planner import Planner
    from core.capability_map import CapabilityMap

    with tempfile.TemporaryDirectory() as td:
        cm = CapabilityMap(persist_path=os.path.join(td, "cap.json"))
        cm.record("file", "list_files", True)
        pl = Planner(capability_map=cm)

        cands = pl.plan_actions({"intent": "list_files", "confidence": 0.9, "entities": {"path": "/tmp"}})
        assert len(cands) > 0
        base_conf = cands[0]["confidence"]

        class FakeEv:
            def __init__(self, t, v, h):
                self.type = t; self.value = v; self.effect_hint = h

        wf_ev = FakeEv("workflow", {"tool_sequence": ["file"], "signature": "file.list_files"}, "boost_action")
        cands2 = pl.plan_actions({"intent": "list_files", "confidence": 0.9, "entities": {"path": "/tmp"}}, evidence=[wf_ev])
        assert cands2[0]["confidence"] >= base_conf

        fail_ev = FakeEv("failure", {"tool": "file", "error_class": "permission"}, "block_action")
        cands3 = pl.plan_actions({"intent": "list_files", "confidence": 0.9, "entities": {"path": "/tmp"}}, evidence=[fail_ev])
        assert cands3[0]["confidence"] <= base_conf


# ── 9. IFO bundle limits ─────────────────────────────────

def test_ifo_bundle_limits():
    from core.retrieval import _MODE_LIMITS
    assert _MODE_LIMITS["parse"] == 5
    assert _MODE_LIMITS["plan"] == 7
    assert _MODE_LIMITS["execute"] == 5
    assert _MODE_LIMITS["respond"] == 7
    assert _MODE_LIMITS["repair"] == 5


# ── 10. EvidenceItem recency ─────────────────────────────

def test_evidence_item_recency():
    from core.retrieval import EvidenceItem as EI
    ei = EI(type="test", value="v", confidence=0.8, relevance=0.5,
            source="test", effect_hint="boost_action", recency=0.9)
    assert ei.recency == 0.9
    assert "recency" in ei.to_dict()

    ei_default = EI(type="test", value="v", confidence=0.8, relevance=0.5, source="test")
    assert ei_default.recency == 0.5


# ── 11. procedure memory ─────────────────────────────────

def test_procedure_memory():
    from storage.memory import MemorySystem
    from core.retrieval import RetrievalBus

    with tempfile.TemporaryDirectory() as td:
        mem = MemorySystem(
            episodic_file=os.path.join(td, "ep.jsonl"),
            facts_file=os.path.join(td, "facts.json"),
            tasks_file=os.path.join(td, "tasks.json"),
        )
        rb = RetrievalBus(mem, data_dir=td)

        rb.store_procedure("search_and_read", "search_files",
                           [{"action": "search_files"}, {"action": "read_file"}],
                           domain="filesystem")
        assert len(rb._procedures) == 1
        assert rb._procedures[0]["domain"] == "filesystem"

        evidence = rb.retrieve_context_bundle("search_files", "plan", intent="search_files")
        assert any(e.type == "procedure" for e in evidence)

        evidence2 = rb.retrieve_context_bundle("search_files", "execute", intent="search_files")
        assert any(e.type == "procedure" for e in evidence2)


# ── 12. reflect mode retrieval ────────────────────────────

def test_reflect_mode():
    from storage.memory import MemorySystem
    from core.retrieval import RetrievalBus

    with tempfile.TemporaryDirectory() as td:
        mem = MemorySystem(
            episodic_file=os.path.join(td, "ep.jsonl"),
            facts_file=os.path.join(td, "facts.json"),
            tasks_file=os.path.join(td, "tasks.json"),
        )
        rb = RetrievalBus(mem, data_dir=td)
        rb.store_workflow("file.list_files", ["list_files"], ["file"], intent="list_files")
        rb.store_failure(intent="list_files", tool="file", params={},
                         error_class="perm", context="test", lesson="test")

        evidence = rb.retrieve_context_bundle("list_files", "reflect", intent="list_files")
        types = {e.type for e in evidence}
        assert "workflow" in types
        assert "failure" in types


# ── 13. parse evidence rewrite ────────────────────────────

def test_parse_rewrite():
    from agent.agent_loop import AgentLoop, load_config

    config = load_config("config.json")
    agent = AgentLoop(config)

    agent.memory.save_fact("lang:map:gimme", "give me", source="user")
    agent.normalizer.reload_from_memory(agent.memory)

    evidence = agent.retrieval.retrieve_context_bundle("gimme files", "parse")
    rewrite_items = [e for e in evidence if e.effect_hint == "rewrite_input"]
    assert len(rewrite_items) > 0


# ── Direct execution support ─────────────────────────────

if __name__ == "__main__":
    import traceback
    passed = 0
    failed = 0
    test_funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in test_funcs:
        try:
            fn()
            print(f"  PASS: {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    total = passed + failed
    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
