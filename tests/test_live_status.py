"""Tests for live-status / current-state introspection lane."""



from agent.agent_loop import AgentLoop, load_config


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_agent():
    cfg = load_config("config.json")
    return AgentLoop(cfg)


def _base_state():
    return {
        "last_run": "2026-04-17T10:00:00",
        "current_task": None,
        "task_history": [],
        "memory_summary": {},
        "decision_summary": {},
        "execution_log": [],
        "confidence": 0.0,
    }


# ── query classifier ──────────────────────────────────────────────────────────


def test_live_status_triggers_detected():
    triggers = [
        "what are you doing right now",
        "what are you working on",
        "what is blocked",
        "what's blocked",
        "what failed most recently",
        "what happens next",
        "what are you waiting on",
        "what should I inspect next",
        "are you blocked",
        "are you stuck",
        "current status",
        "show status",
    ]
    for q in triggers:
        assert AgentLoop._is_live_status_query(q), f"Expected live-status trigger: {q!r}"


def test_live_status_antitokens_suppress():
    suppressed = [
        "how does karma architecture work",
        "explain the history of the project",
        "what is karma",
    ]
    for q in suppressed:
        assert not AgentLoop._is_live_status_query(q), f"Should be suppressed: {q!r}"


def test_live_status_does_not_match_unrelated():
    unrelated = [
        "list files in /tmp",
        "run shell ls",
        "what is the capital of France",
        "deploy to production",
    ]
    for q in unrelated:
        assert not AgentLoop._is_live_status_query(q), f"Should not match: {q!r}"


# ── snapshot builder ──────────────────────────────────────────────────────────


def test_get_live_status_snapshot_no_state():
    agent = _make_agent()
    snap = agent._get_live_status_snapshot()
    assert "current_task" in snap
    assert "blocked_reason" in snap
    assert "last_failure" in snap
    assert "run_last" in snap


def test_get_live_status_snapshot_uses_current_state():
    agent = _make_agent()
    agent.current_state["current_task"] = "run_shell"
    agent.current_state["blocked_reason"] = "2 consecutive failures on 'run_shell'"
    agent.current_state["last_failure"] = {
        "intent": "run_shell", "error": "permission denied", "ts": "2026-04-17T09:55:00"
    }

    snap = agent._get_live_status_snapshot()

    assert snap["current_task"] == "run_shell"
    assert snap["blocked_reason"] == "2 consecutive failures on 'run_shell'"
    assert snap["last_failure"]["error"] == "permission denied"


def test_get_live_status_snapshot_reads_run_last():
    agent = _make_agent()
    agent.memory.save_fact(
        "run:last",
        {"task": "deploy", "outcome": "failed", "path_findings": [], "touched_paths": []},
        source="run_artifact", confidence=0.9, topic="run_history",
    )

    snap = agent._get_live_status_snapshot()

    assert snap["run_last"] is not None
    assert snap["run_last"]["task"] == "deploy"


# ── format_live_status ────────────────────────────────────────────────────────


def test_format_live_status_blocked():
    agent = _make_agent()
    snap = {
        "current_task": "run_shell", "last_run": "2026-04-17T10:00:00",
        "confidence": 0.4,
        "blocked_reason": "2 consecutive failures on 'run_shell'",
        "last_failure": None, "run_last": {},
    }
    result = agent._format_live_status(snap, "what is blocked")
    assert result is not None
    assert "blocked" in result.lower() or "consecutive" in result.lower(), result


def test_format_live_status_last_failure():
    agent = _make_agent()
    snap = {
        "current_task": "deploy", "last_run": "2026-04-17T10:00:00",
        "confidence": 0.5,
        "blocked_reason": None,
        "last_failure": {
            "intent": "deploy", "error": "connection refused", "ts": "2026-04-17T09:50:00"
        },
        "run_last": {},
    }
    result = agent._format_live_status(snap, "what failed most recently")
    assert result is not None
    assert "deploy" in result
    assert "connection refused" in result


def test_format_live_status_nothing_failed():
    agent = _make_agent()
    snap = {
        "current_task": "list_files", "last_run": "2026-04-17T10:00:00",
        "confidence": 0.9, "blocked_reason": None, "last_failure": None, "run_last": {},
    }
    result = agent._format_live_status(snap, "what failed")
    assert result is not None
    assert "no recent" in result.lower() or "no failure" in result.lower() or "failed" in result.lower()


