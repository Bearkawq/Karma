"""Tests for planner/critic seat loop integration."""

from unittest.mock import MagicMock, patch

import pytest

from agent.agent_loop import AgentLoop


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_agent():
    from agent.agent_loop import AgentLoop, load_config

    cfg = load_config("config.json")
    return AgentLoop(cfg)


def _mock_mgr(execute_side_effect=None, no_model_mode=False):
    """Return a mock AgentModelManager."""
    mgr = MagicMock()
    mgr._no_model_mode = no_model_mode
    if execute_side_effect:
        mgr.execute.side_effect = execute_side_effect
    return mgr


# ── planner seat in _generate_candidates ─────────────────────────────────────


def test_planner_seat_called_when_core_planner_empty():
    """_planner_seat_candidates fires when core planner returns []."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    mock_result = PipelineResult(
        success=True,
        output={
            "plan_steps": [
                {"step": 1, "action": "RESEARCH", "target": "neural nets"},
                {"step": 2, "action": "SUMMARIZE", "target": "findings"},
            ],
            "model_generated": True,
        },
        pipeline_type="agent_only",
    )

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr()
        mock_get.return_value.execute.return_value = mock_result
        mock_get.return_value._no_model_mode = False

        intent = {
            "intent": "unknown_task",
            "confidence": 0.8,
            "entities": {"topic": "neural nets"},
        }
        candidates = agent._planner_seat_candidates(intent)

    assert len(candidates) == 1
    assert candidates[0]["name"] == "RESEARCH"
    assert "neural nets" in candidates[0]["parameters"]["task"]
    assert candidates[0]["_seat_generated"] is True


def test_planner_seat_returns_empty_on_no_model_mode():
    agent = _make_agent()
    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr(no_model_mode=True)
        intent = {"intent": "something", "confidence": 0.9, "entities": {}}
        result = agent._planner_seat_candidates(intent)
    assert result == []


def test_planner_seat_returns_empty_on_exception():
    agent = _make_agent()
    with patch(
        "core.agent_model_manager.get_agent_model_manager",
        side_effect=RuntimeError("boom"),
    ):
        intent = {"intent": "something", "confidence": 0.9, "entities": {}}
        result = agent._planner_seat_candidates(intent)
    assert result == []


def test_generate_candidates_uses_seat_when_core_empty():
    """_generate_candidates() calls seat planner for unknown intent."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    seat_candidate = [
        {
            "name": "process",
            "tool": None,
            "parameters": {"task": "do it"},
            "cost": 1,
            "confidence": 0.55,
            "_seat_generated": True,
        }
    ]

    with patch.object(
        agent, "_planner_seat_candidates", return_value=seat_candidate
    ) as mock_seat:
        intent = {"intent": "completely_unknown", "confidence": 0.8, "entities": {}}
        # core planner returns [] for unknown intent with confidence >= 0.5
        candidates = agent._generate_candidates(intent)

    mock_seat.assert_called_once_with(intent)
    # ml_manager.refine_actions may return same or filtered list
    assert any(c.get("_seat_generated") for c in candidates) or candidates == []


def test_generate_candidates_skips_seat_when_core_has_results():
    """Seat planner is NOT called when core planner already produced candidates."""
    agent = _make_agent()

    with patch.object(agent, "_planner_seat_candidates") as mock_seat:
        intent = {"intent": "list_files", "confidence": 0.9, "entities": {"path": "."}}
        candidates = agent._generate_candidates(intent)

    mock_seat.assert_not_called()
    assert len(candidates) >= 1


# ── critic after execution ────────────────────────────────────────────────────


def test_critic_fires_for_critic_intent_on_success():
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    crit_result = PipelineResult(
        success=True,
        output={
            "critique": "- Output is vague\n- Missing error handling",
            "model_generated": True,
        },
        pipeline_type="agent_only",
    )

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr()
        mock_get.return_value.execute.return_value = crit_result
        mock_get.return_value._no_model_mode = False

        result = agent._seat_critique(
            {"success": True, "output": {"content": "some long output text"}},
            "run_shell",
        )

    assert result is not None
    assert "vague" in result or "Missing" in result


def test_critic_skips_non_critic_intents():
    agent = _make_agent()
    result = agent._seat_critique(
        {"success": True, "output": "some output"},
        "list_files",
    )
    assert result is None


def test_critic_skips_failed_execution():
    agent = _make_agent()
    result = agent._seat_critique(
        {"success": False, "error": "command not found"},
        "run_shell",
    )
    assert result is None


def test_critic_returns_none_when_ok():
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    crit_result = PipelineResult(
        success=True,
        output={"critique": "OK", "model_generated": True},
        pipeline_type="agent_only",
    )

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr()
        mock_get.return_value.execute.return_value = crit_result
        mock_get.return_value._no_model_mode = False

        result = agent._seat_critique(
            {"success": True, "output": "looks good"},
            "golearn",
        )

    assert result is None


def test_critic_returns_none_on_no_model_mode():
    agent = _make_agent()
    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr(no_model_mode=True)
        result = agent._seat_critique({"success": True, "output": "x"}, "run_shell")
    assert result is None


def test_critic_returns_none_on_exception():
    agent = _make_agent()
    with patch(
        "core.agent_model_manager.get_agent_model_manager",
        side_effect=RuntimeError("boom"),
    ):
        result = agent._seat_critique({"success": True, "output": "x"}, "run_shell")
    assert result is None


# ── critic + _run_artifact integration ───────────────────────────────────────


def _make_run_artifact(
    outcome="success", n_steps=2, n_failed=0, n_skipped=0, recovery=None
):
    steps = []
    for i in range(n_steps):
        if i < n_steps - n_failed - n_skipped:
            steps.append(
                {"step": i + 1, "status": "done", "action": f"A{i + 1}", "target": "x"}
            )
        elif i < n_steps - n_skipped:
            steps.append(
                {
                    "step": i + 1,
                    "status": "failed",
                    "action": f"A{i + 1}",
                    "target": "x",
                    "error": "err",
                }
            )
        else:
            steps.append(
                {
                    "step": i + 1,
                    "status": "skipped",
                    "action": f"A{i + 1}",
                    "target": "x",
                }
            )
    return {
        "task": "test multi-step task",
        "outcome": outcome,
        "plan": [
            {"step": s["step"], "action": s["action"], "target": s["target"]}
            for s in steps
        ],
        "steps": steps,
        "outputs": [f"Step {s['step']}: done" for s in steps if s["status"] == "done"],
        "prior_results": [],
        "failed": [s for s in steps if s["status"] == "failed"],
        "recovery": recovery,
    }


def test_critic_receives_run_artifact_when_present():
    """When _run_artifact is in execution_result, critic receives run_artifact content_type."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    captured = {}

    def _execute(task, context=None, explicit_role=None):
        if explicit_role == "critic":
            captured["ctx"] = context or {}
            return PipelineResult(
                success=True,
                output={"critique": "- Step A2 redundant"},
                pipeline_type="agent_only",
            )
        return PipelineResult(success=False, output=None, pipeline_type="agent_only")

    artifact = _make_run_artifact(outcome="success", n_steps=2)
    execution_result = {
        "success": True,
        "output": "Step 1: ok\nStep 2: ok",
        "_run_artifact": artifact,
    }

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        result = agent._seat_critique(
            execution_result, "list_files"
        )  # non-critic intent

    assert captured.get("ctx", {}).get("content_type") == "run_artifact", (
        "Critic must receive content_type='run_artifact' when _run_artifact is present"
    )
    assert "test multi-step task" in captured.get("ctx", {}).get("content", "")
    assert result is not None
    assert "redundant" in result


def test_critic_run_artifact_fires_regardless_of_intent():
    """Critic fires for any intent when _run_artifact is present (not gated by _CRITIC_INTENTS)."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    fired = [False]

    def _execute(task, context=None, explicit_role=None):
        if explicit_role == "critic":
            fired[0] = True
            return PipelineResult(
                success=True,
                output={"critique": "- Step 2 could be batched with step 1"},
                pipeline_type="agent_only",
            )
        return PipelineResult(success=False, output=None, pipeline_type="agent_only")

    artifact = _make_run_artifact(outcome="success", n_steps=3)
    execution_result = {"success": True, "output": "ok", "_run_artifact": artifact}

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        # Use a non-critic intent — critic should still fire due to _run_artifact
        result = agent._seat_critique(execution_result, "respond")

    assert fired[0], "Critic must fire for any intent when _run_artifact present"
    assert result is not None


def test_critic_legacy_path_still_gated_by_critic_intents():
    """Without _run_artifact, critic is still gated to _CRITIC_INTENTS only."""
    agent = _make_agent()

    fired = [False]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: (_ for _ in ()).throw(
            AssertionError("should not be called")
        )
        mock_get.return_value = mock_mgr

        # No _run_artifact, non-critic intent → must return None without calling critic
        result = agent._seat_critique(
            {"success": True, "output": "some output"},
            "list_files",  # not in _CRITIC_INTENTS
        )

    assert result is None


def test_critic_legacy_path_fires_for_critic_intent():
    """Without _run_artifact, critic still fires normally for _CRITIC_INTENTS."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.return_value = PipelineResult(
            success=True,
            output={"critique": "- output too vague"},
            pipeline_type="agent_only",
        )
        mock_get.return_value = mock_mgr

        result = agent._seat_critique(
            {"success": True, "output": "some shell output"},
            "run_shell",  # in _CRITIC_INTENTS
        )

    assert result is not None
    assert "vague" in result


def test_critic_skips_run_artifact_when_no_steps():
    """If _run_artifact has no steps, critic returns None."""
    agent = _make_agent()

    artifact = {
        "task": "empty",
        "outcome": "empty",
        "steps": [],
        "outputs": [],
        "failed": [],
        "recovery": None,
    }
    result = agent._seat_critique(
        {"success": True, "output": "", "_run_artifact": artifact},
        "respond",
    )
    assert result is None


def test_critic_agent_review_run_artifact_detects_failure_no_recovery():
    """CriticAgent._review_run_artifact flags failed steps with no recovery."""
    from agents.critic_agent import CriticAgent

    agent_c = CriticAgent()

    content = (
        "Task: fetch and deploy\n"
        "Outcome: failed\n"
        "Steps: 2 total (1 done, 1 failed, 0 skipped)\n"
        "Results:\n  Step 1: fetched\n"
        "Failed: step 2 (DEPLOY prod) — connection refused\n"
    )
    review = agent_c._review_run_artifact(content)

    issues = review.get("issues", [])
    assert any("failed" in i.lower() for i in issues), (
        f"Should flag failed outcome: {issues}"
    )
    assert any("no recovery" in i.lower() or "recovery" in i.lower() for i in issues), (
        f"Should flag lack of recovery: {issues}"
    )


def test_critic_agent_review_run_artifact_detects_recovery_failure():
    """CriticAgent._review_run_artifact flags recovery_failed outcome."""
    from agents.critic_agent import CriticAgent

    agent_c = CriticAgent()

    content = (
        "Task: complex op\n"
        "Outcome: recovery_failed\n"
        "Steps: 3 total (1 done, 1 failed, 1 skipped)\n"
        "Failed: step 2 (TRANSFORM x) — parse error\n"
        "Recovery: recovery_failed\n"
        "  Recovery steps: 1\n"
    )
    review = agent_c._review_run_artifact(content)

    issues = review.get("issues", [])
    assert any("recovery" in i.lower() for i in issues), (
        f"Should flag recovery failure: {issues}"
    )


def test_critic_agent_review_run_artifact_clean_run_no_issues():
    """CriticAgent._review_run_artifact finds no issues for a clean successful run."""
    from agents.critic_agent import CriticAgent

    agent_c = CriticAgent()

    content = (
        "Task: simple task\n"
        "Outcome: success\n"
        "Steps: 2 total (2 done, 0 failed, 0 skipped)\n"
        "Results:\n  Step 1: done\n  Step 2: done\n"
    )
    review = agent_c._review_run_artifact(content)

    assert review.get("score", 0) >= 75, f"Clean run should score >= 75: {review}"
    assert review.get("issues", []) == [], f"Clean run should have no issues: {review}"


def test_critic_run_artifact_multi_step_failure_structure_visible():
    """Full path: _seat_critique with multi-step failure passes rich content to critic."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    received_content = {}

    def _execute(task, context=None, explicit_role=None):
        if explicit_role == "critic":
            received_content["content"] = (context or {}).get("content", "")
            received_content["content_type"] = (context or {}).get("content_type", "")
            return PipelineResult(
                success=True,
                output={"critique": "- Step 2 failed with no recovery path"},
                pipeline_type="agent_only",
            )
        return PipelineResult(success=False, output=None, pipeline_type="agent_only")

    artifact = _make_run_artifact(
        outcome="failed",
        n_steps=3,
        n_failed=1,
        n_skipped=1,
        recovery={"outcome": "stopped", "recovery_plan": None},
    )
    execution_result = {
        "success": True,
        "output": "Step 1: ok",
        "_run_artifact": artifact,
    }

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        result = agent._seat_critique(execution_result, "any_intent")

    assert received_content.get("content_type") == "run_artifact"
    content = received_content.get("content", "")
    # Artifact content must expose structure for critic reasoning
    assert "failed" in content.lower()
    assert "skipped" in content.lower()
    assert "Recovery" in content
    assert result == "- Step 2 failed with no recovery path"


# ── critic touched_paths analysis ────────────────────────────────────────────


def test_analyze_touched_paths_overlap_risk():
    """Same path in parent and recovery triggers overlap risk finding."""
    from agents.critic_agent import CriticAgent

    findings = CriticAgent._analyze_touched_paths(
        ["src/foo.py", "src/bar.py"],
        ["src/foo.py", "src/qux.py"],
    )
    kinds = [f["kind"] for f in findings]
    assert "overlap_risk" in kinds, f"Expected overlap_risk finding: {findings}"
    assert any("src/foo.py" in f["detail"] for f in findings), f"Expected path in detail: {findings}"


def test_analyze_touched_paths_gap_risk():
    """Parent paths not addressed in recovery triggers gap finding."""
    from agents.critic_agent import CriticAgent

    findings = CriticAgent._analyze_touched_paths(
        ["src/foo.py", "src/bar.py", "src/baz.py"],
        ["src/foo.py"],
    )
    kinds = [f["kind"] for f in findings]
    assert "gap_risk" in kinds, f"Expected gap_risk finding: {findings}"


def test_analyze_touched_paths_weak_coverage():
    """No overlap between parent and recovery paths triggers weak coverage."""
    from agents.critic_agent import CriticAgent

    findings = CriticAgent._analyze_touched_paths(
        ["src/foo.py"],
        ["src/completely_different.py"],
    )
    kinds = [f["kind"] for f in findings]
    assert "weak_coverage" in kinds, f"Expected weak_coverage finding: {findings}"


