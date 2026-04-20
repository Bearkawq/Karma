from core.retrieval import RetrievalBus


class DummyMem:
    def __init__(self, facts):
        self.facts = facts


def _run_history_fact():
    return {
        "value": {"task": "t", "run_id": "run:1", "summary": "s"},
        "topic": "run_history",
        "last_updated": "2026-04-17T12:00:00",
        "confidence": 0.9,
    }


def test_metrics_run_history_injected():
    mem = DummyMem({"run:last": _run_history_fact()})
    rb = RetrievalBus(mem)
    bundle = rb.retrieve_context_bundle("what just ran", mode="respond")
    metrics = rb.get_metrics()
    assert metrics.get("run_history_injected", 0) > 0
    assert metrics.get("total_hits", 0) >= 0
