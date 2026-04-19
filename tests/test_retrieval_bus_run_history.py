from core.retrieval import RetrievalBus, EvidenceItem


class _FakeMem:
    def __init__(self, facts):
        self.facts = facts


def _run_history_fact(task="demo task", outcome="success", ts="2026-04-17T12:00:00"):
    return {
        "value": {"task": task, "outcome": outcome, "summary": f"Run: {task}", "ts": ts, "run_id": "run:1"},
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


def test_recent_query_prefers_run_history():
    mem = _FakeMem({"run:last": _run_history_fact(), "other:1": _generic_fact()})
    rb = RetrievalBus(mem)
    bundle = rb.retrieve_context_bundle("what did you do", mode="respond")
    assert len(bundle) > 0
    assert isinstance(bundle[0], EvidenceItem)
    assert bundle[0].source == "run_history"


def test_fallback_when_no_run_history():
    mem = _FakeMem({"some:key": _generic_fact()})
    rb = RetrievalBus(mem)
    bundle = rb.retrieve_context_bundle("what failed recently", mode="respond")
    # Should not crash and should return non-run_history if nothing present
    assert all(getattr(it, "source", None) != "run_history" for it in bundle)


def test_non_recent_query_does_not_prioritize_run_history():
    mem = _FakeMem({"run:last": _run_history_fact(), "karma:arch": _generic_fact()})
    rb = RetrievalBus(mem)
    bundle = rb.retrieve_context_bundle("what is karma", mode="respond")
    # run_history should not be artificially first for a non-recent query
    if bundle:
        assert bundle[0].source != "run_history"
