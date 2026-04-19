"""Tests for routing lanes and safe mode."""

import unittest
from pathlib import Path
import tempfile
import sys

# Ensure project root on path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


class TestRoutingLanes(unittest.TestCase):
    """Test routing lane determination."""

    def setUp(self):
        from agent.agent_loop import load_config, AgentLoop
        self.cfg = load_config("config.json")
        self.agent = AgentLoop(self.cfg)

    def test_chat_lane_for_questions(self):
        """Questions should route to chat lane."""
        from agent.agent_loop import RoutingLane
        
        lane = self.agent._determine_lane("What is Python?", None, "question")
        self.assertEqual(lane, RoutingLane.CHAT)

    def test_chat_lane_for_prose(self):
        """Free-form prose should route to chat lane."""
        from agent.agent_loop import RoutingLane
        
        # This starts with "Remember" which triggers memory lane - that's correct behavior
        # For true prose, use safe mode
        lane = self.agent._determine_lane("Tell me about Python programming", None, "statement")
        self.assertEqual(lane, RoutingLane.CHAT)

    def test_command_lane_for_explicit_commands(self):
        """Explicit commands should route to command lane."""
        from agent.agent_loop import RoutingLane
        
        lane = self.agent._determine_lane("list files", {"intent": "list_files", "confidence": 0.9}, "command")
        self.assertEqual(lane, RoutingLane.COMMAND)

    def test_memory_lane_for_remember(self):
        """Memory operations should route to memory lane."""
        from agent.agent_loop import RoutingLane
        
        lane = self.agent._determine_lane("remember this fact", None, "statement")
        self.assertEqual(lane, RoutingLane.MEMORY)

    def test_safe_mode_forces_chat(self):
        """Safe mode should force all input to chat lane."""
        from agent.agent_loop import RoutingLane
        
        self.agent.set_safe_mode(True)
        
        # Even explicit commands should go to chat in safe mode
        lane = self.agent._determine_lane("list files", {"intent": "list_files", "confidence": 0.9}, "command")
        self.assertEqual(lane, RoutingLane.CHAT)
        
        # Questions should definitely go to chat
        lane = self.agent._determine_lane("What is Python?", None, "question")
        self.assertEqual(lane, RoutingLane.CHAT)
        
        self.agent.set_safe_mode(False)

    def test_safe_mode_prevents_misrouting(self):
        """Safe mode should prevent prose from becoming file lookups."""
        from agent.agent_loop import RoutingLane
        
        self.agent.set_safe_mode(True)
        
        # These phrases should NOT become file lookups
        test_phrases = [
            "Which should come first and why?",
            "Remember this for this conversation: my test color is ultraviolet green",
            "Tell me about the color of the sky",
        ]
        
        for phrase in test_phrases:
            lane = self.agent._determine_lane(phrase, None, "question" if "?" in phrase else "statement")
            self.assertEqual(lane, RoutingLane.CHAT, f"Phrase '{phrase}' should route to chat, not {lane}")
        
        self.agent.set_safe_mode(False)


class TestRevisionSystem(unittest.TestCase):
    """Test state revision system."""

    def setUp(self):
        from agent.agent_loop import load_config, AgentLoop
        self.cfg = load_config("config.json")
        self.agent = AgentLoop(self.cfg)

    def test_revision_increments_on_execution(self):
        """Revision should increment on successful execution."""
        initial_rev = self.agent.get_revision()
        
        self.agent.increment_revision("test")
        
        self.assertEqual(self.agent.get_revision(), initial_rev + 1)

    def test_last_mutation_recorded(self):
        """Last mutation should be recorded."""
        self.agent.increment_revision("test_action")
        
        mutation = self.agent.get_last_mutation()
        self.assertEqual(mutation["source"], "test_action")
        self.assertIn("revision", mutation)
        self.assertIn("ts", mutation)


class TestAPISchema(unittest.TestCase):
    """Test unified API response schema."""

    def test_api_response_schema(self):
        """API responses should follow unified schema."""
        from ui.web import api_response, api_error
        
        # Test success response
        resp = api_response(data={"test": "value"}, revision=5)
        self.assertIn("ok", resp)
        self.assertIn("data", resp)
        self.assertIn("error", resp)
        self.assertIn("revision", resp)
        self.assertIn("ts", resp)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["data"], {"test": "value"})
        self.assertIsNone(resp["error"])
        
        # Test error response
        resp = api_error("TEST_ERROR", "Test error message", revision=10)
        self.assertFalse(resp["ok"])
        self.assertIsNone(resp["data"])
        self.assertEqual(resp["error"]["code"], "TEST_ERROR")
        self.assertEqual(resp["error"]["message"], "Test error message")
        self.assertEqual(resp["revision"], 10)


if __name__ == "__main__":
    unittest.main()