def test_analyze_touched_paths_absent_degrades_safely():
    """Empty/None path lists produce no findings."""
    from agents.critic_agent import CriticAgent

    assert CriticAgent._analyze_touched_paths([], []) == []
    assert CriticAgent._analyze_touched_paths(None, None) == []
    assert CriticAgent._analyze_touched_paths(["src/foo.py"], []) == []
    assert CriticAgent._analyze_touched_paths([], ["src/foo.py"]) == []


def test_review_run_artifact_non_recovery_unchanged():
    """_review_run_artifact with no recovery does not add path findings."""
    from agents.critic_agent import CriticAgent

    agent_c = CriticAgent()
    content = (
        "Task: simple\n"
        "Outcome: success\n"
        "Steps: 2 total (2 done, 0 failed, 0 skipped)\n"
    )
    review = agent_c._review_run_artifact(
        content,
        parent_paths=["src/foo.py"],
        recovery_paths=["src/bar.py"],
    )
    # No recovery in content → has_recovery=False → no path findings appended
    issues = review.get("issues", [])
    assert not any("overlap" in i.lower() or "gap" in i.lower() or "weak" in i.lower() for i in issues), (
        f"No path findings expected without recovery: {issues}"
    )


def test_review_run_artifact_with_recovery_adds_path_findings():
    """_review_run_artifact with recovery and overlapping paths adds path findings."""
    from agents.critic_agent import CriticAgent

    agent_c = CriticAgent()
    content = (
        "Task: complex\n"
        "Outcome: recovered\n"
        "Steps: 3 total (2 done, 1 failed, 0 skipped)\n"
        "Failed: step 2 (WRITE src/foo.py) — permission denied\n"
        "Recovery: recovered\n"
        "  Recovery steps: 1\n"
    )
    review = agent_c._review_run_artifact(
        content,
        parent_paths=["src/foo.py"],
        recovery_paths=["src/foo.py"],
    )
    pf = review.get("path_findings", [])
    kinds = [f["kind"] for f in pf]
    assert "overlap_risk" in kinds, f"Expected overlap_risk in path_findings: {pf}"
    # Issues should also contain the detail text
    issues = review.get("issues", [])
    assert any("re-touches" in i for i in issues), (
        f"Expected overlap detail in issues: {issues}"
    )


def test_seat_critique_passes_touched_paths_to_critic():
    """_seat_critique extracts and passes touched_paths_parent/recovery to critic context."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    received_context: dict = {}

    def _execute(task, context=None, explicit_role=None):
        if explicit_role == "critic":
            received_context.update(context or {})
            return PipelineResult(
                success=True,
                output={"critique": "- some issue"},
                pipeline_type="agent_only",
            )
        return PipelineResult(success=False, output=None, pipeline_type="agent_only")

    artifact = _make_run_artifact(
        outcome="recovered",
        n_steps=3,
        n_failed=1,
        recovery={
            "outcome": "recovered",
            "recovery_plan": [
                {"step": 1, "action": "RETRY", "target": "src/foo.py"}
            ],
        },
    )
    # Give steps path-like targets so _extract_touched_paths picks them up
    for step in artifact["steps"]:
        step["target"] = "src/foo.py"
    artifact["plan"] = [
        {"step": s["step"], "action": s["action"], "target": s["target"]}
        for s in artifact["steps"]
    ]

    execution_result = {"success": True, "output": "ok", "_run_artifact": artifact}

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        agent._seat_critique(execution_result, "any_intent")

    assert "touched_paths_parent" in received_context, "touched_paths_parent missing from critic context"
    assert "touched_paths_recovery" in received_context, "touched_paths_recovery missing from critic context"
    assert isinstance(received_context["touched_paths_parent"], list)
    assert isinstance(received_context["touched_paths_recovery"], list)


# ── path_findings persistence and formatting ──────────────────────────────────


def test_seat_critique_attaches_path_findings_to_run_artifact():
    """_seat_critique attaches structured path_findings to _run_artifact when paths present."""
    agent = _make_agent()

    artifact = _make_run_artifact(
        outcome="recovered",
        n_steps=2,
        n_failed=1,
        recovery={"outcome": "recovered", "recovery_plan": [
            {"step": 1, "action": "RETRY", "target": "src/foo.py"}
        ]},
    )
    for step in artifact["steps"]:
        step["target"] = "src/foo.py"
    artifact["plan"] = [
        {"step": s["step"], "action": s["action"], "target": s["target"]}
        for s in artifact["steps"]
    ]

    execution_result = {"success": True, "output": "ok", "_run_artifact": artifact}

    # No model mode — path findings are deterministic, should still attach
    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr(no_model_mode=True)
        agent._seat_critique(execution_result, "any_intent")

    pf = artifact.get("path_findings")
    assert pf is not None, "path_findings should be attached to _run_artifact"
    assert isinstance(pf, list) and len(pf) > 0, f"path_findings should be non-empty: {pf}"
    kinds = [f["kind"] for f in pf]
    assert any(k in kinds for k in ("overlap_risk", "weak_coverage", "gap_risk", "broad_spread")), (
        f"Expected at least one typed finding: {kinds}"
    )


def test_persist_run_digest_stores_path_findings():
    """_persist_run_digest stores path_findings field in the persisted digest."""
    agent = _make_agent()

    artifact = _make_run_artifact(outcome="recovered", n_steps=2, n_failed=1)
    artifact["path_findings"] = [
        {"kind": "overlap_risk", "detail": "recovery re-touches 1 failed-run path(s): src/foo.py"}
    ]

    saved: dict = {}

    def _save_fact(key, value, source=None, confidence=None, topic=None):
        saved[key] = value

    agent.memory.save_fact = _save_fact
    agent._persist_run_digest(artifact, "test summary")

    parent_digest = saved.get("run:last") or next(
        (v for k, v in saved.items() if k.startswith("run:") and "recovery" not in k and k != "run:last"),
        None,
    )
    assert parent_digest is not None, f"Expected parent digest: {list(saved.keys())}"
    pf = parent_digest.get("path_findings")
    assert isinstance(pf, list) and len(pf) > 0, f"path_findings missing from digest: {parent_digest}"
    assert pf[0]["kind"] == "overlap_risk"


def test_format_linked_run_result_renders_path_findings():
    """_format_linked_run_result includes Risks: line when path_findings present."""
    linked = {
        "kind": "linked_run_history",
        "parent": {
            "task": "deploy service",
            "outcome": "failed",
            "summary": "failed at step 2",
            "touched_paths": [],
            "path_findings": [
                {"kind": "gap_risk", "detail": "2 failed-run path(s) not addressed: src/a.py, src/b.py"}
            ],
        },
        "recovery": {
            "task": "recovery for deploy",
            "outcome": "recovered",
            "n_steps": 1,
            "n_failed": 0,
            "summary": "recovery succeeded",
            "touched_paths": [],
        },
    }
    text = AgentLoop._format_linked_run_result(linked)
    assert "Risks:" in text, f"Expected 'Risks:' line in output: {text!r}"
    assert "gap" in text.lower() or "missed" in text.lower(), (
        f"Expected gap_risk label: {text!r}"
    )


def test_format_retrieval_results_renders_path_findings():
    """_format_retrieval_results includes Risks: line for plain run_history with path_findings."""
    output = {
        "method": "memory",
        "results": [
            {
                "key": "run:abc123",
                "value": {
                    "task": "build pipeline",
                    "outcome": "recovery_failed",
                    "summary": "step 2 failed",
                    "touched_paths": [],
                    "path_findings": [
                        {"kind": "weak_coverage", "detail": "recovery touches no paths from failed run"}
                    ],
                },
            }
        ],
    }
    text = AgentLoop._format_retrieval_results(output)
    assert text is not None, "Expected formatted text output"
    assert "Risks:" in text, f"Expected 'Risks:' in output: {text!r}"
    assert "skipped" in text.lower() or "weak" in text.lower() or "recovery" in text.lower(), (
        f"Expected weak_coverage label: {text!r}"
    )


def test_coherent_linked_answer_contains_all_lanes():
    """Full linked run answer surfaces: task, outcome, review targets with risks, recovery, paths."""
    linked = {
        "kind": "linked_run_history",
        "parent": {
            "task": "deploy pipeline",
            "outcome": "failed",
            "summary": "step 2 WRITE src/main.py failed",
            "touched_paths": ["src/main.py", "src/config.py"],
            "path_findings": [
                {
                    "kind": "gap_risk",
                    "detail": "1 failed-run path(s) not addressed: src/config.py",
                    "paths": ["src/config.py"],
                }
            ],
        },
        "recovery": {
            "task": "recovery: deploy pipeline",
            "outcome": "recovered",
            "n_steps": 2,
            "n_failed": 0,
            "summary": "fixed src/main.py and deployed",
            "touched_paths": ["src/main.py"],
        },
    }
    text = AgentLoop._format_linked_run_result(linked)

    # Task and outcomes present
    assert "deploy pipeline" in text
    assert "failed" in text.lower()
    assert "recovered" in text.lower() or "recovery" in text.lower()

    # Risk targets visible
    assert "gap" in text.lower() or "missed" in text.lower(), f"Expected gap risk: {text!r}"

    # Both run kinds present
    assert "Failed run" in text
    assert "Recovery" in text or "recovery" in text


def test_path_findings_absent_on_non_recovery_run():
    """_seat_critique does not attach path_findings when run has no recovery."""
    agent = _make_agent()

    artifact = _make_run_artifact(outcome="success", n_steps=2)
    # Give path-like targets
    for step in artifact["steps"]:
        step["target"] = "src/foo.py"

    execution_result = {"success": True, "output": "ok", "_run_artifact": artifact}

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr(no_model_mode=True)
        agent._seat_critique(execution_result, "any_intent")

    # No recovery → no path_findings (or empty list)
    pf = artifact.get("path_findings")
    assert not pf, f"Non-recovery run should have no path_findings: {pf}"


# ── seam 1: run:last summary surfaces path_findings ──────────────────────────


def test_run_history_response_surfaces_risks_when_present():
    """_try_run_history_response includes Risks: lines when digest has path_findings."""
    agent = _make_agent_with_clean_memory()

    # Seed memory with a run:last digest that includes path_findings
    agent.memory.save_fact(
        "run:last",
        {
            "run_id": "run:test01",
            "run_kind": "primary",
            "task": "deploy pipeline",
            "outcome": "recovery_failed",
            "n_steps": 3,
            "n_failed": 1,
            "summary": "Step 2 failed; recovery also failed",
            "ts": "2026-04-17T10:00:00",
            "touched_paths": ["src/deploy.py"],
            "path_findings": [
                {"kind": "weak_coverage", "detail": "recovery touches no paths from failed run"}
            ],
        },
        source="run_artifact",
        confidence=0.9,
        topic="run_history",
    )

    response = agent._try_run_history_response("what happened last run?")

    assert response is not None, "Expected a response for last run query"
    assert "Risks:" in response, f"Expected 'Risks:' in response: {response!r}"
    assert "skipped" in response.lower() or "recovery" in response.lower() or "weak" in response.lower(), (
        f"Expected weak_coverage label: {response!r}"
    )


def test_recovery_query_triggers_linked_path():
    """'last recovery' / 'latest recovery' triggers recovery-linked retriever path."""
    from agents.retriever_agent import RetrieverAgent

    for q in ["last recovery", "latest recovery", "show me the recovery run", "recovery run"]:
        assert RetrieverAgent._is_recovery_linked_query(q), f"Expected recovery linked: {q!r}"


def test_review_target_query_triggers_path_query():
    """'what to review' / 'review targets' triggers path query."""
    from agents.retriever_agent import RetrieverAgent

    for q in ["what to review", "files to review", "review targets", "files to inspect"]:
        assert RetrieverAgent._is_path_query(q), f"Expected path query: {q!r}"


def test_run_history_response_plain_run_no_risks_unaffected():
    """_try_run_history_response for plain success run does not emit spurious Risks: lines."""
    agent = _make_agent()

    agent.memory.save_fact(
        "run:last",
        {
            "run_id": "run:test02",
            "run_kind": "primary",
            "task": "list files",
            "outcome": "success",
            "n_steps": 1,
            "n_failed": 0,
            "summary": "listed 5 files",
            "ts": "2026-04-17T10:01:00",
            "touched_paths": [],
            "path_findings": [],
        },
        source="run_artifact",
        confidence=0.9,
        topic="run_history",
    )

    response = agent._try_run_history_response("what happened last run?")

    if response is not None:
        assert "Risks:" not in response, f"No Risks: expected for clean run: {response!r}"


# ── role router audit ─────────────────────────────────────────────────────────


def test_router_routes_question_to_planner():
    from core.role_router import RoleRouter

    r = RoleRouter()
    decision = r.route("what is machine learning?")
    assert decision.role == "planner"


def test_router_routes_explain_to_planner():
    from core.role_router import RoleRouter

    r = RoleRouter()
    decision = r.route("explain neural networks")
    assert decision.role == "planner"


def test_router_does_not_match_run_inside_return():
    """Short pattern 'run' should not match inside 'return'."""
    from core.role_router import RoleRouter

    r = RoleRouter()
    # "return" contains "run" as substring but not as word boundary
    decision = r.route("return value from function")
    # Should not match "run" → executor; falls to default executor or planner
    # We just check it doesn't incorrectly fire on the substring
    assert decision.role != "executor" or decision.fallback_used


def test_router_explicit_role_overrides_all():
    from core.role_router import RoleRouter

    r = RoleRouter()
    decision = r.route("summarize this", explicit_role="critic")
    assert decision.role == "critic"


def test_router_search_routes_to_retriever():
    from core.role_router import RoleRouter

    r = RoleRouter()
    decision = r.route("search for python files")
    assert decision.role == "retriever"


# ── fallback still works ──────────────────────────────────────────────────────


def test_seat_critique_no_output_returns_none():
    agent = _make_agent()
    result = agent._seat_critique({"success": True, "output": None}, "run_shell")
    assert result is None


def test_planner_seat_no_plan_steps_returns_empty():
    agent = _make_agent()
    from core.agent_model_manager import PipelineResult

    empty_result = PipelineResult(
        success=True, output={"no_plan": True}, pipeline_type="agent_only"
    )
    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr()
        mock_get.return_value.execute.return_value = empty_result
        mock_get.return_value._no_model_mode = False
        result = agent._planner_seat_candidates(
            {"intent": "x", "confidence": 0.8, "entities": {}}
        )
    assert result == []


# ── _execute_action: seat-generated candidate execution ───────────────────────


def test_execute_action_seat_generated_routes_to_executor_seat():
    """_seat_generated candidates must not hit 'Tool not found: None'."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    exec_result = PipelineResult(
        success=True,
        output={"execution": "1. Do the thing\n2. Verify it worked"},
        pipeline_type="agent_only",
    )

    action = {
        "name": "RESEARCH",
        "tool": None,
        "parameters": {
            "task": "explore neural nets",
            "plan": [{"step": 1, "action": "RESEARCH", "target": "neural nets"}],
        },
        "cost": 1,
        "confidence": 0.55,
        "_seat_generated": True,
    }

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_get.return_value = _mock_mgr()
        mock_get.return_value.execute.return_value = exec_result
        mock_get.return_value._no_model_mode = False

        result = agent._execute_action(action)

    assert result["success"] is True
    assert "Tool not found" not in str(result.get("error", ""))
    assert result["output"] is not None


