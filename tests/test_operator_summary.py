"""Tests for operator summary, boot doctor, run detail, failure-first sort, and badges."""

from unittest.mock import MagicMock


from agent.agent_loop import AgentLoop, load_config


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_agent():
    cfg = load_config("config.json")
    return AgentLoop(cfg)


def _make_agent_clean():
    agent = _make_agent()
    agent.memory.facts.clear()
    return agent


def _make_health(status="healthy", n_issues=0, issues=None):
    h = MagicMock()
    h.run_check.return_value = {
        "status": status,
        "issues_found": n_issues,
        "issues": issues or [],
    }
    return h


def _seed_run_last(agent, task="build service", outcome="success", **extra):
    digest = {
        "run_id": "run:test01",
        "run_kind": "primary",
        "task": task,
        "outcome": outcome,
        "outcome_badge": outcome if outcome == "ok" else outcome,
        "ts": "2026-04-19T10:00:00",
        **extra,
    }
    agent.memory.save_fact(
        "run:last", digest, source="run_artifact", confidence=0.9, topic="run_history"
    )
    return digest


# ── outcome_badge ─────────────────────────────────────────────────────────────


def test_outcome_badge_known_values():
    from agent.services.run_history_service import outcome_badge

    assert outcome_badge("success") == "ok"
    assert outcome_badge("recovered") == "recovered"
    assert outcome_badge("failed") == "failed"
    assert outcome_badge("recovery_failed") == "recovery_failed"
    assert outcome_badge("partial") == "partial"
    assert outcome_badge("empty") == "empty"


def test_outcome_badge_unknown_falls_back():
    from agent.services.run_history_service import outcome_badge

    assert outcome_badge("something_else") == "unknown"
    assert outcome_badge("") == "unknown"
    assert outcome_badge(None) == "unknown"


def test_persist_run_digest_stores_outcome_badge():

    agent = _make_agent_clean()
    artifact = {
        "task": "test task",
        "outcome": "success",
        "steps": [{"step": 1, "status": "done", "action": "A", "target": "x"}],
        "failed": [],
        "outputs": [],
        "recovery": None,
    }

    saved: dict = {}
    agent.memory.save_fact = lambda k, v, **kw: saved.update({k: v})
    agent._persist_run_digest(artifact, "")

    digest = saved.get("run:last") or {}
    assert "outcome_badge" in digest, f"outcome_badge missing: {list(digest.keys())}"
    assert digest["outcome_badge"] == "ok"


def test_persist_run_digest_failed_outcome_badge():
    agent = _make_agent_clean()
    artifact = {
        "task": "failing task",
        "outcome": "failed",
        "steps": [{"step": 1, "status": "failed", "action": "A", "target": "x"}],
        "failed": [{"step": 1, "action": "A", "target": "x", "error": "oops"}],
        "outputs": [],
        "recovery": None,
    }

    saved: dict = {}
    agent.memory.save_fact = lambda k, v, **kw: saved.update({k: v})
    agent._persist_run_digest(artifact, "")

    digest = saved.get("run:last") or {}
    assert digest.get("outcome_badge") == "failed"


# ── format_compact_output ─────────────────────────────────────────────────────


def test_format_compact_output_string_multiline():
    from agent.services.run_history_service import format_compact_output

    result = format_compact_output("line one\nline two\nline three")
    assert "line one" in result
    assert "|" in result or "line one" in result  # collapsed with separator


def test_format_compact_output_list_with_count():
    from agent.services.run_history_service import format_compact_output

    items = list(range(15))
    result = format_compact_output(items)
    assert "+5 more" in result


def test_format_compact_output_dict_compact():
    from agent.services.run_history_service import format_compact_output

    result = format_compact_output({"a": 1, "b": 2})
    assert "a=1" in result
    assert "b=2" in result


def test_format_compact_output_none_returns_empty():
    from agent.services.run_history_service import format_compact_output

    assert format_compact_output(None) == ""


# ── format_error_compact ──────────────────────────────────────────────────────


def test_format_error_compact_surfaces_error_line():
    from agent.services.run_history_service import format_error_compact

    tb = "Traceback (most recent call last):\n  File x.py, line 10\nPermissionError: [Errno 13] denied"
    result = format_error_compact(tb)
    assert "PermissionError" in result
    assert "Traceback" not in result


def test_format_error_compact_plain_string():
    from agent.services.run_history_service import format_error_compact

    assert format_error_compact("connection refused") == "connection refused"


def test_format_error_compact_empty():
    from agent.services.run_history_service import format_error_compact

    assert format_error_compact("") == ""
    assert format_error_compact(None) == ""


# ── build_run_detail ──────────────────────────────────────────────────────────


