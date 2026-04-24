"""Tests for RetrieverAgent recent-task query routing and run_history preference."""

from unittest.mock import MagicMock
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_memory(facts=None):
    mem = MagicMock()
    mem.facts = facts or {}
    return mem


def _run_history_fact(task="fetch data", outcome="success", ts="2026-04-17T12:00:00"):
    """Return a fact dict as stored by _persist_run_digest."""
    return {
        "value": {
            "task": task,
            "outcome": outcome,
            "summary": f"Run: {task}",
            "ts": ts,
        },
        "source": "run_artifact",
        "confidence": 0.9,
        "last_updated": ts,
        "topic": "run_history",
    }


def _generic_fact(val="some knowledge"):
    return {
        "value": val,
        "source": "agent",
        "confidence": 0.8,
        "last_updated": "2026-04-17T10:00:00",
        "topic": "general",
    }


def _make_retriever():
    from agents.retriever_agent import RetrieverAgent

    return RetrieverAgent()


# ── _is_recent_task_query classifier ─────────────────────────────────────────


class TestIsRecentTaskQuery:
    def setup_method(self):
        from agents.retriever_agent import RetrieverAgent

        self.fn = RetrieverAgent._is_recent_task_query

    # Should match
    def test_what_happened(self):
        assert self.fn("what happened last run") is True

    def test_what_just_ran(self):
        assert self.fn("what just ran") is True

    def test_last_task(self):
        assert self.fn("show me the last task") is True

    def test_last_run(self):
        assert self.fn("what was the last run") is True

    def test_failed_recently(self):
        assert self.fn("what failed recently") is True

    def test_recent_failure(self):
        assert self.fn("show me the recent failure") is True

    def test_most_recent(self):
        assert self.fn("what was the most recent execution") is True

    def test_previous_run(self):
        assert self.fn("tell me about the previous run") is True

    def test_just_did(self):
        assert self.fn("what did karma just do") is True

    def test_what_did_you_do(self):
        assert self.fn("what did you do") is True

    def test_recovery_attempt(self):
        assert self.fn("what was the recovery attempt") is True

    def test_run_history(self):
        assert self.fn("show run history") is True

    def test_just_completed(self):
        assert self.fn("what just completed") is True

    def test_earlier_today(self):
        assert self.fn("what happened earlier today") is True

    def test_show_last_run(self):
        assert self.fn("show last run") is True

    # Should NOT match
    def test_what_is_karma(self):
        assert self.fn("what is karma") is False

    def test_explain_architecture(self):
        assert self.fn("explain the architecture") is False

    def test_how_does_retriever_work(self):
        assert self.fn("how does the retriever work") is False

    def test_summarize_project(self):
        assert self.fn("summarize the project") is False

    def test_describe_design(self):
        assert self.fn("describe the design of the planner") is False

    def test_recent_commit(self):
        assert self.fn("show me the recent commit") is False

    def test_recent_version(self):
        assert self.fn("what was the recent version") is False

    def test_git_history(self):
        assert self.fn("show git history") is False

    def test_unrelated_question(self):
        assert self.fn("how many seats does karma have") is False

    def test_empty_string(self):
        assert self.fn("") is False


# ── _run_history_lookup ───────────────────────────────────────────────────────