def test_execute_action_seat_generated_deterministic_fallback():
    """When executor seat fails, plan steps are returned as readable output."""
    agent = _make_agent()

    action = {
        "name": "RESEARCH",
        "tool": None,
        "parameters": {
            "task": "explore something",
            "plan": [
                {"step": 1, "action": "RESEARCH", "target": "topic"},
                {"step": 2, "action": "SUMMARIZE", "target": "findings"},
            ],
        },
        "cost": 1,
        "confidence": 0.55,
        "_seat_generated": True,
    }

    with patch(
        "core.agent_model_manager.get_agent_model_manager",
        side_effect=RuntimeError("no model"),
    ):
        result = agent._execute_action(action)

    assert result["success"] is True
    assert "Tool not found" not in str(result.get("error", ""))
    # Deterministic fallback: plan steps rendered as text
    assert "RESEARCH" in result["output"] or "topic" in result["output"]


def test_execute_action_non_seat_still_hits_tool_not_found():
    """Normal (non-seat) candidates with tool=None still produce the expected error."""
    agent = _make_agent()
    action = {"name": "unknown_thing", "tool": None, "parameters": {}}
    result = agent._execute_action(action)
    assert result["success"] is False
    assert "Tool not found" in result["error"]


# ── plan_steps handoff: planner → executor ───────────────────────────────────


def test_execute_action_seat_generated_passes_plan_steps_to_executor():
    """plan_steps from planner-seat candidate reaches executor seat context for every step."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    captured_contexts = []

    def capture_execute(task, context=None, explicit_role=None):
        captured_contexts.append(dict(context or {}))
        return PipelineResult(
            success=True,
            output={"execution": "done"},
            pipeline_type="agent_only",
        )

    action = {
        "name": "RESEARCH",
        "tool": None,
        "parameters": {
            "task": "explore topic X",
            "plan": [
                {"step": 1, "action": "RESEARCH", "target": "topic X"},
                {"step": 2, "action": "SUMMARIZE", "target": "findings"},
            ],
        },
        "cost": 1,
        "confidence": 0.55,
        "_seat_generated": True,
    }

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.side_effect = capture_execute
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._execute_action(action)

    assert result["success"] is True
    # Both steps must have been executed
    assert len(captured_contexts) == 2, (
        f"Expected 2 executor calls, got {len(captured_contexts)}"
    )
    # Every call must carry the full plan_steps
    for ctx in captured_contexts:
        assert "plan_steps" in ctx
        assert len(ctx["plan_steps"]) == 2
        assert ctx["plan_steps"][0]["action"] == "RESEARCH"


# ── multi-step execution ──────────────────────────────────────────────────────


def test_execute_plan_steps_executes_all_steps():
    """2-step plan executes both steps, output contains both results."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    call_log = []

    def step_execute(task, context=None, explicit_role=None):
        call_log.append(task)
        return PipelineResult(
            success=True,
            output={"execution": f"result of: {task}"},
            pipeline_type="agent_only",
        )

    steps = [
        {"step": 1, "action": "RESEARCH", "target": "neural nets"},
        {"step": 2, "action": "SUMMARIZE", "target": "findings"},
    ]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.side_effect = step_execute
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "research and summarize")

    assert len(call_log) == 2, f"Expected 2 executor calls, got {len(call_log)}"
    assert result["success"] is True
    assert "Step 1" in result["output"]
    assert "Step 2" in result["output"]
    assert result.get("error") is None


def test_execute_plan_steps_tracks_step_states():
    """_step_states reflects done/failed/skipped correctly."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    call_count = [0]

    def fail_on_second(task, context=None, explicit_role=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return PipelineResult(
                success=True, output={"execution": "ok"}, pipeline_type="agent_only"
            )
        return PipelineResult(success=False, output=None, pipeline_type="agent_only")

    steps = [
        {"step": 1, "action": "FETCH", "target": "data"},
        {"step": 2, "action": "PROCESS", "target": "data"},
        {"step": 3, "action": "STORE", "target": "result"},
    ]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.side_effect = fail_on_second
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "pipeline")

    states = result["_step_states"]
    assert states[0]["status"] == "done"
    assert states[1]["status"] == "failed"
    assert states[2]["status"] == "skipped"


def test_execute_plan_steps_stops_on_failure_preserves_partial():
    """Failure on step 2 stops; step 1 output is preserved in result."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    def fail_on_second(task, context=None, explicit_role=None):
        if "RESEARCH" in task:
            return PipelineResult(
                success=True,
                output={"execution": "research done"},
                pipeline_type="agent_only",
            )
        return PipelineResult(success=False, output=None, pipeline_type="agent_only")

    steps = [
        {"step": 1, "action": "RESEARCH", "target": "topic"},
        {"step": 2, "action": "DEPLOY", "target": "unknown"},
    ]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.side_effect = fail_on_second
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "research and deploy")

    assert result["success"] is False
    assert result["output"] is not None, "Partial output from step 1 must be preserved"
    assert "research done" in result["output"]
    assert result["error"] is not None


def test_execute_plan_steps_single_step_works():
    """Single-step plan still executes correctly (regression guard)."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.return_value = PipelineResult(
            success=True,
            output={"execution": "single step done"},
            pipeline_type="agent_only",
        )
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(
            [{"step": 1, "action": "RUN", "target": "task"}], "run task"
        )

    assert result["success"] is True
    assert "single step done" in result["output"]
    assert len(result["_step_states"]) == 1
    assert result["_step_states"][0]["status"] == "done"


def test_execute_plan_steps_no_model_deterministic():
    """No-model mode returns all steps as deterministic text output."""
    agent = _make_agent()

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr(no_model_mode=True)
        mock_get.return_value = mock_mgr

        steps = [
            {"step": 1, "action": "ANALYZE", "target": "data"},
            {"step": 2, "action": "REPORT", "target": "findings"},
        ]
        result = agent._execute_plan_steps(steps, "analyze and report")

    assert result["success"] is True
    assert "ANALYZE" in result["output"]
    assert "REPORT" in result["output"]
    assert all(s["status"] == "done" for s in result["_step_states"])
    mock_mgr.execute.assert_not_called()


def test_execute_action_seat_generated_multi_step_both_steps_run():
    """_execute_action with 2-step _seat_generated plan calls executor twice."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    tasks_executed = []

    def record_execute(task, context=None, explicit_role=None):
        tasks_executed.append(task)
        return PipelineResult(
            success=True,
            output={"execution": f"done:{task}"},
            pipeline_type="agent_only",
        )

    action = {
        "name": "RESEARCH",
        "tool": None,
        "parameters": {
            "task": "step one task",
            "plan": [
                {"step": 1, "action": "FETCH", "target": "raw data"},
                {"step": 2, "action": "ANALYZE", "target": "raw data"},
            ],
        },
        "_seat_generated": True,
    }

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.side_effect = record_execute
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._execute_action(action)

    assert result["success"] is True
    assert len(tasks_executed) == 2, (
        f"Expected 2 steps executed, got {len(tasks_executed)}"
    )
    assert "Step 1" in result["output"]
    assert "Step 2" in result["output"]


def test_execute_plan_steps_respects_max_cap():
    """Plans exceeding _MAX_PLAN_STEPS are truncated, not run indefinitely."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    call_count = [0]

    def count_execute(task, context=None, explicit_role=None):
        call_count[0] += 1
        return PipelineResult(
            success=True, output={"execution": "ok"}, pipeline_type="agent_only"
        )

    # 15 steps — more than _MAX_PLAN_STEPS (10)
    steps = [{"step": i, "action": "DO", "target": f"item{i}"} for i in range(1, 16)]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.side_effect = count_execute
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "do all")

    assert call_count[0] == agent._MAX_PLAN_STEPS, (
        f"Expected {agent._MAX_PLAN_STEPS} calls, got {call_count[0]}"
    )


# ── critic timeout guard ──────────────────────────────────────────────────────


def test_critic_timeout_degrades_safely():
    """Critic seat that times out returns None without blocking the loop."""
    from concurrent.futures import TimeoutError as FuturesTimeout

    agent = _make_agent()

    # Simulate timeout at the future.result() call — no actual sleep needed
    with patch("concurrent.futures.ThreadPoolExecutor") as mock_pool_cls:
        mock_pool = MagicMock()
        mock_pool.__enter__ = MagicMock(return_value=mock_pool)
        mock_pool.__exit__ = MagicMock(return_value=False)
        mock_future = MagicMock()
        mock_future.result.side_effect = FuturesTimeout()
        mock_pool.submit.return_value = mock_future
        mock_pool_cls.return_value = mock_pool

        with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
            mock_mgr = _mock_mgr()
            mock_mgr._no_model_mode = False
            mock_get.return_value = mock_mgr

            result = agent._seat_critique(
                {"success": True, "output": "something"},
                "run_shell",
            )

    assert result is None


def test_critic_timeout_does_not_affect_fast_critic():
    """Fast critic (mocked) still returns its critique under timeout guard."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    crit_result = PipelineResult(
        success=True,
        output={"critique": "- Missing validation"},
        pipeline_type="agent_only",
    )

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.return_value = crit_result
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._seat_critique(
            {"success": True, "output": "some output"},
            "run_shell",
        )

    assert result is not None
    assert "Missing" in result


# ── embed_index.db TTL eviction ───────────────────────────────────────────────


def test_evict_stale_removes_old_rows():
    """Rows older than TTL are removed; bootstrap rows are kept."""
    import tempfile, os, sqlite3, struct, time

    from agents.retriever_agent import RetrieverAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_embed.db")

        # Point the class at our temp DB
        orig_path = RetrieverAgent._index_path
        RetrieverAgent._index_path = db_path
        RetrieverAgent._cache_loaded = False
        RetrieverAgent._embed_cache = {}

        try:
            con = RetrieverAgent._ensure_db()

            old_ts = time.time() - (RetrieverAgent._EMBED_TTL_DAYS + 1) * 86400
            fresh_ts = time.time()

            vec_blob = struct.pack("3f", 0.1, 0.2, 0.3)

            # Old non-bootstrap row → should be evicted
            con.execute(
                "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)",
                ("old_key", vec_blob, old_ts, None),
            )
            # Fresh non-bootstrap row → should survive
            con.execute(
                "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)",
                ("fresh_key", vec_blob, fresh_ts, None),
            )
            # Old bootstrap row → should survive despite age
            con.execute(
                "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)",
                ("bootstrap_key", vec_blob, old_ts, '{"source":"bootstrap"}'),
            )
            con.commit()
            con.close()

            # Also put them in in-process cache to verify cache eviction
            RetrieverAgent._embed_cache["old_key"] = [0.1, 0.2, 0.3]
            RetrieverAgent._embed_cache["fresh_key"] = [0.1, 0.2, 0.3]
            RetrieverAgent._embed_cache["bootstrap_key"] = [0.1, 0.2, 0.3]

            RetrieverAgent._evict_stale()

            con2 = sqlite3.connect(db_path)
            keys = {r[0] for r in con2.execute("SELECT key FROM vectors")}
            con2.close()

            assert "old_key" not in keys, "Stale row should be evicted"
            assert "fresh_key" in keys, "Fresh row should survive"
            assert "bootstrap_key" in keys, (
                "Bootstrap row must survive regardless of age"
            )
            assert "old_key" not in RetrieverAgent._embed_cache, (
                "In-process cache must be cleaned"
            )
            assert "fresh_key" in RetrieverAgent._embed_cache

        finally:
            RetrieverAgent._index_path = orig_path
            RetrieverAgent._cache_loaded = False
            RetrieverAgent._embed_cache = {}


def test_evict_stale_enforces_max_rows():
    """When non-bootstrap rows exceed _EMBED_MAX_ROWS, oldest are removed."""
    import tempfile, os, sqlite3, struct, time

    from agents.retriever_agent import RetrieverAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_embed_cap.db")
        orig_path = RetrieverAgent._index_path
        orig_max = RetrieverAgent._EMBED_MAX_ROWS
        RetrieverAgent._index_path = db_path
        RetrieverAgent._EMBED_MAX_ROWS = 3  # tiny cap for test
        RetrieverAgent._cache_loaded = False
        RetrieverAgent._embed_cache = {}

        try:
            con = RetrieverAgent._ensure_db()
            vec_blob = struct.pack("3f", 0.1, 0.2, 0.3)
            now = time.time()

            # Insert 5 rows with increasing timestamps
            for i in range(5):
                con.execute(
                    "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)",
                    (f"key_{i}", vec_blob, now + i, None),
                )
            con.commit()
            con.close()

            RetrieverAgent._evict_stale()

            con2 = sqlite3.connect(db_path)
            remaining = [
                r[0]
                for r in con2.execute("SELECT key FROM vectors ORDER BY updated_at ASC")
            ]
            con2.close()

            assert len(remaining) == 3, (
                f"Expected 3 rows after cap eviction, got {len(remaining)}"
            )
            # Oldest rows (key_0, key_1) should be gone; newest 3 survive
            assert "key_0" not in remaining
            assert "key_1" not in remaining
            assert "key_4" in remaining

        finally:
            RetrieverAgent._index_path = orig_path
            RetrieverAgent._EMBED_MAX_ROWS = orig_max
            RetrieverAgent._cache_loaded = False
            RetrieverAgent._embed_cache = {}


def test_evict_triggered_by_write_counter():
    """_evict_stale is called after _EVICT_EVERY_N_WRITES writes."""
    from agents.retriever_agent import RetrieverAgent

    orig_counter = RetrieverAgent._write_counter
    orig_every = RetrieverAgent._EVICT_EVERY_N_WRITES
    RetrieverAgent._EVICT_EVERY_N_WRITES = 3
    RetrieverAgent._write_counter = 2  # one write away from trigger

    evict_called = []

    orig_evict = RetrieverAgent._evict_stale
    RetrieverAgent._evict_stale = classmethod(lambda cls: evict_called.append(1))

    try:
        with patch.object(RetrieverAgent, "_ensure_db") as mock_db:
            con = MagicMock()
            con.__enter__ = MagicMock(return_value=con)
            con.__exit__ = MagicMock(return_value=False)
            mock_db.return_value = con

            RetrieverAgent._persist_vector("k", [0.1, 0.2], meta="test")

        assert len(evict_called) == 1, "Eviction should fire on Nth write"
    finally:
        RetrieverAgent._write_counter = orig_counter
        RetrieverAgent._EVICT_EVERY_N_WRITES = orig_every
        RetrieverAgent._evict_stale = orig_evict


# ── _try_seat_response timeout guard ─────────────────────────────────────────


