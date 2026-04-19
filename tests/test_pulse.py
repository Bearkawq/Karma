"""Tests for Karma Pulse system (v3.5.7)."""

import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_pulse_event_creation():
    """Test pulse event creation."""
    from research.pulse import Pulse, PulseEvent
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse = Pulse(storage_dir=tmpdir)
        
        event = pulse.emit("action", "Testing pulse", "info", "system")
        assert event is not None
        assert event.type == "action"
        assert event.message == "Testing pulse"
        assert event.severity == "info"
        assert event.subsystem == "system"


def test_pulse_need_generation():
    """Test need generation."""
    from research.pulse import Pulse
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse = Pulse(storage_dir=tmpdir)
        
        need = pulse.add_need("python decorators", "Need examples of Python decorators", "code", "01_python/", urgency=3)
        assert need is not None
        assert need.topic == "python decorators"
        assert need.suggested_folder == "01_python/"
        assert need.urgency == 3


def test_pulse_blocker_generation():
    """Test blocker generation."""
    from research.pulse import Pulse
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse = Pulse(storage_dir=tmpdir)
        
        blocker = pulse.add_blocker("Live search provider blocked", "warning", "golearn")
        assert blocker is not None
        assert blocker.message == "Live search provider blocked"
        assert blocker.severity == "warning"
        assert blocker.subsystem == "golearn"


def test_pulse_win_generation():
    """Test win generation."""
    from research.pulse import Pulse
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse = Pulse(storage_dir=tmpdir)
        
        win = pulse.add_win("Fixed NameError in session.py", "code")
        assert win is not None
        assert win.message == "Fixed NameError in session.py"
        assert win.subsystem == "code"


def test_pulse_feed_me_generation():
    """Test feed me generation."""
    from research.pulse import Pulse
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse = Pulse(storage_dir=tmpdir)
        
        feed = pulse.add_feed_me("Kali persistence", "01_kali_linux/", "docs,tutorials", "Need local docs because live search failed", urgency=3)
        assert feed is not None
        assert feed.requested_topic == "Kali persistence"
        assert feed.suggested_folder == "01_kali_linux/"
        assert feed.preferred_source_type == "docs,tutorials"


def test_pulse_wording_translation():
    """Test wording translation."""
    from research.pulse_words import translate_provider_code, translate_error, translate_status
    
    assert translate_provider_code("provider_exhausted") == "All current search providers failed"
    assert translate_provider_code("search_parse_error") == "Search provider returned unreadable results"
    assert translate_provider_code("unknown_code") == "unknown_code"
    
    assert translate_error("FileNotFoundError") == "File not found"
    assert translate_error("NameError") == "Variable not defined"
    assert translate_error("UnknownError") == "UnknownError"
    
    assert translate_status("completed") == "Finished"
    assert translate_status("quarantine") == "Needs review before use"
    assert translate_status("unknown") == "unknown"


def test_pulse_summary_generation():
    """Test summary generation."""
    from research.pulse import Pulse
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse = Pulse(storage_dir=tmpdir)
        
        pulse.emit_action("Starting golearn", "golearn")
        pulse.add_need("python asyncio", "Need asyncio examples", "code", "01_python/")
        pulse.add_blocker("Live search blocked", "warning", "golearn")
        pulse.add_win("Found 10 useful sources", "golearn")
        pulse.add_feed_me("Kali tools", "01_kali_linux/", "docs", "Need more docs", urgency=2)
        
        summary = pulse.generate_summary()
        assert "recent_events" in summary
        assert "needs" in summary
        assert "blockers" in summary
        assert "wins" in summary
        assert "feed_me" in summary
        
        assert len(summary["recent_events"]) > 0
        assert len(summary["needs"]) > 0
        assert len(summary["blockers"]) > 0
        assert len(summary["wins"]) > 0
        assert len(summary["feed_me"]) > 0


def test_pulse_persistence():
    """Test pulse data persists across instances."""
    from research.pulse import Pulse
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse1 = Pulse(storage_dir=tmpdir)
        pulse1.emit_action("Test action", "system")
        pulse1.add_need("test topic", "test description", "knowledge")
        
        pulse2 = Pulse(storage_dir=tmpdir)
        assert len(pulse2.events) == 1
        assert len(pulse2.needs) == 1


def test_pulse_clear_methods():
    """Test clearing needs, blockers, wins."""
    from research.pulse import Pulse
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pulse = Pulse(storage_dir=tmpdir)
        
        need = pulse.add_need("test", "test desc", "knowledge")
        blocker = pulse.add_blocker("test block", "error", "system")
        win = pulse.add_win("test win", "system")
        
        pulse.clear_need(need.id)
        pulse.clear_blocker(blocker.id)
        
        assert len(pulse.needs) == 0
        assert len(pulse.blockers) == 0
        assert len(pulse.wins) == 1


def test_pulse_integration_with_session():
    """Test that session integration doesn't break import."""
    from research.session import GoLearnSession, PULSE_AVAILABLE
    
    assert PULSE_AVAILABLE is True


def test_pulse_integration_with_code_tool():
    """Test that code tool integration doesn't break import."""
    from tools.code_tool import CodeTool, PULSE_AVAILABLE
    
    assert PULSE_AVAILABLE is True


if __name__ == "__main__":
    test_pulse_event_creation()
    test_pulse_need_generation()
    test_pulse_blocker_generation()
    test_pulse_win_generation()
    test_pulse_feed_me_generation()
    test_pulse_wording_translation()
    test_pulse_summary_generation()
    test_pulse_persistence()
    test_pulse_clear_methods()
    test_pulse_integration_with_session()
    test_pulse_integration_with_code_tool()
    print("All Pulse tests passed!")