class TestRunHistoryLookup:
    def setup_method(self):
        from agents.retriever_agent import RetrieverAgent

        self.fn = RetrieverAgent._run_history_lookup

    def test_returns_run_history_facts(self):
        mem = _make_memory(
            {
                "run:last": _run_history_fact("task A", ts="2026-04-17T12:00:00"),
                "run:abc12345": _run_history_fact("task B", ts="2026-04-17T11:00:00"),
                "other:key": _generic_fact("irrelevant"),
            }
        )
        results = self.fn(mem, 8)
        keys = [r["key"] for r in results]
        assert "run:last" in keys
        assert "run:abc12345" in keys
        assert "other:key" not in keys

    def test_sorted_newest_first(self):
        mem = _make_memory(
            {
                "run:old": _run_history_fact("old task", ts="2026-04-16T10:00:00"),
                "run:new": _run_history_fact("new task", ts="2026-04-17T12:00:00"),
            }
        )
        results = self.fn(mem, 8)
        assert results[0]["key"] == "run:new"
        assert results[1]["key"] == "run:old"

    def test_empty_when_no_run_history(self):
        mem = _make_memory({"some:key": _generic_fact()})
        assert self.fn(mem, 8) == []

    def test_empty_when_no_memory(self):
        assert self.fn(None, 8) == []

    def test_respects_limit(self):
        mem = _make_memory(
            {
                f"run:{i}": {
                    "value": {"task": f"t{i}"},
                    "source": "run_artifact",
                    "confidence": 0.9,
                    "last_updated": f"2026-04-17T{i:02d}:00:00",
                    "topic": "run_history",
                }
                for i in range(10)
            }
        )
        results = self.fn(mem, 3)
        assert len(results) == 3

    def test_source_is_run_history(self):
        mem = _make_memory({"run:last": _run_history_fact()})
        results = self.fn(mem, 8)
        assert results[0]["source"] == "run_history"

    def test_value_unwrapped(self):
        mem = _make_memory({"run:last": _run_history_fact("my task")})
        results = self.fn(mem, 8)
        assert results[0]["value"]["task"] == "my task"

    def test_ignores_non_dict_facts(self):
        mem = _make_memory(
            {
                "run:last": _run_history_fact(),
                "bare:key": "raw string value",
            }
        )
        results = self.fn(mem, 8)
        assert len(results) == 1


# ── _merge_with_prefix ───────────────────────────────────────────────────────


class TestMergeWithPrefix:
    def setup_method(self):
        from agents.retriever_agent import RetrieverAgent

        self.fn = RetrieverAgent._merge_with_prefix

    def test_prefix_comes_first(self):
        prefix = [{"key": "run:last", "source": "run_history", "value": {}}]
        general = [{"key": "some:fact", "source": "facts", "value": {}}]
        result = self.fn(prefix, general, 8)
        assert result[0]["key"] == "run:last"
        assert result[1]["key"] == "some:fact"

    def test_deduplicates_by_key(self):
        prefix = [{"key": "run:last", "source": "run_history", "value": {}}]
        general = [
            {"key": "run:last", "source": "facts", "value": {}},  # duplicate
            {"key": "other:key", "source": "facts", "value": {}},
        ]
        result = self.fn(prefix, general, 8)
        run_last_entries = [r for r in result if r["key"] == "run:last"]
        assert len(run_last_entries) == 1  # deduplicated
        assert run_last_entries[0]["source"] == "run_history"  # prefix wins

    def test_respects_limit(self):
        prefix = [
            {"key": f"run:{i}", "source": "run_history", "value": {}} for i in range(3)
        ]
        general = [
            {"key": f"gen:{i}", "source": "facts", "value": {}} for i in range(5)
        ]
        result = self.fn(prefix, general, 4)
        assert len(result) == 4

    def test_empty_prefix_returns_general(self):
        general = [{"key": "a", "source": "facts", "value": {}}]
        result = self.fn([], general, 8)
        assert result == general

    def test_empty_general_returns_prefix(self):
        prefix = [{"key": "run:last", "source": "run_history", "value": {}}]
        result = self.fn(prefix, [], 8)
        assert result == prefix


# ── RetrieverAgent.run() integration ─────────────────────────────────────────