def test_try_seat_response_fast_path_works():
    """Fast seat response is returned correctly under timeout guard."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    seat_result = PipelineResult(
        success=True,
        output="Neural networks are computational models inspired by the brain.",
        pipeline_type="agent_only",
    )

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr.execute.return_value = seat_result
        mock_mgr._no_model_mode = False
        mock_get.return_value = mock_mgr

        result = agent._try_seat_response("what is a neural network?")

    assert result is not None
    assert "Neural" in result or len(result) > 10


def test_try_seat_response_timeout_degrades_safely():
    """Timed-out seat response returns None without hanging."""
    from concurrent.futures import TimeoutError as FuturesTimeout

    agent = _make_agent()

    with patch("concurrent.futures.ThreadPoolExecutor") as mock_pool_cls:
        mock_pool = MagicMock()
        mock_pool.__enter__ = MagicMock(return_value=mock_pool)
        mock_pool.__exit__ = MagicMock(return_value=False)
        mock_future = MagicMock()
        mock_future.result.side_effect = FuturesTimeout()
        mock_pool.submit.return_value = mock_future
        mock_pool_cls.return_value = mock_pool

        result = agent._try_seat_response("explain something complex")

    assert result is None


def test_try_seat_response_exception_degrades_safely():
    """Exception inside seat call returns None, does not propagate."""
    agent = _make_agent()

    with patch(
        "core.agent_model_manager.get_agent_model_manager",
        side_effect=RuntimeError("boom"),
    ):
        result = agent._try_seat_response("what is X?")

    assert result is None


def test_try_seat_response_no_model_mode_returns_none():
    """No-model mode skips seat call and returns None."""
    agent = _make_agent()

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr(no_model_mode=True)
        mock_get.return_value = mock_mgr

        result = agent._try_seat_response("what is Y?")

    assert result is None
    mock_mgr.execute.assert_not_called()


# ── adaptive replanning ───────────────────────────────────────────────────────


def test_replan_after_failure_calls_planner_seat():
    """Step failure triggers _replan_after_failure; planner seat is called with failure context."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    recovery_steps = [
        {"step": 1, "action": "RETRY", "target": "failed task"},
    ]
    replan_result = PipelineResult(
        success=True,
        output={"plan_steps": recovery_steps},
        pipeline_type="agent_only",
    )

    steps = [
        {"step": 1, "action": "FETCH", "target": "data"},
        {"step": 2, "action": "PROCESS", "target": "data"},
    ]

    call_roles = []

    def _capture_execute(**kwargs):
        call_roles.append(kwargs.get("explicit_role"))
        if kwargs.get("explicit_role") == "executor":
            if kwargs.get("task", "").startswith("FETCH"):
                return PipelineResult(
                    success=False, output=None, pipeline_type="agent_only"
                )
            return PipelineResult(
                success=True, output={"execution": "done"}, pipeline_type="agent_only"
            )
        # planner seat (replan call)
        return replan_result

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _capture_execute(**kw)
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "fetch and process")

    assert "planner" in call_roles, "Planner seat must be called for replan"
    assert result.get("_replan_artifact") is not None


def test_replan_recovery_steps_executed_with_recovery_prefix():
    """Recovery steps execute and output contains '[Recovery]' prefix."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    recovery_steps = [{"step": 1, "action": "RETRY", "target": "task"}]

    def _execute(**kwargs):
        role = kwargs.get("explicit_role")
        task = kwargs.get("task", "")
        if role == "executor":
            if "STEP1" in task or "do work" in task:
                return PipelineResult(
                    success=False, output=None, pipeline_type="agent_only"
                )
            # recovery executor call
            return PipelineResult(
                success=True,
                output={"execution": "recovered"},
                pipeline_type="agent_only",
            )
        # planner replan
        return PipelineResult(
            success=True,
            output={"plan_steps": recovery_steps},
            pipeline_type="agent_only",
        )

    steps = [{"step": 1, "action": "STEP1", "target": "do work"}]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _execute(**kw)
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "do work")

    assert result.get("output") is not None
    assert "[Recovery]" in result["output"]
    artifact = result.get("_replan_artifact", {})
    assert artifact.get("outcome") in ("recovered", "recovery_failed")


def test_replan_returns_stopped_when_planner_returns_empty():
    """When replanner returns [], artifact outcome is 'stopped', no recursion."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    def _execute(**kwargs):
        role = kwargs.get("explicit_role")
        if role == "executor":
            return PipelineResult(
                success=False, output=None, pipeline_type="agent_only"
            )
        # planner returns empty plan
        return PipelineResult(
            success=True,
            output={"plan_steps": []},
            pipeline_type="agent_only",
        )

    steps = [{"step": 1, "action": "FAIL_ME", "target": "x"}]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _execute(**kw)
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "should fail cleanly")

    assert result["success"] is False
    artifact = result.get("_replan_artifact", {})
    assert artifact.get("outcome") == "stopped"


def test_replan_not_triggered_when_allow_replan_false():
    """Recursive guard: allow_replan=False means no planner seat called on failure."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    planner_calls = []

    def _execute(**kwargs):
        role = kwargs.get("explicit_role")
        if role == "planner":
            planner_calls.append(1)
        return PipelineResult(success=False, output=None, pipeline_type="agent_only")

    steps = [{"step": 1, "action": "FAIL", "target": "x"}]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _execute(**kw)
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "no replan", allow_replan=False)

    assert result["success"] is False
    assert len(planner_calls) == 0, "Planner must NOT be called when allow_replan=False"
    assert result.get("_replan_artifact") is None


def test_replan_exception_in_planner_degrades_cleanly():
    """Exception inside _replan_after_failure returns [] — no crash, stops cleanly."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    def _execute(**kwargs):
        role = kwargs.get("explicit_role")
        if role == "executor":
            return PipelineResult(
                success=False, output=None, pipeline_type="agent_only"
            )
        raise RuntimeError("planner seat exploded")

    steps = [{"step": 1, "action": "BOOM", "target": "x"}]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _execute(**kw)
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "exception path")

    assert result["success"] is False
    artifact = result.get("_replan_artifact", {})
    assert artifact.get("outcome") == "stopped"


# ── stateful step propagation + run artifact ─────────────────────────────────


def test_step2_receives_prior_results_from_step1():
    """Step 2 executor call receives prior_results containing step 1 output."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    received_prior = {}

    def _execute(task, context=None, explicit_role=None):
        step_num = (context or {}).get("plan_steps", [{}])[0].get("step", 0)
        prior = (context or {}).get("prior_results", [])
        if "FETCH" in task:
            return PipelineResult(
                success=True,
                output={"execution": "fetched data"},
                pipeline_type="agent_only",
            )
        # PROCESS step — capture what prior_results it sees
        received_prior["prior"] = list(prior)
        return PipelineResult(
            success=True,
            output={"execution": "processed"},
            pipeline_type="agent_only",
        )

    steps = [
        {"step": 1, "action": "FETCH", "target": "raw"},
        {"step": 2, "action": "PROCESS", "target": "raw"},
    ]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "fetch then process")

    assert result["success"] is True
    prior = received_prior.get("prior", [])
    assert len(prior) == 1, f"Step 2 should see 1 prior result, got {prior}"
    assert prior[0]["step"] == 1
    assert prior[0]["action"] == "FETCH"
    assert "fetched data" in prior[0]["output"]


def test_run_artifact_always_present_on_success():
    """_run_artifact is present and correct on a clean 2-step success."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    def _execute(task, context=None, explicit_role=None):
        return PipelineResult(
            success=True,
            output={"execution": f"done:{task}"},
            pipeline_type="agent_only",
        )

    steps = [
        {"step": 1, "action": "A", "target": "x"},
        {"step": 2, "action": "B", "target": "y"},
    ]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "do A then B")

    art = result.get("_run_artifact")
    assert art is not None, "_run_artifact must always be present"
    assert art["task"] == "do A then B"
    assert art["outcome"] == "success"
    assert len(art["plan"]) == 2
    assert len(art["steps"]) == 2
    assert len(art["prior_results"]) == 2
    assert art["prior_results"][0]["action"] == "A"
    assert art["prior_results"][1]["action"] == "B"
    assert art["failed"] == []
    assert art["recovery"] is None


def test_run_artifact_present_on_failure():
    """_run_artifact is present with outcome='failed' when a step fails."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    def _execute(**kwargs):
        role = kwargs.get("explicit_role")
        if role == "executor":
            return PipelineResult(
                success=False, output=None, pipeline_type="agent_only"
            )
        # planner (replan) — return empty so no recovery loop
        return PipelineResult(
            success=True, output={"plan_steps": []}, pipeline_type="agent_only"
        )

    steps = [{"step": 1, "action": "FAIL", "target": "x"}]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _execute(**kw)
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "fail test")

    art = result.get("_run_artifact")
    assert art is not None
    assert art["outcome"] in ("failed", "stopped")
    assert len(art["failed"]) == 1


def test_run_artifact_no_model_mode():
    """No-model path also produces a structured _run_artifact."""
    agent = _make_agent()

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr(no_model_mode=True)
        mock_get.return_value = mock_mgr

        steps = [
            {"step": 1, "action": "X", "target": "a"},
            {"step": 2, "action": "Y", "target": "b"},
        ]
        result = agent._execute_plan_steps(steps, "no model task")

    art = result.get("_run_artifact")
    assert art is not None
    assert art["outcome"] == "success"
    assert len(art["prior_results"]) == 2
    assert art["prior_results"][0]["action"] == "X"


def test_replanner_receives_run_artifact_in_context():
    """_replan_after_failure passes run_artifact in context to planner seat."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    captured_ctx = {}

    def _execute(**kwargs):
        role = kwargs.get("explicit_role")
        ctx = kwargs.get("context", {})
        if role == "executor":
            return PipelineResult(
                success=False, output=None, pipeline_type="agent_only"
            )
        # planner (replan call) — capture context
        captured_ctx.update(ctx)
        return PipelineResult(
            success=True, output={"plan_steps": []}, pipeline_type="agent_only"
        )

    steps = [{"step": 1, "action": "FAIL", "target": "task"}]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _execute(**kw)
        mock_get.return_value = mock_mgr

        agent._execute_plan_steps(steps, "task with structured replan")

    assert "run_artifact" in captured_ctx, (
        "Planner seat must receive run_artifact in context"
    )
    art = captured_ctx["run_artifact"]
    assert isinstance(art, dict)
    assert "plan" in art
    assert "steps" in art
    assert "failed" in art


def test_prior_results_empty_for_first_step():
    """Step 1 receives an empty prior_results list."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    received_prior = {}

    def _execute(task, context=None, explicit_role=None):
        if not received_prior:
            received_prior["prior"] = list(
                (context or {}).get("prior_results", ["SENTINEL"])
            )
        return PipelineResult(
            success=True, output={"execution": "ok"}, pipeline_type="agent_only"
        )

    steps = [{"step": 1, "action": "FIRST", "target": "thing"}]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        agent._execute_plan_steps(steps, "first step")

    assert received_prior.get("prior") == [], (
        f"Step 1 must receive empty prior_results, got {received_prior.get('prior')}"
    )


# ── ExecutorAgent prior_results consumption ───────────────────────────────────


def _make_executor():
    from agents.executor_agent import ExecutorAgent

    return ExecutorAgent()


def _make_agent_context(task, prior_results=None, plan_steps=None):
    from agents.base_agent import AgentContext

    return AgentContext(
        task=task,
        input_data={
            "prior_results": prior_results or [],
            "plan_steps": plan_steps or [],
            "intent": "execute",
        },
    )


def test_executor_includes_prior_results_in_prompt():
    """ExecutorAgent includes prior step outputs in the model prompt."""
    executor = _make_executor()

    captured_prompt = {}

    def mock_try_model(prompt, system=None, max_tokens=None):
        captured_prompt["prompt"] = prompt
        return "1. do the thing"

    executor._try_model = mock_try_model

    prior = [
        {"step": 1, "action": "FETCH", "target": "data", "output": "fetched 42 records"}
    ]
    ctx = _make_agent_context("PROCESS data", prior_results=prior)
    result = executor.run(ctx)

    assert result.success is True
    assert (
        "prior" in captured_prompt.get("prompt", "").lower()
        or "step 1" in captured_prompt.get("prompt", "").lower()
    ), (
        f"Prompt should reference prior results: {captured_prompt.get('prompt', '')[:200]}"
    )
    assert "fetched 42 records" in captured_prompt.get("prompt", "")


def test_executor_empty_prior_results_gives_plain_prompt():
    """When prior_results is empty, executor prompt has no prior context block."""
    executor = _make_executor()

    captured_prompt = {}

    def mock_try_model(prompt, system=None, max_tokens=None):
        captured_prompt["prompt"] = prompt
        return "1. do task"

    executor._try_model = mock_try_model

    ctx = _make_agent_context("RUN task", prior_results=[])
    executor.run(ctx)

    prompt = captured_prompt.get("prompt", "")
    assert "Prior" not in prompt, (
        f"Empty prior_results should not add prior block: {prompt}"
    )
    assert "RUN task" in prompt


def test_executor_model_path_runs_even_when_plan_steps_present():
    """plan_steps in context does NOT block the model path when task is set."""
    executor = _make_executor()

    model_called = [False]

    def mock_try_model(prompt, system=None, max_tokens=None):
        model_called[0] = True
        return "execute the task"

    executor._try_model = mock_try_model

    plan_steps = [{"step": 1, "action": "A"}, {"step": 2, "action": "B"}]
    ctx = _make_agent_context("A target", plan_steps=plan_steps)
    result = executor.run(ctx)

    assert model_called[0], (
        "Model path must be used when task is set, even if plan_steps present"
    )
    assert result.success is True


def test_executor_deterministic_fallback_when_no_task():
    """When task is empty, executor falls through to deterministic plan_steps loop."""
    executor = _make_executor()

    model_called = [False]

    def mock_try_model(prompt, system=None, max_tokens=None):
        model_called[0] = True
        return "model output"

    executor._try_model = mock_try_model

    from agents.base_agent import AgentContext

    ctx = AgentContext(
        task="",  # empty task
        input_data={
            "plan_steps": [{"step": 1, "action": "research", "target": "x"}],
            "prior_results": [],
        },
    )
    result = executor.run(ctx)

    assert not model_called[0], "Model must not be called when task is empty"
    assert result.success is True
    assert "step_results" in (result.output or {})


# ── recovery-run prior_results inheritance ────────────────────────────────────


def test_recovery_steps_inherit_original_prior_results():
    """Recovery steps start with the original run's completed prior_results."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    # Track prior_results received by each executor call
    executor_priors = []

    def _execute(**kwargs):
        role = kwargs.get("explicit_role")
        ctx = kwargs.get("context", {})
        if role == "executor":
            executor_priors.append(list(ctx.get("prior_results", [])))
            task = kwargs.get("task", "")
            if "STEP1" in task:
                return PipelineResult(
                    success=True,
                    output={"execution": "step1 done"},
                    pipeline_type="agent_only",
                )
            if "FAIL" in task:
                return PipelineResult(
                    success=False, output=None, pipeline_type="agent_only"
                )
            # recovery step
            return PipelineResult(
                success=True,
                output={"execution": "recovered"},
                pipeline_type="agent_only",
            )
        # planner (replan)
        return PipelineResult(
            success=True,
            output={"plan_steps": [{"step": 1, "action": "RECOVER", "target": "x"}]},
            pipeline_type="agent_only",
        )

    steps = [
        {"step": 1, "action": "STEP1", "target": "thing"},
        {"step": 2, "action": "FAIL", "target": "thing"},
    ]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _execute(**kw)
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "step1 then fail then recover")

    # executor_priors: [step1_prior, step2_prior, recovery_prior]
    assert len(executor_priors) >= 3, (
        f"Expected 3+ executor calls, got {len(executor_priors)}"
    )
    step1_prior = executor_priors[0]
    step2_prior = executor_priors[1]
    recovery_prior = executor_priors[2]

    assert step1_prior == [], "Step 1 must start with empty prior_results"
    assert len(step2_prior) == 1, f"Step 2 must see step1 result, got {step2_prior}"
    assert step2_prior[0]["action"] == "STEP1"

    # Recovery step must inherit at least step1's completed output
    assert len(recovery_prior) >= 1, (
        f"Recovery step must inherit original prior_results, got {recovery_prior}"
    )
    assert any(r["action"] == "STEP1" for r in recovery_prior), (
        f"Recovery prior_results must include original completed steps: {recovery_prior}"
    )


