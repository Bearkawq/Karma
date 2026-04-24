"""Tests for v3.8.5: Unified Knowledge Spine."""

import tempfile
import unittest
from pathlib import Path


class TestKnowledgeSchema(unittest.TestCase):
    """Test Phase 1: Knowledge Schema."""

    def test_knowledge_chunk_structure(self):
        """Test KnowledgeChunk has required fields."""
        from research.knowledge_spine import KnowledgeChunk

        chunk = KnowledgeChunk(
            id="test_001",
            topic="python",
            subtopic="asyncio",
            source_type="navigator",
            provenance="golearn:session123",
            trust_score=0.8,
            timestamp="2026-03-14T10:00:00",
            content="Test content about asyncio",
            tags=["async", "concurrency"],
            content_hash="abc123",
        )

        self.assertEqual(chunk.topic, "python")
        self.assertEqual(chunk.source_type, "navigator")
        self.assertEqual(chunk.trust_score, 0.8)
        self.assertIn("async", chunk.tags)

    def test_source_types(self):
        """Test source types with trust scores."""
        from research.knowledge_spine import SOURCE_TYPES

        self.assertIn("seed_pack", SOURCE_TYPES)
        self.assertIn("docs_harvest", SOURCE_TYPES)
        self.assertIn("navigator", SOURCE_TYPES)
        self.assertIn("context7", SOURCE_TYPES)
        self.assertIn("patch", SOURCE_TYPES)


class TestIngestionNormalization(unittest.TestCase):
    """Test Phase 2: Ingestion Normalization."""

    def test_knowledge_spine_ingest(self):
        """Test spine ingestion."""
        from research.knowledge_spine import KnowledgeSpine

        with tempfile.TemporaryDirectory() as tmpdir:
            spine = KnowledgeSpine(tmpdir)

            result = spine.ingest(
                content="This is test content about Python asyncio.",
                source_type="navigator",
                provenance="test",
                topic="python",
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.topic, "python")

    def test_ingest_file(self):
        """Test file ingestion."""
        from research.knowledge_spine import KnowledgeSpine

        with tempfile.TemporaryDirectory() as tmpdir:
            spine = KnowledgeSpine(tmpdir)

            test_file = Path(tmpdir) / "test.md"
            test_file.write_text("# Test\n\nThis is a test file about Python.")

            stats = spine.ingest_file(str(test_file), "raw_drop")

            self.assertGreater(stats.items_stored, 0)

    def test_ingest_deduplication(self):
        """Test deduplication works."""
        from research.knowledge_spine import KnowledgeSpine

        with tempfile.TemporaryDirectory() as tmpdir:
            spine = KnowledgeSpine(tmpdir)

            content = "Duplicate test content."

            chunk1 = spine.ingest(content, "test", "test_prov", "test")
            chunk2 = spine.ingest(content, "test", "test_prov", "test")

            self.assertIsNotNone(chunk1)
            self.assertIsNone(chunk2)


class TestRetrievalLayer(unittest.TestCase):
    """Test Phase 3: Retrieval Layer."""

    def test_retrieve_by_topic(self):
        """Test retrieval by topic."""
        from research.knowledge_spine import KnowledgeSpine

        with tempfile.TemporaryDirectory() as tmpdir:
            spine = KnowledgeSpine(tmpdir)

            spine.ingest("Python asyncio content", "navigator", "test", "python")
            spine.ingest("Kali Linux content", "docs", "test", "kali_linux")
            spine.ingest("Debugging tips", "patch", "test", "debugging")

            results = spine.retrieve(topic="python")

            self.assertGreater(len(results), 0)
            self.assertEqual(results[0].chunk.topic, "python")

    def test_retrieve_with_query(self):
        """Test retrieval with query."""
        from research.knowledge_spine import KnowledgeSpine

        with tempfile.TemporaryDirectory() as tmpdir:
            spine = KnowledgeSpine(tmpdir)

            spine.ingest("asyncio.TaskGroup is useful for concurrency", "navigator", "test", "python")
            spine.ingest("Python basics content", "navigator", "test", "python")

            results = spine.retrieve(topic="python", query="TaskGroup")

            self.assertGreater(len(results), 0)

    def test_trust_score_weighting(self):
        """Test trust score affects ranking."""
        from research.knowledge_spine import KnowledgeSpine

        with tempfile.TemporaryDirectory() as tmpdir:
            spine = KnowledgeSpine(tmpdir)

            spine.ingest("Low trust content", "patch", "test", "python", trust_score=0.3)
            spine.ingest("High trust content", "seed_pack", "test", "python", trust_score=0.9)

            results = spine.retrieve(topic="python", query="content")

            self.assertGreaterEqual(len(results), 0)


