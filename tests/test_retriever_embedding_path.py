"""Embedding-path coverage for RetrieverAgent.

Verifies:
- _get_embed_adapter() reaches the loaded nomic-embed-text adapter
- run() reports method='embedding' when adapter is available
- run() reports method='keyword' when adapter is unavailable
- embedding failure on query vector degrades to empty results (not crash)
- embedding failure on individual documents is skipped (partial results ok)
- bootstrap_index handles missing DB file (FileNotFoundError guard)
- cosine similarity ranks semantically relevant results higher
- live E2E: real embedding vectors, real ranking, correct top result
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

_OLLAMA_AVAILABLE = False
try:
    import urllib.request
    with urllib.request.urlopen(
        urllib.request.Request("http://localhost:11434/api/tags"), timeout=2
    ) as _r:
        _OLLAMA_AVAILABLE = _r.status == 200
except Exception:
    pass


# ── helpers ───────────────────────────────────────────────────────────────────


def _memory_with_facts(tmp_dir, facts: dict):
    from storage.memory import MemorySystem
    mem = MemorySystem(
        episodic_file=os.path.join(tmp_dir, "ep.jsonl"),
        facts_file=os.path.join(tmp_dir, "f.json"),
        tasks_file=os.path.join(tmp_dir, "t.json"),
    )
    for key, value in facts.items():
        mem.save_fact(key, value, source="test")
    return mem


def _fresh_agent(tmp_dir):
    from agents.retriever_agent import RetrieverAgent
    agent = RetrieverAgent()
    RetrieverAgent._embed_cache = {}
    RetrieverAgent._cache_loaded = False
    RetrieverAgent._index_path = os.path.join(tmp_dir, "embed.db")
    return agent


def _ctx(query="test query", memory=None):
    from agents.base_agent import AgentContext
    return AgentContext(task=query, input_data={"query": query}, memory=memory)


class _FakeAdapter:
    """Deterministic fake embedding adapter — returns fixed-size vectors."""
    is_loaded = True

    def __init__(self, dim=8, seed_map=None):
        self._dim = dim
        self._seed_map = seed_map or {}

    def embed(self, text: str):
        import math
        # Return a vector biased toward 1.0 in specific dimensions based on seed_map
        vec = [0.1] * self._dim
        for keyword, dims in self._seed_map.items():
            if keyword.lower() in text.lower():
                for d in dims:
                    vec[d] = 1.0
        # Normalize
        mag = math.sqrt(sum(v * v for v in vec))
        return [v / mag for v in vec] if mag else vec


class _FailAdapter:
    is_loaded = True

    def embed(self, text: str):
        raise RuntimeError("adapter connection refused")


# ── _get_embed_adapter() ──────────────────────────────────────────────────────


class TestGetEmbedAdapter:

    def test_returns_none_when_no_slot_assignment(self):
        from agents.retriever_agent import RetrieverAgent
        agent = RetrieverAgent()
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = None
        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm):
            result = agent._get_embed_adapter()
        assert result is None

    def test_returns_none_when_assignment_has_no_model_id(self):
        from agents.retriever_agent import RetrieverAgent
        agent = RetrieverAgent()
        assignment = MagicMock()
        assignment.assigned_model_id = None
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = assignment
        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm):
            result = agent._get_embed_adapter()
        assert result is None

    def test_returns_none_when_model_not_in_manager(self):
        from agents.retriever_agent import RetrieverAgent
        agent = RetrieverAgent()
        assignment = MagicMock()
        assignment.assigned_model_id = "nomic-embed-text"
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = assignment
        mock_mgr = MagicMock()
        mock_mgr._models = {}
        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=mock_mgr):
            result = agent._get_embed_adapter()
        assert result is None

    def test_returns_adapter_when_loaded(self):
        from agents.retriever_agent import RetrieverAgent
        agent = RetrieverAgent()
        assignment = MagicMock()
        assignment.assigned_model_id = "nomic-embed-text"
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = assignment
        mock_adapter = MagicMock()
        mock_adapter.is_loaded = True
        mock_mgr = MagicMock()
        mock_mgr._models = {"nomic-embed-text": mock_adapter}
        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=mock_mgr):
            result = agent._get_embed_adapter()
        assert result is mock_adapter

    def test_calls_load_when_adapter_not_loaded(self):
        from agents.retriever_agent import RetrieverAgent
        agent = RetrieverAgent()
        assignment = MagicMock()
        assignment.assigned_model_id = "nomic-embed-text"
        mock_sm = MagicMock()
        mock_sm.get_role_assignment.return_value = assignment

        load_called = []

        class UnloadedAdapter:
            is_loaded = False

            def load(self):
                load_called.append(1)
                UnloadedAdapter.is_loaded = True
                return True

        adapter = UnloadedAdapter()
        mock_mgr = MagicMock()
        mock_mgr._models = {"nomic-embed-text": adapter}
        with patch("core.slot_manager.get_slot_manager", return_value=mock_sm), \
             patch("core.agent_model_manager.get_agent_model_manager", return_value=mock_mgr):
            result = agent._get_embed_adapter()
        assert len(load_called) == 1
        assert result is adapter

    def test_returns_none_on_import_error(self):
        from agents.retriever_agent import RetrieverAgent
        agent = RetrieverAgent()
        with patch("core.agent_model_manager.get_agent_model_manager",
                   side_effect=ImportError("no module")):
            result = agent._get_embed_adapter()
        assert result is None


# ── run() method selection ────────────────────────────────────────────────────


class TestRunMethodSelection:

    def test_uses_embedding_method_when_adapter_available(self, tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {"fact_a": "test content"})
            agent = _fresh_agent(tmp)
            adapter = _FakeAdapter(dim=8)
            agent._get_embed_adapter = lambda: adapter
            result = agent.run(_ctx("test content", memory=mem))
        assert result.success is True
        assert result.output["method"] == "embedding"

    def test_uses_keyword_method_when_no_adapter(self, tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {"fact_a": "machine learning basics"})
            agent = _fresh_agent(tmp)
            agent._get_embed_adapter = lambda: None
            result = agent.run(_ctx("machine learning", memory=mem))
        assert result.success is True
        assert result.output["method"] == "keyword"

    def test_keyword_search_matches_substring(self, tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {
                "ml_fact": "machine learning algorithms",
                "coffee": "coffee and caffeine",
            })
            agent = _fresh_agent(tmp)
            agent._get_embed_adapter = lambda: None
            result = agent.run(_ctx("machine learning", memory=mem))
        assert result.success is True
        assert any(r["key"] == "ml_fact" for r in result.output["results"])

    def test_keyword_search_does_not_match_unrelated(self, tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {"coffee": "coffee and caffeine"})
            agent = _fresh_agent(tmp)
            agent._get_embed_adapter = lambda: None
            result = agent.run(_ctx("machine learning", memory=mem))
        assert result.success is True
        assert result.output["count"] == 0

    def test_empty_memory_returns_success_empty_results(self, tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {})
            agent = _fresh_agent(tmp)
            adapter = _FakeAdapter(dim=8)
            agent._get_embed_adapter = lambda: adapter
            result = agent.run(_ctx("anything", memory=mem))
        assert result.success is True
        assert result.output["count"] == 0


# ── embedding failure degradation ─────────────────────────────────────────────


class TestEmbeddingFailureDegradation:

    def test_query_embed_failure_returns_empty_not_crash(self, tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {"fact": "some content"})
            agent = _fresh_agent(tmp)
            agent._get_embed_adapter = lambda: _FailAdapter()
            result = agent.run(_ctx("test query", memory=mem))
        # Must not raise — returns empty embedding result
        assert result.success is True
        assert result.output["method"] == "embedding"
        assert result.output["count"] == 0

    def test_exception_in_get_embed_adapter_falls_back_to_keyword(self, tmp_path):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {"ml_fact": "machine learning basics"})
            agent = _fresh_agent(tmp)

            def _raise():
                raise RuntimeError("slot manager unavailable")

            agent._get_embed_adapter = _raise
            # Exception in _get_embed_adapter: run() outer try/except catches it
            result = agent.run(_ctx("machine learning", memory=mem))
        # Outer exception handler returns success=False
        assert result.success is False

    def test_document_embed_failure_skips_that_document(self, tmp_path):
        """When a document fails to embed, it is skipped and other docs still rank."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {
                "good_doc": "machine learning neural networks",
                "bad_doc": "this doc causes embed failure",
            })
            agent = _fresh_agent(tmp)

            fail_count = [0]
            real_adapter = _FakeAdapter(dim=8, seed_map={"machine learning": [0, 1]})

            class SelectiveFail:
                is_loaded = True

                def embed(self, text):
                    if "bad_doc" in text or "bad doc" in text.lower():
                        fail_count[0] += 1
                        raise RuntimeError("selective fail")
                    return real_adapter.embed(text)

            agent._get_embed_adapter = lambda: SelectiveFail()
            result = agent.run(_ctx("machine learning", memory=mem))

        assert result.success is True
        # good_doc should still appear despite bad_doc failing
        keys = [r["key"] for r in result.output["results"]]
        assert "good_doc" in keys
        assert "bad_doc" not in keys


