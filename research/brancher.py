"""SubtopicBrancher — choose next subtopic based on concepts found in fetched content.

No LLM needed. Uses n-gram frequency + keyword pattern scoring.
"""

import re
from collections import Counter
from typing import Dict, List, Optional, Set

SIGNAL_PATTERNS = [
    r"\b(?:how to|implement|build|deploy|configure|setup|install)\b",
    r"\b(?:algorithm|protocol|architecture|framework|library|api)\b",
    r"\b(?:vs\.?|versus|compared to|alternative)\b",
    r"\b(?:best practices?|tutorial|guide|example)\b",
    # Programming-specific signals
    r"\b(?:error|exception|traceback|bug|fix|debug|stacktrace)\b",
    r"\b(?:function|method|class|module|package|decorator|async)\b",
    r"\b(?:pattern|design pattern|singleton|factory|observer)\b",
    r"\b(?:testing|unittest|pytest|assert|mock|fixture)\b",
    r"\b(?:performance|optimization|profiling|benchmark|memory leak)\b",
    r"\b(?:documentation|docstring|type hint|annotation)\b",
    r"\b(?:syntax|parsing|ast|compile|interpret|runtime)\b",
    r"\b(?:database|sql|query|orm|migration|schema)\b",
    r"\b(?:http|rest|websocket|endpoint|request|response)\b",
]

# Low-value patterns that should be penalized
LOW_VALUE_PATTERNS = [
    r"\b(?:click here|read more|sign up|log in|subscribe)\b",
    r"\b(?:follow us|share this|advertisement|sponsored)\b",
    r"\b(?:copyright|all rights reserved|terms of service)\b",
    r"^\s*(?:home|about|contact|faq|menu|search)\s*$",
]

# Minimum score threshold - topics below this are discarded
MIN_QUALITY_THRESHOLD = 1.0

# Maximum queue size to prevent runaway growth
MAX_QUEUE_SIZE = 50

STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "about", "between", "under", "above", "this",
    "that", "these", "those", "it", "its", "or", "and", "but", "not",
    "no", "so", "if", "than", "too", "very", "just", "also", "more",
    "other", "some", "such", "only", "same", "then", "when", "which",
    "who", "how", "what", "where", "why", "all", "each", "every",
    "both", "few", "many", "most", "own", "new", "first", "last",
    "long", "great", "little", "right", "big", "high", "old", "well",
}


VARIATION_SUFFIXES = [
    "tutorial", "examples", "best practices", "common mistakes",
    "advanced", "beginner guide", "how it works", "alternatives",
    "use cases", "troubleshooting", "performance", "comparison",
    "real world", "cheat sheet", "deep dive",
]

REPHRASE_TEMPLATES = [
    "what is {topic}",
    "how to use {topic}",
    "{topic} explained simply",
    "learn {topic} from scratch",
    "{topic} tips and tricks",
    "why use {topic}",
    "{topic} vs alternatives",
    "getting started with {topic}",
    "{topic} practical examples",
    "common {topic} problems",
]


