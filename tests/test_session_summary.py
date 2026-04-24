"""Tests for session/boot summary and self-check introspection lanes."""

from unittest.mock import MagicMock


from agent.agent_loop import AgentLoop, load_config


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_agent():
    cfg = load_config("config.json")
    return AgentLoop(cfg)


def _make_log_entry(intent: str, success: bool, error: str = "", ts: str = "2026-04-17T10:00:00") -> dict:
    return {
        "timestamp": ts,
        "intent": {"intent": intent},
        "execution_result": {"success": success, "error": error if not success else ""},
        "success": success,
        "confidence": 0.8 if success else 0.3,
    }


# ── session summary classifier ────────────────────────────────────────────────


def test_session_summary_triggers_detected():
    triggers = [
        "what did you do last session",
        "what happened this session",
        "summarize recent work",
        "what tasks ran this session",
        "session summary",
        "boot summary",
        "what did karma do this session",
        "since startup what happened",
        "since boot what ran",
        "what have you done",
        "recent work",
    ]
    for q in triggers:
        assert AgentLoop._is_session_summary_query(q), f"Expected session-summary trigger: {q!r}"


def test_session_summary_antitokens_suppress():
    suppressed = [
        "how does karma architecture work",
        "explain the history of the project",
        "history of sessions",
    ]
    for q in suppressed:
        assert not AgentLoop._is_session_summary_query(q), f"Should be suppressed: {q!r}"


def test_session_summary_does_not_match_unrelated():
    unrelated = [
        "list files in /tmp",
        "run shell ls",
        "what is the capital of France",
        "deploy to production",
        "what are you doing right now",
    ]
    for q in unrelated:
        assert not AgentLoop._is_session_summary_query(q), f"Should not match: {q!r}"


# ── _build_session_summary ────────────────────────────────────────────────────


def test_build_session_summary_empty_no_logs():
    agent = _make_agent()
    agent.current_state["execution_log"] = []
    agent.current_state["session_start_ts"] = "2026-04-17T10:00:00"

    summary = agent._build_session_summary()

    assert summary["empty"] is True
    assert "session_start" in summary


def test_build_session_summary_empty_uses_run_last_fallback():
    agent = _make_agent()
    agent.current_state["execution_log"] = []
    agent.current_state["session_start_ts"] = "2026-04-17T10:00:00"
    agent.memory.save_fact(
        "run:last",
        {"task": "deploy", "outcome": "success", "path_findings": [], "touched_paths": []},
        source="run_artifact", confidence=0.9, topic="run_history",
    )

    summary = agent._build_session_summary()

    assert summary["empty"] is True
    assert summary.get("run_last") is not None
    assert summary["run_last"]["task"] == "deploy"


def test_build_session_summary_filters_to_current_session():
    agent = _make_agent()
    session_start = "2026-04-17T10:00:00"
    agent.current_state["session_start_ts"] = session_start

    old_entry = _make_log_entry("old_task", True, ts="2026-04-16T09:00:00")
    new_entry = _make_log_entry("new_task", True, ts="2026-04-17T10:30:00")
    agent.current_state["execution_log"] = [old_entry, new_entry]

    summary = agent._build_session_summary()

    assert summary["empty"] is False
    assert summary["total"] == 1
    assert "new_task" in summary["success_intents"]


def test_build_session_summary_counts_ok_and_failed():
    agent = _make_agent()
    agent.current_state["session_start_ts"] = "2026-04-17T09:00:00"
    agent.current_state["execution_log"] = [
        _make_log_entry("task_a", True, ts="2026-04-17T10:00:00"),
        _make_log_entry("task_b", True, ts="2026-04-17T10:01:00"),
        _make_log_entry("task_c", False, error="oops", ts="2026-04-17T10:02:00"),
    ]

    summary = agent._build_session_summary()

    assert summary["n_succeeded"] == 2
    assert summary["n_failed"] == 1
    assert summary["total"] == 3


def test_build_session_summary_fail_entries_include_error():
    agent = _make_agent()
    agent.current_state["session_start_ts"] = "2026-04-17T09:00:00"
    agent.current_state["execution_log"] = [
        _make_log_entry("deploy", False, error="connection refused", ts="2026-04-17T10:00:00"),
    ]

    summary = agent._build_session_summary()

    assert summary["fail_entries"]
    assert summary["fail_entries"][0]["intent"] == "deploy"
    assert "connection refused" in summary["fail_entries"][0]["error"]


