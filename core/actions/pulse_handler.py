"""Pulse action handler.

Shows Karma pulse/status.
"""

from __future__ import annotations

from typing import Any, Dict

from research.pulse import Pulse
from research.pulse_words import get_status_summary


class PulseHandler:
    """Handler for pulse/status display."""
    
    def __init__(self, agent):
        self.agent = agent
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Show Karma pulse status."""
        pulse = Pulse()
        summary = pulse.generate_summary()
        
        lines = [
            "# Karma Pulse",
            "",
            "## Recent Activity",
        ]
        
        for e in summary.get("recent_events", [])[:5]:
            icon = {"info": "•", "warning": "⚠", "error": "✗", "success": "✓"}.get(e.get("severity", "info"), "•")
            lines.append(f"{icon} [{e.get('subsystem', 'system')}] {e.get('message', '')}")
        
        if summary.get("needs"):
            lines.extend(["", "## Needs",])
            for n in summary["needs"][:3]:
                lines.append(f"- **{n.get('topic', 'unknown')}**: {n.get('description', '')}")
        
        if summary.get("blockers"):
            lines.extend(["", "## Blockers",])
            for b in summary["blockers"][:3]:
                lines.append(f"- {b.get('message', '')}")
        
        if summary.get("wins"):
            lines.extend(["", "## Recent Wins",])
            for w in summary["wins"][:3]:
                lines.append(f"- ✓ {w.get('message', '')}")
        
        if summary.get("feed_me"):
            lines.extend(["", "## Feed Me",])
            for f in summary["feed_me"][:3]:
                topic = f.get('requested_topic') or f.get('topic', 'docs')
                folder = f.get('suggested_folder') or f.get('folder', '?')
                reason = f.get('reason', '')
                lines.append(f"- {topic}: Drop in `{folder}`")
                if reason:
                    lines.append(f"  - {reason}")
        
        status_line = get_status_summary(summary)
        lines.extend(["", f"**Status**: {status_line}",])
        
        return {
            "success": True,
            "output": {"content": "\n".join(lines)},
            "error": None,
        }
