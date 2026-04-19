"""Local cache spine for GoLearn.

Provides file-based caching for:
- Search query results
- Fetched page content
- Provider diagnostic history
- Timestamps with TTL

Cache entries record:
- provider
- timestamp
- topic/query
- diagnostic state
- content
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from research.providers import SearchResult


DEFAULT_CACHE_TTL_HOURS = 24
CACHE_DIR = Path("data/learn_cache")


@dataclass
class CacheEntry:
    """Single cache entry for search or fetch results."""
    key: str
    provider: str
    query_or_url: str
    timestamp: str
    data: Dict[str, Any]
    diagnostic_code: str
    diagnostic_message: str
    ttl_hours: int = DEFAULT_CACHE_TTL_HOURS

    def is_stale(self) -> bool:
        """Check if cache entry is stale."""
        try:
            cached_time = datetime.fromisoformat(self.timestamp)
            age = datetime.now() - cached_time
            return age > timedelta(hours=self.ttl_hours)
        except Exception:
            return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "provider": self.provider,
            "query_or_url": self.query_or_url,
            "timestamp": self.timestamp,
            "data": self.data,
            "diagnostic_code": self.diagnostic_code,
            "diagnostic_message": self.diagnostic_message,
            "ttl_hours": self.ttl_hours,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CacheEntry:
        return cls(
            key=d["key"],
            provider=d["provider"],
            query_or_url=d["query_or_url"],
            timestamp=d["timestamp"],
            data=d["data"],
            diagnostic_code=d.get("diagnostic_code", ""),
            diagnostic_message=d.get("diagnostic_message", ""),
            ttl_hours=d.get("ttl_hours", DEFAULT_CACHE_TTL_HOURS),
        )


class GoLearnCache:
    """Local file-based cache for GoLearn search and fetch results."""

    def __init__(self, cache_dir: str = None):
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._search_index: Dict[str, CacheEntry] = {}
        self._fetch_index: Dict[str, CacheEntry] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Load cache index from disk."""
        index_file = self.cache_dir / "index.json"
        if not index_file.exists():
            return
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            self._search_index = {
                k: CacheEntry.from_dict(v) for k, v in data.get("search", {}).items()
            }
            self._fetch_index = {
                k: CacheEntry.from_dict(v) for k, v in data.get("fetch", {}).items()
            }
        except Exception:
            pass

    def _save_index(self) -> None:
        """Save cache index to disk."""
        index_file = self.cache_dir / "index.json"
        data = {
            "search": {k: v.to_dict() for k, v in self._search_index.items()},
            "fetch": {k: v.to_dict() for k, v in self._fetch_index.items()},
        }
        index_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _make_search_key(self, query: str, provider: str) -> str:
        """Generate cache key for search query."""
        normalized = query.lower().strip()
        combined = f"{provider}:{normalized}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _make_fetch_key(self, url: str, provider: str) -> str:
        """Generate cache key for fetched URL."""
        combined = f"{provider}:{url}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def get_search(self, query: str, provider: str = "duckduckgo") -> Tuple[Optional[List[SearchResult]], Optional[CacheEntry]]:
        """Get cached search results. Returns (results, cache_entry) tuple."""
        key = self._make_search_key(query, provider)
        entry = self._search_index.get(key)
        if entry is None:
            return None, None
        if entry.is_stale():
            del self._search_index[key]
            self._save_index()
            return None, None
        results = []
        for r in entry.data.get("results", []):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", ""),
                quality=r.get("quality", 0.5),
            ))
        return results, entry

    def put_search(self, query: str, provider: str, results: List[SearchResult],
                   diagnostic_code: str, diagnostic_message: str) -> CacheEntry:
        """Cache search results."""
        key = self._make_search_key(query, provider)
        entry = CacheEntry(
            key=key,
            provider=provider,
            query_or_url=query,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            data={"results": [{"title": r.title, "url": r.url, "snippet": r.snippet, "quality": r.quality} for r in results]},
            diagnostic_code=diagnostic_code,
            diagnostic_message=diagnostic_message,
        )
        self._search_index[key] = entry
        self._save_index()
        return entry

    def get_fetch(self, url: str, provider: str = "duckduckgo") -> Tuple[Optional[Dict[str, Any]], Optional[CacheEntry]]:
        """Get cached fetch result. Returns (artifact, cache_entry) tuple."""
        key = self._make_fetch_key(url, provider)
        entry = self._fetch_index.get(key)
        if entry is None:
            return None, None
        if entry.is_stale():
            del self._fetch_index[key]
            self._save_index()
            return None, None
        return entry.data, entry

    def put_fetch(self, url: str, provider: str, artifact: Dict[str, Any],
                  diagnostic_code: str = "", diagnostic_message: str = "") -> CacheEntry:
        """Cache fetch result."""
        key = self._make_fetch_key(url, provider)
        entry = CacheEntry(
            key=key,
            provider=provider,
            query_or_url=url,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            data=artifact,
            diagnostic_code=diagnostic_code,
            diagnostic_message=diagnostic_message,
        )
        self._fetch_index[key] = entry
        self._save_index()
        return entry

    def get_cache_status(self, query: str, url: str = None, provider: str = "duckduckgo") -> str:
        """Get cache status for a query or URL."""
        if url:
            key = self._make_fetch_key(url, provider)
            entry = self._fetch_index.get(key)
            if entry:
                return "cache_hit" if not entry.is_stale() else "cache_stale"
        if query:
            key = self._make_search_key(query, provider)
            entry = self._search_index.get(key)
            if entry:
                return "cache_hit" if not entry.is_stale() else "cache_stale"
        return "cache_miss"

    def has_useful_cache(self, query: str, provider: str = "duckduckgo") -> bool:
        """Check if there's useful (non-stale) cached search results."""
        results, entry = self.get_search(query, provider)
        return results is not None and len(results) > 0

    def clear_stale(self) -> Tuple[int, int]:
        """Clear stale cache entries. Returns (search_cleared, fetch_cleared)."""
        search_cleared = 0
        fetch_cleared = 0
        for key in list(self._search_index.keys()):
            if self._search_index[key].is_stale():
                del self._search_index[key]
                search_cleared += 1
        for key in list(self._fetch_index.keys()):
            if self._fetch_index[key].is_stale():
                del self._fetch_index[key]
                fetch_cleared += 1
        if search_cleared > 0 or fetch_cleared > 0:
            self._save_index()
        return search_cleared, fetch_cleared

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        stale_search = sum(1 for e in self._search_index.values() if e.is_stale())
        stale_fetch = sum(1 for e in self._fetch_index.values() if e.is_stale())
        return {
            "search_entries": len(self._search_index),
            "fetch_entries": len(self._fetch_index),
            "stale_search": stale_search,
            "stale_fetch": stale_fetch,
            "cache_dir": str(self.cache_dir),
        }


_global_cache: Optional[GoLearnCache] = None


def get_cache() -> GoLearnCache:
    """Get global cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = GoLearnCache()
    return _global_cache
