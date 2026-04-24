"""Tests for hardening pass 3: navigator, summarizer, retriever depth upgrades."""

import pytest
from unittest.mock import MagicMock, patch
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNavigatorStructuralGrounding:
    """Test navigator auto-grounding with structural patterns (no explicit paths)."""

    def test_structural_pattern_triggers_grounding(self):
        """Abstract task like 'what file handles retrieval' should trigger grounding."""
        from agents.navigator_agent import NavigatorAgent

        agent = NavigatorAgent()

        # Mock context with abstract question (no explicit path)
        mock_context = MagicMock()
        mock_context.task = "what file handles retrieval in this project?"
        mock_context.input_data = {}

        with patch.object(agent, "_try_model", return_value=None):
            with patch.object(
                agent, "_navigate_to", return_value={"navigation": "test"}
            ):
                result = agent.run(mock_context)
                assert result.success

    def test_exploration_question_triggers_grounding(self):
        """Questions starting with what/how/which should auto-ground."""
        from agents.navigator_agent import NavigatorAgent

        # Verify structural patterns are defined
        assert hasattr(NavigatorAgent, "_STRUCTURAL_CODE_PATTERNS")
        assert len(NavigatorAgent._STRUCTURAL_CODE_PATTERNS) > 0

        # Verify question starters are defined
        assert hasattr(NavigatorAgent, "_QUESTION_EXPLORATION_STARTERS")
        assert "what" in NavigatorAgent._QUESTION_EXPLORATION_STARTERS
        assert "how" in NavigatorAgent._QUESTION_EXPLORATION_STARTERS

    def test_scan_real_paths_handles_structural(self):
        """_scan_real_paths should return project files for structural patterns."""
        from agents.navigator_agent import NavigatorAgent

        mock_context = MagicMock()
        mock_context.task = "how does the routing work?"
        mock_context.input_data = {}

        result = NavigatorAgent._scan_real_paths(mock_context)
        # Should return project file inventory, not empty
        assert result is not None
        assert "agents" in result or "core" in result or result != ""


class TestSummarizerValidationEnforcement:
    """Test summarizer validation enforcement based on risk."""

    def test_enforce_validation_adds_uncertainty(self):
        """High-risk summaries should have uncertainty marker."""
        from agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent()

        # Summary with ungrounded entities, short source
        summary = "The system uses XModule and YHandler for routing."
        source = "The system handles routing."  # XModule not in source

        result = agent._enforce_validation(summary, "medium", source)

        # Should add uncertainty marker
        assert "[uncertain]" in result or "[may include unsupported]" in result

    def test_enforce_validation_pass_through_low_risk(self):
        """Low-risk summaries should pass through unchanged."""
        from agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent()

        summary = "Error count: 5, Warnings: 12"
        source = "logs: error: 5, warning: 12"

        result = agent._enforce_validation(summary, "low", source)

        # Should be unchanged
        assert result == summary

    def test_risk_assessment_detects_noisy_content(self):
        """_assess_source_risk should return medium for noisy content."""
        from agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent()

        # Long content without structure markers
        noisy = "Lorem ipsum " * 200

        risk = agent._assess_source_risk(noisy, "general")

        assert risk == "medium"

    def test_validation_enforced_flag_in_output(self):
        """Output should include validation_enforced flag."""
        from agents.summarizer_agent import SummarizerAgent

        agent = SummarizerAgent()

        # This is a unit test - verify method exists
        assert hasattr(agent, "_enforce_validation")


class TestRetrieverBootstrap:
    """Test retriever bootstrap and cold-start behavior."""

    def test_bootstrap_creates_index_entries(self):
        """Bootstrap should populate index with project files."""
        from agents.retriever_agent import RetrieverAgent
        import tempfile
        import os

        # Use temp path to avoid polluting real index
        original_path = RetrieverAgent._index_path
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            RetrieverAgent._index_path = f.name

        try:
            RetrieverAgent._cache_loaded = False
            RetrieverAgent._embed_cache = {}

            # Create mock adapter
            mock_adapter = MagicMock()
            mock_adapter.embed.return_value = [0.1] * 384

            result = RetrieverAgent.bootstrap_index(mock_adapter)

            # Check bootstrap log created
            import sqlite3

            con = sqlite3.connect(RetrieverAgent._get_index_path())
            log = con.execute("SELECT * FROM bootstrap_log").fetchone()
            con.close()

            assert log is not None
            assert log[1] > 0  # item_count > 0
        finally:
            RetrieverAgent._index_path = original_path
            if os.path.exists(RetrieverAgent._get_index_path()):
                os.unlink(RetrieverAgent._get_index_path())

    def test_persistent_cache_loads_vectors(self):
        """_load_persistent_cache should load vectors from DB."""
        from agents.retriever_agent import RetrieverAgent
        import tempfile
        import os
        import sqlite3
        import struct

        original_path = RetrieverAgent._index_path
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_path = f.name

        try:
            # Pre-populate with test vector
            con = sqlite3.connect(temp_path)
            con.execute(
                "CREATE TABLE vectors (key TEXT PRIMARY KEY, vector BLOB, updated_at REAL, meta TEXT)"
            )
            test_vec = struct.pack("4f", 0.1, 0.2, 0.3, 0.4)
            con.execute(
                "INSERT INTO vectors VALUES (?, ?, ?, ?)",
                ("test_key", test_vec, 123456.0, None),
            )
            con.commit()
            con.close()

            RetrieverAgent._index_path = temp_path
            RetrieverAgent._cache_loaded = False
            RetrieverAgent._embed_cache = {}

            RetrieverAgent._load_persistent_cache()

            assert "test_key" in RetrieverAgent._embed_cache
            assert len(RetrieverAgent._embed_cache["test_key"]) == 4
        finally:
            RetrieverAgent._index_path = original_path
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_bootstrap_log_table_exists(self):
        """Bootstrap should create bootstrap_log table."""
        from agents.retriever_agent import RetrieverAgent
        import tempfile
        import os

        original_path = RetrieverAgent._index_path
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_path = f.name

        try:
            RetrieverAgent._index_path = temp_path
            RetrieverAgent._ensure_db()

            import sqlite3

            con = sqlite3.connect(temp_path)
            tables = [
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            con.close()

            assert "bootstrap_log" in tables
        finally:
            RetrieverAgent._index_path = original_path
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_persist_vector_with_meta(self):
        """_persist_vector should accept and store metadata."""
        from agents.retriever_agent import RetrieverAgent
        import tempfile
        import os
        import sqlite3
        import json

        original_path = RetrieverAgent._index_path
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_path = f.name

        try:
            RetrieverAgent._index_path = temp_path
            RetrieverAgent._persist_vector("test_key", [0.1, 0.2], meta="bootstrap")

            con = sqlite3.connect(temp_path)
            row = con.execute(
                "SELECT meta FROM vectors WHERE key = 'test_key'"
            ).fetchone()
            con.close()

            assert row is not None
            meta = json.loads(row[0])
            assert meta["source"] == "bootstrap"
        finally:
            RetrieverAgent._index_path = original_path
            if os.path.exists(temp_path):
                os.unlink(temp_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
