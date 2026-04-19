from agent.services.status_query_service import is_live_status_query, is_session_summary_query, is_self_check_query


def test_live_status_with_punctuation_and_case():
    assert is_live_status_query("What's the status?")
    assert is_live_status_query("WHAT'S YOUR STATUS!")
    assert is_live_status_query("What is your status?")
    assert is_live_status_query("show me STATUS")


def test_session_summary_with_variants():
    assert is_session_summary_query("Last session summary")
    assert is_session_summary_query("what did you do since boot?")
    assert is_session_summary_query("this session")


def test_self_check_variants():
    assert is_self_check_query("run a quick self-check")
    assert is_self_check_query("Run self check now")
    assert is_self_check_query("diagnose karma!")
