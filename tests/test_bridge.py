"""Tests for the bridge module."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bridge


@pytest.fixture
def temp_bridge(tmp_path):
    """Create a temporary bridge directory."""
    bridge.DEFAULT_BRIDGE_PATH = tmp_path
    bridge.init_bridge(tmp_path)
    yield tmp_path
    # Reset
    bridge.DEFAULT_BRIDGE_PATH = Path(__file__).resolve().parent.parent / "bridge"


def test_init_bridge(temp_bridge):
    """Test bridge initialization creates all directories."""
    assert (temp_bridge / "inbox").exists()
    assert (temp_bridge / "outbox").exists()
    assert (temp_bridge / "workers").exists()
    assert (temp_bridge / "planner").exists()
    assert (temp_bridge / "events").exists()
    assert (temp_bridge / "locks").exists()
    assert (temp_bridge / "archive").exists()


def test_update_worker_state(temp_bridge):
    """Test worker state update."""
    state = bridge.update_worker_state(
        role="scout",
        status="active",
        current_task="Find test files",
        current_files=["tests/test_gui.py", "tests/test_hardening.py"],
        progress_percent=50,
    )
    
    assert state["role"] == "scout"
    assert state["status"] == "active"
    assert state["current_task"] == "Find test files"
    assert state["progress_percent"] == 50
    assert state["last_update"] is not None


def test_get_worker_state(temp_bridge):
    """Test reading worker state."""
    bridge.update_worker_state(
        role="coder",
        status="active",
        current_task="Fix bug in web.py",
    )
    
    state = bridge.get_worker_state("coder")
    assert state is not None
    assert state["role"] == "coder"
    assert state["status"] == "active"


def test_append_event(temp_bridge):
    """Test event logging."""
    event = bridge.append_event(
        event_type="test_event",
        worker="tester",
        data={"result": "passed"},
    )
    
    assert event["type"] == "test_event"
    assert event["worker"] == "tester"
    assert event["data"]["result"] == "passed"
    
    # Verify it was written
    events = bridge.get_events(limit=5)
    assert len(events) >= 1
    assert events[-1]["type"] == "test_event"


def test_event_append_correctness(temp_bridge):
    """Test that multiple events append correctly."""
    for i in range(3):
        bridge.append_event(
            event_type=f"event_{i}",
            worker="worker",
            data={"index": i},
        )
    
    events = bridge.get_events(limit=10)
    assert len(events) == 3
    
    # Verify order
    assert events[0]["data"]["index"] == 0
    assert events[1]["data"]["index"] == 1
    assert events[2]["data"]["index"] == 2


def test_generate_planner_summary(temp_bridge):
    """Test planner summary generation."""
    # Add some workers
    bridge.update_worker_state("scout", status="active", current_task="Map files", progress_percent=30)
    bridge.update_worker_state("coder", status="blocked", current_task="Fix bug", blockers=["Unknown dependency"], needs_decision=True)
    bridge.update_worker_state("tester", status="idle")
    
    summary = bridge.generate_planner_summary()
    
    assert summary["generated_at"] is not None
    # Fresh update (within last 30s) should be tracked
    assert len(summary["fresh_updates"]) >= 1
    assert len(summary["blocked_workers"]) == 1
    assert summary["blocked_workers"][0]["role"] == "coder"
    assert len(summary["decision_requests"]) == 1  # blocked worker needs decision
    assert len(summary["idle_workers"]) == 1


def test_blocker_propagation(temp_bridge):
    """Test that blockers are propagated to summary."""
    bridge.update_worker_state(
        role="builder",
        status="blocked",
        blockers=["Missing config file", "Need test output"],
    )
    
    summary = bridge.generate_planner_summary()
    
    # Check blocked workers list contains blockers
    assert len(summary["blocked_workers"]) == 1
    blockers = summary["blocked_workers"][0].get("blockers", [])
    # Blockers are stored as strings in the list
    assert "Missing config file" in blockers
    assert "Need test output" in blockers


def test_handoff_visibility(temp_bridge):
    """Test that handoffs are visible in outbox and events."""
    handoff = bridge.publish_handoff(
        from_role="scout",
        to_role="coder",
        task="Fix failing test",
        context={"file": "tests/test_gui.py", "line": 145},
    )
    
    assert handoff["from"] == "scout"
    assert handoff["to"] == "coder"
    assert handoff["task"] == "Fix failing test"
    
    # Check outbox file exists
    outbox_files = list((temp_bridge / "outbox").glob("*.json"))
    assert len(outbox_files) >= 1
    
    # Check events
    events = bridge.get_events(limit=5)
    handoff_events = [e for e in events if e["type"] == "handoff"]
    assert len(handoff_events) >= 1


def test_stale_worker_detection(temp_bridge):
    """Test stale worker detection."""
    # Create a worker with old timestamp
    old_state = {
        "role": "stale_worker",
        "status": "active",
        "current_task": "Old task",
        "last_update": "2020-01-01T00:00:00+00:00",
    }
    
    worker_file = temp_bridge / "workers" / "stale_worker.json"
    worker_file.write_text(json.dumps(old_state))
    
    summary = bridge.generate_planner_summary()
    
    # The worker should be marked as stale (depends on 10min threshold)
    assert len(summary["stale_workers"]) >= 1


def test_claim_task(temp_bridge):
    """Test task claiming."""
    state = bridge.claim_task(
        role="builder",
        task="Implement feature X",
        files=["agent/agent_loop.py"],
    )
    
    assert state["status"] == "active"
    assert state["current_task"] == "Implement feature X"
    assert state["progress_percent"] == 0
    
    # Check event was logged
    events = bridge.get_events(limit=5)
    claim_events = [e for e in events if e["type"] == "task_claim"]
    assert len(claim_events) >= 1


def test_complete_task(temp_bridge):
    """Test task completion."""
    bridge.claim_task("tester", "Run tests")
    
    state = bridge.complete_task(
        role="tester",
        artifacts=["tests/test_results.txt"],
        next_worker="builder",
        next_action="Fix failures",
    )
    
    assert state["status"] == "completed"
    assert state["progress_percent"] == 100
    assert "tests/test_results.txt" in state["output_files"]


def test_mark_blocked(temp_bridge):
    """Test marking a worker as blocked."""
    state = bridge.mark_blocked(
        role="builder",
        blocker="Cannot find config file",
        decision_needed="Should I create config or use default?",
    )
    
    assert state["status"] == "blocked"
    assert state["needs_decision"] is True
    assert "Cannot find config file" in state["blockers"]


def test_get_worker_statuses(temp_bridge):
    """Test quick status retrieval."""
    bridge.update_worker_state("scout", status="active", current_task="Find files", progress_percent=25)
    bridge.update_worker_state("coder", status="completed", current_task="", progress_percent=100)
    
    statuses = bridge.get_worker_statuses()
    
    assert "scout" in statuses
    assert statuses["scout"]["status"] == "active"
    assert statuses["scout"]["progress"] == 25
    assert statuses["coder"]["status"] == "completed"


def test_planner_summary_json_and_md(temp_bridge):
    """Test both JSON and MD summaries are generated."""
    bridge.update_worker_state("tester", status="active", current_task="Run tests")
    
    summary = bridge.generate_planner_summary()
    
    # Check JSON file
    json_path = temp_bridge / "planner" / "summary.json"
    assert json_path.exists()
    
    # Check MD file
    md_path = temp_bridge / "planner" / "summary.md"
    assert md_path.exists()
    assert "# Planner Summary" in md_path.read_text()


class TestAppendEventHardening:
    """Verify append_event failure tracking and get_events resilience."""

    def test_append_failed_flag_false_initially(self, temp_bridge):
        import bridge as _b
        _b._last_append_failed = False  # reset module state
        bridge.append_event("init_check", worker="tester")
        assert bridge.get_append_failed() is False

    def test_append_failed_flag_set_on_write_error(self, temp_bridge):
        """Write failure must set _last_append_failed and propagate the exception."""
        import bridge as _b
        _b._last_append_failed = False
        event_file = temp_bridge / "events" / "events.jsonl"
        # Make the file a directory so open(..., 'a') raises IsADirectoryError
        event_file.unlink(missing_ok=True)
        event_file.mkdir(parents=True, exist_ok=True)

        with pytest.raises(Exception):
            bridge.append_event("should_fail", worker="tester")

        assert bridge.get_append_failed() is True
        # Cleanup
        event_file.rmdir()

    def test_flag_clears_after_recovery(self, temp_bridge):
        """Successful write after a failure must clear the flag."""
        import bridge as _b
        _b._last_append_failed = True  # simulate prior failure

        bridge.append_event("recovery_event", worker="tester")
        assert bridge.get_append_failed() is False

    def test_get_events_skips_corrupt_line(self, temp_bridge):
        """get_events must skip non-JSON lines without raising."""
        event_file = temp_bridge / "events" / "events.jsonl"
        # Write one good event then a corrupt partial line then another good event
        bridge.append_event("before_corrupt", worker="tester")
        with open(event_file, "a") as f:
            f.write('{"id":"bad","incomplete":true\n')  # truncated JSON
        bridge.append_event("after_corrupt", worker="tester")

        events = bridge.get_events(limit=100)
        types = [e["type"] for e in events]
        assert "before_corrupt" in types
        assert "after_corrupt" in types
        # The corrupt line must have been silently skipped
        assert len(types) == 2

    def test_events_dir_auto_created(self, tmp_path):
        """append_event must create the events dir if it is missing."""
        import bridge as _b
        original = _b.DEFAULT_BRIDGE_PATH
        _b.DEFAULT_BRIDGE_PATH = tmp_path
        # Do NOT call init_bridge — events/ should be created on demand
        try:
            bridge.append_event("auto_dir_test", worker="tester")
            assert (tmp_path / "events" / "events.jsonl").exists()
        finally:
            _b.DEFAULT_BRIDGE_PATH = original

    def test_get_append_failed_reflects_module_state(self, temp_bridge):
        import bridge as _b
        _b._last_append_failed = False
        assert bridge.get_append_failed() is False
        _b._last_append_failed = True
        assert bridge.get_append_failed() is True
        _b._last_append_failed = False  # restore

    def test_summary_failure_does_not_mask_write_success(self, temp_bridge):
        """A crash in generate_planner_summary must not set _last_append_failed."""
        import bridge as _b
        _b._last_append_failed = False

        original = bridge.generate_planner_summary
        def boom():
            raise RuntimeError("summary exploded")
        bridge.generate_planner_summary = boom
        try:
            bridge.append_event("after_summary_boom", worker="tester")
            assert bridge.get_append_failed() is False
        finally:
            bridge.generate_planner_summary = original

    def test_normal_append_still_works_after_hardening(self, temp_bridge):
        """Regression: existing callers must see the same return value."""
        ev = bridge.append_event(
            "regression_check",
            worker="regression",
            data={"x": 1},
            severity="warning",
        )
        assert ev["type"] == "regression_check"
        assert ev["worker"] == "regression"
        assert ev["data"]["x"] == 1
        assert ev["severity"] == "warning"
        assert "id" in ev
        assert "timestamp" in ev


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
