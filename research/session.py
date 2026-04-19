"""GoLearnSession — time-bounded autonomous web learning session.

Orchestrates: TimeBudget -> SearchProvider -> NoteWriter -> SubtopicBrancher
All events emitted through existing EventBus.

Uses search provider abstraction for explicit diagnostics.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .brancher import SubtopicBrancher
from .providers import (
    DiagnosticCode,
    SearchProvider,
    create_provider,
    MAX_PAGES_PER_SLICE,
)
from .index import NoteWriter
from .timekeeper import TimeBudget

try:
    from .pulse import get_pulse
    from .pulse_words import translate_provider_code, build_live_fail_message, build_cache_message
    PULSE_AVAILABLE = True
except ImportError:
    PULSE_AVAILABLE = False
    get_pulse = None
    translate_provider_code = lambda x: x


@dataclass
class ResearchSession:
    """Persistent schema for a golearn session."""
    id: str
    topic: str
    mode: str
    start_ts: str
    end_ts: Optional[str] = None
    budget_minutes: float = 5.0
    visited: List[str] = field(default_factory=list)
    queue: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    notes_count: int = 0
    status: str = "running"
    stop_reason: Optional[str] = None
    # Provider tracking (PHASE 2: MultiProvider truth)
    provider: str = "duckduckgo"  # Default provider name
    provider_diagnostic: Optional[str] = None  # Search provider status
    provider_code: Optional[str] = None  # Explicit diagnostic code
    providers_attempted: List[str] = field(default_factory=list)  # All providers tried
    provider_used: Optional[str] = None  # Which provider actually returned results
    provider_failures: Dict[str, str] = field(default_factory=dict)  # provider -> failure reason
    # Cache provenance (PHASE 3: Cache truth labels)
    cache_status: Optional[str] = None  # cache_hit, cache_partial, cache_miss, cache_replay_only
    result_origin: Optional[str] = None  # live, cache, mixed
    # Artifact counts (PHASE 4: Artifact truth)
    accepted_sources: int = 0  # Total sources accepted
    accepted_sources_live: int = 0  # Live sources accepted
    accepted_sources_cached: int = 0  # Cached sources accepted
    fetched_pages: int = 0  # Total pages fetched
    fetched_pages_live: int = 0  # Live pages fetched
    fetched_pages_cached: int = 0  # Cached pages fetched
    useful_artifacts: int = 0  # Total useful artifacts
    useful_artifacts_live: int = 0  # Live useful artifacts
    useful_artifacts_cached: int = 0  # Cached useful artifacts
    cache_hits: int = 0  # Number of cache hits during session
    errors: List[str] = field(default_factory=list)


class GoLearnSession:
    """Time-bounded autonomous web learning session."""

    def __init__(self, topic: str, minutes: float, mode: str = "auto",
                 memory=None, bus=None, base_dir: str = "data/learn",
                 provider_name: str = "duckduckgo"):
        self.session_id = (
            f"learn_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        self.session_dir = Path(base_dir) / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.session = ResearchSession(
            id=self.session_id,
            topic=topic,
            mode=mode,
            start_ts=datetime.now().isoformat(timespec="seconds"),
            budget_minutes=minutes,
            provider=provider_name,
        )

        self.timer = TimeBudget(minutes)
        self.provider: SearchProvider = create_provider(self.session_dir, provider_name)
        self.brancher = SubtopicBrancher(topic, mode=mode)
        self.note_writer = NoteWriter(memory, bus=bus) if memory else None
        self.bus = bus
        self.memory = memory
        self.notes: List[Dict[str, Any]] = []
        # Low-yield tracking: abort after repeated empty/junk slices
        self._consecutive_empty = 0
        self._max_consecutive_empty = 3  # abort after this many in a row
        self._slice_failures: List[Dict[str, str]] = []  # per-slice failure log

        # Incremental learning: pre-seed visited topics from memory
        if memory:
            self._load_prior_progress(topic)

    def _query_local_knowledge(self, topic: str) -> List[Dict[str, Any]]:
        """Query local memory/evidence for existing knowledge about a topic."""
        if not self.memory:
            return []
        
        local_notes = []
        topic_lower = topic.lower()
        
        # Check memory facts for related content
        for key, value in self.memory.facts.items():
            key_lower = key.lower()
            # Match on topic keywords
            if any(word in key_lower for word in topic_lower.split()[:2]):
                # Extract just the topic label, not raw values with timestamps
                summary = key.split(":")[-1] if ":" in key else key
                local_notes.append({
                    "topic": key,
                    "summary": summary[:500] if summary else "",
                    "source": "local_memory",
                })
        
        return local_notes[:3]

    def _load_prior_progress(self, topic: str) -> None:
        """Load previously visited subtopics for this root topic from memory facts."""
        topic_key = topic.lower().replace(" ", "_")
        prior_visited = set()
        for key in self.memory.facts:
            if key.startswith(f"learn:{topic_key}:") or key.startswith(f"learn:{topic.lower()}:"):
                prior_visited.add(topic.lower())
            # Also check subtopic keys like "learn:python decorators:point_0"
            parts = key.split(":")
            if len(parts) >= 2 and parts[0] == "learn":
                subtopic = parts[1].lower()
                # Only count if it's related to our root topic
                root_words = set(topic.lower().split())
                sub_words = set(subtopic.split("_")) | set(subtopic.split())
                if root_words & sub_words:
                    prior_visited.add(subtopic.replace("_", " "))

        if prior_visited:
            self.brancher.visited.update(prior_visited)
            if self.bus:
                self.bus.emit("learn_resume", session_id=self.session_id,
                              prior_topics=len(prior_visited))

    def run(self) -> Dict[str, Any]:
        """Execute the learning loop. Returns session summary."""
        self.timer.start()

        if PULSE_AVAILABLE:
            pulse = get_pulse()
            pulse.emit_action(f"Learning about {self.session.topic}", "golearn")

        if self.bus:
            self.bus.emit("learn_start", topic=self.session.topic,
                          budget_minutes=self.session.budget_minutes,
                          mode=self.session.mode, session_id=self.session_id)

        try:
            while not self.timer.expired():
                # Abort early if too many consecutive empty slices
                if self._consecutive_empty >= self._max_consecutive_empty:
                    self.session.stop_reason = "low_yield"
                    if PULSE_AVAILABLE:
                        get_pulse().emit_warning("Not enough useful results found", "golearn")
                        get_pulse().add_blocker("GoLearn stopped: not enough useful results", "warning", "golearn")
                    if self.bus:
                        self.bus.emit("learn_abort", session_id=self.session_id,
                                      reason="low_yield",
                                      empty_streak=self._consecutive_empty)
                    break
                subtopic = self.brancher.pick_next()
                if subtopic is None:
                    self.session.stop_reason = "queue_exhausted"
                    if PULSE_AVAILABLE:
                        get_pulse().emit_warning("No more subtopics to explore", "golearn")
                    break
                try:
                    self._research_slice(subtopic)
                except Exception as slice_err:
                    self._slice_failures.append({
                        "subtopic": subtopic, "reason": "exception",
                        "detail": str(slice_err)[:200],
                    })
                    self._consecutive_empty += 1
                    if self.bus:
                        self.bus.emit("learn_error", session_id=self.session_id,
                                      subtopic=subtopic, error=str(slice_err))
                self._save_session()

            # Set stop_reason if not already set
            if self.session.stop_reason is None:
                if self.timer.expired():
                    self.session.stop_reason = "budget_exhausted"
                else:
                    self.session.stop_reason = "completed"
            self.session.status = "completed"
        except Exception as e:
            self.session.status = "failed"
            self.session.stop_reason = "exception"
            if self.bus:
                self.bus.emit("learn_error", session_id=self.session_id, error=str(e))

        # Finalize
        self.session.end_ts = datetime.now().isoformat(timespec="seconds")
        self.session.visited = list(self.brancher.visited)
        self.session.notes_count = len(self.notes)

        report_path = self.session_dir / "report.md"
        if self.note_writer:
            self.note_writer.generate_report(
                session_id=self.session_id,
                root_topic=self.session.topic,
                notes=self.notes,
                elapsed_seconds=self.timer.elapsed(),
                visited_topics=list(self.brancher.visited),
                report_path=report_path,
                provider=self.session.provider,
                provider_code=self.session.provider_code,
                provider_diagnostic=self.session.provider_diagnostic,
                stop_reason=self.session.stop_reason,
                accepted_sources=self.session.accepted_sources,
                useful_artifacts=self.session.useful_artifacts,
                cache_status=self.session.cache_status,
                cache_hits=self.session.cache_hits,
                providers_attempted=self.session.providers_attempted,
                provider_used=self.session.provider_used,
                provider_failures=self.session.provider_failures,
                result_origin=self.session.result_origin,
                accepted_sources_live=self.session.accepted_sources_live,
                accepted_sources_cached=self.session.accepted_sources_cached,
                useful_artifacts_live=self.session.useful_artifacts_live,
                useful_artifacts_cached=self.session.useful_artifacts_cached,
            )
        self._save_session()

        if self.bus:
            self.bus.emit("learn_done", session_id=self.session_id,
                          topics_explored=len(self.brancher.visited),
                          sources_fetched=len(self.session.artifacts),
                          notes_written=len(self.notes),
                          elapsed=self.timer.elapsed(),
                          report_path=str(report_path))

        summary = self._compact_summary()

        if PULSE_AVAILABLE:
            pulse = get_pulse()
            accepted = self.session.accepted_sources or 0
            useful = self.session.useful_artifacts or 0
            stop_reason = self.session.stop_reason or "unknown"
            provider_code = self.session.provider_code

            if stop_reason == "completed":
                pulse.emit_success(f"Learned about {self.session.topic} - {accepted} sources, {useful} useful", "golearn")
            elif stop_reason == "low_yield":
                pulse.emit_warning(f"Learning stopped early - not enough useful results", "golearn")
            elif stop_reason == "budget_exhausted":
                pulse.emit_result(f"Completed learning {self.session.topic} - time's up", "golearn")
            else:
                pulse.emit_result(f"Learning {self.session.topic} ended: {stop_reason}", "golearn")

            # Add blocker if provider failed
            if provider_code in ("provider_exhausted", "search_provider_blocked"):
                msg = translate_provider_code(provider_code)
                pulse.add_blocker(msg, "warning", "golearn")
                pulse.add_feed_me(
                    self.session.topic,
                    f"01_{self.session.topic.lower().replace(' ', '_')}/",
                    "docs,tutorials,examples",
                    f"Live search failed - need local {self.session.topic} docs",
                    urgency=3
                )

        return {
            "session": asdict(self.session),
            "report_path": str(report_path),
            "summary": summary,
        }

    # ── slice ─────────────────────────────────────────────────

    def _research_slice(self, subtopic: str) -> None:
        """Research a single subtopic: search, fetch, note, branch."""
        if self.bus:
            self.bus.emit("learn_slice", session_id=self.session_id,
                          subtopic=subtopic, time_remaining=self.timer.remaining())

        results, provider_diag = self.provider.search(subtopic, max_results=MAX_PAGES_PER_SLICE)
        
        # Track provider truth (PHASE 2)
        if provider_diag.details.get("providers_tried"):
            self.session.providers_attempted = provider_diag.details["providers_tried"]
        if provider_diag.details.get("provider_used"):
            self.session.provider_used = provider_diag.details["provider_used"]
        if provider_diag.details.get("provider_failures"):
            self.session.provider_failures = provider_diag.details["provider_failures"]
        
        self.session.provider_code = provider_diag.code
        self.session.provider_diagnostic = provider_diag.message
        
        # Track cache provenance (PHASE 3)
        result_origin = provider_diag.details.get("result_origin", "live")
        if self.session.result_origin is None:
            self.session.result_origin = result_origin
        elif self.session.result_origin != result_origin:
            self.session.result_origin = "mixed"
        
        if provider_diag.code == DiagnosticCode.CACHE_HIT:
            self.session.cache_hits += 1
            if self.session.cache_status is None:
                self.session.cache_status = "cache_hit"
            elif self.session.cache_status == "cache_miss":
                self.session.cache_status = "cache_partial"
            # Update cached counts
            self.session.accepted_sources_cached += len(results) if results else 0

        if not results:
            self._slice_failures.append({
                "subtopic": subtopic, 
                "reason": provider_diag.code,
                "diagnostic": provider_diag.message,
            })
            if provider_diag.code != DiagnosticCode.PROVIDER_OK and provider_diag.code != DiagnosticCode.CACHE_HIT:
                self.session.provider_diagnostic = provider_diag.message
            
            # Try local knowledge fallback when live search fails
            local_knowledge = self._query_local_knowledge(subtopic)
            if local_knowledge:
                for note in local_knowledge:
                    self.notes.append(note)
                self.session.accepted_sources += len(local_knowledge)
                self.session.accepted_sources_cached += len(local_knowledge)
                self.session.cache_status = "cache_partial"
                if self.session.result_origin is None:
                    self.session.result_origin = "cache"
                elif self.session.result_origin == "live":
                    self.session.result_origin = "mixed"
            
            if self.session.cache_status is None:
                self.session.cache_status = "cache_miss"
            if self.session.result_origin is None:
                self.session.result_origin = "live_failed"
            self._consecutive_empty += 1
            return

        # Got results - clear any previous provider diagnostic since search is working
        self.session.provider_diagnostic = None
        if provider_diag.code != DiagnosticCode.CACHE_HIT:
            self.session.provider_code = DiagnosticCode.PROVIDER_OK
            self.session.accepted_sources_live += len(results)
        else:
            self.session.accepted_sources_cached += len(results)

        artifacts: List[Dict[str, Any]] = []
        cache_fetch_count = 0
        live_fetch_count = 0
        for result in results[:MAX_PAGES_PER_SLICE]:
            if self.timer.expired():
                break
            fetch_timeout = min(15.0, self.timer.remaining() * 0.8)
            if fetch_timeout < 2.0:
                break
            artifact = self.provider.fetch(result.url, timeout=fetch_timeout)
            if artifact:
                if artifact.get("_cache_hit"):
                    cache_fetch_count += 1
                    self.session.fetched_pages_cached += 1
                else:
                    live_fetch_count += 1
                    self.session.fetched_pages_live += 1
                artifacts.append(artifact)
                self.session.artifacts.append(artifact["id"])
                self.session.fetched_pages += 1

        if cache_fetch_count > 0:
            self.session.cache_hits += cache_fetch_count
            if self.session.cache_status is None:
                self.session.cache_status = "cache_partial" if cache_fetch_count < len(artifacts) else "cache_hit"
            elif self.session.cache_status == "cache_miss":
                self.session.cache_status = "cache_partial"

        if not artifacts:
            self._slice_failures.append({"subtopic": subtopic, "reason": "fetch_failed"})
            self._consecutive_empty += 1
            return

        # Check if content is actually useful (not just boilerplate)
        total_text = sum(len(a.get("text", "")) for a in artifacts)
        if total_text < 200:
            self._slice_failures.append({"subtopic": subtopic, "reason": "empty_content"})
            self._consecutive_empty += 1
            return

        # Got useful content — reset empty streak and track useful artifacts (PHASE 4)
        self._consecutive_empty = 0
        # Separate live vs cached useful artifacts
        for a in artifacts:
            if a.get("_cache_hit"):
                self.session.useful_artifacts_cached += 1
            else:
                self.session.useful_artifacts_live += 1
        self.session.useful_artifacts += len(artifacts)
        self.session.accepted_sources += len(artifacts)

        if self.note_writer:
            note = self.note_writer.write_note(subtopic, artifacts, self.session_id)
            self.notes.append(note)

        texts = [a.get("text", "") for a in artifacts]
        new_topics = self.brancher.extract_and_enqueue(texts, subtopic)
        if self.bus and new_topics:
            self.bus.emit("branch_selected", session_id=self.session_id,
                          from_topic=subtopic, new_topics=new_topics)

    # ── persistence ───────────────────────────────────────────

    def _save_session(self) -> None:
        session_file = self.session_dir / "session.json"
        data = asdict(self.session)
        # Save brancher state for resume
        data["_queue"] = list(self.brancher.queue)
        data["_visited"] = list(self.brancher.visited)
        data["_failures"] = self._slice_failures[-20:]  # keep last 20
        session_file.write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    @classmethod
    def resume(cls, session_dir: str, memory=None, bus=None) -> Optional["GoLearnSession"]:
        """Resume an incomplete session from disk."""
        sdir = Path(session_dir)
        session_file = sdir / "session.json"
        if not session_file.exists():
            return None
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
        except Exception:
            return None
        if data.get("status") != "running":
            return None
        obj = cls(
            topic=data["topic"],
            minutes=data.get("budget_minutes", 5),
            mode=data.get("mode", "auto"),
            memory=memory,
            bus=bus,
            base_dir=str(sdir.parent),
        )
        # Restore brancher state
        obj.session_dir = sdir
        obj.session_id = data["id"]
        obj.session = ResearchSession(**{k: v for k, v in data.items() if not k.startswith("_")})
        if "_queue" in data:
            obj.brancher.queue = list(data["_queue"])
        if "_visited" in data:
            obj.brancher.visited = set(data["_visited"])
        return obj

    def _compact_summary(self) -> str:
        elapsed = self.timer.elapsed()
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        stop_reason = self.session.stop_reason
        if stop_reason == "low_yield":
            stop_note = " (stopped early: not enough useful results)"
        elif stop_reason == "queue_exhausted":
            stop_note = " (ran out of topics to explore)"
        elif stop_reason == "exception":
            stop_note = " (encountered an error)"
        else:
            stop_note = ""

        lines = [
            f"Finished learning about \"{self.session.topic}\".{stop_note}",
            f"Spent {time_str} exploring {len(self.brancher.visited)} subtopics across {len(self.session.artifacts)} sources.",
        ]

        # Show what was learned
        if self.notes:
            lines.append("")
            lines.append("What I learned:")
            for note in self.notes[:6]:
                summary = note.get("summary", "")
                if summary:
                    # Collapse whitespace, take first sentence
                    clean = " ".join(summary.split())
                    first = clean.split(". ")[0].strip()
                    if first and not first.endswith("."):
                        first += "."
                    if len(first) > 10:
                        lines.append(f"  - {note['topic']}: {first[:150]}")
                    else:
                        lines.append(f"  - {note['topic']}")
                else:
                    lines.append(f"  - {note['topic']}")
            if len(self.notes) > 6:
                lines.append(f"  ... and {len(self.notes) - 6} more topics.")

        lines.append(f"\nFull report: {self.session_dir / 'report.md'}")
        return "\n".join(lines)