class TestRetrieverRunIntegration:
    def setup_method(self):
        self.agent = _make_retriever()
        # Disable embed adapter so tests use keyword path
        self.agent._get_embed_adapter = lambda: None

    def _make_context(self, query, memory=None):
        from agents.base_agent import AgentContext

        return AgentContext(
            task=query,
            input_data={"query": query},
            memory=memory,
        )

    def test_recent_task_query_returns_run_history_first(self):
        """Recent-task query surfaces run_history facts at the top of results."""
        mem = _make_memory(
            {
                "run:last": _run_history_fact("shell task", outcome="success"),
                "general:knowledge": _generic_fact("irrelevant general fact"),
            }
        )
        ctx = self._make_context("what happened last run", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        results = result.output.get("results", [])
        assert len(results) > 0
        assert results[0]["source"] == "run_history", (
            f"run_history must come first for recent-task query, got: {results[0]}"
        )
        assert results[0]["value"]["task"] == "shell task"

    def test_general_query_does_not_prefer_run_history(self):
        """General query does not artificially prioritize run_history."""
        mem = _make_memory(
            {
                "run:last": _run_history_fact("some task"),
                "karma:architecture": _generic_fact("karma is a 6-seat agent"),
            }
        )
        ctx = self._make_context("what is karma", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        results = result.output.get("results", [])
        # run_history should NOT be first (query doesn't trigger recent-task classifier)
        # (keyword search may or may not find run_history depending on content,
        # but it won't be forcibly prepended)
        sources = [r.get("source") for r in results]
        # If run_history appears, it must not be because of the recent-task pre-pass
        method = result.output.get("method", "")
        assert "run_history" not in method, (
            f"General query must not trigger run_history pre-pass, method={method}"
        )

    def test_run_history_absent_falls_back_to_keyword(self):
        """When no run_history facts exist, recent-task query still returns keyword results."""
        mem = _make_memory(
            {
                "some:fact": _generic_fact("helpful context"),
            }
        )
        ctx = self._make_context("what failed recently", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        # No crash, method should not include run_history+ prefix
        method = result.output.get("method", "")
        assert "run_history" not in method

    def test_run_history_empty_memory_does_not_crash(self):
        """Recent-task query with empty memory returns success with empty results."""
        mem = _make_memory({})
        ctx = self._make_context("what just ran", memory=mem)
        result = self.agent.run(ctx)
        assert result.success is True

    def test_method_includes_run_history_prefix_label(self):
        """When run_history is injected, method string reflects it."""
        mem = _make_memory(
            {
                "run:last": _run_history_fact(),
            }
        )
        ctx = self._make_context("what was the last run", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        method = result.output.get("method", "")
        assert method.startswith("run_history+"), (
            f"Method should start with 'run_history+' when run_history injected: {method}"
        )

    def test_multiple_run_history_facts_sorted_newest_first(self):
        """Multiple run_history facts appear newest-first in results."""
        mem = _make_memory(
            {
                "run:old": _run_history_fact("old task", ts="2026-04-16T09:00:00"),
                "run:new": _run_history_fact("new task", ts="2026-04-17T15:00:00"),
            }
        )
        ctx = self._make_context("show me the last run", memory=mem)
        result = self.agent.run(ctx)

        results = result.output.get("results", [])
        run_h = [r for r in results if r.get("source") == "run_history"]
        assert run_h[0]["value"]["task"] == "new task"
        assert run_h[1]["value"]["task"] == "old task"

    def test_run_history_not_duplicated_in_results(self):
        """run_history facts present in both prefix and keyword results are not duplicated."""
        mem = _make_memory(
            {
                "run:last": _run_history_fact("task X"),
            }
        )
        ctx = self._make_context("what just ran", memory=mem)
        result = self.agent.run(ctx)

        results = result.output.get("results", [])
        run_last_count = sum(1 for r in results if r.get("key") == "run:last")
        assert run_last_count == 1, (
            f"run:last must not be duplicated, got {run_last_count}"
        )

    def test_wording_variants_all_trigger_preference(self):
        """Several different phrasings all trigger the run_history pre-pass."""
        mem = _make_memory({"run:last": _run_history_fact()})
        variants = [
            "what happened last run",
            "what just ran",
            "show me the last task",
            "what was the most recent execution",
            "what failed recently",
            "tell me about the previous run",
            "what did karma just do",
            "show run history",
        ]
        for query in variants:
            ctx = self._make_context(query, memory=mem)
            result = self.agent.run(ctx)
            method = result.output.get("method", "")
            assert method.startswith("run_history+"), (
                f"Query '{query}' should trigger run_history pre-pass, got method='{method}'"
            )

    def test_non_recent_queries_do_not_trigger_preference(self):
        """General/architectural queries never trigger run_history pre-pass."""
        mem = _make_memory({"run:last": _run_history_fact()})
        non_recent = [
            "explain the architecture",
            "what is karma",
            "how does the retriever work",
            "summarize the project",
            "show me the recent commit",
            "describe the design",
        ]
        for query in non_recent:
            ctx = self._make_context(query, memory=mem)
            result = self.agent.run(ctx)
            method = result.output.get("method", "")
            assert not method.startswith("run_history+"), (
                f"Query '{query}' must NOT trigger run_history pre-pass, got method='{method}'"
            )

    def test_limit_respected_with_run_history_and_general(self):
        """Combined results do not exceed limit."""
        mem = _make_memory(
            {
                "run:a": _run_history_fact("a", ts="2026-04-17T12:00:00"),
                "run:b": _run_history_fact("b", ts="2026-04-17T11:00:00"),
                "fact:1": _generic_fact("f1"),
                "fact:2": _generic_fact("f2"),
                "fact:3": _generic_fact("f3"),
            }
        )
        from agents.base_agent import AgentContext

        ctx = AgentContext(
            task="what just ran",
            input_data={"query": "what just ran", "limit": 3},
            memory=mem,
        )


# ── Recovery-Linked Query Tests ─────────────────────────────────────────


class TestIsRecoveryLinkedQuery:
    """Tests for _is_recovery_linked_query detection."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from agents.retriever_agent import RetrieverAgent

        self.fn = RetrieverAgent._is_recovery_linked_query

    def test_recovery_trigger(self):
        assert self.fn("what happened in the failed run") is True

    def test_recovered_trigger(self):
        assert self.fn("show the recovery") is True

    def test_after_failure_trigger(self):
        assert self.fn("what happened after the failure") is True

    def test_recovery_attempt_trigger(self):
        assert self.fn("recovery attempt") is True

    def test_what_did_recovery_do(self):
        assert self.fn("what did recovery do") is True

    def test_non_recovery_architecture(self):
        """Architecture query with recovery keyword should NOT trigger."""
        assert self.fn("explain the recovery architecture") is False

    def test_non_recovery_design(self):
        assert self.fn("design of recovery system") is False


class TestRetrieveLinkedRunHistory:
    """Tests for _retrieve_linked_run_history linking parent + recovery child."""

    def _run_with_recovery(
        self, task, run_id, outcome, recovery_id=None, parent_id=None, ts=None
    ):
        # Simple dict, not wrapped
        return {
            "run_id": run_id,
            "run_kind": "recovery" if parent_id else "primary",
            "task": task,
            "outcome": outcome,
            "recovery_run_id": recovery_id,
            "parent_run_id": parent_id,
            "summary": f"{task} - {outcome}",
            "last_updated": ts or "2026-04-17T12:00:00",
            "topic": "run_history",
        }

    def test_parent_with_recovery_returns_linked(self):
        """Parent with recovery_run_id returns both parent and recovery linked."""
        parent = self._run_with_recovery(
            "main task", "run:abc", "failure", recovery_id="run:rec1"
        )
        recovery = self._run_with_recovery(
            "recovery task", "run:rec1", "success", parent_id="run:abc"
        )

        mem = _make_memory({"run:abc": parent, "run:rec1": recovery})
        from agents.retriever_agent import RetrieverAgent

        results = RetrieverAgent._retrieve_linked_run_history(mem, limit=2)

        assert len(results) == 1
        result = results[0]
        assert "linked" in result
        assert result["linked"]["parent"]["task"] == "main task"
        assert result["linked"]["recovery"]["task"] == "recovery task"

    def test_recovery_without_parent_returns_single(self):
        """Recovery child without parent returns cleanly."""
        recovery = self._run_with_recovery(
            "recovery task", "run:rec1", "success", parent_id="run:missing"
        )

        mem = _make_memory({"run:rec1": recovery})
        from agents.retriever_agent import RetrieverAgent

        results = RetrieverAgent._retrieve_linked_run_history(mem, limit=2)

        assert len(results) == 1
        assert "linked" not in results[0]

    def test_parent_without_recovery_returns_single(self):
        """Parent without recovery returns without link."""
        parent = self._run_with_recovery("main task", "run:abc", "success")

        mem = _make_memory({"run:abc": parent})
        from agents.retriever_agent import RetrieverAgent

        results = RetrieverAgent._retrieve_linked_run_history(mem, limit=2)

        assert len(results) == 1
        assert "linked" not in results[0]

    def test_linked_result_has_kind_field(self):
        """Linked result carries kind='linked_run_history'."""
        parent = self._run_with_recovery(
            "main task", "run:abc", "failure", recovery_id="run:rec1"
        )
        recovery = self._run_with_recovery(
            "recovery task", "run:rec1", "success", parent_id="run:abc"
        )
        mem = _make_memory({"run:abc": parent, "run:rec1": recovery})
        from agents.retriever_agent import RetrieverAgent

        results = RetrieverAgent._retrieve_linked_run_history(mem, limit=2)

        assert results[0]["linked"]["kind"] == "linked_run_history"

    def test_recovery_child_first_resolves_parent(self):
        """Recovery child iterated before parent still produces a single linked result."""
        # Make recovery newer so it sorts first
        parent = self._run_with_recovery(
            "main task", "run:abc", "failure", recovery_id="run:rec1",
            ts="2026-04-17T12:00:00",
        )
        recovery = self._run_with_recovery(
            "recovery task", "run:rec1", "success", parent_id="run:abc",
            ts="2026-04-17T12:01:00",
        )
        mem = _make_memory({"run:abc": parent, "run:rec1": recovery})
        from agents.retriever_agent import RetrieverAgent

        results = RetrieverAgent._retrieve_linked_run_history(mem, limit=2)

        assert len(results) == 1
        linked = results[0].get("linked")
        assert linked is not None
        assert linked["parent"]["task"] == "main task"
        assert linked["recovery"]["task"] == "recovery task"

    def test_broken_linkage_degrades_safely(self):
        """Parent references a missing recovery child — returns parent without linked."""
        parent = self._run_with_recovery(
            "main task", "run:abc", "failure", recovery_id="run:missing"
        )
        mem = _make_memory({"run:abc": parent})
        from agents.retriever_agent import RetrieverAgent

        results = RetrieverAgent._retrieve_linked_run_history(mem, limit=2)

        assert len(results) == 1
        assert "linked" not in results[0]
        assert results[0]["value"]["task"] == "main task"

    def test_empty_and_none_memory_return_empty(self):
        from agents.retriever_agent import RetrieverAgent

        assert RetrieverAgent._retrieve_linked_run_history(None, 8) == []
        assert RetrieverAgent._retrieve_linked_run_history(_make_memory({}), 8) == []

    def test_limit_respected(self):
        """Limit caps total linked results returned."""
        mem = _make_memory({
            "run:a": self._run_with_recovery("a", "run:a", "success", ts="2026-04-17T10:00:00"),
            "run:b": self._run_with_recovery("b", "run:b", "success", ts="2026-04-17T11:00:00"),
            "run:c": self._run_with_recovery("c", "run:c", "success", ts="2026-04-17T12:00:00"),
        })
        from agents.retriever_agent import RetrieverAgent

        results = RetrieverAgent._retrieve_linked_run_history(mem, limit=2)

        assert len(results) <= 2


# ── Recovery-Linked Integration Tests (through run()) ────────────────────────


def _make_linked_memory(parent_task="main task", recovery_task="recovery task"):
    """Return memory with a parent + linked recovery child."""
    parent_fact = {
        "value": {
            "run_id": "run:parent1",
            "run_kind": "primary",
            "task": parent_task,
            "outcome": "failure",
            "recovery_run_id": "run:recovery1",
            "parent_run_id": None,
            "summary": f"{parent_task} - failure",
            "ts": "2026-04-17T12:00:00",
        },
        "source": "run_artifact",
        "confidence": 0.9,
        "last_updated": "2026-04-17T12:00:00",
        "topic": "run_history",
    }
    recovery_fact = {
        "value": {
            "run_id": "run:recovery1",
            "run_kind": "recovery",
            "task": recovery_task,
            "outcome": "success",
            "recovery_run_id": None,
            "parent_run_id": "run:parent1",
            "summary": f"{recovery_task} - success",
            "ts": "2026-04-17T12:01:00",
        },
        "source": "run_artifact",
        "confidence": 0.9,
        "last_updated": "2026-04-17T12:01:00",
        "topic": "run_history",
    }
    return _make_memory({
        "run:parent1": parent_fact,
        "run:recovery1": recovery_fact,
    })


class TestRecoveryLinkedIntegration:
    def setup_method(self):
        from agents.retriever_agent import RetrieverAgent

        self.agent = RetrieverAgent()
        self.agent._get_embed_adapter = lambda: None

    def _ctx(self, query, memory=None):
        from agents.base_agent import AgentContext

        return AgentContext(task=query, input_data={"query": query}, memory=memory)

    def test_recovery_query_returns_linked_result(self):
        """Recovery-oriented query surfaces a linked parent+recovery result."""
        mem = _make_linked_memory()
        ctx = self._ctx("what happened in the failed run", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        results = result.output.get("results", [])
        assert len(results) > 0
        linked_results = [r for r in results if r.get("linked")]
        assert len(linked_results) >= 1, "At least one result must carry linked parent+recovery"
        lr = linked_results[0]
        assert lr["linked"]["kind"] == "linked_run_history"
        assert lr["linked"]["parent"]["task"] == "main task"
        assert lr["linked"]["recovery"]["task"] == "recovery task"

    def test_show_recovery_query_returns_linked(self):
        """'show the recovery' triggers linked mode."""
        mem = _make_linked_memory()
        ctx = self._ctx("show the recovery", memory=mem)
        result = self.agent.run(ctx)

        results = result.output.get("results", [])
        linked_results = [r for r in results if r.get("linked")]
        assert len(linked_results) >= 1

    def test_after_failure_query_returns_linked(self):
        """'what happened after the failure' triggers linked mode."""
        mem = _make_linked_memory()
        ctx = self._ctx("what happened after the failure", memory=mem)
        result = self.agent.run(ctx)

        method = result.output.get("method", "")
        assert method.startswith("recovery_linked+"), (
            f"Expected recovery_linked+ method, got: {method}"
        )

    def test_method_string_reflects_recovery_linked(self):
        """method starts with 'recovery_linked+' for recovery queries."""
        mem = _make_linked_memory()
        ctx = self._ctx("what did recovery do", memory=mem)
        result = self.agent.run(ctx)

        assert result.output["method"].startswith("recovery_linked+")

    def test_parent_only_run_unchanged(self):
        """Parent with no recovery child returns a single plain result."""
        mem = _make_memory({
            "run:plain": {
                "value": {
                    "run_id": "run:plain",
                    "run_kind": "primary",
                    "task": "plain run",
                    "outcome": "success",
                    "recovery_run_id": None,
                    "summary": "all good",
                    "ts": "2026-04-17T12:00:00",
                },
                "source": "run_artifact",
                "confidence": 0.9,
                "last_updated": "2026-04-17T12:00:00",
                "topic": "run_history",
            }
        })
        ctx = self._ctx("what did recovery do", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        results = result.output.get("results", [])
        # No linked key on any result
        for r in results:
            assert "linked" not in r or r.get("linked") is None

    def test_generic_recent_query_does_not_force_linked_mode(self):
        """'what just ran' uses run_history+ not recovery_linked+."""
        mem = _make_linked_memory()
        ctx = self._ctx("what just ran", memory=mem)
        result = self.agent.run(ctx)

        method = result.output.get("method", "")
        assert not method.startswith("recovery_linked+"), (
            f"'what just ran' must not trigger recovery_linked mode, got: {method}"
        )

    def test_architecture_query_does_not_trigger_linked(self):
        """Architecture queries with 'recovery' word must not trigger linked mode."""
        mem = _make_linked_memory()
        ctx = self._ctx("explain the recovery architecture", memory=mem)
        result = self.agent.run(ctx)

        method = result.output.get("method", "")
        assert not method.startswith("recovery_linked+"), (
            f"Architecture query must not trigger linked mode, got: {method}"
        )

    def test_broken_linkage_in_run_degrades_gracefully(self):
        """Parent referencing missing child returns non-linked result without crashing."""
        mem = _make_memory({
            "run:orphan": {
                "value": {
                    "run_id": "run:orphan",
                    "run_kind": "primary",
                    "task": "orphan task",
                    "outcome": "failure",
                    "recovery_run_id": "run:gone",
                    "summary": "failed, recovery lost",
                    "ts": "2026-04-17T12:00:00",
                },
                "source": "run_artifact",
                "confidence": 0.9,
                "last_updated": "2026-04-17T12:00:00",
                "topic": "run_history",
            }
        })
        ctx = self._ctx("what happened in the failed run", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        # Result must not have linked key (broken linkage)
        results = result.output.get("results", [])
        for r in results:
            assert not r.get("linked"), "Broken linkage must not produce a linked result"


# ── Path-query retrieval tests ────────────────────────────────────────────────

def _make_path_memory(parent_paths=None, recovery_paths=None):
    """Return memory with run_history facts that include touched_paths."""
    parent_paths = parent_paths or ["src/fetcher.py", "data/input.csv"]
    parent_fact = {
        "value": {
            "run_id": "run:parent1",
            "run_kind": "primary",
            "task": "fetch and process",
            "outcome": "failure",
            "recovery_run_id": "run:rec1" if recovery_paths is not None else None,
            "summary": "failed midway",
            "touched_paths": parent_paths,
            "ts": "2026-04-17T12:00:00",
        },
        "source": "run_artifact",
        "confidence": 0.9,
        "last_updated": "2026-04-17T12:00:00",
        "topic": "run_history",
    }

    facts = {"run:parent1": parent_fact}

    if recovery_paths is not None:
        rec_fact = {
            "value": {
                "run_id": "run:rec1",
                "run_kind": "recovery",
                "task": "retry fetch",
                "outcome": "success",
                "parent_run_id": "run:parent1",
                "summary": "retry succeeded",
                "touched_paths": recovery_paths,
                "ts": "2026-04-17T12:01:00",
            },
            "source": "run_artifact",
            "confidence": 0.9,
            "last_updated": "2026-04-17T12:01:00",
            "topic": "run_history",
        }
        facts["run:rec1"] = rec_fact

    return _make_memory(facts)


class TestIsPathQuery:
    """Tests for RetrieverAgent._is_path_query."""

    def setup_method(self):
        from agents.retriever_agent import RetrieverAgent
        self.fn = RetrieverAgent._is_path_query

    def test_files_touched_triggers(self):
        assert self.fn("what files were touched") is True

    def test_which_files_triggers(self):
        assert self.fn("which files were modified") is True

    def test_what_file_triggers(self):
        assert self.fn("what file did it change") is True

    def test_files_involved_triggers(self):
        assert self.fn("files involved in the run") is True

    def test_paths_involved_triggers(self):
        assert self.fn("paths involved in the recovery") is True

    def test_what_was_modified_triggers(self):
        assert self.fn("what was modified") is True

    def test_files_in_failed_triggers(self):
        assert self.fn("files in the failed run") is True

    def test_paths_changed_triggers(self):
        assert self.fn("paths changed during the run") is True

    def test_architecture_veto(self):
        assert self.fn("explain the architecture") is False

    def test_how_does_veto(self):
        assert self.fn("how does retrieval work") is False

    def test_generic_question_no_trigger(self):
        assert self.fn("what is karma") is False

    def test_empty_returns_false(self):
        assert self.fn("") is False


class TestPathQueryRetrieval:
    """Integration tests: path queries route into run_history and surface touched_paths."""

    def setup_method(self):
        from agents.retriever_agent import RetrieverAgent
        self.agent = RetrieverAgent()
        self.agent._get_embed_adapter = lambda: None

    def _ctx(self, query, memory=None):
        from agents.base_agent import AgentContext
        return AgentContext(task=query, input_data={"query": query}, memory=memory)

    # ── 5. path queries trigger run_history retrieval ────────────────────────

    def test_path_query_triggers_run_history_prefix(self):
        """A file/path query gets run_history facts surfaced first."""
        mem = _make_path_memory()
        ctx = self._ctx("what files were touched by the run", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        method = result.output.get("method", "")
        assert "run_history" in method, (
            f"Path query must trigger run_history prefix, got method={method!r}"
        )

    def test_path_query_returns_touched_paths_in_result(self):
        """Run_history results for path queries carry touched_paths."""
        mem = _make_path_memory(parent_paths=["src/fetcher.py", "data/input.csv"])
        ctx = self._ctx("what files were touched", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        results = result.output.get("results", [])
        assert len(results) > 0
        # The value dict of the first result should contain touched_paths
        val = results[0].get("value", {})
        assert isinstance(val.get("touched_paths"), list)
        assert "src/fetcher.py" in val["touched_paths"]

    def test_path_query_no_run_history_still_succeeds(self):
        """Path query with empty memory returns success (no crash)."""
        mem = _make_memory({})
        ctx = self._ctx("which files were modified", memory=mem)
        result = self.agent.run(ctx)
        assert result.success is True

    # ── 6. recovery-linked path queries return linked structure ──────────────

    def test_recovery_path_query_returns_linked_result(self):
        """'files in the failed run' triggers linked mode when recovery exists."""
        mem = _make_path_memory(
            parent_paths=["src/broken.py"],
            recovery_paths=["src/fixed.py"],
        )
        ctx = self._ctx("files in the failed run", memory=mem)
        result = self.agent.run(ctx)

        assert result.success is True
        results = result.output.get("results", [])
        linked_results = [r for r in results if r.get("linked")]
        assert len(linked_results) >= 1, "Recovery-linked path query must return linked result"
        linked = linked_results[0]["linked"]
        assert linked.get("kind") == "linked_run_history"

    def test_recovery_path_query_linked_has_parent_and_recovery_paths(self):
        """Linked result carries touched_paths on both parent and recovery."""
        mem = _make_path_memory(
            parent_paths=["src/broken.py"],
            recovery_paths=["src/patched.py"],
        )
        ctx = self._ctx("files in the failed run", memory=mem)
        result = self.agent.run(ctx)

        results = result.output.get("results", [])
        linked_results = [r for r in results if r.get("linked")]
        assert linked_results, "Must have linked result"
        linked = linked_results[0]["linked"]
        assert "src/broken.py" in linked["parent"].get("touched_paths", [])
        assert "src/patched.py" in linked["recovery"].get("touched_paths", [])

    def test_recovery_path_query_method_reflects_mode(self):
        """Method string for recovery path query starts with recovery_linked+."""
        mem = _make_path_memory(
            parent_paths=["src/x.py"],
            recovery_paths=["src/y.py"],
        )
        ctx = self._ctx("files in the failed run", memory=mem)
        result = self.agent.run(ctx)
        method = result.output.get("method", "")
        assert method.startswith("recovery_linked+"), (
            f"Expected recovery_linked+ method, got: {method!r}"
        )

    # ── 7. no-path runs degrade safely ───────────────────────────────────────

    def test_no_paths_in_digest_returns_result_without_crash(self):
        """Run_history facts with no touched_paths field return cleanly."""
        mem = _make_memory({
            "run:plain": {
                "value": {
                    "run_id": "run:plain",
                    "run_kind": "primary",
                    "task": "plain task",
                    "outcome": "success",
                    "summary": "done",
                    "ts": "2026-04-17T12:00:00",
                    # no touched_paths key
                },
                "source": "run_artifact",
                "confidence": 0.9,
                "last_updated": "2026-04-17T12:00:00",
                "topic": "run_history",
            }
        })
        ctx = self._ctx("what files were touched", memory=mem)
        result = self.agent.run(ctx)
        assert result.success is True

    def test_empty_touched_paths_list_returns_result_without_crash(self):
        """touched_paths=[] in digest does not produce a paths line."""
        mem = _make_memory({
            "run:plain": {
                "value": {
                    "run_id": "run:plain",
                    "run_kind": "primary",
                    "task": "shell task",
                    "outcome": "success",
                    "summary": "done",
                    "touched_paths": [],
                    "ts": "2026-04-17T12:00:00",
                },
                "source": "run_artifact",
                "confidence": 0.9,
                "last_updated": "2026-04-17T12:00:00",
                "topic": "run_history",
            }
        })
        ctx = self._ctx("what files were touched", memory=mem)
        result = self.agent.run(ctx)
        assert result.success is True

    # ── 8. unrelated queries unchanged ───────────────────────────────────────

    def test_architecture_query_does_not_trigger_path_mode(self):
        """Architecture queries must not be classified as path queries."""
        mem = _make_path_memory()
        ctx = self._ctx("explain the architecture", memory=mem)
        result = self.agent.run(ctx)
        method = result.output.get("method", "")
        assert "run_history" not in method, (
            f"Architecture query must not trigger run_history, got method={method!r}"
        )

    def test_generic_question_does_not_trigger_path_mode(self):
        """General questions must not be classified as path queries."""
        mem = _make_path_memory()
        ctx = self._ctx("what is karma", memory=mem)
        result = self.agent.run(ctx)
        method = result.output.get("method", "")
        assert "run_history" not in method, (
            f"Generic question must not trigger run_history, got method={method!r}"
        )
