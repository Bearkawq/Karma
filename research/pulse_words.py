"""Karma Pulse - Wording Translation Layer

Translates internal machine state into understandable plain English.
Maps provider codes, parse errors, path errors, validation states, etc.
"""

from typing import Dict, Optional


# Provider code translations
PROVIDER_CODE_WORDS = {
    "provider_exhausted": "All current search providers failed",
    "search_provider_blocked": "Search provider blocked the request",
    "search_timeout": "Search request timed out",
    "search_parse_error": "Search provider returned unreadable results",
    "search_empty": "Search returned no results",
    "rate_limited": "Rate limited - too many requests",
    "cache_hit": "Using saved knowledge",
    "cache_miss": "No saved knowledge found",
    "cache_replay_only": "Using saved knowledge because live search failed",
    "live_success": "Successfully acquired fresh knowledge",
    "live_failed": "Live search failed",
    "live_partial": "Some live results, some from cache",
    "provider_ok": "Search provider working",
}

# Error translations
ERROR_WORDS = {
    "FileNotFoundError": "File not found",
    "PermissionError": "Permission denied",
    "TimeoutError": "Request timed out",
    "ConnectionError": "Could not connect",
    "NameError": "Variable not defined",
    "SyntaxError": "Invalid syntax",
    "TypeError": "Wrong type used",
    "ValueError": "Invalid value provided",
    "ImportError": "Could not import module",
    "ModuleNotFoundError": "Module not installed",
    "rglob_absolute_unsupported": "This path cannot be searched as a pattern",
    "path_not_found": "This path does not exist",
}

# Status translations
STATUS_WORDS = {
    "completed": "Finished",
    "running": "In progress",
    "failed": "Failed",
    "blocked": "Blocked",
    "quarantine": "Needs review before use",
    "thin_page": "This page did not contain enough useful content",
    "noisy_page": "This page is too noisy to use",
    "parsing_failed": "Could not understand this file",
    "validation_passed": "Tests passed",
    "validation_failed": "Tests failed",
    "runtime_proof_needed": "Need runtime proof before trusting this",
}

# Subsystem translations
SUBSYSTEM_WORDS = {
    "golearn": "GoLearn",
    "ingest": "Knowledge Ingestion",
    "code": "Code Tool",
    "debug": "Debugger",
    "tests": "Testing",
    "system": "System",
    "patching": "Patching",
    "knowledge": "Knowledge Base",
    "conversation": "Conversation",
}


def translate_provider_code(code: Optional[str]) -> str:
    """Translate provider code to readable text."""
    if not code:
        return "Unknown status"
    return PROVIDER_CODE_WORDS.get(code, code)


def translate_error(error_type: str) -> str:
    """Translate error type to readable text."""
    return ERROR_WORDS.get(error_type, error_type)


def translate_status(status: str) -> str:
    """Translate status to readable text."""
    return STATUS_WORDS.get(status, status)


def translate_subsystem(subsystem: str) -> str:
    """Translate subsystem to readable text."""
    return SUBSYSTEM_WORDS.get(subsystem, subsystem)


def translate_diagnostic(code: Optional[str], message: Optional[str]) -> str:
    """Translate a diagnostic code/message pair to readable text."""
    if message and message in PROVIDER_CODE_WORDS.values():
        return message
    
    if code in PROVIDER_CODE_WORDS:
        return PROVIDER_CODE_WORDS[code]
    
    return message or "Unknown"


def translate_result_origin(origin: Optional[str]) -> str:
    """Translate result origin to readable text."""
    if not origin:
        return "Unknown source"
    
    origin_map = {
        "live": "Fresh web search",
        "cache": "Saved knowledge",
        "mixed": "Mixed - some fresh, some saved",
        "local": "Local knowledge",
        "live_failed": "Live failed, used saved",
    }
    
    return origin_map.get(origin, origin)


def translate_cache_status(status: Optional[str]) -> str:
    """Translate cache status to readable text."""
    if not status:
        return "Unknown"
    
    status_map = {
        "cache_hit": "Found saved knowledge",
        "cache_miss": "No saved knowledge",
        "cache_partial": "Some saved, some new",
        "cache_replay_only": "Only saved knowledge available",
    }
    
    return status_map.get(status, status)