# ── run artifact summarization + memory persistence ───────────────────────────


def test_format_run_artifact_content_success():
    """_format_run_artifact_content produces structured text from a clean run."""
    from agent.agent_loop import AgentLoop, load_config

    artifact = {
        "task": "fetch and process",
        "outcome": "success",
        "steps": [
            {"status": "done"},
            {"status": "done"},
        ],
        "outputs": ["Step 1: fetched", "Step 2: processed"],
        "failed": [],
        "recovery": None,
    }
    content = AgentLoop._format_run_artifact_content(artifact)
    assert "fetch and process" in content
    assert "success" in content
    assert "2 total" in content
    assert "fetched" in content


def test_format_run_artifact_content_with_failure_and_recovery():
    """_format_run_artifact_content captures failure and recovery info."""
    from agent.agent_loop import AgentLoop, load_config

    artifact = {
        "task": "complex task",
        "outcome": "recovered",
        "steps": [
            {"status": "done"},
            {"status": "failed"},
        ],
        "outputs": ["Step 1: ok"],
        "failed": [
            {"step": 2, "action": "DEPLOY", "target": "prod", "error": "timeout"}
        ],
        "recovery": {"outcome": "recovered", "recovery_plan": [{"step": 1}]},
    }
    content = AgentLoop._format_run_artifact_content(artifact)
    assert "recovered" in content
    assert "DEPLOY" in content or "timeout" in content
    assert "Recovery" in content


def test_seat_summarize_run_calls_summarizer_seat():
    """_seat_summarize_run calls summarizer seat with run_artifact content_type."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    captured = {}

    def _execute(task, context=None, explicit_role=None):
        if explicit_role == "summarizer":
            captured["ctx"] = context or {}
            return PipelineResult(
                success=True,
                output={"summary": "Run completed 2 steps successfully."},
                pipeline_type="agent_only",
            )
        return PipelineResult(success=False, output=None, pipeline_type="agent_only")

    artifact = {
        "task": "test run",
        "outcome": "success",
        "steps": [{"status": "done"}, {"status": "done"}],
        "outputs": ["Step 1: ok", "Step 2: ok"],
        "failed": [],
        "recovery": None,
    }

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        summary = agent._seat_summarize_run(artifact)

    assert captured.get("ctx", {}).get("content_type") == "run_artifact"
    assert "test run" in captured.get("ctx", {}).get("content", "")
    assert "Run completed" in summary


def test_seat_summarize_run_fallback_on_no_model():
    """_seat_summarize_run falls back to deterministic content when no model."""
    agent = _make_agent()

    artifact = {
        "task": "no model task",
        "outcome": "success",
        "steps": [{"status": "done"}],
        "outputs": ["Step 1: done"],
        "failed": [],
        "recovery": None,
    }

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr(no_model_mode=True)
        mock_get.return_value = mock_mgr

        summary = agent._seat_summarize_run(artifact)

    assert "no model task" in summary
    assert "success" in summary


def test_persist_run_digest_writes_to_memory():
    """_persist_run_digest writes run:last and run:<hash> facts to memory."""
    agent = _make_agent()
    agent.memory.facts.clear()

    artifact = {
        "task": "persist test",
        "outcome": "success",
        "steps": [{"status": "done"}],
        "outputs": [],
        "failed": [],
        "recovery": None,
    }

    agent._persist_run_digest(artifact, "Run succeeded in 1 step.")

    assert "run:last" in agent.memory.facts, "run:last must be written to memory"
    digest = agent.memory.facts["run:last"]
    # Facts are stored as wrapped dicts with "value" key
    val = digest.get("value", digest) if isinstance(digest, dict) else digest
    assert val.get("task") == "persist test"
    assert val.get("outcome") == "success"
    # summary is now always compact computed format (task: outcome | ...)
    summary = val.get("summary", "")
    assert "persist test" in summary
    assert "success" in summary
    # enriched fields present
    assert "completed_steps" in val
    assert "failed_steps" in val

    # Also verify a run:<hash> key exists
    run_keys = [
        k for k in agent.memory.facts if k.startswith("run:") and k != "run:last"
    ]
    assert len(run_keys) >= 1, "Per-run keyed fact must be written"


def test_run_artifact_propagates_through_execute_action():
    """_execute_action propagates _run_artifact from _execute_plan_steps."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    def _execute(task, context=None, explicit_role=None):
        return PipelineResult(
            success=True,
            output={"execution": "done"},
            pipeline_type="agent_only",
        )

    action = {
        "name": "TASK",
        "tool": None,
        "parameters": {
            "task": "two step task",
            "plan": [
                {"step": 1, "action": "A", "target": "x"},
                {"step": 2, "action": "B", "target": "y"},
            ],
        },
        "_seat_generated": True,
    }

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = _execute
        mock_get.return_value = mock_mgr

        result = agent._execute_action(action)

    assert result.get("_run_artifact") is not None, (
        "_run_artifact must propagate through _execute_action"
    )
    art = result["_run_artifact"]
    assert art["task"] == "two step task"
    assert art["outcome"] == "success"


def test_summarizer_run_artifact_deterministic_fallback():
    """SummarizerAgent handles run_artifact content_type in deterministic path."""
    from agents.summarizer_agent import SummarizerAgent
    from agents.base_agent import AgentContext

    agent_s = SummarizerAgent()
    agent_s._try_model = lambda *a, **kw: None  # force deterministic

    content = (
        "Task: test\nOutcome: success\nSteps: 1 total (1 done, 0 failed, 0 skipped)"
    )
    ctx = AgentContext(
        task="summarize run",
        input_data={"content_type": "run_artifact", "content": content},
    )
    result = agent_s.run(ctx)

    assert result.success is True
    assert "test" in result.output.get("summary", "")


# ── linked recovery persistence ───────────────────────────────────────────────


def _make_agent_with_clean_memory():
    """Return an AgentLoop with a clean facts dict for isolation."""
    agent = _make_agent()
    agent.memory.facts.clear()
    return agent


def _build_run_artifact_with_recovery(
    parent_outcome="recovered",
    recovery_outcome="success",
    recovery_steps=None,
):
    """Build a synthetic _run_artifact that includes a recovery_execution."""
    recovery_exec = {
        "task": "fetch and process data",
        "outcome": recovery_outcome,
        "steps": recovery_steps
        or [{"step": 1, "status": "done", "action": "RETRY", "target": "data"}],
        "outputs": ["Step 1: retried"],
        "prior_results": [],
        "failed": [],
        "recovery": None,  # no nested recovery (allow_replan=False enforces this)
    }
    replan_artifact = {
        "original_plan": [{"step": 1, "action": "FETCH", "target": "data"}],
        "failed_step": {
            "step": 1,
            "action": "FETCH",
            "target": "data",
            "error": "timeout",
        },
        "recovery_plan": [{"step": 1, "action": "RETRY", "target": "data"}],
        "outcome": parent_outcome,
        "recovery_execution": recovery_exec,
    }
    return {
        "task": "fetch and process data",
        "outcome": parent_outcome,
        "plan": [{"step": 1, "action": "FETCH", "target": "data"}],
        "steps": [
            {
                "step": 1,
                "status": "failed",
                "action": "FETCH",
                "target": "data",
                "error": "timeout",
            },
        ],
        "outputs": ["[Recovery] Step 1: retried"],
        "prior_results": [],
        "failed": [
            {"step": 1, "action": "FETCH", "target": "data", "error": "timeout"}
        ],
        "recovery": replan_artifact,
    }


def test_persist_run_digest_creates_linked_recovery_entry():
    """Parent + recovery both written to memory when recovery_execution is present."""
    agent = _make_agent_with_clean_memory()

    artifact = _build_run_artifact_with_recovery()
    agent._persist_run_digest(artifact, "Run recovered after 1 failure.")

    keys = list(agent.memory.facts.keys())

    # Parent must be written
    assert "run:last" in keys
    run_keys = [k for k in keys if k.startswith("run:") and k not in ("run:last",)]
    parent_keys = [k for k in run_keys if not k.startswith("run:recovery:")]
    recovery_keys = [k for k in run_keys if k.startswith("run:recovery:")]

    assert len(parent_keys) >= 1, f"Parent run key must be written, got keys: {keys}"
    assert len(recovery_keys) == 1, (
        f"Exactly one recovery key must be written, got: {recovery_keys}"
    )


def test_parent_digest_references_recovery_run_id():
    """Parent digest contains recovery_run_id pointing to the child entry."""
    agent = _make_agent_with_clean_memory()

    artifact = _build_run_artifact_with_recovery()
    agent._persist_run_digest(artifact, "Run recovered.")

    parent_val = agent.memory.facts["run:last"].get(
        "value", agent.memory.facts["run:last"]
    )
    assert parent_val.get("recovery_run_id") is not None, (
        "Parent digest must have recovery_run_id set"
    )
    # The recovery_run_id must point to an actual key in memory
    rec_id = parent_val["recovery_run_id"]
    assert rec_id in agent.memory.facts, (
        f"recovery_run_id '{rec_id}' must be a real key in memory"
    )


def test_recovery_digest_references_parent_run_id():
    """Recovery child digest contains parent_run_id and run_kind='recovery'."""
    agent = _make_agent_with_clean_memory()

    artifact = _build_run_artifact_with_recovery()
    agent._persist_run_digest(artifact, "Run recovered.")

    keys = list(agent.memory.facts.keys())
    recovery_keys = [k for k in keys if k.startswith("run:recovery:")]
    assert len(recovery_keys) == 1

    rec_entry = agent.memory.facts[recovery_keys[0]]
    rec_val = rec_entry.get("value", rec_entry)

    assert rec_val.get("run_kind") == "recovery", (
        f"run_kind must be 'recovery': {rec_val}"
    )
    assert rec_val.get("parent_run_id") is not None, (
        "Recovery digest must have parent_run_id"
    )

    parent_id = rec_val["parent_run_id"]
    parent_entry = agent.memory.facts.get(parent_id)
    assert parent_entry is not None, f"parent_run_id '{parent_id}' must exist in memory"

    parent_val = parent_entry.get("value", parent_entry)
    assert parent_val.get("run_id") == parent_id, (
        "Parent's run_id must match child's parent_run_id"
    )


def test_parent_summary_does_not_contain_full_child_body():
    """Parent digest summary is concise and does not inline the full recovery child."""
    agent = _make_agent_with_clean_memory()

    artifact = _build_run_artifact_with_recovery()
    agent._persist_run_digest(artifact, "Run recovered after 1 failure.")

    parent_val = agent.memory.facts["run:last"].get(
        "value", agent.memory.facts["run:last"]
    )
    summary = parent_val.get("summary", "")

    # Summary is compact (single-line digest format, not multi-line artifact dump)
    assert "\n" not in summary, "Parent summary must be single-line compact format"
    assert len(summary) <= 300, f"Parent summary must be concise: {len(summary)} chars"
    # Must reference task and outcome
    assert "fetch and process data" in summary or "process" in summary.lower()


def test_no_recovery_present_behavior_unchanged():
    """Plain successful run with no recovery writes only parent keys, no recovery key."""
    agent = _make_agent_with_clean_memory()

    plain_artifact = {
        "task": "simple task",
        "outcome": "success",
        "steps": [{"step": 1, "status": "done", "action": "RUN", "target": "x"}],
        "outputs": ["Step 1: done"],
        "prior_results": [],
        "failed": [],
        "recovery": None,
    }
    agent._persist_run_digest(plain_artifact, "Simple task succeeded.")

    keys = list(agent.memory.facts.keys())
    recovery_keys = [k for k in keys if k.startswith("run:recovery:")]
    assert len(recovery_keys) == 0, (
        f"No recovery keys should be written for plain run: {keys}"
    )
    assert "run:last" in keys


def test_nested_recovery_does_not_recurse():
    """recovery_execution has no nested recovery_execution — no infinite loop."""
    agent = _make_agent_with_clean_memory()

    # Build an artifact where the recovery_execution itself has a (malformed) nested recovery_execution.
    # _persist_run_digest must not recurse into it.
    nested_artifact = _build_run_artifact_with_recovery()
    # Inject a spurious nested recovery_execution into the child (should be ignored)
    nested_artifact["recovery"]["recovery_execution"]["recovery"] = {
        "recovery_execution": {
            "task": "deeply nested",
            "steps": [{"step": 1}],
            "outcome": "unknown",
        }
    }

    # Must complete without error and must NOT create a grandchild recovery key
    agent._persist_run_digest(nested_artifact, "Nested test.")

    keys = list(agent.memory.facts.keys())
    recovery_keys = [k for k in keys if k.startswith("run:recovery:")]
    # Exactly one recovery child — no deeper nesting
    assert len(recovery_keys) == 1, (
        f"Only one recovery level must be persisted: {recovery_keys}"
    )


def test_recovery_execution_in_execute_plan_steps():
    """End-to-end: _execute_plan_steps threads recovery _run_artifact into replan_artifact."""
    agent = _make_agent()

    from core.agent_model_manager import PipelineResult

    def _execute(**kwargs):
        role = kwargs.get("explicit_role")
        task = kwargs.get("task", "")
        if role == "executor":
            if "FAIL" in task:
                return PipelineResult(
                    success=False, output=None, pipeline_type="agent_only"
                )
            # Recovery step
            return PipelineResult(
                success=True,
                output={"execution": "recovered"},
                pipeline_type="agent_only",
            )
        # Planner replan
        return PipelineResult(
            success=True,
            output={"plan_steps": [{"step": 1, "action": "RECOVER", "target": "x"}]},
            pipeline_type="agent_only",
        )

    steps = [{"step": 1, "action": "FAIL", "target": "x"}]

    with patch("core.agent_model_manager.get_agent_model_manager") as mock_get:
        mock_mgr = _mock_mgr()
        mock_mgr._no_model_mode = False
        mock_mgr.execute.side_effect = lambda **kw: _execute(**kw)
        mock_get.return_value = mock_mgr

        result = agent._execute_plan_steps(steps, "fail then recover")

    artifact = result.get("_run_artifact", {})
    recovery = artifact.get("recovery", {})

    assert recovery is not None, "_run_artifact must have recovery field"
    assert "recovery_execution" in recovery, (
        "replan_artifact must contain recovery_execution after successful recovery"
    )
    rec_exec = recovery["recovery_execution"]
    assert rec_exec is not None
    assert len(rec_exec.get("steps", [])) >= 1, "recovery_execution must have step data"
    # recovery_execution must not itself have a recovery (allow_replan=False)
    assert rec_exec.get("recovery") is None, (
        "recovery_execution must not have nested recovery (allow_replan=False enforces this)"
    )


