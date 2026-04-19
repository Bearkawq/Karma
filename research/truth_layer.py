"""Truth Layer — Result state translation and follow-up handling.

Provides truthful, consistent result states and natural follow-up mapping.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ResultState:
    """Truthful result state labels."""
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    CACHE_ONLY = "cache_only"
    LOCAL_ONLY = "local_only"
    MIXED = "mixed"
    FAILED = "failed"


def determine_result_state(
    stop_reason: Optional[str],
    provider_code: Optional[str],
    accepted_sources_live: int = 0,
    accepted_sources_cached: int = 0,
    accepted_sources_local: int = 0,
    useful_artifacts: int = 0,
) -> tuple[str, str]:
    """Determine truthful result state and summary.
    
    Returns: (state, summary_message)
    
    State options:
    - completed: Run finished normally with useful results
    - partial: Some results but not ideal
    - blocked: Live search was blocked/failed
    - cache_only: Only cached results used
    - local_only: Only local memory used
    - mixed: Mix of live/cached/local
    - failed: No useful results
    """
    total_sources = accepted_sources_live + accepted_sources_cached + accepted_sources_local
    
    # If no useful artifacts, it's a failure
    if useful_artifacts == 0:
        if provider_code in ("provider_exhausted", "search_provider_blocked", "search_timeout"):
            return ResultState.BLOCKED, "No useful results - live search was blocked or unavailable"
        elif provider_code == "low_yield":
            return ResultState.FAILED, "No useful results found - search returned low quality content"
        elif accepted_sources_cached > 0 or accepted_sources_local > 0:
            return ResultState.CACHE_ONLY, "No useful results - used cached/local knowledge only"
        return ResultState.FAILED, "No useful results - run produced nothing useful"
    
    # If we have useful results, determine the source mix
    has_live = accepted_sources_live > 0
    has_cache = accepted_sources_cached > 0
    has_local = accepted_sources_local > 0
    
    # Check if run was blocked/limited
    if provider_code in ("provider_exhausted", "search_provider_blocked", "search_timeout", "rate_limited"):
        if has_live and (has_cache or has_local):
            return ResultState.MIXED, f"Got {useful_artifacts} useful results - mix of live and cached sources"
        elif has_cache and not has_live:
            return ResultState.CACHE_ONLY, f"Got {useful_artifacts} useful results from cache (live search was blocked)"
        elif has_local and not has_live:
            return ResultState.LOCAL_ONLY, f"Got {useful_artifacts} useful results from local memory (live search was blocked)"
    
    # Check stop reason
    if stop_reason == "low_yield":
        if has_live:
            return ResultState.PARTIAL, f"Got {useful_artifacts} useful results but stopped early (low yield)"
        elif has_cache or has_local:
            return ResultState.PARTIAL, f"Got {useful_artifacts} useful results from cache but stopped early"
        return ResultState.FAILED, "Stopped early due to low yield"
    
    if stop_reason == "budget_exhausted":
        if has_live and (has_cache or has_local):
            return ResultState.MIXED, f"Learned {useful_artifacts} useful things - mix of sources"
        elif has_live:
            return ResultState.COMPLETED, f"Successfully learned {useful_artifacts} useful things from live search"
        elif has_cache:
            return ResultState.CACHE_ONLY, f"Got {useful_artifacts} useful results from cache"
        elif has_local:
            return ResultState.LOCAL_ONLY, f"Got {useful_artifacts} useful results from local memory"
    
    if stop_reason == "queue_exhausted":
        return ResultState.COMPLETED, f"Completed - explored all subtopics, got {useful_artifacts} useful results"
    
    # Default: check source mix
    if has_live and has_cache and has_local:
        return ResultState.MIXED, f"Got {useful_artifacts} useful results from multiple sources"
    elif has_live and has_cache:
        return ResultState.MIXED, f"Got {useful_artifacts} useful results - mix of live and cached"
    elif has_live and not has_cache and not has_local:
        return ResultState.COMPLETED, f"Successfully learned {useful_artifacts} useful things from live search"
    elif has_cache and not has_live:
        return ResultState.CACHE_ONLY, f"Got {useful_artifacts} useful results from cache"
    elif has_local and not has_live:
        return ResultState.LOCAL_ONLY, f"Got {useful_artifacts} useful results from local memory"
    
    return ResultState.COMPLETED, f"Completed with {useful_artifacts} useful results"


# Natural follow-up patterns and their handlers
FOLLOWUP_PATTERNS = {
    "errors": ["any errors?", "what errors?", "did it fail", "what failed", "errors", "failures"],
    "failed": ["what failed?", "what went wrong", "what didn't work", "what problem", "what issue"],
    "needs": ["what do you need", "what do you need?", "what do you want", "what do you need more"],
    "stopped": ["why did it stop", "why did it stop?", "why did it end", "what made it stop"],
    "feed": ["what should i feed", "what should i feed you", "what to feed", "feed me", "what to add"],
    "worked": ["what worked", "what worked?", "what succeeded", "what went well", "any wins"],
    "happened": ["what happened", "what happened?", "what's going on", "what's the status"],
    "learned": ["what did you learn", "what did you learn?", "learn anything", "learned anything"],
    "blockers": ["what are the blockers", "what's blocking", "what's stopping", "any blockers"],
}


def handle_followup(query: str, pulse_data: Optional[Dict] = None, 
                   golearn_result: Optional[Dict] = None) -> Optional[str]:
    """Handle natural language follow-up queries.
    
    Returns a response string or None if the query isn't a follow-up.
    """
    low = query.lower().strip().rstrip("?.!")
    
    # Check which pattern matches
    matched_pattern = None
    for pattern_name, patterns in FOLLOWUP_PATTERNS.items():
        for p in patterns:
            if low == p or low.startswith(p.rstrip("?")):
                matched_pattern = pattern_name
                break
        if matched_pattern:
            break
    
    if not matched_pattern:
        return None
    
    # Handle based on pattern type
    if matched_pattern in ("errors", "failed"):
        return _handle_errors_followup(pulse_data, golearn_result)
    elif matched_pattern == "needs":
        return _handle_needs_followup(pulse_data)
    elif matched_pattern == "stopped":
        return _handle_stopped_followup(golearn_result)
    elif matched_pattern == "feed":
        return _handle_feed_followup(pulse_data)
    elif matched_pattern == "worked":
        return _handle_worked_followup(pulse_data, golearn_result)
    elif matched_pattern == "happened":
        return _handle_happened_followup(pulse_data, golearn_result)
    elif matched_pattern == "learned":
        return _handle_learned_followup(golearn_result)
    elif matched_pattern == "blockers":
        return _handle_blockers_followup(pulse_data)
    
    return None


def _handle_errors_followup(pulse_data: Optional[Dict], golearn_result: Optional[Dict]) -> str:
    """Handle 'any errors?' type follow-ups."""
    blockers = pulse_data.get("blockers", []) if pulse_data else []
    
    if golearn_result:
        session = golearn_result.get("session", {})
        provider_code = session.get("provider_code")
        stop_reason = session.get("stop_reason")
        
        if provider_code in ("provider_exhausted", "search_provider_blocked"):
            return "Yes - live search providers were blocked or unavailable. Used cache instead."
        elif provider_code == "search_timeout":
            return "Yes - search requests timed out. Used cached results."
        elif stop_reason == "low_yield":
            return "Yes - search returned low quality results. Not enough useful content found."
        elif stop_reason == "failed":
            return "Yes - the learning session failed completely."
    
    if blockers:
        blocker = blockers[0]
        return f"Yes - {blocker.get('message', 'there was an issue')}"
    
    return "No major errors - the system is running normally."


def _handle_needs_followup(pulse_data: Optional[Dict]) -> str:
    """Handle 'what do you need?' type follow-ups."""
    needs = pulse_data.get("needs", []) if pulse_data else []
    feed_me = pulse_data.get("feed_me", []) if pulse_data else []
    
    if needs:
        need = needs[0]
        return f"I need more {need.get('topic', 'knowledge')} - specifically: {need.get('description', '')}"
    
    if feed_me:
        feed = feed_me[0]
        topic = feed.get("requested_topic", feed.get("topic", "knowledge"))
        folder = feed.get("suggested_folder", "")
        return f"I could use some {topic} docs - drop them in {folder}"
    
    return "I'm currently well-supplied. Ask me to learn something new if you'd like!"


def _handle_stopped_followup(golearn_result: Optional[Dict]) -> str:
    """Handle 'why did it stop?' type follow-ups."""
    if not golearn_result:
        return "No recent learning session to check."
    
    session = golearn_result.get("session", {})
    stop_reason = session.get("stop_reason", "unknown")
    provider_code = session.get("provider_code")
    
    if stop_reason == "low_yield":
        return "It stopped early because not enough useful results were found."
    elif stop_reason == "queue_exhausted":
        return "It completed normally - ran out of subtopics to explore."
    elif stop_reason == "budget_exhausted":
        return "It stopped because the time limit was reached."
    elif stop_reason == "completed":
        return "It completed normally."
    elif provider_code in ("provider_exhausted", "search_provider_blocked"):
        return "It stopped because live search was blocked. Used cached/local knowledge instead."
    elif provider_code:
        return f"It stopped because: {provider_code}"
    
    return f"It stopped for reason: {stop_reason}"


def _handle_feed_followup(pulse_data: Optional[Dict]) -> str:
    """Handle 'what should I feed you?' type follow-ups."""
    feed_me = pulse_data.get("feed_me", []) if pulse_data else []
    
    if not feed_me:
        return "Nothing specific right now. Drop any docs in the knowledge folder and I'll ingest them!"
    
    lines = ["You could feed me:"]
    for feed in feed_me[:3]:
        topic = feed.get("requested_topic", feed.get("topic", "docs"))
        folder = feed.get("suggested_folder", "??")
        lines.append(f"  - {topic} -> drop in {folder}")
    
    return "\n".join(lines)


def _handle_worked_followup(pulse_data: Optional[Dict], golearn_result: Optional[Dict]) -> str:
    """Handle 'what worked?' type follow-ups."""
    wins = pulse_data.get("wins", []) if pulse_data else []
    
    if wins:
        win = wins[0]
        return f"What's working: {win.get('message', 'recent successes')}"
    
    if golearn_result:
        session = golearn_result.get("session", {})
        useful = session.get("useful_artifacts", 0)
        if useful > 0:
            return f"Got {useful} useful results from the last session."
    
    return "Nothing major working right now. The search providers are blocked."


def _handle_happened_followup(pulse_data: Optional[Dict], golearn_result: Optional[Dict]) -> str:
    """Handle 'what happened?' type follow-ups."""
    recent_events = pulse_data.get("recent_events", []) if pulse_data else []
    
    if recent_events:
        event = recent_events[0]
        return f"Last activity: [{event.get('subsystem', 'system')}] {event.get('message', 'something happened')}"
    
    return "Not much happening right now. Ask me to do something!"


def _handle_learned_followup(golearn_result: Optional[Dict]) -> str:
    """Handle 'what did you learn?' type follow-ups."""
    if not golearn_result:
        return "No recent learning session to check."
    
    session = golearn_result.get("session", {})
    topic = session.get("topic", "unknown")
    visited = session.get("visited", [])
    useful = session.get("useful_artifacts", 0)
    accepted = session.get("accepted_sources", 0)
    
    if useful > 0 or accepted > 0:
        sources = session.get("accepted_sources_live", 0)
        cached = session.get("accepted_sources_cached", 0)
        
        if sources > 0 and cached > 0:
            return f"Learned about {topic}: got {useful} useful from live + {cached} from cache, explored {len(visited)} topics."
        elif sources > 0:
            return f"Learned about {topic}: got {useful} useful results from live search, explored {len(visited)} topics."
        elif cached > 0:
            return f"Learned about {topic}: got {useful} useful results from cache, explored {len(visited)} topics."
    
    return f"Last session on '{topic}' didn't find much useful - search providers are blocked."


def _handle_blockers_followup(pulse_data: Optional[Dict]) -> str:
    """Handle 'what are the blockers?' type follow-ups."""
    blockers = pulse_data.get("blockers", []) if pulse_data else []
    
    if not blockers:
        return "No active blockers! Things are running smoothly."
    
    lines = ["Current blockers:"]
    for b in blockers[:3]:
        lines.append(f"  - {b.get('message', 'unknown issue')}")
    
    return "\n".join(lines)


def translate_result_for_display(result: Dict[str, Any]) -> str:
    """Translate a GoLearn result into a truthful, readable summary."""
    session = result.get("session", {})
    
    state, summary = determine_result_state(
        stop_reason=session.get("stop_reason"),
        provider_code=session.get("provider_code"),
        accepted_sources_live=session.get("accepted_sources_live", 0),
        accepted_sources_cached=session.get("accepted_sources_cached", 0),
        accepted_sources_local=session.get("accepted_sources_local", 0),
        useful_artifacts=session.get("useful_artifacts", 0),
    )
    
    return f"[{state.upper()}] {summary}"


def generate_truthful_report(pulse_data: Dict, golearn_result: Optional[Dict] = None) -> str:
    """Generate a truthful, readable status report."""
    lines = ["# Karma Status", ""]
    
    # Recent activity
    recent = pulse_data.get("recent_events", [])[:3]
    if recent:
        lines.append("## Recent")
        for e in recent:
            icon = {"info": "•", "warning": "⚠", "error": "✗", "success": "✓"}.get(e.get("severity", "info"), "•")
            lines.append(f"{icon} {e.get('message', '')}")
        lines.append("")
    
    # Result state
    if golearn_result:
        state, summary = translate_result_for_display(golearn_result)
        lines.append(f"## Result: {state}")
        lines.append(summary)
        lines.append("")
    
    # Blockers (truthful)
    blockers = pulse_data.get("blockers", [])[:3]
    if blockers:
        lines.append("## Blockers")
        for b in blockers:
            lines.append(f"- {b.get('message', 'unknown')}")
        lines.append("")
    
    # Feed Me (clean formatting)
    feed_me = pulse_data.get("feed_me", [])[:3]
    if feed_me:
        lines.append("## Feed Me")
        for f in feed_me:
            topic = f.get("requested_topic", f.get("topic", "docs"))
            folder = f.get("suggested_folder", "?")
            lines.append(f"- {topic} -> {folder}")
        lines.append("")
    
    return "\n".join(lines)