"""Tests for v3.8: Knowledge spines, code intelligence, semantic prep."""

import tempfile
import unittest
from pathlib import Path


class TestNavigatorSpine(unittest.TestCase):
    """Test Phase 1: Navigator Spine."""

    def test_wikipedia_navigation(self):
        """Test Wikipedia navigation capability."""
        from navigator.navigator import SiteNavigator

        nav = SiteNavigator()
        self.assertIsNotNone(nav)
        self.assertTrue(hasattr(nav, 'navigate'))

    def test_site_rules(self):
        """Test site rules for Wikipedia."""
        from navigator.site_rules import WIKIPEDIA_RULES, create_rule_for_url

        self.assertEqual(WIKIPEDIA_RULES.site_name, "wikipedia")
        self.assertEqual(WIKIPEDIA_RULES.max_pages, 6)
        self.assertEqual(WIKIPEDIA_RULES.max_depth, 2)

        rule = create_rule_for_url("https://en.wikipedia.org/wiki/Python")
        self.assertEqual(rule.site_name, "wikipedia")


class TestDocsHarvester(unittest.TestCase):
    """Test Phase 2: Documentation Harvester."""

    def test_harvester_imports(self):
        """Test docs harvester can be imported."""
        from research.docs_harvester import DOCS_SOURCES

        self.assertIn("python", DOCS_SOURCES)
        self.assertIn("kali", DOCS_SOURCES)
        self.assertIn("debian", DOCS_SOURCES)

    def test_harvester_init(self):
        """Test harvester initialization."""
        from research.docs_harvester import DocsHarvester

        h = DocsHarvester()
        self.assertIsNotNone(h)
        self.assertTrue(hasattr(h, 'harvest'))


class TestDropboxDigest(unittest.TestCase):
    """Test Phase 3: Dropbox Digest."""

    def test_dropbox_digest_init(self):
        """Test dropbox digest initialization."""
        from research.dropbox_digest import DropboxDigest, SUPPORTED_EXTENSIONS

        self.assertIn(".md", SUPPORTED_EXTENSIONS)
        self.assertIn(".txt", SUPPORTED_EXTENSIONS)
        self.assertIn(".py", SUPPORTED_EXTENSIONS)

        d = DropboxDigest()
        self.assertIsNotNone(d)


class TestSavedPageDigest(unittest.TestCase):
    """Test Phase 4: Saved Page Digest + MHT Support."""

    def test_mht_support(self):
        """Test MHT/MHTML support."""
        from research.saved_page_digest import SavedPageDigester

        d = SavedPageDigester()
        self.assertIsNotNone(d)
        self.assertTrue(hasattr(d, 'digest_file'))

    def test_mht_digester_init(self):
        """Test MHT digester can be imported."""
        from research.saved_page_digest import MHT_BOUNDARY_RE

        self.assertIsNotNone(MHT_BOUNDARY_RE)


class TestPatchLearning(unittest.TestCase):
    """Test Phase 9: Self-Patch Learning."""

    def test_patch_learner(self):
        """Test patch learning system."""
        from research.patch_learning import PatchLearner

        with tempfile.TemporaryDirectory() as tmpdir:
            learner = PatchLearner(tmpdir)
            self.assertIsNotNone(learner)

            case = learner.record_patch(
                bug_description="Test bug",
                diagnosis="Test diagnosis",
                fix_applied="Test fix",
                file_path="test.py",
                subsystem="tests",
            )

            self.assertIsNotNone(case)
            self.assertEqual(case.bug_description, "Test bug")

            found = learner.search_patches("Test")
            self.assertGreater(len(found), 0)


class TestSemanticPrep(unittest.TestCase):
    """Test Phase 8: Semantic Retrieval Preparation."""

    def test_semantic_preparer(self):
        """Test semantic preparation."""
        from research.semantic_preparation import SemanticPreparer

        with tempfile.TemporaryDirectory() as tmpdir:
            preparer = SemanticPreparer(tmpdir)
            self.assertIsNotNone(preparer)

    def test_chunk_creation(self):
        """Test chunk creation."""
        from research.semantic_preparation import SemanticPreparer

        with tempfile.TemporaryDirectory() as tmpdir:
            preparer = SemanticPreparer(tmpdir)

            test_file = Path(tmpdir) / "test.md"
            test_file.write_text("# Test\n\nSome content here.")

            chunks = preparer.chunk_file(str(test_file))
            self.assertGreater(len(chunks), 0)


class TestCodeIntelligence(unittest.TestCase):
    """Test Phase 10: Code Intelligence Layer."""

    def test_code_intel_imports(self):
        """Test code intelligence can be imported."""
        from tools.code_intelligence import CodeSymbol, ModuleInfo

        self.assertIsNotNone(CodeSymbol)
        self.assertIsNotNone(ModuleInfo)

    def test_scan_repo(self):
        """Test repo scanning."""
        from tools.code_intelligence import scan_repo

        result = scan_repo([".py"])
        self.assertIn("modules_found", result)
        self.assertGreater(result["modules_found"], 0)

    def test_find_symbol(self):
        """Test finding symbols."""
        from tools.code_intelligence import find_symbol

        results = find_symbol("navigate")
        self.assertIsInstance(results, list)

    def test_edit_targets(self):
        """Test finding edit targets."""
        from tools.code_intelligence import find_edit_targets

        targets = find_edit_targets("navigate wikipedia")
        self.assertIsInstance(targets, list)


class TestVersion(unittest.TestCase):
    """Test version update."""

    def test_version_3_8(self):
        """Test version is 3.8.0 or higher."""
        import json

        config_path = Path(__file__).parent.parent / "config.json"
        with open(config_path) as f:
            config = json.load(f)

        self.assertEqual(config["system"]["version"], "3.8.6")


class TestPulseIntegration(unittest.TestCase):
    """Test Phase 11: Pulse / Needs / Feed Me Integration."""

    def test_pulse_works(self):
        """Test pulse integration."""
        from research.pulse import get_pulse

        pulse = get_pulse()
        self.assertIsNotNone(pulse)
        self.assertTrue(hasattr(pulse, 'emit_action'))
        self.assertTrue(hasattr(pulse, 'add_need'))


if __name__ == "__main__":
    unittest.main([__file__, "-v"])