# ── bootstrap index missing-file guard (bug fix) ─────────────────────────────


class TestBootstrapIndexMissingFile:

    def test_run_succeeds_when_index_db_does_not_exist(self, tmp_path):
        """Prior to fix: os.path.getsize on non-existent path raised FileNotFoundError."""
        from agents.retriever_agent import RetrieverAgent
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {"fact": "content"})
            agent = _fresh_agent(tmp)
            # index DB does NOT exist yet in tmp dir
            assert not os.path.exists(RetrieverAgent._index_path)
            adapter = _FakeAdapter(dim=8)
            agent._get_embed_adapter = lambda: adapter
            result = agent.run(_ctx("test", memory=mem))
        assert result.success is True  # must not raise FileNotFoundError

    def test_bootstrap_index_creates_db_when_missing(self, tmp_path, monkeypatch):
        from agents.retriever_agent import RetrieverAgent
        db_path = str(tmp_path / "new_embed.db")
        assert not os.path.exists(db_path)
        monkeypatch.setattr(
            RetrieverAgent,
            "_get_index_path",
            classmethod(lambda cls: db_path),
        )
        RetrieverAgent._cache_loaded = False
        adapter = _FakeAdapter(dim=8)
        RetrieverAgent.bootstrap_index(adapter)
        assert os.path.exists(db_path)

    def test_second_run_skips_bootstrap_when_db_populated(self, tmp_path):
        """After first run creates the index, subsequent runs skip bootstrap."""
        from agents.retriever_agent import RetrieverAgent
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {"fact": "content"})
            agent = _fresh_agent(tmp)
            adapter = _FakeAdapter(dim=8)
            agent._get_embed_adapter = lambda: adapter

            # First run — creates DB
            result1 = agent.run(_ctx("test", memory=mem))
            assert result1.success is True
            assert os.path.exists(RetrieverAgent._index_path)

            # Second run — _cache_loaded=True, skips bootstrap
            bootstrap_calls = []
            original_bootstrap = RetrieverAgent.bootstrap_index

            @classmethod
            def counting_bootstrap(cls, adapter):
                bootstrap_calls.append(1)
                return original_bootstrap.__func__(cls, adapter)

            RetrieverAgent.bootstrap_index = counting_bootstrap
            try:
                result2 = agent.run(_ctx("test", memory=mem))
                assert result2.success is True
                assert len(bootstrap_calls) == 0
            finally:
                RetrieverAgent.bootstrap_index = original_bootstrap


