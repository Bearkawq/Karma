"""GoLearn action handler.

Handles GoLearn research sessions.
"""

from __future__ import annotations

from typing import Any, Dict

from research.session import GoLearnSession


class GoLearnHandler:
    """Handler for GoLearn research sessions."""

    def __init__(self, agent):
        self.agent = agent

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a golearn research session."""
        topic = params.get("topic", "")
        minutes = float(params.get("minutes", 5))
        mode = params.get("mode") or "auto"

        if not topic:
            return {"success": False, "output": None, "error": "No topic provided"}

        max_minutes = self.agent.config.get("tools", {}).get("research", {}).get(
            "max_session_minutes", 30
        )
        minutes = min(minutes, max_minutes)

        session_dir = self.agent.base_dir / "data" / "learn"
        session = GoLearnSession(
            topic=topic,
            minutes=minutes,
            mode=mode,
            memory=self.agent.memory,
            bus=self.agent.bus,
            base_dir=str(session_dir),
        )
        result = session.run()

        langmap_facts = {k: v for k, v in self.agent.memory.facts.items()
                         if k.startswith("lang:map:")}
        if langmap_facts:
            self.agent.normalizer.reload_from_memory(self.agent.memory)

        session_status = result["session"]["status"]
        stop_reason = result["session"].get("stop_reason")
        provider_diag = result["session"].get("provider_diagnostic")
        provider_code = result["session"].get("provider_code")
        accepted_sources = result["session"].get("accepted_sources", 0)
        useful_artifacts = result["session"].get("useful_artifacts", 0)

        acquired_useful_results = accepted_sources > 0 and useful_artifacts > 0

        if session_status == "completed":
            if provider_code in ("search_provider_blocked", "search_timeout", "search_parse_error", "search_empty"):
                return {
                    "success": False,
                    "output": result,
                    "error": f"Search provider failed: {provider_diag or provider_code}. Try again later or with a different topic.",
                }

            if stop_reason in ("low_yield", "queue_exhausted"):
                diag_msg = provider_diag or f"Research completed with limited results ({stop_reason}). Try a broader topic."
                return {
                    "success": True,
                    "output": result,
                    "error": None,
                    "diagnostic": diag_msg,
                }

            if not acquired_useful_results:
                return {
                    "success": False,
                    "output": result,
                    "error": f"Research completed but no useful content was acquired. Provider: {provider_diag or provider_code or 'unknown'}",
                }

            return {
                "success": True,
                "output": result,
                "error": None,
            }
        else:
            return {
                "success": False,
                "output": result,
                "error": f"Research failed: {stop_reason or 'unknown error'}",
            }