def test_build_session_summary_includes_blocked_reason():
    agent = _make_agent()
    agent.current_state["session_start_ts"] = "2026-04-17T09:00:00"
    agent.current_state["blocked_reason"] = "2 consecutive failures on 'deploy'"
    agent.current_state["execution_log"] = [
        _make_log_entry("deploy", False, ts="2026-04-17T10:00:00"),
    ]

    summary = agent._build_session_summary()

    assert summary["blocked_reason"] == "2 consecutive failures on 'deploy'"


def test_build_session_summary_no_session_start_falls_back_to_last_20():
    agent = _make_agent()
    agent.current_state.pop("session_start_ts", None)
    agent.current_state["execution_log"] = [
        _make_log_entry(f"task_{i}", True, ts=f"2026-04-17T{10+i//60:02d}:{i%60:02d}:00")
        for i in range(25)
    ]

    summary = agent._build_session_summary()

    assert summary["empty"] is False
    assert summary["total"] == 20


# ── _format_session_summary ───────────────────────────────────────────────────


def test_format_session_summary_empty_no_run_last():
    agent = _make_agent()
    result = agent._format_session_summary({"empty": True, "session_start": "", "run_last": None})
    assert result is not None
    assert "no tasks" in result.lower()


def test_format_session_summary_empty_with_run_last():
    agent = _make_agent()
    result = agent._format_session_summary({
        "empty": True,
        "session_start": "",
        "run_last": {"task": "build", "outcome": "success"},
    })
    assert result is not None
    assert "build" in result
    assert "success" in result.lower() or "last" in result.lower()


def test_format_session_summary_header_includes_counts():
    agent = _make_agent()
    summary = {
        "empty": False,
        "session_start": "2026-04-17T10:00:00",
        "total": 5,
        "n_succeeded": 3,
        "n_failed": 2,
        "success_intents": ["task_a", "task_b"],
        "fail_entries": [{"intent": "deploy", "error": "timeout"}],
        "blocked_reason": None,
        "last_intent": "task_b",
    }
    result = agent._format_session_summary(summary)
    assert result is not None
    assert "5" in result
    assert "3" in result
    assert "2" in result


def test_format_session_summary_includes_success_intents():
    agent = _make_agent()
    summary = {
        "empty": False,
        "session_start": "2026-04-17T10:00:00",
        "total": 2,
        "n_succeeded": 2,
        "n_failed": 0,
        "success_intents": ["list_files", "run_shell"],
        "fail_entries": [],
        "blocked_reason": None,
        "last_intent": "run_shell",
    }
    result = agent._format_session_summary(summary)
    assert "list_files" in result
    assert "run_shell" in result


def test_format_session_summary_includes_failure_with_error():
    agent = _make_agent()
    summary = {
        "empty": False,
        "session_start": "2026-04-17T10:00:00",
        "total": 1,
        "n_succeeded": 0,
        "n_failed": 1,
        "success_intents": [],
        "fail_entries": [{"intent": "deploy", "error": "connection refused"}],
        "blocked_reason": None,
        "last_intent": "deploy",
    }
    result = agent._format_session_summary(summary)
    assert "deploy" in result
    assert "connection refused" in result


def test_format_session_summary_shows_blocked():
    agent = _make_agent()
    summary = {
        "empty": False,
        "session_start": "2026-04-17T10:00:00",
        "total": 3,
        "n_succeeded": 1,
        "n_failed": 2,
        "success_intents": ["task_a"],
        "fail_entries": [{"intent": "deploy", "error": "failed"}],
        "blocked_reason": "2 consecutive failures on 'deploy'",
        "last_intent": "deploy",
    }
    result = agent._format_session_summary(summary)
    assert "blocked" in result.lower() or "consecutive" in result.lower()


# ── _try_session_summary_response integration ─────────────────────────────────


def test_try_session_summary_response_returns_text_for_trigger():
    agent = _make_agent()
    agent.current_state["session_start_ts"] = "2026-04-17T09:00:00"
    agent.current_state["execution_log"] = [
        _make_log_entry("run_shell", True, ts="2026-04-17T10:00:00"),
    ]

    result = agent._try_session_summary_response("what did you do this session")

    assert result is not None
    assert "run_shell" in result


def test_try_session_summary_response_none_for_unrelated():
    agent = _make_agent()
    assert agent._try_session_summary_response("list files in /tmp") is None
    assert agent._try_session_summary_response("what are you doing right now") is None