def test_format_live_status_next_action_when_blocked():
    agent = _make_agent()
    snap = {
        "current_task": "run_shell",
        "last_run": "2026-04-17T10:00:00",
        "confidence": 0.3,
        "blocked_reason": "3 consecutive failures on 'run_shell'",
        "last_failure": {"intent": "run_shell", "error": "timeout", "ts": ""},
        "run_last": {},
    }
    result = agent._format_live_status(snap, "what happens next")
    assert result is not None
    assert "blocked" in result.lower() or "failure" in result.lower() or "resolve" in result.lower()


def test_format_live_status_next_action_when_clear():
    agent = _make_agent()
    snap = {
        "current_task": "list_files", "last_run": "2026-04-17T10:00:00",
        "confidence": 0.9, "blocked_reason": None,
        "last_failure": {"intent": "deploy", "error": "old error", "ts": ""},
        "run_last": {},
    }
    result = agent._format_live_status(snap, "what happens next")
    assert result is not None
    assert "deploy" in result.lower() or "retry" in result.lower() or "ready" in result.lower()


def test_format_live_status_inspect_uses_review_targets():
    agent = _make_agent()
    snap = {
        "current_task": "run_shell", "last_run": "2026-04-17T10:00:00",
        "confidence": 0.5, "blocked_reason": None, "last_failure": None,
        "run_last": {
            "task": "build",
            "touched_paths": ["src/foo.py"],
            "path_findings": [
                {"kind": "gap_risk", "detail": "1 path not addressed", "paths": ["src/foo.py"]}
            ],
        },
    }
    result = agent._format_live_status(snap, "what should I inspect next")
    assert result is not None
    assert "src/foo.py" in result or "gap" in result.lower() or "missed" in result.lower()


def test_format_live_status_no_state_returns_none():
    agent = _make_agent()
    snap = {
        "current_task": None, "last_run": None, "confidence": 0.0,
        "blocked_reason": None, "last_failure": None, "run_last": None,
    }
    result = agent._format_live_status(snap, "what are you doing right now")
    assert result is None, f"Expected None for empty state: {result!r}"


def test_format_live_status_working_on():
    agent = _make_agent()
    snap = {
        "current_task": "code_test", "last_run": "2026-04-17T10:00:00",
        "confidence": 0.75, "blocked_reason": None, "last_failure": None, "run_last": {},
    }
    result = agent._format_live_status(snap, "what are you working on")
    assert result is not None
    assert "code_test" in result


# ── try_live_status_response ──────────────────────────────────────────────────


def test_try_live_status_response_returns_text_for_status_query():
    agent = _make_agent()
    agent.current_state["current_task"] = "run_shell"
    agent.current_state["last_run"] = "2026-04-17T10:00:00"
    agent.current_state["confidence"] = 0.8

    result = agent._try_live_status_response("what are you doing right now")

    assert result is not None
    assert "run_shell" in result


def test_try_live_status_response_returns_none_for_unrelated():
    agent = _make_agent()
    assert agent._try_live_status_response("list files in /tmp") is None
    assert agent._try_live_status_response("run shell ls") is None


def test_try_live_status_response_blocked_state():
    agent = _make_agent()
    agent.current_state["blocked_reason"] = "2 consecutive failures on 'deploy'"

    result = agent._try_live_status_response("are you blocked?")

    assert result is not None
    assert "blocked" in result.lower() or "consecutive" in result.lower()


def test_try_live_status_response_no_state_no_fake_claim():
    """When no current_task and no run:last, does not fabricate 'currently running' text."""
    agent = _make_agent()
    agent.current_state["current_task"] = None
    agent.current_state.pop("blocked_reason", None)
    agent.current_state.pop("last_failure", None)

    result = agent._try_live_status_response("what are you working on")

    # Either None (nothing to say) or a factual "no active task" message
    if result is not None:
        assert "currently" not in result.lower() or "no" in result.lower(), (
            f"Should not claim to be currently doing something: {result!r}"
        )


# ── reflection_engine blocked detection ──────────────────────────────────────