def test_build_run_detail_returns_enriched_dict():
    from agent.services.run_history_service import build_run_detail

    agent = _make_agent_clean()
    _seed_run_last(
        agent,
        task="deploy service",
        outcome="failed",
        critic_issues=["step 2 timed out — reduce scope"],
        critic_lesson="step 2 timed out — reduce scope",
        key_error="connection refused",
        n_steps=3,
        n_failed=1,
    )

    detail = build_run_detail("run:last", agent.memory)
    assert detail is not None
    assert detail["task"] == "deploy service"
    assert detail["outcome"] == "failed"
    assert detail["outcome_badge"] is not None
    assert detail["critic_issues"] == ["step 2 timed out — reduce scope"]
    assert detail["critic_lesson"] == "step 2 timed out — reduce scope"
    assert detail["key_error"] == "connection refused"
    assert detail["n_steps"] == 3
    assert detail["n_failed"] == 1


def test_build_run_detail_missing_key_returns_none():
    from agent.services.run_history_service import build_run_detail

    agent = _make_agent_clean()
    result = build_run_detail("run:nonexistent", agent.memory)
    assert result is None


def test_get_run_detail_delegates_to_service():
    """AgentLoop.get_run_detail returns enriched dict for run:last."""
    agent = _make_agent_clean()
    _seed_run_last(agent, task="test task", outcome="success")

    detail = agent.get_run_detail("run:last")
    assert detail is not None
    assert detail["task"] == "test task"
    assert detail["outcome_badge"] is not None


def test_build_run_detail_all_required_keys_present():
    from agent.services.run_history_service import build_run_detail

    agent = _make_agent_clean()
    _seed_run_last(agent, task="t", outcome="success")
    detail = build_run_detail("run:last", agent.memory)
    for key in (
        "run_id", "run_kind", "outcome_badge", "task", "outcome", "ts",
        "n_steps", "n_failed", "n_skipped", "completed_steps", "failed_steps",
        "key_output", "key_error", "recovery_outcome", "recovery_run_id",
        "path_findings", "touched_paths", "critic_issues", "critic_lesson", "summary",
    ):
        assert key in detail, f"Missing key: {key}"


# ── failure_first_sort ────────────────────────────────────────────────────────


def test_failure_first_sort_orders_failures_before_successes():
    from agent.services.run_history_service import failure_first_sort

    results = [
        {"value": {"outcome": "success", "task": "ok1"}},
        {"value": {"outcome": "failed", "task": "fail1"}},
        {"value": {"outcome": "recovered", "task": "rec1"}},
        {"value": {"outcome": "recovery_failed", "task": "fail2"}},
        {"value": {"outcome": "success", "task": "ok2"}},
    ]
    sorted_results = failure_first_sort(results)
    outcomes = [r["value"]["outcome"] for r in sorted_results]

    # Failures should come first
    assert outcomes[0] in ("failed", "recovery_failed")
    assert outcomes[1] in ("failed", "recovery_failed")
    # Recovered before success
    assert outcomes[2] == "recovered"
    # Successes last
    assert outcomes[3] == "success"
    assert outcomes[4] == "success"


def test_failure_first_sort_stable_within_tier():
    from agent.services.run_history_service import failure_first_sort

    results = [
        {"value": {"outcome": "failed", "task": "fail_a"}},
        {"value": {"outcome": "failed", "task": "fail_b"}},
    ]
    sorted_results = failure_first_sort(results)
    # Stable: order within tier preserved
    assert sorted_results[0]["value"]["task"] == "fail_a"
    assert sorted_results[1]["value"]["task"] == "fail_b"


def test_format_retrieval_results_failure_first_flag():
    from agent.services.run_history_service import format_retrieval_results

    output = {
        "method": "run_history",
        "results": [
            {"key": "run:s1", "value": {"task": "ok run", "outcome": "success",
                                         "run_kind": "primary", "summary": "ok run: success",
                                         "touched_paths": [], "path_findings": []}},
            {"key": "run:f1", "value": {"task": "failed run", "outcome": "failed",
                                         "run_kind": "primary", "summary": "failed run: failed",
                                         "touched_paths": [], "path_findings": []}},
        ],
    }
    text = format_retrieval_results(output, failure_first=True)
    assert text is not None
    # "failed run" should appear before "ok run"
    idx_fail = text.find("failed run")
    idx_ok = text.find("ok run")
    assert idx_fail < idx_ok, f"Expected failure-first ordering: {text!r}"


# ── unified operator summary ──────────────────────────────────────────────────


def test_build_operator_summary_shape():
    agent = _make_agent_clean()
    agent.health = _make_health()

    summary = agent.build_operator_summary()

    for key in ("current_task", "blocked_reason", "confidence", "last_run",
                "last_failure", "latest_recovery", "session", "health", "ts"):
        assert key in summary, f"Missing key: {key}"


def test_build_operator_summary_health_present():
    agent = _make_agent_clean()
    agent.health = _make_health(status="warning", n_issues=1,
                                issues=[{"severity": "warn", "issue": "log bloat", "subsystem": "logs"}])

    summary = agent.build_operator_summary()
    health = summary.get("health")
    assert health is not None
    assert health["status"] == "warning"
    assert health["issues_found"] == 1


