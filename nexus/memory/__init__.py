"""
Temporal-Intensity Memory System

Instead of just storing by vector similarity, each memory is weighted by:
- Recency: How recent (more recent = higher weight)
- Emotional Intensity: How significant (more intense = higher weight)
- Success Rate: How often similar tasks succeeded (higher = higher weight)

This creates a "memory that matters" rather than just "memory that matches".
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta
import time
import uuid
import json


@dataclass
class MemoryEntry:
    """A single memory with temporal-intensity weighting."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content: str = ""
    context: str = ""  # What task/situation triggered this
    outcome: str = ""  # success, failure, partial
    emotional_intensity: float = 0.5  # 0.0-1.0
    tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    success_count: int = 0
    attempt_count: int = 1
    
    def weight(self, now: float, decay_factor: float = 0.1) -> float:
        """Calculate the temporal-intensity weight."""
        # Time decay: older memories lose weight
        age_hours = (now - self.timestamp) / 3600
        recency = 1.0 / (1.0 + decay_factor * age_hours)
        
        # Success rate
        success_rate = (
            self.success_count / self.attempt_count 
            if self.attempt_count > 0 else 0.5
        )
        
        # Final weight = recency * emotional_intensity * success_rate
        return recency * (0.5 + 0.5 * self.emotional_intensity) * (0.5 + 0.5 * success_rate)
    
    def access(self):
        """Record an access to this memory."""
        self.access_count += 1
        self.last_accessed = time.time()
    
    def record_outcome(self, success: bool):
        """Record the outcome of this memory's pattern."""
        self.attempt_count += 1
        if success:
            self.success_count += 1


@dataclass
class MemorySnapshot:
    """A point-in-time snapshot of memory state."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    entries: list[MemoryEntry] = field(default_factory=list)
    key_insights: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class TemporalIntensityMemory:
    """Memory system with temporal-intensity weighting."""
    
    def __init__(self, max_entries: int = 1000):
        self.max_entries = max_entries
        self.entries: list[MemoryEntry] = []
        self.snapshots: list[MemorySnapshot] = []
    
    def add(
        self, content: str, context: str = "", outcome: str = "unknown",
        emotional_intensity: float = 0.5, tags: list[str] = None
    ) -> MemoryEntry:
        """Add a new memory entry."""
        entry = MemoryEntry(
            content=content,
            context=context,
            outcome=outcome,
            emotional_intensity=emotional_intensity,
            tags=tags or []
        )
        
        self.entries.append(entry)
        
        # Prune if needed
        if len(self.entries) > self.max_entries:
            self._prune()
        
        return entry
    
    def _prune(self):
        """Remove lowest-weighted memories."""
        now = time.time()
        # Sort by weight (ascending - keep worst, remove best)
        self.entries.sort(key=lambda e: e.weight(now))
        # Remove bottom 10%
        remove_count = max(1, len(self.entries) // 10)
        self.entries = self.entries[remove_count:]
    
    def recall(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Recall relevant memories, weighted by T-I."""
        now = time.time()
        
        # Score each entry
        scored = []
        for entry in self.entries:
            entry.access()
            # Simple text matching (would use embeddings in production)
            query_words = set(query.lower().split())
            entry_words = set(entry.content.lower().split())
            overlap = len(query_words & entry_words)
            
            if overlap > 0:
                text_score = overlap / max(len(query_words), len(entry_words))
                weight_score = entry.weight(now)
                final_score = 0.3 * text_score + 0.7 * weight_score
                scored.append((final_score, entry))
        
        # Return top k
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]
    
    def get_insights(self) -> list[str]:
        """Get key insights from memory."""
        now = time.time()
        insights = []
        
        # Recent failures
        recent_failures = [
            e for e in self.entries 
            if e.outcome == "failure" and (now - e.timestamp) < 86400 * 7
        ]
        if recent_failures:
            insights.append(f"Recent failures to learn from: {len(recent_failures)}")
        
        # High-intensity successes
        high_intensity = [
            e for e in self.entries
            if e.emotional_intensity > 0.7 and e.outcome == "success"
        ]
        if high_intensity:
            insights.append(f"High-impact successes: {len(high_intensity)}")
        
        # Success patterns
        if len(self.entries) > 10:
            success_rate = sum(1 for e in self.entries if e.outcome == "success") / len(self.entries)
            insights.append(f"Overall success rate: {success_rate:.0%}")
        
        return insights
    
    def create_snapshot(self, key_insights: list[str] = None) -> MemorySnapshot:
        """Create a snapshot of current memory state."""
        snapshot = MemorySnapshot(
            entries=list(self.entries),  # Copy
            key_insights=key_insights or self.get_insights()
        )
        self.snapshots.append(snapshot)
        return snapshot
    
    def save_to_file(self, filepath: str):
        """Save memory to file."""
        data = {
            "entries": [
                {
                    "id": e.id,
                    "content": e.content,
                    "context": e.context,
                    "outcome": e.outcome,
                    "emotional_intensity": e.emotional_intensity,
                    "tags": e.tags,
                    "timestamp": e.timestamp,
                    "success_count": e.success_count,
                    "attempt_count": e.attempt_count,
                }
                for e in self.entries
            ],
            "snapshots": [
                {
                    "id": s.id,
                    "key_insights": s.key_insights,
                    "timestamp": s.timestamp,
                }
                for s in self.snapshots
            ]
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load_from_file(self, filepath: str):
        """Load memory from file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        self.entries = [
            MemoryEntry(
                id=e["id"],
                content=e["content"],
                context=e["context"],
                outcome=e["outcome"],
                emotional_intensity=e["emotional_intensity"],
                tags=e["tags"],
                timestamp=e["timestamp"],
                success_count=e["success_count"],
                attempt_count=e["attempt_count"],
            )
            for e in data.get("entries", [])
        ]
    
    def summary(self) -> str:
        """Get a summary of memory state."""
        now = time.time()
        total_weight = sum(e.weight(now) for e in self.entries)
        
        return (
            f"Memory: {len(self.entries)} entries, "
            f"{len(self.snapshots)} snapshots, "
            f"total weight: {total_weight:.2f}"
        )