def test_recovery_run_history_retrievable():
    """Recovery child is retrievable as a run_history fact via standard lookup."""
    from agents.retriever_agent import RetrieverAgent

    agent = _make_agent_with_clean_memory()
    artifact = _build_run_artifact_with_recovery()
    agent._persist_run_digest(artifact, "Recovered run.")

    # Use the retriever's run_history_lookup to confirm child is retrievable
    results = RetrieverAgent._run_history_lookup(agent.memory, 10)
    sources = [r.get("source") for r in results]
    kinds = [r.get("value", {}).get("run_kind") for r in results]

    assert "run_history" in sources, "run_history source must appear in lookup results"
    assert "recovery" in kinds, "recovery run_kind must appear in lookup results"
    assert "primary" in kinds, "primary run_kind must appear in lookup results"


def test_parent_run_id_stable_and_unique():
    """Each _persist_run_digest call generates a unique run_id for the parent."""
    agent = _make_agent_with_clean_memory()

    plain = {
        "task": "task A",
        "outcome": "success",
        "steps": [{"step": 1, "status": "done", "action": "A", "target": "x"}],
        "outputs": ["Step 1: done"],
        "prior_results": [],
        "failed": [],
        "recovery": None,
    }

    agent._persist_run_digest(plain, "Run A done.")
    # Capture first run_id
    first_id = (
        agent.memory.facts["run:last"]
        .get("value", agent.memory.facts["run:last"])
        .get("run_id")
    )

    plain["task"] = "task B"
    agent._persist_run_digest(plain, "Run B done.")
    second_id = (
        agent.memory.facts["run:last"]
        .get("value", agent.memory.facts["run:last"])
        .get("run_id")
    )

    assert first_id is not None
    assert second_id is not None
    assert first_id != second_id, "Each persist call must generate a distinct run_id"


# ── Recovery child summarizer-path tests ─────────────────────────────────────


def _get_rec_digest(agent):
    """Return the recovery child digest from agent memory (first run:recovery: key)."""
    for key, val in agent.memory.facts.items():
        if key.startswith("run:recovery:"):
            return (
                val.get("value", val)
                if isinstance(val, dict) and "value" in val
                else val
            )
    return None


def test_recovery_child_uses_compact_summary():
    """_persist_run_digest uses _build_compact_digest_summary for recovery child."""
    agent = _make_agent_with_clean_memory()
    artifact = _build_run_artifact_with_recovery()

    agent._persist_run_digest(artifact, "Parent summary.")

    rec = _get_rec_digest(agent)
    assert rec is not None, "Recovery child digest must be written"
    # Compact format: "task: outcome | ..."
    summary = rec["summary"]
    assert ":" in summary, f"Compact summary must include task:outcome: {summary!r}"
    assert rec.get("completed_steps") is not None, "Recovery child must have completed_steps"


def test_recovery_child_summary_contains_outcome():
    """Recovery child digest always has compact summary with outcome."""
    agent = _make_agent_with_clean_memory()
    artifact = _build_run_artifact_with_recovery(recovery_outcome="success")

    agent._persist_run_digest(artifact, "Parent summary.")

    rec = _get_rec_digest(agent)
    assert rec is not None
    # compact summary references outcome
    assert "success" in rec["summary"]


def test_recovery_child_compact_format_single_line():
    """Recovery child digest summary is single-line compact, not multi-line artifact dump."""
    agent = _make_agent_with_clean_memory()
    artifact = _build_run_artifact_with_recovery(recovery_outcome="failed")

    agent._persist_run_digest(artifact, "Parent summary.")

    rec = _get_rec_digest(agent)
    assert rec is not None
    # Must be compact single-line, not the multi-line _format_run_artifact_content
    assert "\n" not in rec["summary"], f"Recovery summary must be compact: {rec['summary']!r}"
    assert "failed" in rec["summary"]


def test_recovery_child_summary_differs_from_parent():
    """Parent and recovery child have independent compact summaries."""
    agent = _make_agent_with_clean_memory()
    artifact = _build_run_artifact_with_recovery()

    agent._persist_run_digest(artifact, "Distinct parent summary.")

    parent = agent.memory.facts.get("run:last", {})
    parent = (
        parent.get("value", parent)
        if isinstance(parent, dict) and "value" in parent
        else parent
    )
    rec = _get_rec_digest(agent)
    assert rec is not None
    # Both have compact summaries but they differ (different tasks/outcomes)
    assert parent["summary"] != rec["summary"], "Parent and child summaries must differ"
    assert ":" in parent["summary"], "Parent summary must be compact format"
    assert ":" in rec["summary"], "Child summary must be compact format"


def test_recovery_child_linkage_fields_intact():
    """Child has parent_run_id; parent has recovery_run_id pointing to child."""
    from unittest.mock import patch

    agent = _make_agent_with_clean_memory()
    artifact = _build_run_artifact_with_recovery()

    with patch.object(agent, "_seat_summarize_run", return_value="Recovery done."):
        agent._persist_run_digest(artifact, "Parent.")

    parent = agent.memory.facts.get("run:last", {})
    parent = (
        parent.get("value", parent)
        if isinstance(parent, dict) and "value" in parent
        else parent
    )
    rec = _get_rec_digest(agent)

    assert rec["parent_run_id"] == parent["run_id"], (
        "child.parent_run_id must match parent.run_id"
    )
    assert parent["recovery_run_id"] == rec["run_id"], (
        "parent.recovery_run_id must match child.run_id"
    )
    assert rec["run_kind"] == "recovery"
    assert parent["run_kind"] == "primary"


def test_non_recovery_run_unchanged_by_summarizer_path():
    """Plain (non-recovery) runs are unaffected — no child entry, parent intact."""
    from unittest.mock import patch

    agent = _make_agent_with_clean_memory()
    plain = {
        "task": "plain task",
        "outcome": "success",
        "steps": [{"step": 1, "status": "done", "action": "RUN", "target": "x"}],
        "outputs": ["done"],
        "prior_results": [],
        "failed": [],
        "recovery": None,
    }

    mock_calls = []
    with patch.object(
        agent,
        "_seat_summarize_run",
        side_effect=lambda a: mock_calls.append(a) or "seat summary",
    ):
        agent._persist_run_digest(plain, "Plain done.")

    # _seat_summarize_run called 0 times for the recovery child (no recovery_exec)
    # (it may be called 0 or 1 times but NOT for a child artifact)
    rec = _get_rec_digest(agent)
    assert rec is None, "No recovery child must be written for plain runs"
    parent = agent.memory.facts.get("run:last", {})
    parent = (
        parent.get("value", parent)
        if isinstance(parent, dict) and "value" in parent
        else parent
    )
    # Summary is compact format from artifact, not passed-in string
    summary = parent["summary"]
    assert "plain task" in summary
    assert "success" in summary


# ── Run-history response formatting tests ────────────────────────────────────


def _linked_dict(
    parent_task="main task",
    parent_outcome="failure",
    recovery_task="recovery task",
    recovery_outcome="success",
    recovery_summary="Retry succeeded.",
    recovery_n_steps=1,
    recovery_n_failed=0,
):
    return {
        "kind": "linked_run_history",
        "parent": {
            "task": parent_task,
            "outcome": parent_outcome,
            "summary": f"{parent_task} failed due to timeout",
        },
        "recovery": {
            "task": recovery_task,
            "outcome": recovery_outcome,
            "summary": recovery_summary,
            "n_steps": recovery_n_steps,
            "n_failed": recovery_n_failed,
        },
    }


def _retriever_output(results, method="recovery_linked+keyword"):
    return {
        "query": "test",
        "results": results,
        "count": len(results),
        "method": method,
    }