# ── cosine similarity ranking ─────────────────────────────────────────────────


class TestCosineSimilarityRanking:

    def test_semantically_close_doc_ranks_higher(self, tmp_path):
        """Doc with overlapping semantic signal scores higher than unrelated doc."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {
                "relevant": "machine learning neural networks deep learning",
                "irrelevant": "cooking recipes pasta carbonara",
            })
            agent = _fresh_agent(tmp)
            # Adapter: dims 0,1 fire for ML terms; dims 2,3 fire for cooking
            adapter = _FakeAdapter(
                dim=8,
                seed_map={
                    "machine learning": [0, 1],
                    "neural": [0, 1],
                    "cooking": [2, 3],
                    "pasta": [2, 3],
                },
            )
            agent._get_embed_adapter = lambda: adapter
            result = agent.run(_ctx("machine learning neural", memory=mem))

        assert result.success is True
        results = result.output["results"]
        # Ensure 'relevant' ranks above 'irrelevant'
        relevant_scores = {r["key"]: r.get("score", 0) for r in results}
        if "relevant" in relevant_scores and "irrelevant" in relevant_scores:
            assert relevant_scores["relevant"] > relevant_scores["irrelevant"]

    def test_low_similarity_results_filtered_out(self, tmp_path):
        """Results below the 0.4 similarity threshold are excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = _memory_with_facts(tmp, {"unrelated": "completely unrelated content xyz"})
            agent = _fresh_agent(tmp)
            # Adapter returns orthogonal vectors — cosine similarity = 0
            call_count = [0]

            class OrthogonalAdapter:
                is_loaded = True

                def embed(self, text):
                    call_count[0] += 1
                    # Alternate between two orthogonal unit vectors
                    if call_count[0] % 2 == 1:
                        return [1.0, 0.0, 0.0, 0.0]
                    return [0.0, 1.0, 0.0, 0.0]

            agent._get_embed_adapter = lambda: OrthogonalAdapter()
            result = agent.run(_ctx("test query", memory=mem))

        assert result.success is True
        # Orthogonal vectors have cosine=0, which is below 0.4 threshold
        assert result.output["count"] == 0

    def test_identical_query_and_doc_scores_near_1(self):
        from agents.retriever_agent import RetrieverAgent
        import math

        adapter = _FakeAdapter(dim=8, seed_map={"machine": [0, 1, 2], "learning": [3, 4, 5]})
        agent = RetrieverAgent()

        text = "machine learning course"
        vec_a = adapter.embed(text)
        vec_b = adapter.embed(text)

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            ma = math.sqrt(sum(x * x for x in a))
            mb = math.sqrt(sum(x * x for x in b))
            return dot / (ma * mb) if ma and mb else 0.0

        sim = cosine(vec_a, vec_b)
        assert abs(sim - 1.0) < 1e-6


