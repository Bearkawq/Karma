from core.retrieval import RetrievalBus, EvidenceItem


class DummyMem:
    def __init__(self):
        self.facts = {}


def test_retrieval_dedup(monkeypatch):
    mem = DummyMem()
    rb = RetrievalBus(mem)

    def fake_world(query, words):
        return [EvidenceItem("fact", {"k": "v"}, 0.8, 0.4, "world", "")]

    def fake_crystals(query, words):
        return [EvidenceItem("fact", {"k": "v"}, 0.7, 0.3, "crystals", "")]

    monkeypatch.setattr(rb, '_retrieve_world', fake_world)
    monkeypatch.setattr(rb, '_retrieve_crystals', fake_crystals)

    bundle = rb.retrieve_context_bundle("some query", mode="respond")
    # Only one evidence for identical value should remain
    matches = [b for b in bundle if getattr(b,'value',None) == {'k':'v'}]
    assert len(matches) == 1