def test_try_session_summary_response_empty_session_does_not_fabricate():
    agent = _make_agent()
    agent.current_state["execution_log"] = []
    agent.current_state["session_start_ts"] = "2026-04-17T10:00:00"

    result = agent._try_session_summary_response("session summary")

    assert result is not None
    assert "no tasks" in result.lower()


def test_try_session_summary_response_with_failures_shows_them():
    agent = _make_agent()
    agent.current_state["session_start_ts"] = "2026-04-17T09:00:00"
    agent.current_state["execution_log"] = [
        _make_log_entry("deploy", False, error="permission denied", ts="2026-04-17T10:00:00"),
    ]

    result = agent._try_session_summary_response("what happened this session")

    assert result is not None
    assert "deploy" in result


# ── self-check classifier ─────────────────────────────────────────────────────


def test_self_check_triggers_detected():
    triggers = [
        "self-check",
        "self check",
        "run self check",
        "diagnose yourself",
        "diagnose karma",
        "run diagnostics",
        "quick diagnostics",
        "check yourself",
        "run a check",
        "run a quick self-check",
    ]
    for q in triggers:
        assert AgentLoop._is_self_check_query(q), f"Expected self-check trigger: {q!r}"


def test_self_check_does_not_match_unrelated():
    unrelated = [
        "list files",
        "what did you do",
        "how healthy is karma",
        "what is blocked",
    ]
    for q in unrelated:
        assert not AgentLoop._is_self_check_query(q), f"Should not match: {q!r}"


# ── _try_self_check_response ──────────────────────────────────────────────────


def test_try_self_check_response_returns_none_for_unrelated():
    agent = _make_agent()
    assert agent._try_self_check_response("list files") is None
    assert agent._try_self_check_response("what are you doing") is None


def test_try_self_check_response_clean_health():
    agent = _make_agent()
    agent.health = MagicMock()
    agent.health.run_check.return_value = {
        "status": "healthy",
        "issues_found": 0,
        "issues": [],
    }

    result = agent._try_self_check_response("self-check")

    assert result is not None
    assert "healthy" in result.lower()
    assert "no issues" in result.lower()


def test_try_self_check_response_issues_listed():
    agent = _make_agent()
    agent.health = MagicMock()
    agent.health.run_check.return_value = {
        "status": "degraded",
        "issues_found": 2,
        "issues": [
            {"severity": "warn", "subsystem": "memory", "issue": "high usage"},
            {"severity": "error", "subsystem": "tool", "issue": "tool_x unavailable"},
        ],
    }

    result = agent._try_self_check_response("run diagnostics")

    assert result is not None
    assert "2" in result
    assert "memory" in result
    assert "tool" in result
    assert "warn" in result.lower() or "error" in result.lower()


def test_try_self_check_response_compact_not_verbose():
    agent = _make_agent()
    agent.health = MagicMock()
    agent.health.run_check.return_value = {
        "status": "healthy",
        "issues_found": 0,
        "issues": [],
    }

    result = agent._try_self_check_response("diagnose karma")

    assert result is not None
    assert len(result.splitlines()) <= 7, f"Too verbose: {result!r}"


# ── ordering: self-check takes priority over session-summary ──────────────────


def test_self_check_priority_over_session_summary():
    """Queries matching self-check are routed there, not to session-summary."""
    agent = _make_agent()
    agent.health = MagicMock()
    agent.health.run_check.return_value = {
        "status": "healthy", "issues_found": 0, "issues": []
    }
    agent.current_state["session_start_ts"] = "2026-04-17T09:00:00"
    agent.current_state["execution_log"] = [
        _make_log_entry("run_shell", True, ts="2026-04-17T10:00:00"),
    ]

    sc = agent._try_self_check_response("self-check")
    ss = agent._try_session_summary_response("self-check")

    assert sc is not None
    # self-check query should not be captured by session-summary
    assert ss is None


# ── no regression on live-status ─────────────────────────────────────────────


def test_session_summary_does_not_steal_live_status_query():
    """'what are you doing right now' should not match session-summary."""
    assert not AgentLoop._is_session_summary_query("what are you doing right now")
    assert not AgentLoop._is_session_summary_query("what is blocked")
    assert not AgentLoop._is_session_summary_query("are you stuck")
    assert not AgentLoop._is_session_summary_query("show status")


def test_live_status_does_not_steal_session_summary_query():
    """'what did you do last session' should not match live-status."""
    from agent.agent_loop import AgentLoop as AL
    assert not AL._is_live_status_query("what did you do last session")
    assert not AL._is_live_status_query("session summary")
    assert not AL._is_live_status_query("since boot what happened")