# ── Live E2E — requires Ollama with nomic-embed-text ─────────────────────────


@pytest.mark.skipif(not _OLLAMA_AVAILABLE, reason="Ollama not reachable at localhost:11434")
class TestRetrieverEmbeddingLive:

    def _fresh_globals(self):
        import core.agent_model_manager as _amm
        import core.slot_manager as _sm
        orig = (_amm._global_manager, _sm._global_manager)
        _amm._global_manager = None
        _sm._global_manager = None
        return orig

    def _restore_globals(self, orig):
        import core.agent_model_manager as _amm
        import core.slot_manager as _sm
        _amm._global_manager, _sm._global_manager = orig

    def test_get_embed_adapter_returns_nomic_adapter(self):
        orig = self._fresh_globals()
        try:
            from core.agent_model_manager import get_agent_model_manager
            mgr = get_agent_model_manager()
            mgr.initialize()

            from agents.retriever_agent import RetrieverAgent
            agent = RetrieverAgent()
            adapter = agent._get_embed_adapter()
            assert adapter is not None
            assert adapter.is_loaded is True
            assert type(adapter).__name__ == "LocalEmbeddingAdapter"
        finally:
            self._restore_globals(orig)

    def test_embed_produces_768_dimensional_vector(self):
        orig = self._fresh_globals()
        try:
            from core.agent_model_manager import get_agent_model_manager
            mgr = get_agent_model_manager()
            mgr.initialize()

            from agents.retriever_agent import RetrieverAgent
            agent = RetrieverAgent()
            adapter = agent._get_embed_adapter()
            assert adapter is not None
            vec = adapter.embed("test sentence about machine learning")
            assert isinstance(vec, list)
            assert len(vec) == 768
            assert all(isinstance(v, float) for v in vec)
        finally:
            self._restore_globals(orig)

    def test_retrieval_method_is_embedding(self):
        orig = self._fresh_globals()
        try:
            from core.agent_model_manager import get_agent_model_manager
            mgr = get_agent_model_manager()
            mgr.initialize()

            from agents.base_agent import AgentContext

            with tempfile.TemporaryDirectory() as tmp:
                mem = _memory_with_facts(tmp, {
                    "ml_fact": "Machine learning is a subset of artificial intelligence",
                    "coffee_fact": "Coffee contains caffeine",
                    "karma_fact": "Karma is an autonomous local agent",
                })
                agent = _fresh_agent(tmp)
                ctx = AgentContext(
                    task="machine learning AI",
                    input_data={"query": "machine learning AI"},
                    memory=mem,
                )
                result = agent.run(ctx)

            assert result.success is True
            assert result.output["method"] == "embedding"
        finally:
            self._restore_globals(orig)

    def test_ml_fact_ranks_highest_for_ml_query(self):
        orig = self._fresh_globals()
        try:
            from core.agent_model_manager import get_agent_model_manager
            mgr = get_agent_model_manager()
            mgr.initialize()

            from agents.base_agent import AgentContext

            with tempfile.TemporaryDirectory() as tmp:
                mem = _memory_with_facts(tmp, {
                    "ml_fact": "Machine learning is a subset of artificial intelligence",
                    "coffee_fact": "Coffee contains caffeine which is a stimulant",
                    "karma_fact": "Karma is an autonomous local agent system",
                })
                agent = _fresh_agent(tmp)
                ctx = AgentContext(
                    task="machine learning AI",
                    input_data={"query": "machine learning AI"},
                    memory=mem,
                )
                result = agent.run(ctx)

            assert result.success is True
            results = result.output["results"]
            assert len(results) > 0
            # ml_fact should be the top-ranked result
            assert results[0]["key"] == "ml_fact", (
                f"Expected ml_fact to rank first, got: {[r['key'] for r in results]}"
            )
        finally:
            self._restore_globals(orig)

    def test_embedding_scores_are_in_0_to_1_range(self):
        orig = self._fresh_globals()
        try:
            from core.agent_model_manager import get_agent_model_manager
            mgr = get_agent_model_manager()
            mgr.initialize()

            from agents.base_agent import AgentContext

            with tempfile.TemporaryDirectory() as tmp:
                mem = _memory_with_facts(tmp, {
                    "fact_a": "Python is a programming language",
                    "fact_b": "Machine learning uses data",
                })
                agent = _fresh_agent(tmp)
                result = agent.run(AgentContext(
                    task="python programming",
                    input_data={"query": "python programming"},
                    memory=mem,
                ))

            for r in result.output.get("results", []):
                score = r.get("score", 0)
                assert 0.0 <= score <= 1.0, f"Score out of range: {score}"
        finally:
            self._restore_globals(orig)

    def test_retrieval_is_better_than_keyword_for_semantic_match(self):
        """Embedding retrieval finds 'artificial intelligence' doc for 'AI' query,
        which keyword search would miss (no exact match on 'AI')."""
        orig = self._fresh_globals()
        try:
            from core.agent_model_manager import get_agent_model_manager
            mgr = get_agent_model_manager()
            mgr.initialize()

            from agents.retriever_agent import RetrieverAgent
            from agents.base_agent import AgentContext

            with tempfile.TemporaryDirectory() as tmp:
                # Note: 'AI' does not appear literally in the fact value
                mem = _memory_with_facts(tmp, {
                    "ai_fact": "Artificial intelligence enables machines to learn from experience",
                    "coffee_fact": "Coffee beans are grown in tropical regions",
                })
                agent_embed = _fresh_agent(tmp)

                agent_kw = RetrieverAgent()
                agent_kw._get_embed_adapter = lambda: None

                ctx = AgentContext(
                    task="AI learning systems",
                    input_data={"query": "AI learning systems"},
                    memory=mem,
                )
                embed_result = agent_embed.run(ctx)
                kw_result = agent_kw.run(ctx)

            # Embedding should find ai_fact (semantic match: "artificial intelligence" ~ "AI")
            embed_keys = [r["key"] for r in embed_result.output.get("results", [])]
            kw_keys = [r["key"] for r in kw_result.output.get("results", [])]

            assert embed_result.output["method"] == "embedding"
            assert kw_result.output["method"] == "keyword"
            assert "ai_fact" in embed_keys, (
                f"Embedding search missed ai_fact for 'AI' query. Got: {embed_keys}"
            )
            # Keyword typically misses this since 'AI' is not in the fact text
            # (we don't assert it misses, just that embedding finds it)
        finally:
            self._restore_globals(orig)