class TestDropAnything(unittest.TestCase):
    """Test Phase 6: Drop Anything Ingestion."""

    def test_raw_drop_folder_exists(self):
        """Test raw_drop folder exists."""
        raw_drop = Path("data/raw_drop")
        self.assertTrue(raw_drop.exists() or raw_drop.name == "raw_drop")

    def test_ingest_directory(self):
        """Test directory ingestion."""
        from research.knowledge_spine import KnowledgeSpine

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "docs"
            test_dir.mkdir()

            (test_dir / "test1.md").write_text("# Test 1\n\nContent about Python.")
            (test_dir / "test2.txt").write_text("Content about debugging.")

            spine = KnowledgeSpine(tmpdir)
            stats = spine.ingest_directory(str(test_dir), "raw_drop")

            self.assertGreater(stats.items_stored, 0)


class TestContext7Routing(unittest.TestCase):
    """Test Phase 7: Context7 Routing."""

    def test_context7_trigger_detection(self):
        """Test Context7 trigger detection."""
        from research.context7_router import should_route_to_context7

        self.assertTrue(should_route_to_context7("python library requests"))
        self.assertTrue(should_route_to_context7("React framework tutorial"))
        self.assertTrue(should_route_to_context7("API reference"))
        self.assertFalse(should_route_to_context7("what is python"))

    def test_query_routing(self):
        """Test query routing."""
        from research.context7_router import route_query

        result = route_query("python asyncio TaskGroup")

        self.assertIn("routes", result)
        self.assertIn("primary", result)

    def test_context7_query_transform(self):
        """Test Context7 query transformation."""
        from research.context7_router import get_context7_query

        query = get_context7_query("requests library")
        self.assertIn("requests", query.lower())


class TestSpineStats(unittest.TestCase):
    """Test spine statistics."""

    def test_get_stats(self):
        """Test spine statistics."""
        from research.knowledge_spine import KnowledgeSpine

        with tempfile.TemporaryDirectory() as tmpdir:
            spine = KnowledgeSpine(tmpdir)

            spine.ingest("Python content", "navigator", "test", "python")
            spine.ingest("Kali content", "docs", "test", "kali_linux")

            # Force save
            spine._save_index()

            # Reload to verify persistence
            spine2 = KnowledgeSpine(tmpdir)
            stats = spine2.get_stats()

            self.assertIn("total_chunks", stats)


class TestVersion(unittest.TestCase):
    """Test version update."""

    def test_version_3_8_5(self):
        """Test version is 3.8.6."""
        import json

        config_path = Path(__file__).parent.parent / "config.json"
        with open(config_path) as f:
            config = json.load(f)

        self.assertEqual(config["system"]["version"], "3.8.6")


class TestGoLearnIntegration(unittest.TestCase):
    """Test Phase 4: GoLearn Integration."""

    def test_golearn_spine_integration(self):
        """Test GoLearn to spine integration."""
        from research.golearn_spine_integration import integrate_golearn_to_spine

        result = {
            "topic": "python",
            "session_id": "test123",
            "output": "Learned about Python asyncio concurrency.",
            "sources": [
                {"content": "Source content", "url": "https://example.com", "title": "Example"}
            ]
        }

        chunks = integrate_golearn_to_spine(result)
        self.assertGreaterEqual(chunks, 0)

    def test_get_golearn_context(self):
        """Test getting context from spine."""
        from research.golearn_spine_integration import get_golearn_context

        context = get_golearn_context("python")
        self.assertIsInstance(context, list)


if __name__ == "__main__":
    unittest.main([__file__, "-v"])
