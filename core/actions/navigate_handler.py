"""Navigate action handler.

Handles Wikipedia/site navigation.
"""

from __future__ import annotations

from typing import Any, Dict

from navigator import navigate_wikipedia


class NavigateHandler:
    """Handler for site navigation."""

    def __init__(self, agent):
        self.agent = agent

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Navigate a site (e.g., Wikipedia) to gather information."""
        topic = params.get("topic", "").strip()
        if not topic:
            return {
                "success": False,
                "output": None,
                "error": "No topic provided. Use: navigate wikipedia <topic>",
            }

        site = params.get("site", "wikipedia")

        try:
            session_dir = self.agent.base_dir / "data" / "learn"
            result = navigate_wikipedia(topic, max_pages=5, max_depth=2, session_dir=session_dir)

            if not result.success or not result.pages:
                return {
                    "success": False,
                    "output": None,
                    "error": f"Navigation failed: {result.stop_reason}",
                }

            lines = [
                f"# Wikipedia Navigation: {topic}",
                "",
                f"**Pages visited**: {len(result.pages)}",
                f"**Stop reason**: {result.stop_reason}",
                "",
            ]

            for i, page in enumerate(result.pages, 1):
                lines.append(f"## {i}. {page.title}")
                lines.append(f"URL: {page.url}")
                lines.append(f"Depth: {page.depth}")
                lines.append("")
                content_preview = page.content[:300].replace("\n", " ")
                lines.append(content_preview)
                lines.append("")
                lines.append("---")
                lines.append("")

            lines.extend([
                "",
                f"**Total content**: {len(result.total_content)} chars",
                "",
                "Content saved to local knowledge for future use.",
            ])

            return {
                "success": True,
                "output": {"content": "\n".join(lines)},
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"Navigation failed: {str(e)}",
            }