class SubtopicBrancher:
    """Choose next subtopic based on concepts found in fetched content."""

    def __init__(self, root_topic: str, mode: str = "auto"):
        self.root_topic = root_topic
        self.mode = mode
        self.visited: Set[str] = set()
        self.queue: List[str] = [root_topic]
        self._depth_level = 0
        self._variation_idx = 0
        self._rephrase_idx = 0

    def pick_next(self) -> Optional[str]:
        """Return next subtopic to research, or None if truly exhausted."""
        while self.queue:
            topic = self.queue.pop(0)
            normalized = topic.lower().strip()
            if normalized not in self.visited:
                self.visited.add(normalized)
                return topic
        # Queue empty — try suffix variations first, then rephrased queries
        v = self._next_variation()
        if v:
            return v
        return self._next_rephrase()

    def _next_variation(self) -> Optional[str]:
        """Generate a new search variation of the root topic."""
        while self._variation_idx < len(VARIATION_SUFFIXES):
            suffix = VARIATION_SUFFIXES[self._variation_idx]
            self._variation_idx += 1
            variation = f"{self.root_topic} {suffix}"
            normalized = variation.lower().strip()
            if normalized not in self.visited:
                self.visited.add(normalized)
                return variation
        return None

    def _next_rephrase(self) -> Optional[str]:
        """Generate rephrased search queries when suffixes are exhausted."""
        while self._rephrase_idx < len(REPHRASE_TEMPLATES):
            template = REPHRASE_TEMPLATES[self._rephrase_idx]
            self._rephrase_idx += 1
            query = template.format(topic=self.root_topic)
            normalized = query.lower().strip()
            if normalized not in self.visited:
                self.visited.add(normalized)
                return query
        return None

    def extract_and_enqueue(self, texts: List[str], current_topic: str) -> List[str]:
        """Extract subtopics from fetched texts and add to queue.
        Returns list of newly added subtopics.
        """
        # Early exit if queue is getting too large
        if len(self.queue) >= MAX_QUEUE_SIZE:
            return []
        
        candidates = self._extract_candidates(texts, current_topic)
        scored = self._score_candidates(candidates)

        # Filter by minimum quality threshold
        scored = [(t, s) for t, s in scored if s >= MIN_QUALITY_THRESHOLD]

        if self.mode == "depth":
            top = scored[:2]
        elif self.mode == "breadth":
            top = scored[:4]
        else:  # auto
            n = 3 if self._depth_level < 3 else 2
            top = scored[:n]

        new_topics: List[str] = []
        for topic, _score in top:
            # Skip if queue is full
            if len(self.queue) >= MAX_QUEUE_SIZE:
                break
            normalized = topic.lower().strip()
            if normalized not in self.visited and topic not in self.queue:
                self.queue.append(topic)
                new_topics.append(topic)

        self._depth_level += 1
        return new_topics

    def _extract_candidates(self, texts: List[str], current_topic: str) -> List[str]:
        combined = " ".join(texts)
        bigrams = self._extract_ngrams(combined, 2)
        trigrams = self._extract_ngrams(combined, 3)

        root_words = set(self.root_topic.lower().split())
        current_words = set(current_topic.lower().split())

        candidates: List[str] = []
        for phrase in bigrams + trigrams:
            phrase_words = set(phrase.lower().split())
            if phrase_words == root_words or phrase_words == current_words:
                continue
            if phrase_words & (root_words | current_words):
                candidates.append(phrase)
            elif any(re.search(p, phrase, re.IGNORECASE) for p in SIGNAL_PATTERNS):
                candidates.append(phrase)
        return candidates

    def _extract_ngrams(self, text: str, n: int) -> List[str]:
        words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]+\b", text)
        words = [w for w in words if w.lower() not in STOP_WORDS and len(w) > 2]

        ngrams: Counter = Counter()
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i : i + n])
            if len(gram) > 6:
                ngrams[gram] += 1

        seen: Set[str] = set()
        result: List[str] = []
        for gram, _count in ngrams.most_common(30):
            key = gram.lower()
            if key not in seen:
                seen.add(key)
                result.append(gram)
        return result

    def _word_overlap_ratio(self, a: set, b: set) -> float:
        """Jaccard similarity between two word sets."""
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _score_candidates(self, candidates: List[str]) -> List[tuple]:
        root_words = set(self.root_topic.lower().split())
        scored: List[tuple] = []

        for candidate in candidates:
            score = 0.0
            cand_words = set(candidate.lower().split())

            # Strong boost for root topic overlap
            overlap = len(cand_words & root_words)
            score += overlap * 3.0

            # Boost for programming signals
            for pattern in SIGNAL_PATTERNS:
                if re.search(pattern, candidate, re.IGNORECASE):
                    score += 3.0
                    break

            # Penalize low-value patterns
            for pattern in LOW_VALUE_PATTERNS:
                if re.search(pattern, candidate, re.IGNORECASE):
                    score -= 5.0
                    break

            # Penalize near-duplicates of visited topics (not just exact matches)
            max_sim = 0.0
            for visited in self.visited:
                sim = self._word_overlap_ratio(cand_words, set(visited.split()))
                if sim > max_sim:
                    max_sim = sim
            if max_sim >= 1.0:
                score -= 15.0  # exact duplicate
            elif max_sim >= 0.5:
                score -= 8.0  # near-duplicate (>= 50% overlap)
            elif max_sim >= 0.3:
                score -= 3.0  # moderately similar

            # Also penalize near-duplicates of other candidates already in queue
            for queued in self.queue:
                sim = self._word_overlap_ratio(cand_words, set(queued.lower().split()))
                if sim >= 0.75:
                    score -= 3.0
                    break

            # Penalize very short phrases
            if len(cand_words) < 2:
                score -= 2.0

            # Penalize generic/common phrases that aren't specific
            generic_words = {"introduction", "overview", "summary", "basic", "info", "information"}
            if cand_words & generic_words and overlap < 2:
                score -= 2.0

            scored.append((candidate, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def get_state(self) -> Dict:
        return {
            "root_topic": self.root_topic,
            "mode": self.mode,
            "visited": list(self.visited),
            "queue": list(self.queue),
            "depth_level": self._depth_level,
        }