def translate_golearn_result(result: Dict) -> str:
    """Translate a golearn result to readable summary."""
    lines = []
    
    status = result.get("status", "unknown")
    if status == "completed":
        lines.append("✓ GoLearn completed")
    elif status == "failed":
        lines.append("✗ GoLearn failed")
    else:
        lines.append(f"• GoLearn {status}")
    
    # Show what was acquired
    provider = result.get("provider", "")
    if provider:
        lines.append(f"  Provider: {provider}")
    
    accepted = result.get("accepted_sources", 0)
    if accepted > 0:
        lines.append(f"  ✓ Found {accepted} useful sources")
    
    # Show origin
    origin = result.get("result_origin", "")
    if origin:
        lines.append(f"  Source: {translate_result_origin(origin)}")
    
    # Show if cached
    cached = result.get("accepted_sources_cached", 0)
    live = result.get("accepted_sources_live", 0)
    if cached > 0 and live == 0:
        lines.append("  Using saved knowledge (live search failed)")
    elif cached > 0 and live > 0:
        lines.append(f"  Mix: {live} fresh, {cached} saved")
    
    # Show blockers if any
    if result.get("provider_code") == "provider_exhausted":
        lines.append("  ✗ All search providers failed")
    
    return "\n".join(lines)


def translate_ingest_result(result: Dict) -> str:
    """Translate an ingest result to readable summary."""
    lines = []
    
    if result.get("success"):
        lines.append("✓ Ingestion complete")
    else:
        lines.append("✗ Ingestion failed")
    
    # Stats
    scanned = result.get("output", {}).get("content", "")
    if "Files scanned" in scanned:
        lines.append(f"  {scanned}")
    
    return "\n".join(lines)


# Short message builders for common scenarios
def build_live_fail_message(provider_code: str) -> str:
    """Build message for live search failure."""
    if provider_code == "provider_exhausted":
        return "All search providers failed - trying saved knowledge"
    if provider_code == "rate_limited":
        return "Too many requests - waiting before trying again"
    if provider_code == "search_timeout":
        return "Search timed out"
    if provider_code == "search_parse_error":
        return "Search provider returned unreadable results"
    return f"Live search failed: {provider_code}"


def build_cache_message(result_origin: str, cached: int, live: int) -> str:
    """Build message for cache/live mix."""
    if cached > 0 and live == 0:
        return f"Using {cached} saved sources (live search failed)"
    if cached > 0 and live > 0:
        return f"Mixed: {live} fresh + {cached} saved sources"
    if live > 0 and cached == 0:
        return f"Found {live} fresh sources from web"
    return "No sources found"


def build_feed_me_suggestion(topic: str, subsystem: str) -> tuple:
    """Build feed me suggestion based on topic/subsystem."""
    suggestions = {
        "python": ("01_python/", "Python docs, tutorials, examples"),
        "debugging": ("03_debugging/", "Debug guides, bug examples"),
        "kali_linux": ("01_kali_linux/", "Kali tools, security guides"),
        "ai_frameworks": ("04_ai_frameworks/", "AI/ML framework docs"),
        "coding_patterns": ("05_coding_patterns/", "Design patterns, architecture"),
        "systems": ("06_systems/", "OS, networking docs"),
    }
    
    folder, reason = suggestions.get(topic.lower(), ("00_inbox/", "General docs"))
    return folder, f"Needed for {subsystem} - {topic}"


def get_status_summary(pulse_data: Dict) -> str:
    """Get a short status summary."""
    lines = []
    
    # Blockers - if there are blockers, show them instead of wins (avoid contradiction)
    blockers = pulse_data.get("blockers", [])
    if blockers:
        lines.append(f"✗ {blockers[0]['message'][:50]}")
    else:
        # Only show wins if no blockers (avoid contradiction)
        wins = pulse_data.get("wins", [])
        if wins:
            lines.append(f"✓ {wins[0]['message'][:50]}")
    
    # Needs
    needs = pulse_data.get("needs", [])
    if needs:
        lines.append(f"→ Need: {needs[0]['topic']}")
    
    # Feed Me
    feed_me = pulse_data.get("feed_me", [])
    if feed_me:
        topic = feed_me[0].get('requested_topic') or feed_me[0].get('topic') or feed_me[0].get('requested_topic', '')
        lines.append(f"📥 Feed Me: {topic}")
    
    if not lines:
        return "No recent activity"
    
    return " | ".join(lines)