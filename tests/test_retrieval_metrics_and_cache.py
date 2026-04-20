import pytest
from unittest.mock import MagicMock, patch
from core.retrieval import RetrievalBus


def test_retrieval_metrics_read():
    """get_metrics should return a copy of metrics."""
    rb = RetrievalBus(data_dir="data")
    rb._metrics["test_metric"] = 42
    metrics = rb.get_metrics(reset=False)
    assert metrics["test_metric"] == 42
    assert rb._metrics["test_metric"] == 42  # original unchanged


def test_retrieval_metrics_reset():
    """get_metrics with reset=True should clear metrics."""
    rb = RetrievalBus(data_dir="data")
    rb._metrics["decisions"] = 5
    metrics = rb.get_metrics(reset=True)
    assert metrics["decisions"] == 5
    assert rb._metrics["decisions"] == 0  # cleared


def test_lru_cache_eviction():
    """Bundle cache should evict oldest entries when full."""
    from core.evidence import EvidenceItem
    rb = RetrievalBus(data_dir="data")
    # Fill cache beyond limit
    for i in range(300):
        key = (f"query_{i}", "plan", "", "", ())
        rb._bundle_cache[key] = [EvidenceItem("test", {}, 0.9, 0.8, "test", "test", 1.0)]
    # Should have been evicted to under limit
    assert len(rb._bundle_cache) <= 256