class TestFormatLinkedRunResult:
    """Tests for AgentLoop._format_linked_run_result."""

    def test_contains_parent_task(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result(_linked_dict())
        assert "main task" in text

    def test_contains_recovery_task(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result(_linked_dict())
        assert "recovery task" in text or "Recovery" in text

    def test_contains_parent_outcome(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result(
            _linked_dict(parent_outcome="failure")
        )
        assert "failure" in text

    def test_contains_recovery_outcome(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result(
            _linked_dict(recovery_outcome="success")
        )
        assert "success" in text

    def test_includes_recovery_summary(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result(
            _linked_dict(recovery_summary="Retry succeeded.")
        )
        assert "Retry succeeded." in text

    def test_recovery_succeeded_note_when_no_failures(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result(
            _linked_dict(recovery_outcome="success", recovery_n_failed=0)
        )
        assert "succeeded" in text.lower()

    def test_remaining_failures_when_n_failed_nonzero(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result(_linked_dict(recovery_n_failed=2))
        assert "2" in text and ("fail" in text.lower() or "Remaining" in text)

    def test_empty_linked_dict_does_not_crash(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result({})
        assert isinstance(text, str)

    def test_missing_parent_does_not_crash(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result({"recovery": {"task": "r"}})
        assert isinstance(text, str)

    def test_missing_recovery_does_not_crash(self):
        from agent.agent_loop import AgentLoop

        text = AgentLoop._format_linked_run_result({"parent": {"task": "p"}})
        assert isinstance(text, str)


class TestFormatRetrievalResults:
    """Tests for AgentLoop._format_retrieval_results."""

    def test_returns_none_for_non_dict(self):
        from agent.agent_loop import AgentLoop

        assert AgentLoop._format_retrieval_results("not a dict") is None

    def test_returns_none_when_no_results_key(self):
        from agent.agent_loop import AgentLoop

        assert AgentLoop._format_retrieval_results({"method": "keyword"}) is None

    def test_returns_none_when_no_method_key(self):
        from agent.agent_loop import AgentLoop

        assert AgentLoop._format_retrieval_results({"results": []}) is None

    def test_returns_none_when_results_empty(self):
        from agent.agent_loop import AgentLoop

        assert AgentLoop._format_retrieval_results(_retriever_output([])) is None

    def test_linked_result_formatted_coherently(self):
        from agent.agent_loop import AgentLoop

        results = [
            {
                "source": "run_history",
                "key": "run:p1",
                "value": {},
                "linked": _linked_dict(),
            }
        ]
        text = AgentLoop._format_retrieval_results(_retriever_output(results))
        assert text is not None
        assert "main task" in text
        assert "Recovery" in text or "recovery task" in text

    def test_plain_run_history_formatted(self):
        from agent.agent_loop import AgentLoop

        results = [
            {
                "source": "run_history",
                "key": "run:p1",
                "value": {
                    "task": "fetch data",
                    "outcome": "success",
                    "summary": "all done",
                },
            }
        ]
        text = AgentLoop._format_retrieval_results(
            _retriever_output(results, method="run_history+keyword")
        )
        assert text is not None
        assert "fetch data" in text

    def test_malformed_linked_result_degrades_safely(self):
        from agent.agent_loop import AgentLoop

        # linked dict has kind but missing parent/recovery
        results = [
            {
                "source": "run_history",
                "key": "run:p1",
                "value": {},
                "linked": {"kind": "linked_run_history"},
            }
        ]
        text = AgentLoop._format_retrieval_results(_retriever_output(results))
        # Should not crash, return something or None
        assert text is None or isinstance(text, str)

    def test_multiple_linked_results(self):
        from agent.agent_loop import AgentLoop

        results = [
            {
                "source": "run_history",
                "key": "run:p1",
                "value": {},
                "linked": _linked_dict(parent_task="task A"),
            },
            {
                "source": "run_history",
                "key": "run:p2",
                "value": {},
                "linked": _linked_dict(parent_task="task B"),
            },
        ]
        text = AgentLoop._format_retrieval_results(_retriever_output(results))
        assert text is not None
        assert "task A" in text
        assert "task B" in text

    def test_non_retriever_dict_returns_none(self):
        from agent.agent_loop import AgentLoop

        assert (
            AgentLoop._format_retrieval_results({"summary": "foo", "status": "ok"})
            is None
        )

    def test_unrelated_dict_returns_none(self):
        from agent.agent_loop import AgentLoop

        assert (
            AgentLoop._format_retrieval_results({"tools": [], "memory_stats": {}})
            is None
        )


class TestTryRunHistoryResponse:
    """Tests for AgentLoop._try_run_history_response."""

    def test_recovery_query_invokes_retriever(self):
        from unittest.mock import patch, MagicMock
        from agents.retriever_agent import RetrieverAgent
        from agents.base_agent import AgentResult

        agent = _make_agent_with_clean_memory()
        # Put a linked run_history fact in memory
        agent.memory.facts["run:last"] = {
            "value": {
                "run_id": "run:last",
                "run_kind": "primary",
                "task": "fetch data",
                "outcome": "failure",
                "recovery_run_id": "run:recovery1",
                "summary": "fetch failed",
                "ts": "2026-04-17T12:00:00",
            },
            "source": "run_artifact",
            "confidence": 0.9,
            "last_updated": "2026-04-17T12:00:00",
            "topic": "run_history",
        }
        agent.memory.facts["run:recovery1"] = {
            "value": {
                "run_id": "run:recovery1",
                "run_kind": "recovery",
                "task": "retry fetch",
                "outcome": "success",
                "parent_run_id": "run:last",
                "summary": "retry succeeded",
                "n_steps": 1,
                "n_failed": 0,
                "ts": "2026-04-17T12:01:00",
            },
            "source": "run_artifact",
            "confidence": 0.9,
            "last_updated": "2026-04-17T12:01:00",
            "topic": "run_history",
        }

        result = agent._try_run_history_response("what happened in the failed run")
        assert result is not None
        assert "fetch data" in result or "fetch" in result

    def test_non_run_history_query_returns_none(self):
        agent = _make_agent_with_clean_memory()
        result = agent._try_run_history_response("explain the architecture")
        assert result is None

    def test_empty_memory_returns_none(self):
        agent = _make_agent_with_clean_memory()
        result = agent._try_run_history_response("what just ran")
        assert result is None

    def test_unrelated_query_returns_none(self):
        agent = _make_agent_with_clean_memory()
        result = agent._try_run_history_response("how many seats does karma have")
        assert result is None


class TestResultToTextRetrieverOutput:
    """Tests for _result_to_text with retriever-shaped output."""

    def test_retriever_output_formatted_not_raw(self):
        """_result_to_text should not return raw dict repr for retriever output."""
        from agent.agent_loop import AgentLoop

        execution_result = {
            "success": True,
            "output": _retriever_output(
                [
                    {
                        "source": "run_history",
                        "key": "run:p1",
                        "value": {},
                        "linked": _linked_dict(),
                    }
                ]
            ),
        }
        text = AgentLoop._result_to_text(execution_result)
        # Should not contain raw JSON/dict syntax
        assert "{" not in text or "main task" in text
        assert "main task" in text

    def test_non_retriever_dict_still_handled(self):
        """Dicts without results+method still go through normal dict-to-text path."""
        from agent.agent_loop import AgentLoop

        execution_result = {
            "success": True,
            "output": {"some_key": "some_value", "other": 42},
        }
        text = AgentLoop._result_to_text(execution_result)
        assert "some" in text or "42" in text

    def test_retriever_output_parent_only_shows_run(self):
        """Plain run_history (no linked) is rendered as a run summary."""
        from agent.agent_loop import AgentLoop

        execution_result = {
            "success": True,
            "output": _retriever_output(
                [
                    {
                        "source": "run_history",
                        "key": "run:p1",
                        "value": {
                            "task": "process data",
                            "outcome": "success",
                            "summary": "done",
                        },
                    }
                ],
                method="run_history+keyword",
            ),
        }
        text = AgentLoop._result_to_text(execution_result)
        assert "process data" in text


# ── Touched-paths seam tests ──────────────────────────────────────────────────


def _run_artifact_with_paths(paths=None, outcome="success"):
    """Build a minimal _run_artifact whose steps carry file-path targets."""
    paths = paths or ["src/main.py", "config/settings.json"]
    steps = [
        {
            "step": i + 1,
            "action": "read_file",
            "target": p,
            "status": "done",
            "output": f"read {p}",
            "error": None,
        }
        for i, p in enumerate(paths)
    ]
    return {
        "task": "process files",
        "plan": [
            {"step": s["step"], "action": s["action"], "target": s["target"]}
            for s in steps
        ],
        "steps": steps,
        "outputs": [f"Step {s['step']}: read {s['target']}" for s in steps],
        "prior_results": [],
        "failed": [],
        "recovery": None,
        "outcome": outcome,
    }


def _run_artifact_no_paths(outcome="success"):
    """Build a _run_artifact whose steps have non-path targets."""
    return {
        "task": "run shell command",
        "plan": [{"step": 1, "action": "run_shell", "target": "ls -la"}],
        "steps": [
            {
                "step": 1,
                "action": "run_shell",
                "target": "ls -la",
                "status": "done",
                "output": "done",
                "error": None,
            }
        ],
        "outputs": ["Step 1: done"],
        "prior_results": [],
        "failed": [],
        "recovery": None,
        "outcome": outcome,
    }


class TestExtractTouchedPaths:
    """Tests for AgentLoop._extract_touched_paths."""

    def test_extracts_absolute_paths(self):
        from agent.agent_loop import AgentLoop

        artifact = _run_artifact_with_paths(["/home/user/file.py"])
        assert "/home/user/file.py" in AgentLoop._extract_touched_paths(artifact)

    def test_extracts_relative_with_extension(self):
        from agent.agent_loop import AgentLoop

        artifact = _run_artifact_with_paths(["src/main.py", "config/settings.json"])
        paths = AgentLoop._extract_touched_paths(artifact)
        assert "src/main.py" in paths
        assert "config/settings.json" in paths

    def test_ignores_non_path_targets(self):
        from agent.agent_loop import AgentLoop

        artifact = _run_artifact_no_paths()
        paths = AgentLoop._extract_touched_paths(artifact)
        assert "ls -la" not in paths

    def test_deduplicates(self):
        from agent.agent_loop import AgentLoop

        artifact = _run_artifact_with_paths(["src/main.py", "src/main.py"])
        paths = AgentLoop._extract_touched_paths(artifact)
        assert paths.count("src/main.py") == 1

    def test_empty_steps_returns_empty(self):
        from agent.agent_loop import AgentLoop

        artifact = {"task": "x", "steps": [], "plan": []}
        assert AgentLoop._extract_touched_paths(artifact) == []

    def test_caps_at_20(self):
        from agent.agent_loop import AgentLoop

        many_paths = [f"file{i}.py" for i in range(30)]
        artifact = _run_artifact_with_paths(many_paths)
        assert len(AgentLoop._extract_touched_paths(artifact)) <= 20

    def test_also_scans_plan(self):
        from agent.agent_loop import AgentLoop

        artifact = {
            "task": "x",
            "steps": [],
            "plan": [{"step": 1, "action": "read", "target": "agents/foo.py"}],
        }
        assert "agents/foo.py" in AgentLoop._extract_touched_paths(artifact)

    def test_dotslash_relative_path(self):
        from agent.agent_loop import AgentLoop

        artifact = _run_artifact_with_paths(["./scripts/run.sh"])
        assert "./scripts/run.sh" in AgentLoop._extract_touched_paths(artifact)

    def test_bare_word_without_extension_excluded(self):
        from agent.agent_loop import AgentLoop

        artifact = _run_artifact_with_paths(["fetchdata"])
        # bare word with no extension and no separator should not be included
        paths = AgentLoop._extract_touched_paths(artifact)
        assert "fetchdata" not in paths


class TestPersistRunDigestTouchedPaths:
    """Tests that _persist_run_digest stores touched_paths in digests."""

    def test_parent_digest_includes_touched_paths(self):
        agent = _make_agent_with_clean_memory()
        artifact = _run_artifact_with_paths(["src/main.py"])
        agent._persist_run_digest(artifact, "done")
        stored = agent.memory.facts.get("run:last", {})
        stored = (
            stored.get("value", stored)
            if isinstance(stored, dict) and "value" in stored
            else stored
        )
        assert "touched_paths" in stored
        assert "src/main.py" in stored["touched_paths"]

    def test_parent_digest_empty_paths_when_no_file_targets(self):
        agent = _make_agent_with_clean_memory()
        artifact = _run_artifact_no_paths()
        agent._persist_run_digest(artifact, "done")
        stored = agent.memory.facts.get("run:last", {})
        stored = (
            stored.get("value", stored)
            if isinstance(stored, dict) and "value" in stored
            else stored
        )
        assert stored.get("touched_paths") == []

    def test_recovery_child_digest_includes_its_own_paths(self):
        agent = _make_agent_with_clean_memory()
        recovery_exec = _run_artifact_with_paths(["recovery/retry.py"])
        recovery_exec["task"] = "retry fetch"
        recovery_exec["outcome"] = "success"

        artifact = _run_artifact_with_paths(["src/original.py"])
        artifact["outcome"] = "recovered"
        artifact["recovery"] = {
            "outcome": "success",
            "recovery_execution": recovery_exec,
        }

        agent._persist_run_digest(artifact, "parent summary")

        # Find the recovery child key
        rec_key = None
        for k in agent.memory.facts:
            if k.startswith("run:recovery:"):
                rec_key = k
                break
        assert rec_key is not None, "Recovery child must be persisted"

        rec = agent.memory.facts[rec_key]
        rec = rec.get("value", rec) if isinstance(rec, dict) and "value" in rec else rec
        assert "touched_paths" in rec
        assert "recovery/retry.py" in rec["touched_paths"]

    def test_parent_and_recovery_paths_are_distinct(self):
        agent = _make_agent_with_clean_memory()
        recovery_exec = _run_artifact_with_paths(["recovery/fix.py"])
        recovery_exec["task"] = "fix run"
        recovery_exec["outcome"] = "success"

        artifact = _run_artifact_with_paths(["src/broken.py"])
        artifact["outcome"] = "recovered"
        artifact["recovery"] = {
            "outcome": "success",
            "recovery_execution": recovery_exec,
        }
        agent._persist_run_digest(artifact, "parent")

        parent = agent.memory.facts.get("run:last", {})
        parent = (
            parent.get("value", parent)
            if isinstance(parent, dict) and "value" in parent
            else parent
        )
        parent_paths = parent.get("touched_paths", [])

        rec_key = next(
            (k for k in agent.memory.facts if k.startswith("run:recovery:")), None
        )
        assert rec_key is not None
        rec = agent.memory.facts[rec_key]
        rec = rec.get("value", rec) if isinstance(rec, dict) and "value" in rec else rec
        rec_paths = rec.get("touched_paths", [])

        assert "src/broken.py" in parent_paths
        assert "recovery/fix.py" in rec_paths
        assert "src/broken.py" not in rec_paths
        assert "recovery/fix.py" not in parent_paths


class TestIsPathQuery:
    """Tests for RetrieverAgent._is_path_query."""

    def setup_method(self):
        from agents.retriever_agent import RetrieverAgent

        self.fn = RetrieverAgent._is_path_query

    def test_files_touched(self):
        assert self.fn("what files were touched") is True

    def test_which_files(self):
        assert self.fn("which files were modified") is True

    def test_what_file(self):
        assert self.fn("what file did it change") is True

    def test_files_in_failed_run(self):
        assert self.fn("files in the failed run") is True

    def test_what_was_modified(self):
        assert self.fn("what was modified in the run") is True

    def test_paths_involved(self):
        assert self.fn("paths involved in the recovery") is True

    def test_non_path_query_returns_false(self):
        assert self.fn("what is karma") is False

    def test_architecture_query_returns_false(self):
        assert self.fn("explain the architecture") is False

    def test_empty_returns_false(self):
        assert self.fn("") is False


class TestFormatLinkedRunResultWithPaths:
    """Tests that _format_linked_run_result renders touched_paths."""

    def test_parent_paths_in_output(self):
        from agent.agent_loop import AgentLoop

        linked = {
            "kind": "linked_run_history",
            "parent": {
                "task": "fetch data",
                "outcome": "failure",
                "summary": "failed",
                "touched_paths": ["src/fetch.py", "data/input.csv"],
            },
            "recovery": {
                "task": "retry",
                "outcome": "success",
                "summary": "ok",
                "n_steps": 1,
                "n_failed": 0,
                "touched_paths": [],
            },
        }
        text = AgentLoop._format_linked_run_result(linked)
        assert "src/fetch.py" in text
        assert "data/input.csv" in text

    def test_recovery_paths_in_output(self):
        from agent.agent_loop import AgentLoop

        linked = {
            "kind": "linked_run_history",
            "parent": {
                "task": "fetch",
                "outcome": "failure",
                "summary": "failed",
                "touched_paths": [],
            },
            "recovery": {
                "task": "retry",
                "outcome": "success",
                "summary": "ok",
                "n_steps": 1,
                "n_failed": 0,
                "touched_paths": ["recovery/patch.py"],
            },
        }
        text = AgentLoop._format_linked_run_result(linked)
        assert "recovery/patch.py" in text

    def test_parent_and_recovery_paths_distinct_in_output(self):
        from agent.agent_loop import AgentLoop

        linked = {
            "kind": "linked_run_history",
            "parent": {
                "task": "original",
                "outcome": "failure",
                "summary": "broke",
                "touched_paths": ["src/broken.py"],
            },
            "recovery": {
                "task": "fix",
                "outcome": "success",
                "summary": "fixed",
                "n_steps": 1,
                "n_failed": 0,
                "touched_paths": ["src/fixed.py"],
            },
        }
        text = AgentLoop._format_linked_run_result(linked)
        # Both paths visible; their labels distinguish them
        assert "src/broken.py" in text
        assert "src/fixed.py" in text
        # Verify they appear in clearly separated sections
        broken_pos = text.index("src/broken.py")
        fixed_pos = text.index("src/fixed.py")
        assert broken_pos != fixed_pos

    def test_no_paths_does_not_add_empty_paths_line(self):
        from agent.agent_loop import AgentLoop

        linked = {
            "kind": "linked_run_history",
            "parent": {
                "task": "t",
                "outcome": "failure",
                "summary": "",
                "touched_paths": [],
            },
            "recovery": {
                "task": "r",
                "outcome": "success",
                "summary": "",
                "n_steps": 0,
                "n_failed": 0,
                "touched_paths": [],
            },
        }
        text = AgentLoop._format_linked_run_result(linked)
        assert "Files/paths" not in text
        assert "Recovery files" not in text


class TestFormatRetrievalResultsWithPaths:
    """Tests that _format_retrieval_results renders touched_paths in plain run results."""

    def test_plain_run_history_with_paths_shows_paths(self):
        from agent.agent_loop import AgentLoop

        results = [
            {
                "source": "run_history",
                "key": "run:p1",
                "value": {
                    "task": "run tests",
                    "outcome": "success",
                    "summary": "all tests passed",
                    "touched_paths": ["tests/test_foo.py", "src/foo.py"],
                },
            }
        ]
        output = {
            "query": "what just ran",
            "results": results,
            "count": 1,
            "method": "run_history+keyword",
        }
        text = AgentLoop._format_retrieval_results(output)
        assert text is not None
        assert "tests/test_foo.py" in text
        assert "src/foo.py" in text

    def test_no_paths_in_value_does_not_crash(self):
        from agent.agent_loop import AgentLoop

        results = [
            {
                "source": "run_history",
                "key": "run:p1",
                "value": {"task": "run tests", "outcome": "success", "summary": "ok"},
            }
        ]
        output = {
            "query": "what just ran",
            "results": results,
            "count": 1,
            "method": "run_history+keyword",
        }
        text = AgentLoop._format_retrieval_results(output)
        assert text is not None
        assert "run tests" in text


class TestResolveTouchedPaths:
    """Tests for AgentLoop._resolve_touched_paths."""

    def test_existing_file_classified_as_file(self):
        from agent.agent_loop import AgentLoop

        paths = AgentLoop._resolve_touched_paths(
            ["/home/mikoleye/karma/agent/agent_loop.py"]
        )
        assert len(paths) == 1
        assert paths[0]["status"] == "file"

    def test_existing_directory_classified_as_directory(self):
        from agent.agent_loop import AgentLoop

        paths = AgentLoop._resolve_touched_paths(["/home/mikoleye/karma/agent"])
        assert len(paths) == 1
        assert paths[0]["status"] == "directory"

    def test_missing_path_classified_as_missing(self):
        from agent.agent_loop import AgentLoop

        paths = AgentLoop._resolve_touched_paths(
            ["/home/mikoleye/karma/nonexistent_xyz123.py"]
        )
        assert len(paths) == 1
        assert paths[0]["status"] == "missing"

    def test_out_of_repo_classified_as_unresolvable(self):
        from agent.agent_loop import AgentLoop

        paths = AgentLoop._resolve_touched_paths(
            ["/etc/passwd"], base_dir="/home/mikoleye/karma"
        )
        assert len(paths) == 1
        assert paths[0]["status"] == "unresolvable"

    def test_empty_list_returns_empty(self):
        from agent.agent_loop import AgentLoop

        paths = AgentLoop._resolve_touched_paths([])
        assert paths == []

    def test_none_item_skipped(self):
        from agent.agent_loop import AgentLoop

        paths = AgentLoop._resolve_touched_paths(
            ["/home/mikoleye/karma/agent/agent_loop.py", None, ""]
        )
        assert len(paths) == 1


class TestFormattingWithResolvedPaths:
    """Tests that formatting uses resolved path state."""

    def test_linked_result_shows_existing_vs_missing(self):
        from agent.agent_loop import AgentLoop

        linked = {
            "kind": "linked_run_history",
            "parent": {
                "task": "fetch",
                "outcome": "failure",
                "summary": "failed",
                "touched_paths": ["/home/mikoleye/karma/agent/agent_loop.py"],  # exists
            },
            "recovery": {
                "task": "retry",
                "outcome": "success",
                "summary": "ok",
                "n_steps": 1,
                "n_failed": 0,
                "touched_paths": [
                    "/home/mikoleye/karma/nonexistent_recovery_xyz.py"
                ],  # missing (inside karma)
            },
        }
        text = AgentLoop._format_linked_run_result(linked)
        assert "agent_loop.py" in text
        assert "nonexistent_recovery_xyz.py" in text

    def test_plain_result_shows_existing_vs_missing(self):
        from agent.agent_loop import AgentLoop

        results = [
            {
                "source": "run_history",
                "key": "run:p1",
                "value": {
                    "task": "fix",
                    "outcome": "success",
                    "summary": "done",
                    "touched_paths": [
                        "/home/mikoleye/karma/agent/agent_loop.py",  # exists
                        "/home/mikoleye/karma/nonexistent_file_xyz.py",  # missing
                    ],
                },
            }
        ]
        output = {
            "query": "what ran",
            "results": results,
            "count": 1,
            "method": "run_history+keyword",
        }
        text = AgentLoop._format_retrieval_results(output)
        assert text is not None
        assert "agent_loop.py" in text
        assert "nonexistent_file_xyz.py" in text

    def test_no_paths_unchanged_behavior(self):
        from agent.agent_loop import AgentLoop

        linked = {
            "kind": "linked_run_history",
            "parent": {
                "task": "t",
                "outcome": "failure",
                "summary": "",
                "touched_paths": [],
            },
            "recovery": {
                "task": "r",
                "outcome": "success",
                "summary": "",
                "n_steps": 0,
                "n_failed": 0,
                "touched_paths": [],
            },
        }
        text = AgentLoop._format_linked_run_result(linked)
        assert "exist" not in text.lower()
        assert "missing" not in text.lower()


# ── Single-tool digest tests ──────────────────────────────────────────────────


def _make_agent_clean():
    from agent.agent_loop import AgentLoop, load_config
    cfg = load_config("config.json")
    a = AgentLoop(cfg)
    a.memory.facts.clear()
    return a


def test_should_digest_single_tool_true_for_real_tools():
    from agent.agent_loop import AgentLoop
    for name in ["run_shell", "list_files", "code_read", "code_test", "ingest", "crystallize"]:
        action = {"name": name, "tool": "x", "parameters": {}}
        assert AgentLoop._should_digest_single_tool(action), f"{name} should be digested"


def test_should_digest_single_tool_false_for_skip_list():
    from agent.agent_loop import AgentLoop
    for name in ["help", "status_query", "list_capabilities", "repair_report",
                 "teach_response", "forget_response", "list_custom_tools"]:
        action = {"name": name, "tool": None, "parameters": {}}
        assert not AgentLoop._should_digest_single_tool(action), f"{name} should be skipped"


def test_should_digest_single_tool_false_for_seat_generated():
    from agent.agent_loop import AgentLoop
    action = {"name": "TASK", "_seat_generated": True, "tool": None, "parameters": {}}
    assert not AgentLoop._should_digest_single_tool(action)


def test_build_single_tool_artifact_success():
    from agent.agent_loop import AgentLoop
    intent = {"intent": "list_files", "entities": {"path": "/tmp"}, "confidence": 0.9}
    action = {"name": "list_files", "tool": "filesystem", "parameters": {"path": "/tmp"}}
    result = {"success": True, "output": "a.txt\nb.py", "error": None}

    art = AgentLoop._build_single_tool_artifact(intent, action, result, "list files in /tmp")

    assert art["run_kind"] == "tool"
    assert art["outcome"] == "success"
    assert art["tool"] == "filesystem"
    assert art["target"] == "/tmp"
    assert art["steps"] == []
    assert art["recovery"] is None
    assert "a.txt" in art["key_output"]


def test_build_single_tool_artifact_failure():
    from agent.agent_loop import AgentLoop
    intent = {"intent": "run_shell", "entities": {}, "confidence": 0.8}
    action = {"name": "run_shell", "tool": "shell", "parameters": {"command": "ls /nodir"}}
    result = {"success": False, "output": None, "error": "No such file or directory"}

    art = AgentLoop._build_single_tool_artifact(intent, action, result, "run ls /nodir")

    assert art["outcome"] == "failed"
    assert art["key_error"] == "No such file or directory"
    assert len(art["failed"]) == 1
    assert art["failed"][0]["error"] == "No such file or directory"


def test_build_single_tool_artifact_uses_user_input_as_task():
    from agent.agent_loop import AgentLoop
    intent = {"intent": "run_shell", "entities": {}, "confidence": 0.8}
    action = {"name": "run_shell", "tool": "shell", "parameters": {}}
    result = {"success": True, "output": "ok", "error": None}

    art = AgentLoop._build_single_tool_artifact(intent, action, result, "run ls in /tmp")
    assert art["task"] == "run ls in /tmp"


def test_build_single_tool_artifact_falls_back_to_intent():
    from agent.agent_loop import AgentLoop
    intent = {"intent": "run_shell", "entities": {}, "confidence": 0.8}
    action = {"name": "run_shell", "tool": "shell", "parameters": {}}
    result = {"success": True, "output": "ok", "error": None}

    art = AgentLoop._build_single_tool_artifact(intent, action, result, "")
    assert "run_shell" in art["task"]


def test_compact_summary_tool_run_success():
    from agent.agent_loop import AgentLoop
    art = {
        "task": "list files", "outcome": "success", "run_kind": "tool",
        "tool": "filesystem", "target": "/tmp",
        "steps": [], "failed": [], "recovery": None,
        "key_output": "a.txt b.py", "key_error": "",
    }
    summary = AgentLoop._build_compact_digest_summary(art)
    assert "list files" in summary
    assert "success" in summary
    assert "filesystem" in summary or "/tmp" in summary
    assert "\n" not in summary


def test_compact_summary_tool_run_failure():
    from agent.agent_loop import AgentLoop
    art = {
        "task": "run shell", "outcome": "failed", "run_kind": "tool",
        "tool": "shell", "target": "rm -rf /",
        "steps": [], "recovery": None,
        "failed": [{"step": 1, "action": "shell", "target": "rm -rf /", "error": "permission denied"}],
        "key_output": "", "key_error": "permission denied",
    }
    summary = AgentLoop._build_compact_digest_summary(art)
    assert "failed" in summary
    assert "permission denied" in summary
    assert "\n" not in summary


def test_persist_run_digest_stores_tool_run():
    agent = _make_agent_clean()
    art = {
        "task": "run ls", "outcome": "success", "run_kind": "tool",
        "tool": "shell", "target": "/tmp",
        "steps": [], "outputs": ["file1.txt"], "failed": [], "recovery": None,
        "key_output": "file1.txt", "key_error": "",
    }
    agent._persist_run_digest(art, "")

    assert "run:last" in agent.memory.facts
    val = agent.memory.facts["run:last"].get("value", agent.memory.facts["run:last"])
    assert val["run_kind"] == "tool"
    assert val["tool"] == "shell"
    assert val["target"] == "/tmp"
    assert "run ls" in val["summary"]
    assert "success" in val["summary"]

    run_keys = [k for k in agent.memory.facts if k.startswith("run:") and k != "run:last"]
    assert len(run_keys) >= 1


def test_persist_run_digest_tool_run_no_recovery_child():
    agent = _make_agent_clean()
    art = {
        "task": "list files", "outcome": "success", "run_kind": "tool",
        "tool": "filesystem", "target": "/tmp",
        "steps": [], "outputs": [], "failed": [], "recovery": None,
        "key_output": "", "key_error": "",
    }
    agent._persist_run_digest(art, "")

    rec_keys = [k for k in agent.memory.facts if k.startswith("run:recovery:")]
    assert rec_keys == [], "Single-tool runs must not generate recovery child entries"


def test_planned_run_not_affected_by_single_tool_changes():
    """Multi-step planned run digest still uses run_kind=primary."""
    agent = _make_agent_clean()
    art = {
        "task": "deploy",
        "outcome": "success",
        "steps": [{"step": 1, "action": "build", "target": "src/", "status": "done"}],
        "outputs": ["Built ok"],
        "failed": [],
        "recovery": None,
        "path_findings": [],
    }
    agent._persist_run_digest(art, "")
    val = agent.memory.facts["run:last"].get("value", agent.memory.facts["run:last"])
    assert val["run_kind"] == "primary"
    assert "tool" not in val


def test_session_summary_reflects_tool_run_via_run_last():
    """Session summary fallback shows tool run from run:last when no session logs."""
    from agent.agent_loop import AgentLoop, load_config
    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    agent.current_state["execution_log"] = []
    agent.current_state["session_start_ts"] = "2099-01-01T00:00:00"

    agent.memory.save_fact(
        "run:last",
        {"task": "run_shell", "outcome": "success", "run_kind": "tool",
         "tool": "shell", "summary": "run_shell: success | tool=shell ls"},
        source="run_artifact", confidence=0.9, topic="run_history",
    )

    result = agent._try_session_summary_response("what did you do last session")
    assert result is not None
    assert "run_shell" in result or "shell" in result


# ── Retrieval dedup + formatting tests ───────────────────────────────────────


def _populate_runs(agent, tasks):
    """Write N run digests to memory, returning the hash keys written."""
    keys = []
    import hashlib, datetime
    for task, outcome, kind in tasks:
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        run_key = "run:" + hashlib.md5(f"{task}{ts}".encode()).hexdigest()[:8]
        art = {
            "task": task, "outcome": outcome, "run_kind": kind,
            "tool": "shell" if kind == "tool" else "", "target": "/tmp",
            "steps": [] if kind == "tool" else [{"step":1,"action":"A","target":"x","status":"done"}],
            "outputs": ["ok"], "failed": [], "recovery": None,
            "key_output": "file.txt", "key_error": "", "path_findings": [],
        }
        agent._persist_run_digest(art, "")
        keys.append(run_key)
    return keys


def test_run_history_lookup_no_duplicate_run_last():
    """_run_history_lookup deduplicates run:last vs run:<hash> by run_id."""
    from agents.retriever_agent import RetrieverAgent
    agent = _make_agent_clean()
    _populate_runs(agent, [("task_a", "success", "primary")])

    results = RetrieverAgent._run_history_lookup(agent.memory, limit=10)
    run_ids = [r["value"].get("run_id") for r in results]

    # No run_id should appear twice
    assert len(run_ids) == len(set(run_ids)), f"Duplicate run_ids in results: {run_ids}"
    # run:last key should NOT appear — deduplicated by run_id
    keys = [r["key"] for r in results]
    assert "run:last" not in keys, "run:last should be deduplicated"


def test_run_history_lookup_returns_multiple_runs():
    """_run_history_lookup returns all unique runs up to limit."""
    from agents.retriever_agent import RetrieverAgent
    agent = _make_agent_clean()
    _populate_runs(agent, [
        ("task_a", "success", "primary"),
        ("task_b", "failed", "primary"),
        ("task_c", "success", "tool"),
    ])

    results = RetrieverAgent._run_history_lookup(agent.memory, limit=10)
    tasks = [r["value"].get("task") for r in results]

    assert "task_a" in tasks
    assert "task_b" in tasks
    assert "task_c" in tasks
    # No duplicates
    run_ids = [r["value"].get("run_id") for r in results]
    assert len(run_ids) == len(set(run_ids))


def test_retrieve_linked_run_history_no_duplicate_run_last():
    """_retrieve_linked_run_history deduplicates run:last vs run:<hash>."""
    from agents.retriever_agent import RetrieverAgent
    agent = _make_agent_clean()
    _populate_runs(agent, [("deploy", "success", "primary")])

    results = RetrieverAgent._retrieve_linked_run_history(agent.memory, limit=10)
    run_ids = [r["value"].get("run_id") for r in results]
    assert len(run_ids) == len(set(run_ids)), f"Duplicate run_ids: {run_ids}"
    keys = [r["key"] for r in results]
    assert "run:last" not in keys


def test_extract_tool_output_string():
    from agent.agent_loop import AgentLoop
    assert AgentLoop._extract_tool_output("hello") == "hello"


def test_extract_tool_output_none():
    from agent.agent_loop import AgentLoop
    assert AgentLoop._extract_tool_output(None) == ""


def test_extract_tool_output_dict_output_key():
    from agent.agent_loop import AgentLoop
    assert AgentLoop._extract_tool_output({"output": "result", "success": True}) == "result"


def test_extract_tool_output_dict_stdout():
    from agent.agent_loop import AgentLoop
    assert AgentLoop._extract_tool_output({"stdout": "line1\nline2"}) == "line1\nline2"


def test_extract_tool_output_dict_files_list():
    from agent.agent_loop import AgentLoop
    out = AgentLoop._extract_tool_output({"files": ["a.txt", "b.py"], "success": True})
    assert "a.txt" in out
    assert "b.py" in out


def test_extract_tool_output_list():
    from agent.agent_loop import AgentLoop
    out = AgentLoop._extract_tool_output(["x", "y", "z"])
    assert "x" in out and "y" in out


def test_format_retrieval_results_tool_run_compact():
    """Tool runs render as [tool] single-line, not Run: header."""
    from agent.agent_loop import AgentLoop, load_config
    from agents.retriever_agent import RetrieverAgent
    from agents.base_agent import AgentContext

    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    agent.memory.facts.clear()
    _populate_runs(agent, [("run ls", "success", "tool")])

    ctx = AgentContext(task="what ran", input_data={"query": "what ran recently"}, memory=agent.memory)
    result = RetrieverAgent().run(ctx)
    fmt = agent._format_retrieval_results(result.output)

    assert "[tool]" in fmt
    assert "Run: run ls" not in fmt  # no redundant header


def test_format_retrieval_results_primary_strips_prefix():
    """Planned run summary sub-line strips 'task: outcome | ' prefix."""
    from agent.agent_loop import AgentLoop, load_config
    from agents.retriever_agent import RetrieverAgent
    from agents.base_agent import AgentContext

    cfg = load_config("config.json")
    agent = AgentLoop(cfg)
    agent.memory.facts.clear()
    _populate_runs(agent, [("deploy", "success", "primary")])

    ctx = AgentContext(task="what ran", input_data={"query": "what ran recently"}, memory=agent.memory)
    result = RetrieverAgent().run(ctx)
    fmt = agent._format_retrieval_results(result.output)

    assert "Run: deploy — success" in fmt
    # Sub-line should not start with "deploy: success |"
    lines = fmt.splitlines()
    sub_lines = [l for l in lines if l.startswith("  ")]
    for sl in sub_lines:
        assert not sl.strip().startswith("deploy: success |"), f"Redundant prefix found: {sl!r}"