def test_build_operator_summary_last_run_with_badge():
    agent = _make_agent_clean()
    agent.health = _make_health()
    _seed_run_last(agent, task="build service", outcome="failed")

    summary = agent.build_operator_summary()
    last_run = summary.get("last_run")
    assert last_run is not None
    assert last_run["task"] == "build service"
    assert last_run["outcome_badge"] == "failed"


def test_build_operator_summary_session_counts():
    agent = _make_agent_clean()
    agent.health = _make_health()
    agent.current_state["session_start_ts"] = "2026-04-19T09:00:00"
    agent.current_state["execution_log"] = [
        {"timestamp": "2026-04-19T10:00:00", "intent": {"intent": "task_a"},
         "execution_result": {}, "success": True, "confidence": 0.9},
        {"timestamp": "2026-04-19T10:01:00", "intent": {"intent": "task_b"},
         "execution_result": {"error": "oops"}, "success": False, "confidence": 0.3},
    ]

    summary = agent.build_operator_summary()
    sess = summary.get("session") or {}
    assert sess.get("total") == 2
    assert sess.get("succeeded") == 1
    assert sess.get("failed") == 1


def test_format_operator_summary_text_output():
    agent = _make_agent_clean()
    agent.health = _make_health()
    _seed_run_last(agent, task="deploy pipeline", outcome="success")

    text = agent.format_operator_summary()
    assert text is not None
    assert isinstance(text, str)
    assert len(text) > 0


def test_format_operator_summary_shows_last_run():
    agent = _make_agent_clean()
    agent.health = _make_health()
    _seed_run_last(agent, task="run tests", outcome="failed")

    text = agent.format_operator_summary()
    assert "run tests" in text
    assert "failed" in text.lower()


def test_format_operator_summary_shows_blocked():
    agent = _make_agent_clean()
    agent.health = _make_health()
    agent.current_state["blocked_reason"] = "3 consecutive failures on 'deploy'"

    text = agent.format_operator_summary()
    assert "BLOCKED" in text
    assert "3 consecutive" in text


def test_format_operator_summary_shows_critic_lesson():
    agent = _make_agent_clean()
    agent.health = _make_health()
    _seed_run_last(agent, task="build", outcome="failed",
                   critic_lesson="Step 2 timed out — reduce scope")

    text = agent.format_operator_summary()
    assert "Lesson:" in text
    assert "reduce scope" in text


def test_format_operator_summary_no_state_returns_fallback():
    agent = _make_agent_clean()
    agent.health = _make_health()

    text = agent.format_operator_summary()
    assert text is not None
    assert len(text) > 0


# ── boot doctor ───────────────────────────────────────────────────────────────


def test_build_boot_doctor_summary_shape():
    agent = _make_agent_clean()
    agent.health = _make_health()

    summary = agent.build_boot_doctor_summary()

    for key in ("status", "health_status", "issues", "warnings",
                "last_run", "last_incomplete_task", "recommend_recovery", "session_start"):
        assert key in summary, f"Missing key: {key}"


def test_build_boot_doctor_healthy():
    agent = _make_agent_clean()
    agent.health = _make_health(status="healthy")
    _seed_run_last(agent, task="build service", outcome="success")

    summary = agent.build_boot_doctor_summary()
    assert summary["status"] == "healthy"
    assert summary["recommend_recovery"] is False
    assert summary["last_incomplete_task"] is None


def test_build_boot_doctor_failed_last_run_triggers_recovery():
    agent = _make_agent_clean()
    agent.health = _make_health(status="healthy")
    _seed_run_last(agent, task="deploy", outcome="failed")

    summary = agent.build_boot_doctor_summary()
    assert summary["recommend_recovery"] is True
    assert summary["last_incomplete_task"] is not None
    assert summary["last_incomplete_task"]["task"] == "deploy"
    assert "warning" in summary["status"] or summary["status"] == "warning"


def test_build_boot_doctor_critical_issue():
    agent = _make_agent_clean()
    agent.health = _make_health(
        status="critical", n_issues=1,
        issues=[{"severity": "critical", "issue": "memory corruption", "subsystem": "memory"}]
    )

    summary = agent.build_boot_doctor_summary()
    assert summary["status"] == "critical"
    assert len(summary["issues"]) >= 1
    assert "memory corruption" in summary["issues"][0]


def test_format_boot_doctor_healthy():
    agent = _make_agent_clean()
    agent.health = _make_health()

    text = agent.format_boot_doctor_summary()
    assert "Boot check:" in text
    assert "healthy" in text.lower()


def test_format_boot_doctor_warns_on_failed_last_run():
    agent = _make_agent_clean()
    agent.health = _make_health()
    _seed_run_last(agent, task="broken job", outcome="recovery_failed")

    text = agent.format_boot_doctor_summary()
    assert "broken job" in text or "recovery_failed" in text
    assert "Recovery recommended" in text


def test_format_boot_doctor_critical_issue_shown():
    agent = _make_agent_clean()
    agent.health = _make_health(
        status="critical", n_issues=1,
        issues=[{"severity": "critical", "issue": "disk full", "subsystem": "storage"}]
    )

    text = agent.format_boot_doctor_summary()
    assert "[critical]" in text
    assert "disk full" in text