def test_reflection_engine_sets_last_failure_on_fail():
    from agent.reflection_engine import ReflectionEngine
    from storage.memory import MemorySystem

    mem = MemorySystem()
    state = {
        "last_run": None, "current_task": None, "task_history": [],
        "memory_summary": {}, "decision_summary": {}, "execution_log": [],
        "confidence": 0.5,
    }

    class _FakeRetrieval:
        def retrieve_context_bundle(self, *a, **kw):
            return []

    class _FakeGovernor:
        pass

    eng = ReflectionEngine(mem, _FakeRetrieval(), _FakeGovernor(), state)
    reflection = {
        "timestamp": "2026-04-17T10:00:00",
        "intent": {"intent": "run_shell"},
        "execution_result": {"error": "permission denied"},
        "success": False,
        "confidence": 0.4,
    }
    eng.update_state(reflection)

    assert state.get("last_failure") is not None
    assert state["last_failure"]["intent"] == "run_shell"
    assert state["last_failure"]["error"] == "permission denied"


def test_reflection_engine_sets_blocked_after_consecutive_fails():
    from agent.reflection_engine import ReflectionEngine
    from storage.memory import MemorySystem

    mem = MemorySystem()
    state = {
        "last_run": None, "current_task": None, "task_history": [],
        "memory_summary": {}, "decision_summary": {}, "execution_log": [],
        "confidence": 0.5,
    }

    class _FakeRetrieval:
        def retrieve_context_bundle(self, *a, **kw):
            return []

    class _FakeGovernor:
        pass

    eng = ReflectionEngine(mem, _FakeRetrieval(), _FakeGovernor(), state)

    for _ in range(2):
        fail_reflection = {
            "timestamp": "2026-04-17T10:00:00",
            "intent": {"intent": "deploy"},
            "execution_result": {"error": "failed"},
            "success": False,
            "confidence": 0.3,
        }
        state["execution_log"].append(fail_reflection)
        eng.update_state(fail_reflection)

    assert state.get("blocked_reason") is not None
    assert "consecutive" in state["blocked_reason"]


def test_reflection_engine_clears_blocked_on_success():
    from agent.reflection_engine import ReflectionEngine
    from storage.memory import MemorySystem

    mem = MemorySystem()
    state = {
        "last_run": None, "current_task": None, "task_history": [],
        "memory_summary": {}, "decision_summary": {}, "execution_log": [],
        "confidence": 0.5,
        "blocked_reason": "2 consecutive failures on 'deploy'",
    }

    class _FakeRetrieval:
        def retrieve_context_bundle(self, *a, **kw):
            return []

    class _FakeGovernor:
        pass

    eng = ReflectionEngine(mem, _FakeRetrieval(), _FakeGovernor(), state)
    success_reflection = {
        "timestamp": "2026-04-17T10:00:00",
        "intent": {"intent": "deploy"},
        "execution_result": {"success": True},
        "success": True,
        "confidence": 0.9,
    }
    eng.update_state(success_reflection)

    assert state.get("blocked_reason") is None


# ── confidence / health queries ───────────────────────────────────────────────


def test_confidence_triggers_detected():
    for q in ["how confident are you", "what is your confidence", "success rate", "how healthy is karma", "are you healthy", "system health"]:
        assert AgentLoop._is_live_status_query(q), f"Expected live-status: {q!r}"


def test_format_live_status_confidence():
    agent = _make_agent()
    snap = {
        "current_task": "run_shell", "last_run": "2026-04-17T10:00:00",
        "confidence": 0.72,
        "blocked_reason": None, "last_failure": None,
        "decision_summary": {"success_rate": 0.85, "total_decisions": 42},
        "run_last": {},
    }
    result = agent._format_live_status(snap, "how confident are you")
    assert result is not None
    assert "72%" in result or "Confidence" in result


def test_format_live_status_success_rate():
    agent = _make_agent()
    snap = {
        "current_task": None, "last_run": None, "confidence": 0.6,
        "blocked_reason": None, "last_failure": None,
        "decision_summary": {"success_rate": 0.9, "total_decisions": 10},
        "run_last": {},
    }
    result = agent._format_live_status(snap, "what is your success rate")
    assert result is not None
    assert "90%" in result or "success" in result.lower()


def test_format_live_status_health_no_data():
    agent = _make_agent()
    snap = {
        "current_task": None, "last_run": None, "confidence": 0.0,
        "blocked_reason": None, "last_failure": None,
        "decision_summary": {}, "run_last": {},
    }
    result = agent._format_live_status(snap, "how healthy is karma")
    assert result is not None
    assert "no health data" in result.lower() or "no" in result.lower()
