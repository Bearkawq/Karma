"""Smoke / integration tests for core Karma flows.

Covers 5 end-to-end paths through the real service layer without model calls:
  1. Planned multi-step success run — persist → detail → operator summary
  2. Failed single-tool run — persist → boot doctor flags recovery
  3. Recovery run — parent + child digests stored, linkage wired
  4. Restart / resume — memory survives across MemorySystem instances
  5. Complex state — operator summary + failure-first retrieval ordering

These tests do NOT duplicate unit coverage of individual helpers.  They prove
that the data written in one service is correctly read by another.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, Optional
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(facts_path: Optional[str] = None):
    """Create an in-process MemorySystem, optionally backed by a real temp file."""
    from storage.memory import MemorySystem

    if facts_path is None:
        # Use a temp file that stays for the duration of the test
        fd, facts_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(facts_path)  # let MemorySystem create it fresh
    return MemorySystem(
        episodic_file=os.devnull,
        facts_file=facts_path,
        tasks_file=os.devnull,
    )


def _make_health(status: str = "healthy", n_issues: int = 0, issues=None):
    h = MagicMock()
    h.run_check.return_value = {
        "status": status,
        "issues_found": n_issues,
        "issues": issues or [],
    }
    return h


def _run_history_svc(memory):
    from agent.services.run_history_service import RunHistoryService
    return RunHistoryService(memory)


def _status_query_svc(memory, state=None, health=None):
    from agent.services.status_query_service import StatusQueryService
    if state is None:
        state = {}
    if health is None:
        health = _make_health()
    return StatusQueryService(state, memory, health)


# ── artifact builders ──────────────────────────────────────────────────────


def _step(n: int, status: str, action: str, target: str = "", error: str = ""):
    s: Dict[str, Any] = {"step": n, "status": status, "action": action, "target": target}
    if error:
        s["error"] = error
    return s


def _plan_artifact(
    task: str,
    outcome: str,
    steps=None,
    failed=None,
    recovery=None,
    run_kind: str = "primary",
    **extra,
) -> Dict[str, Any]:
    return {
        "task": task,
        "outcome": outcome,
        "run_kind": run_kind,
        "steps": steps or [],
        "failed": failed or [],
        "outputs": [],
        "recovery": recovery,
        **extra,
    }


def _tool_artifact(
    task: str,
    outcome: str,
    tool: str = "run_shell",
    key_output: str = "",
    key_error: str = "",
) -> Dict[str, Any]:
    return {
        "task": task,
        "outcome": outcome,
        "run_kind": "tool",
        "tool": tool,
        "target": "",
        "key_output": key_output,
        "key_error": key_error,
        "steps": [],
        "failed": [],
        "outputs": [],
        "recovery": None,
    }


def _recovery_execution(
    task: str,
    outcome: str,
    steps=None,
    failed=None,
) -> Dict[str, Any]:
    return {
        "task": task,
        "outcome": outcome,
        "steps": steps or [],
        "failed": failed or [],
    }


# ---------------------------------------------------------------------------
# Flow 1: Planned multi-step success run
# ---------------------------------------------------------------------------


class TestPlannedSuccessRun:
    """Persist a 3-step success plan and verify the full operator read path."""

    def setup_method(self):
        self.memory = _make_memory()
        self.svc = _run_history_svc(self.memory)
        self.artifact = _plan_artifact(
            task="deploy pipeline",
            outcome="success",
            steps=[
                _step(1, "done", "write_file", "deploy.sh"),
                _step(2, "done", "run_shell", "chmod +x deploy.sh"),
                _step(3, "done", "run_shell", "./deploy.sh"),
            ],
        )
        self.svc.persist_run_digest(self.artifact, "deployed successfully")

    def test_run_last_written(self):
        val = self.memory.get_fact_value("run:last")
        assert isinstance(val, dict)
        assert val["task"] == "deploy pipeline"
        assert val["outcome"] == "success"

    def test_outcome_badge_ok(self):
        val = self.memory.get_fact_value("run:last")
        assert val["outcome_badge"] == "ok"

    def test_step_counts_correct(self):
        val = self.memory.get_fact_value("run:last")
        assert val["n_steps"] == 3
        assert val["n_failed"] == 0

    def test_completed_steps_populated(self):
        val = self.memory.get_fact_value("run:last")
        assert len(val["completed_steps"]) == 3
        assert val["completed_steps"][0]["action"] == "write_file"

    def test_hashed_run_key_also_stored(self):
        run_keys = [k for k in self.memory.facts if k.startswith("run:") and k != "run:last"]
        assert len(run_keys) == 1

    def test_build_run_detail_all_keys(self):
        from agent.services.run_history_service import build_run_detail
        detail = build_run_detail("run:last", self.memory)
        assert detail is not None
        for key in (
            "run_id", "run_kind", "outcome_badge", "task", "outcome", "ts",
            "n_steps", "n_failed", "n_skipped", "completed_steps", "failed_steps",
            "key_output", "key_error", "recovery_outcome", "recovery_run_id",
            "path_findings", "touched_paths", "critic_issues", "critic_lesson", "summary",
        ):
            assert key in detail, f"build_run_detail missing key: {key}"

    def test_operator_summary_reflects_run(self):
        svc = _status_query_svc(self.memory)
        summary = svc.build_operator_summary()
        last_run = summary.get("last_run")
        assert last_run is not None
        assert last_run["task"] == "deploy pipeline"
        assert last_run["outcome_badge"] == "ok"

    def test_operator_summary_text_includes_task(self):
        svc = _status_query_svc(self.memory)
        summary = svc.build_operator_summary()
        text = svc.format_operator_summary(summary)
        assert "deploy pipeline" in text
        assert "ok" in text.lower() or "success" in text.lower()

    def test_boot_doctor_healthy_after_success(self):
        svc = _status_query_svc(self.memory, health=_make_health("healthy"))
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] == "healthy"
        assert summary["recommend_recovery"] is False


# ---------------------------------------------------------------------------
# Flow 2: Failed single-tool run
# ---------------------------------------------------------------------------


class TestFailedSingleToolRun:
    """Persist a single-tool failure and verify boot doctor + retrieval path."""

    def setup_method(self):
        self.memory = _make_memory()
        self.svc = _run_history_svc(self.memory)
        self.artifact = _tool_artifact(
            task="run linter",
            outcome="failed",
            tool="run_shell",
            key_error="PermissionError: [Errno 13] Permission denied: '/etc/config'",
        )
        self.svc.persist_run_digest(self.artifact, "")

    def test_run_last_has_failed_badge(self):
        val = self.memory.get_fact_value("run:last")
        assert val["outcome_badge"] == "failed"

    def test_key_error_stored_compact(self):
        val = self.memory.get_fact_value("run:last")
        # format_error_compact should have stripped traceback noise
        err = val.get("key_error", "")
        assert "PermissionError" in err or "Permission denied" in err

    def test_run_kind_is_tool(self):
        val = self.memory.get_fact_value("run:last")
        assert val["run_kind"] == "tool"

    def test_boot_doctor_recommends_recovery(self):
        svc = _status_query_svc(self.memory, health=_make_health("healthy"))
        summary = svc.build_boot_doctor_summary()
        assert summary["recommend_recovery"] is True
        assert summary["last_incomplete_task"] is not None
        assert summary["last_incomplete_task"]["task"] == "run linter"

    def test_boot_doctor_status_is_warning(self):
        svc = _status_query_svc(self.memory, health=_make_health("healthy"))
        summary = svc.build_boot_doctor_summary()
        assert summary["status"] in ("warning", "critical")

    def test_boot_doctor_text_mentions_task(self):
        svc = _status_query_svc(self.memory, health=_make_health("healthy"))
        summary = svc.build_boot_doctor_summary()
        text = svc.format_boot_doctor_summary(summary)
        assert "run linter" in text or "Recovery recommended" in text

    def test_format_retrieval_results_shows_failure(self):
        from agent.services.run_history_service import format_retrieval_results
        output = {
            "method": "run_history",
            "results": [
                {
                    "key": "run:last",
                    "value": self.memory.get_fact_value("run:last"),
                }
            ],
        }
        text = format_retrieval_results(output)
        assert text is not None
        assert "run linter" in text or "failed" in text.lower()

    def test_no_recovery_child_stored(self):
        rec_keys = [k for k in self.memory.facts if k.startswith("run:recovery:")]
        assert len(rec_keys) == 0

    def test_build_run_detail_has_outcome_badge(self):
        from agent.services.run_history_service import build_run_detail
        detail = build_run_detail("run:last", self.memory)
        assert detail is not None
        assert detail["outcome_badge"] == "failed"


# ---------------------------------------------------------------------------
# Flow 3: Recovery run — parent + child digests
# ---------------------------------------------------------------------------


class TestRecoveryRun:
    """Persist a plan with recovery execution; verify parent+child linkage."""

    def setup_method(self):
        self.memory = _make_memory()
        self.svc = _run_history_svc(self.memory)
        recovery_exec = _recovery_execution(
            task="retry deploy pipeline",
            outcome="recovered",
            steps=[
                _step(1, "done", "run_shell", "rollback.sh"),
                _step(2, "done", "run_shell", "./deploy.sh"),
            ],
        )
        self.artifact = _plan_artifact(
            task="deploy pipeline",
            outcome="recovered",
            steps=[
                _step(1, "done", "write_file", "deploy.sh"),
                _step(2, "failed", "run_shell", "./deploy.sh", error="connection refused"),
                _step(3, "skipped", "run_shell", "cleanup.sh"),
            ],
            failed=[_step(2, "failed", "run_shell", "./deploy.sh", error="connection refused")],
            recovery={
                "outcome": "recovered",
                "recovery_execution": recovery_exec,
            },
        )
        self.svc.persist_run_digest(self.artifact, "recovered after connection issue")

    def test_parent_run_kind_primary(self):
        val = self.memory.get_fact_value("run:last")
        assert val["run_kind"] == "primary"

    def test_parent_outcome_badge_recovered(self):
        val = self.memory.get_fact_value("run:last")
        assert val["outcome_badge"] == "recovered"

    def test_parent_recovery_outcome_set(self):
        val = self.memory.get_fact_value("run:last")
        assert val.get("recovery_outcome") == "recovered"

    def test_parent_recovery_run_id_set(self):
        val = self.memory.get_fact_value("run:last")
        rec_id = val.get("recovery_run_id")
        assert rec_id is not None
        assert rec_id.startswith("run:recovery:")

    def test_child_digest_stored_in_memory(self):
        val = self.memory.get_fact_value("run:last")
        rec_id = val["recovery_run_id"]
        child = self.memory.get_fact_value(rec_id)
        assert child is not None
        assert isinstance(child, dict)

    def test_child_run_kind_is_recovery(self):
        val = self.memory.get_fact_value("run:last")
        child = self.memory.get_fact_value(val["recovery_run_id"])
        assert child["run_kind"] == "recovery"

    def test_child_parent_linkage(self):
        val = self.memory.get_fact_value("run:last")
        child = self.memory.get_fact_value(val["recovery_run_id"])
        assert child.get("parent_task") == "deploy pipeline"
        assert child.get("parent_run_id") == val["run_id"]

    def test_child_outcome_badge_recovered(self):
        val = self.memory.get_fact_value("run:last")
        child = self.memory.get_fact_value(val["recovery_run_id"])
        assert child["outcome_badge"] == "recovered"

    def test_child_n_steps(self):
        val = self.memory.get_fact_value("run:last")
        child = self.memory.get_fact_value(val["recovery_run_id"])
        assert child["n_steps"] == 2

    def test_operator_summary_shows_recovery(self):
        svc = _status_query_svc(self.memory)
        summary = svc.build_operator_summary()
        rec = summary.get("latest_recovery")
        assert rec is not None
        assert rec.get("outcome") in ("recovered", "success") or rec.get("outcome_badge") in ("recovered", "ok")

    def test_skipped_step_counted(self):
        val = self.memory.get_fact_value("run:last")
        assert val["n_skipped"] == 1

    def test_failed_step_recorded(self):
        val = self.memory.get_fact_value("run:last")
        assert val["n_failed"] == 1
        assert len(val["failed_steps"]) == 1
        assert "connection refused" in val["failed_steps"][0].get("error", "")


# ---------------------------------------------------------------------------
# Flow 4: Restart / resume — memory persists across MemorySystem instances
# ---------------------------------------------------------------------------


class TestRestartResume:
    """Write facts to a temp file; reload into a fresh MemorySystem and verify."""

    def setup_method(self):
        # Create a real temp file for the facts store
        fd, self._facts_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self._facts_path)  # start fresh

    def teardown_method(self):
        if os.path.exists(self._facts_path):
            os.unlink(self._facts_path)

    def _make_mem(self):
        return _make_memory(self._facts_path)

    def test_fact_survives_across_instances(self):
        mem1 = self._make_mem()
        mem1.save_fact("run:last", {"task": "build", "outcome": "success", "outcome_badge": "ok"},
                       source="run_artifact", confidence=0.9, topic="run_history")
        # Force write (FactStore._save called on save_fact)
        mem2 = self._make_mem()
        val = mem2.get_fact_value("run:last")
        assert val is not None
        assert val["task"] == "build"

    def test_failed_run_digest_survives_restart(self):
        # Write a complete failed run digest through RunHistoryService
        mem1 = self._make_mem()
        svc1 = _run_history_svc(mem1)
        artifact = _plan_artifact(
            task="index codebase",
            outcome="failed",
            steps=[_step(1, "failed", "run_shell", "indexer.py", error="OOM")],
            failed=[_step(1, "failed", "run_shell", "indexer.py", error="OOM")],
        )
        svc1.persist_run_digest(artifact, "")

        # Simulate restart: fresh MemorySystem from same file
        mem2 = self._make_mem()
        val = mem2.get_fact_value("run:last")
        assert val is not None
        assert val["task"] == "index codebase"
        assert val["outcome"] == "failed"
        assert val["outcome_badge"] == "failed"

    def test_boot_doctor_after_restart_flags_recovery(self):
        mem1 = self._make_mem()
        svc1 = _run_history_svc(mem1)
        artifact = _plan_artifact(
            task="deploy service",
            outcome="failed",
            steps=[_step(1, "failed", "run_shell", "deploy.sh", error="timeout")],
            failed=[_step(1, "failed", "run_shell", "deploy.sh", error="timeout")],
        )
        svc1.persist_run_digest(artifact, "")

        # Reload + query boot doctor
        mem2 = self._make_mem()
        query_svc = _status_query_svc(mem2, health=_make_health("healthy"))
        summary = query_svc.build_boot_doctor_summary()
        assert summary["recommend_recovery"] is True
        assert summary["last_incomplete_task"]["task"] == "deploy service"

    def test_run_history_retriever_finds_persisted_run(self):
        mem1 = self._make_mem()
        svc1 = _run_history_svc(mem1)
        artifact = _plan_artifact(
            task="compile assets",
            outcome="success",
            steps=[_step(1, "done", "run_shell", "make")],
        )
        svc1.persist_run_digest(artifact, "compiled ok")

        mem2 = self._make_mem()
        query_svc = _status_query_svc(mem2)
        run = query_svc.find_most_recent_run_digest()
        assert run is not None
        assert run.get("task") == "compile assets"

    def test_operator_summary_after_restart(self):
        mem1 = self._make_mem()
        svc1 = _run_history_svc(mem1)
        artifact = _plan_artifact(
            task="migrate db",
            outcome="success",
            steps=[_step(1, "done", "run_shell", "migrate.py")],
        )
        svc1.persist_run_digest(artifact, "migration done")

        mem2 = self._make_mem()
        query_svc = _status_query_svc(mem2)
        summary = query_svc.build_operator_summary()
        assert summary["last_run"] is not None
        assert summary["last_run"]["task"] == "migrate db"
        assert summary["last_run"]["outcome_badge"] == "ok"


# ---------------------------------------------------------------------------
# Flow 5: Complex state — operator summary + failure-first retrieval
# ---------------------------------------------------------------------------


class TestComplexState:
    """Multiple runs in memory; verify failure-first ordering and operator view."""

    def setup_method(self):
        self.memory = _make_memory()
        svc = _run_history_svc(self.memory)

        # Persist 3 runs in order: success, failed, recovered
        svc.persist_run_digest(
            _plan_artifact("build images", "success",
                           steps=[_step(1, "done", "run_shell", "build.sh")]),
            "images built",
        )
        svc.persist_run_digest(
            _plan_artifact("run tests", "failed",
                           steps=[_step(1, "failed", "run_shell", "pytest", error="assertion failed")],
                           failed=[_step(1, "failed", "run_shell", "pytest", error="assertion failed")]),
            "",
        )
        svc.persist_run_digest(
            _plan_artifact("deploy staging", "recovered",
                           steps=[
                               _step(1, "done", "run_shell", "deploy.sh"),
                               _step(2, "done", "run_shell", "health_check.sh"),
                           ],
                           recovery={"outcome": "recovered", "recovery_execution": {
                               "task": "retry deploy", "outcome": "recovered",
                               "steps": [_step(1, "done", "run_shell", "retry.sh")],
                               "failed": [],
                           }}),
            "staged",
        )

    def test_run_last_is_most_recent(self):
        val = self.memory.get_fact_value("run:last")
        assert val["task"] == "deploy staging"

    def test_three_hashed_keys_exist(self):
        run_keys = [
            k for k in self.memory.facts
            if k.startswith("run:") and k != "run:last" and not k.startswith("run:recovery:")
        ]
        assert len(run_keys) == 3

    def test_failure_first_sort_ordering(self):
        from agent.services.run_history_service import failure_first_sort
        run_keys = [
            k for k in self.memory.facts
            if k.startswith("run:") and k != "run:last" and not k.startswith("run:recovery:")
        ]
        results = [{"key": k, "value": self.memory.get_fact_value(k)} for k in run_keys]
        sorted_results = failure_first_sort(results)
        outcomes = [r["value"]["outcome"] for r in sorted_results]
        # Failed must come before success and recovered
        assert outcomes[0] == "failed"
        # Success/recovered come after
        assert set(outcomes[1:]) == {"success", "recovered"}

    def test_format_retrieval_failure_first(self):
        from agent.services.run_history_service import format_retrieval_results
        run_keys = [
            k for k in self.memory.facts
            if k.startswith("run:") and k != "run:last" and not k.startswith("run:recovery:")
        ]
        results = [{"key": k, "value": self.memory.get_fact_value(k)} for k in run_keys]
        output = {"method": "run_history", "results": results}
        text = format_retrieval_results(output, failure_first=True)
        assert text is not None
        idx_fail = text.find("run tests")
        idx_success = text.find("build images")
        assert idx_fail >= 0 and idx_success >= 0
        assert idx_fail < idx_success, "failed run should appear before success run"

    def test_operator_summary_has_recovery(self):
        svc = _status_query_svc(self.memory)
        summary = svc.build_operator_summary()
        assert summary["latest_recovery"] is not None

    def test_blocked_reason_surfaced_in_summary(self):
        state = {"blocked_reason": "3 consecutive failures on 'run tests'"}
        svc = _status_query_svc(self.memory, state=state)
        summary = svc.build_operator_summary()
        assert summary["blocked_reason"] == "3 consecutive failures on 'run tests'"
        text = svc.format_operator_summary(summary)
        assert "BLOCKED" in text
        assert "3 consecutive" in text

    def test_run_history_response_returns_string(self):
        svc = _status_query_svc(self.memory)
        response = svc.try_run_history_response("what happened last?")
        assert response is not None
        assert isinstance(response, str)
        assert len(response) > 0

    def test_run_history_response_mentions_latest_task(self):
        svc = _status_query_svc(self.memory)
        response = svc.try_run_history_response("show me the last run")
        assert response is not None
        # The most recent run (deploy staging) should appear
        assert "deploy staging" in response or "staging" in response


# ---------------------------------------------------------------------------
# Flow 6: Critic fields survive the full persist → retrieval round-trip
# ---------------------------------------------------------------------------


class TestCriticPersistenceRoundTrip:
    """Critic output attached to artifact survives persist and surfaces in retrieval."""

    def setup_method(self):
        self.memory = _make_memory()
        self.svc = _run_history_svc(self.memory)

    def test_critic_issues_in_retrieval_text(self):
        from agent.services.run_history_service import format_retrieval_results
        artifact = _plan_artifact(
            task="refactor auth",
            outcome="success",
            steps=[_step(1, "done", "write_file", "auth.py")],
            critic="- Step 1 overwrites existing token store — check idempotency\n- Missing rollback on failure",
        )
        self.svc.persist_run_digest(artifact, "")
        val = self.memory.get_fact_value("run:last")
        assert val.get("critic_issues"), "critic_issues should be stored"
        output = {"method": "run_history", "results": [{"key": "run:last", "value": val}]}
        text = format_retrieval_results(output)
        assert "Critic:" in text or "idempotency" in text.lower() or "rollback" in text.lower()

    def test_critic_lesson_in_operator_summary(self):
        artifact = _plan_artifact(
            task="deploy infra",
            outcome="failed",
            steps=[_step(1, "failed", "run_shell", "terraform.sh", error="timeout")],
            failed=[_step(1, "failed", "run_shell", "terraform.sh", error="timeout")],
            critic="- Terraform timed out — reduce apply scope to a single module",
        )
        self.svc.persist_run_digest(artifact, "")
        svc = _status_query_svc(self.memory)
        summary = svc.build_operator_summary()
        last_run = summary.get("last_run") or {}
        lesson = last_run.get("critic_lesson", "")
        text = svc.format_operator_summary(summary)
        assert "Terraform" in text or "reduce" in text.lower() or "Lesson:" in text

    def test_critic_truncated_to_3_issues(self):
        artifact = _plan_artifact(
            task="big refactor",
            outcome="success",
            steps=[_step(1, "done", "write_file", "core.py")],
            critic=(
                "- Issue one: redundant import\n"
                "- Issue two: missing type hint\n"
                "- Issue three: no docstring\n"
                "- Issue four: unused variable\n"
            ),
        )
        self.svc.persist_run_digest(artifact, "")
        val = self.memory.get_fact_value("run:last")
        assert len(val.get("critic_issues", [])) <= 3
