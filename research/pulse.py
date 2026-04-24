"""Karma Pulse - Real-time Status System

Provides a simple, understandable real-time status system showing:
- what Karma is doing
- what it needs
- what failed
- what it recently succeeded at
- what knowledge should be fed into the system next
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Event types
EVENT_TYPES = {
    "intent": "Intent detected",
    "action": "Action taken",
    "need": "Knowledge needed",
    "warning": "Warning",
    "error": "Error occurred",
    "result": "Result obtained",
    "success": "Success",
}

# Subsystems
SUBSYSTEMS = {
    "golearn": "GoLearn",
    "ingest": "Ingestion",
    "code": "Code Tool",
    "debug": "Debugging",
    "tests": "Testing",
    "system": "System",
    "patching": "Patching",
    "knowledge": "Knowledge",
    "conversation": "Conversation",
}

# Severity levels
SEVERITY_LEVELS = {
    "info": 1,
    "warning": 2,
    "error": 3,
    "success": 4,
}


@dataclass
class PulseEvent:
    """A single pulse event."""
    id: str
    type: str  # intent, action, need, warning, error, result, success
    message: str  # Short human-readable message
    severity: str  # info, warning, error, success
    subsystem: str  # golearn, ingest, code, etc.
    timestamp: str  # ISO timestamp
    context: Optional[Dict[str, Any]] = None  # Optional context
    source: Optional[str] = None  # Source file or component

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat(timespec="seconds")
        if not self.id:
            self.id = f"pulse_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class NeedItem:
    """A knowledge need."""
    id: str
    topic: str
    description: str
    subsystem: str
    created_ts: str
    urgency: int = 1  # 1-5
    suggested_folder: Optional[str] = None

    def __post_init__(self):
        if not self.created_ts:
            self.created_ts = datetime.now().isoformat(timespec="seconds")
        if not self.id:
            self.id = f"need_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class BlockerItem:
    """A current blocker or problem."""
    id: str
    message: str
    severity: str  # warning, error
    subsystem: str
    created_ts: str
    context: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.created_ts:
            self.created_ts = datetime.now().isoformat(timespec="seconds")
        if not self.id:
            self.id = f"block_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class WinItem:
    """A recent success/win."""
    id: str
    message: str
    subsystem: str
    created_ts: str

    def __post_init__(self):
        if not self.created_ts:
            self.created_ts = datetime.now().isoformat(timespec="seconds")
        if not self.id:
            self.id = f"win_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class FeedMeItem:
    """A feed me request."""
    id: str
    requested_topic: str
    suggested_folder: str
    preferred_source_type: str
    reason: str
    created_ts: str
    urgency: int = 1

    def __post_init__(self):
        if not self.created_ts:
            self.created_ts = datetime.now().isoformat(timespec="seconds")
        if not self.id:
            self.id = f"feedme_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


class Pulse:
    """Main Pulse system managing all status information."""

    def __init__(self, storage_dir: str = "data/pulse"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Events stream
        self.events: List[PulseEvent] = []

        # Needs
        self.needs: List[NeedItem] = []

        # Blockers
        self.blockers: List[BlockerItem] = []

        # Recent wins
        self.wins: List[WinItem] = []

        # Feed Me requests
        self.feed_me: List[FeedMeItem] = []

        # Load existing data
        self._load()

    def _load(self) -> None:
        """Load existing pulse data."""
        # Load events
        events_file = self.storage_dir / "events.json"
        if events_file.exists():
            try:
                with open(events_file) as f:
                    data = json.load(f)
                    self.events = [PulseEvent(**e) for e in data.get("events", [])]
            except:
                pass

        # Load needs
        needs_file = self.storage_dir / "needs.json"
        if needs_file.exists():
            try:
                with open(needs_file) as f:
                    data = json.load(f)
                    self.needs = [NeedItem(**n) for n in data.get("needs", [])]
            except:
                pass

        # Load blockers
        blockers_file = self.storage_dir / "blockers.json"
        if blockers_file.exists():
            try:
                with open(blockers_file) as f:
                    data = json.load(f)
                    self.blockers = [BlockerItem(**b) for b in data.get("blockers", [])]
            except:
                pass

        # Load wins
        wins_file = self.storage_dir / "wins.json"
        if wins_file.exists():
            try:
                with open(wins_file) as f:
                    data = json.load(f)
                    self.wins = [WinItem(**w) for w in data.get("wins", [])]
            except:
                pass

        # Load feed me
        feedme_file = self.storage_dir / "feed_me.json"
        if feedme_file.exists():
            try:
                with open(feedme_file) as f:
                    data = json.load(f)
                    self.feed_me = [FeedMeItem(**f) for f in data.get("feed_me", [])]
            except:
                pass

    def _save(self) -> None:
        """Save pulse data to disk."""
        # Save events (last 100)
        with open(self.storage_dir / "events.json", "w") as f:
            json.dump({"events": [vars(e) for e in self.events[-100:]]}, f)

        # Save needs
        with open(self.storage_dir / "needs.json", "w") as f:
            json.dump({"needs": [vars(n) for n in self.needs]}, f)

        # Save blockers
        with open(self.storage_dir / "blockers.json", "w") as f:
            json.dump({"blockers": [vars(b) for b in self.blockers]}, f)

        # Save wins
        with open(self.storage_dir / "wins.json", "w") as f:
            json.dump({"wins": [vars(w) for w in self.wins]}, f)

        # Save feed me
        with open(self.storage_dir / "feed_me.json", "w") as f:
            json.dump({"feed_me": [vars(f) for f in self.feed_me]}, f)

    # ── Event methods ─────────────────────────────────────────────

    def emit(self, type: str, message: str, severity: str = "info",
             subsystem: str = "system", context: Optional[Dict] = None,
             source: Optional[str] = None) -> PulseEvent:
        """Emit a new pulse event."""
        event = PulseEvent(
            id=f"pulse_{len(self.events):05d}",
            type=type,
            message=message,
            severity=severity,
            subsystem=subsystem,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            context=context,
            source=source,
        )
        self.events.append(event)

        # Also add as win if success
        if severity == "success" and type in ("success", "result"):
            self.add_win(message, subsystem)

        self._save()
        return event

    def emit_intent(self, message: str, subsystem: str = "system") -> PulseEvent:
        """Emit an intent event."""
        return self.emit("intent", message, "info", subsystem)

    def emit_action(self, message: str, subsystem: str = "system") -> PulseEvent:
        """Emit an action event."""
        return self.emit("action", message, "info", subsystem)

    def emit_need(self, message: str, topic: str, subsystem: str = "knowledge",
                  folder: Optional[str] = None) -> NeedItem:
        """Emit a need event."""
        # Also add to needs list
        need = NeedItem(
            id=f"need_{len(self.needs):05d}",
            topic=topic,
            description=message,
            subsystem=subsystem,
            created_ts=datetime.now().isoformat(timespec="seconds"),
            suggested_folder=folder,
        )
        self.needs.append(need)

        # Also emit as event
        self.emit("need", message, "info", subsystem)

        self._save()
        return need

    def emit_warning(self, message: str, subsystem: str = "system") -> PulseEvent:
        """Emit a warning event."""
        return self.emit("warning", message, "warning", subsystem)

    def emit_error(self, message: str, subsystem: str = "system",
                   context: Optional[Dict] = None) -> PulseEvent:
        """Emit an error event."""
        # Also add to blockers
        blocker = BlockerItem(
            id=f"block_{len(self.blockers):05d}",
            message=message,
            severity="error",
            subsystem=subsystem,
            created_ts=datetime.now().isoformat(timespec="seconds"),
            context=context,
        )
        self.blockers.append(blocker)

        event = self.emit("error", message, "error", subsystem, context)
        self._save()
        return event

    def emit_result(self, message: str, subsystem: str = "system") -> PulseEvent:
        """Emit a result event."""
        return self.emit("result", message, "info", subsystem)

    def emit_success(self, message: str, subsystem: str = "system") -> PulseEvent:
        """Emit a success event."""
        # Add to wins
        win = WinItem(
            id=f"win_{len(self.wins):05d}",
            message=message,
            subsystem=subsystem,
            created_ts=datetime.now().isoformat(timespec="seconds"),
        )
        self.wins.append(win)

        # Keep only last 20 wins
        if len(self.wins) > 20:
            self.wins = self.wins[-20:]

        event = self.emit("success", message, "success", subsystem)
        self._save()
        return event

    # ── Needs methods ─────────────────────────────────────────────

    def add_need(self, topic: str, description: str, subsystem: str = "knowledge",
                 folder: Optional[str] = None, urgency: int = 1) -> NeedItem:
        """Add a need."""
        need = NeedItem(
            id=f"need_{len(self.needs):05d}",
            topic=topic,
            description=description,
            subsystem=subsystem,
            created_ts=datetime.now().isoformat(timespec="seconds"),
            urgency=urgency,
            suggested_folder=folder,
        )
        self.needs.append(need)
        self._save()
        return need

    def get_needs(self) -> List[NeedItem]:
        """Get all needs."""
        return self.needs

    def clear_need(self, need_id: str) -> None:
        """Clear a need (when fulfilled)."""
        self.needs = [n for n in self.needs if n.id != need_id]
        self._save()

    # ── Blocker methods ────────────────────────────────────────────

    def add_blocker(self, message: str, severity: str = "error",
                     subsystem: str = "system", context: Optional[Dict] = None) -> BlockerItem:
        """Add a blocker."""
        blocker = BlockerItem(
            id=f"block_{len(self.blockers):05d}",
            message=message,
            severity=severity,
            subsystem=subsystem,
            created_ts=datetime.now().isoformat(timespec="seconds"),
            context=context,
        )
        self.blockers.append(blocker)
        self._save()
        return blocker

    def get_blockers(self) -> List[BlockerItem]:
        """Get all blockers."""
        return self.blockers

    def clear_blocker(self, blocker_id: str) -> None:
        """Clear a blocker (when resolved)."""
        self.blockers = [b for b in self.blockers if b.id != blocker_id]
        self._save()

    # ── Win methods ────────────────────────────────────────────────

    def add_win(self, message: str, subsystem: str = "system") -> WinItem:
        """Add a win."""
        win = WinItem(
            id=f"win_{len(self.wins):05d}",
            message=message,
            subsystem=subsystem,
            created_ts=datetime.now().isoformat(timespec="seconds"),
        )
        self.wins.append(win)

        # Keep only last 20
        if len(self.wins) > 20:
            self.wins = self.wins[-20:]

        self._save()
        return win

    def get_wins(self, limit: int = 10) -> List[WinItem]:
        """Get recent wins."""
        return self.wins[-limit:]

    # ── Feed Me methods ───────────────────────────────────────────

    def add_feed_me(self, topic: str, folder: str, source_type: str,
                    reason: str, urgency: int = 1) -> FeedMeItem:
        """Add a feed me request."""
        feed = FeedMeItem(
            id=f"feedme_{len(self.feed_me):05d}",
            requested_topic=topic,
            suggested_folder=folder,
            preferred_source_type=source_type,
            reason=reason,
            created_ts=datetime.now().isoformat(timespec="seconds"),
            urgency=urgency,
        )
        self.feed_me.append(feed)

        # Keep only last 10
        if len(self.feed_me) > 10:
            self.feed_me = self.feed_me[-10:]

        self._save()
        return feed

    def get_feed_me(self) -> List[FeedMeItem]:
        """Get feed me requests."""
        return self.feed_me

    # ── Get recent events ──────────────────────────────────────────

    def get_events(self, limit: int = 20, subsystem: Optional[str] = None) -> List[PulseEvent]:
        """Get recent events."""
        events = self.events[-limit:]
        if subsystem:
            events = [e for e in events if e.subsystem == subsystem]
        return events

    # ── Generate summary ────────────────────────────────────────────

    def generate_summary(self) -> Dict[str, Any]:
        """Generate a summary of all pulse data."""
        return {
            "recent_events": [
                {"type": e.type, "message": e.message, "severity": e.severity, "subsystem": e.subsystem}
                for e in self.events[-10:]
            ],
            "needs": [
                {"topic": n.topic, "description": n.description, "urgency": n.urgency, "folder": n.suggested_folder}
                for n in self.needs[-5:]
            ],
            "blockers": [
                {"message": b.message, "severity": b.severity, "subsystem": b.subsystem}
                for b in self.blockers[-5:]
            ],
            "wins": [
                {"message": w.message, "subsystem": w.subsystem}
                for w in self.wins[-5:]
            ],
            "feed_me": [
                {"requested_topic": f.requested_topic, "suggested_folder": f.suggested_folder, "reason": f.reason}
                for f in self.feed_me[-3:]
            ],
        }

    def generate_markdown(self) -> str:
        """Generate markdown summary for display."""
        lines = [
            "# Karma Pulse",
            "",
            "## Recent Activity",
        ]

        # Recent events
        for e in self.events[-5:]:
            icon = {"info": "•", "warning": "⚠", "error": "✗", "success": "✓"}.get(e.severity, "•")
            lines.append(f"{icon} [{e.subsystem}] {e.message}")

        if self.needs:
            lines.extend(["", "## Needs",])
            for n in self.needs[-3:]:
                lines.append(f"- **{n.topic}**: {n.description}")

        if self.blockers:
            lines.extend(["", "## Blockers",])
            for b in self.blockers[-3:]:
                lines.append(f"- {b.message}")

        if self.wins:
            lines.extend(["", "## Recent Wins",])
            for w in self.wins[-3:]:
                lines.append(f"- ✓ {w.message}")

        if self.feed_me:
            lines.extend(["", "## Feed Me",])
            for f in self.feed_me[-3:]:
                lines.append(f"- {f.requested_topic}: Drop in `{f.suggested_folder}`")
                lines.append(f"  - {f.reason}")

        return "\n".join(lines)


def get_pulse() -> Pulse:
    """Get or create pulse singleton."""
    if not hasattr(get_pulse, "_instance"):
        get_pulse._instance = Pulse()
    return get_pulse._instance
