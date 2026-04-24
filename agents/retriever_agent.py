"""Retriever Agent - Searches local knowledge and memory.

This agent is a functional role, NOT a personality.
It searches local knowledge, memory, artifacts, and ingested data.
"""

from __future__ import annotations

from typing import Any, Dict, List
import time

from agents.base_agent import (
    BaseAgent,
    AgentCapabilities,
    AgentContext,
    AgentResult,
    AgentStatus,
)


class RetrieverAgent(BaseAgent):
    """Searches local knowledge, memory, and artifacts.

    Retrieves information from Karma's memory systems without
    requiring external model access.
    """

    def __init__(self):
        super().__init__("retriever", "retriever")
        self._capabilities = AgentCapabilities(
            can_retrieve=True,
            requires_model=False,
            deterministic_fallback=True,
            tags=["retrieval", "search", "memory"],
        )
        self._status = AgentStatus.READY

    def get_capabilities(self) -> AgentCapabilities:
        return self._capabilities

    def run(self, context: AgentContext) -> AgentResult:
        """Search for relevant information — embedding-based if model available.

        Recent-task queries (e.g. "what just ran", "last failure") get run_history
        facts prepended before general retrieval so operational history surfaces first.

        Recovery-linked queries (e.g. "what happened after the failure") get
        linked parent+recovery results when recovery was attempted.
        """
        start_time = time.time()
        try:
            task = context.task
            input_data = context.input_data or {}
            memory = context.memory
            retrieval = context.retrieval
            query = input_data.get("query", task)
            limit = input_data.get("limit", 8)

            # Recent-task pre-pass: inject run_history facts first when query is
            # clearly about recent execution history.
            run_history_prefix: List[Dict[str, Any]] = []
            is_recovery_linked = self._is_recovery_linked_query(query)
            is_path_query = self._is_path_query(query)

            if is_recovery_linked or (is_path_query and self._is_recovery_linked_query(query)):
                # Use linked retrieval for recovery/path queries with recovery signal
                run_history_prefix = self._retrieve_linked_run_history(memory, limit)
            elif self._is_recent_task_query(query) or is_path_query:
                # Recent-run or path-only query — plain run_history lookup
                run_history_prefix = self._run_history_lookup(memory, limit)

            # Embedding path
            embed_adapter = self._get_embed_adapter()
            general_results: List[Dict[str, Any]] = []
            if embed_adapter:
                # Attempt bootstrap on first embedding call if index is empty
                if not RetrieverAgent._cache_loaded:
                    import os

                    path = RetrieverAgent._get_index_path()
                    if not os.path.exists(path) or os.path.getsize(path) < 1000:
                        RetrieverAgent.bootstrap_index(embed_adapter)
                general_results = self._embed_search(
                    query, memory, retrieval, embed_adapter, limit
                )
            else:
                general_results = self._keyword_search(query, memory, retrieval, limit)

            # Merge: run_history first, then general (dedup by key)
            results = self._merge_with_prefix(
                run_history_prefix, general_results, limit
            )

            method = "embedding" if embed_adapter else "keyword"
            if run_history_prefix:
                method = f"run_history+{method}"
            if is_recovery_linked:
                method = f"recovery_linked+{method}"

            if results or run_history_prefix:
                return AgentResult(
                    success=True,
                    output={
                        "query": query,
                        "results": results,
                        "count": len(results),
                        "method": method,
                    },
                    used_model=self.role_name if embed_adapter else None,
                    execution_time_ms=(time.time() - start_time) * 1000,
                )

            # Nothing found — return empty success (not an error)
            return AgentResult(
                success=True,
                output={
                    "query": query,
                    "results": [],
                    "count": 0,
                    "method": method,
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            self._last_error = str(e)
            self._record_execution(False)
            return AgentResult(
                success=False,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    # ── recent-task intent detection ─────────────────────────────────────────

    # Tokens that suggest the query is about recent execution history.
    # Matched as substrings in lower-cased query.
    _RECENT_TASK_TRIGGERS = (
        "just did",
        "just ran",
        "just happened",
        "just completed",
        "just finished",
        "last run",
        "last task",
        "last job",
        "last execution",
        "last shell",
        "what happened",
        "what ran",
        "what did karma",
        "what did you do",
        "what was run",
        "what just",
        "what failed",
        "what succeeded",
        "failed recently",
        "recent failure",
        "recent error",
        "recent run",
        "run history",
        "most recent",
        "previous run",
        "prior run",
        "earlier today",
        "recovery attempt",
        "last time karma",
        "what was the last",
        "show me the run",
        "show last run",
    )

    # Tokens that suggest recovery-linked query — these trigger linked mode.
    _RECOVERY_LINK_TRIGGERS = (
        "recovery",
        "recovered",
        "failed run",
        "after failure",
        "what happened after",
        "recovery attempt",
        "show the recovery",
        "what did recovery do",
        "what happened in the failed",
        "last recovery",
        "latest recovery",
        "most recent recovery",
        "show recovery",
        "recovery run",
        "the recovery",
    )

    @classmethod
    def _is_recovery_linked_query(cls, query: str) -> bool:
        """Return True if query is about a failed run and its recovery.

        Uses anti-tokens veto first, then recovery trigger match.
        """
        q = query.lower().strip()
        # Anti-tokens: general queries that mention recovery but aren't about it
        for anti in ("architecture", "how does", "explain the", "design of"):
            if anti in q:
                return False
        # Recovery triggers
        for trigger in cls._RECOVERY_LINK_TRIGGERS:
            if trigger in q:
                return True
        return False

    # Tokens that suggest a query about which files/paths were touched by a run.
    _PATH_QUERY_TRIGGERS = (
        "files touched", "paths touched", "files involved", "paths involved",
        "files affected", "paths affected", "what files", "which files",
        "what file", "which file", "files changed", "files modified",
        "paths changed", "paths modified", "what was modified",
        "what was changed", "what did it modify", "what did it change",
        "files in the run", "paths in the run",
        "files in the failed", "paths in the failed",
        "files during", "paths during",
        "what to review", "what should i review", "files to review",
        "what to inspect", "files to inspect", "review targets",
        "top files", "which files to look", "what files to look",
        "files to look at", "paths to look at",
    )

    @classmethod
    def _is_path_query(cls, query: str) -> bool:
        """Return True when query is asking about files/paths touched by a run.

        Uses the same anti-token veto as other classifiers.
        """
        q = query.lower().strip()
        for anti in cls._RECENT_TASK_ANTITOKENS:
            if anti in q:
                return False
        for trigger in cls._PATH_QUERY_TRIGGERS:
            if trigger in q:
                return True
        return False

    @staticmethod
    def _retrieve_linked_run_history(memory, limit: int) -> List[Dict[str, Any]]:
        """Return linked parent + recovery child when present.

        If parent has recovery_run_id or child has parent_run_id,
        returns them together in a linked structure for recovery queries.
        Result shape when linked:
          result["linked"] = {"kind": "linked_run_history", "parent": {...}, "recovery": {...}}
        """
        if not memory or not hasattr(memory, "facts"):
            return []

        # Collect all run_history entries as (key, outer_val) — topic lives on outer
        raw_entries = []
        for key, val in memory.facts.items():
            if not isinstance(val, dict):
                continue
            if val.get("topic") == "run_history":
                raw_entries.append((key, val))

        if not raw_entries:
            return []

        # Sort newest first using outer last_updated (set by save_fact)
        raw_entries.sort(key=lambda x: x[1].get("last_updated", ""), reverse=True)

        # Pre-build key→inner dict for O(1) child/parent resolution
        by_key: Dict[str, Any] = {
            key: outer.get("value", outer) for key, outer in raw_entries
        }

        results: List[Dict[str, Any]] = []
        processed: set = set()
        seen_run_ids: set = set()

        for key, outer_val in raw_entries:
            if key in processed:
                continue
            processed.add(key)
            inner_val = outer_val.get("value", outer_val)
            # Deduplicate by run_id (run:last mirrors the most recent run:<hash8>)
            run_id = inner_val.get("run_id") if isinstance(inner_val, dict) else None
            if run_id and run_id in seen_run_ids:
                continue
            if run_id:
                seen_run_ids.add(run_id)

            run_kind = inner_val.get("run_kind", "primary")
            recovery_run_id = inner_val.get("recovery_run_id")
            parent_run_id = inner_val.get("parent_run_id")

            result: Dict[str, Any] = {
                "source": "run_history",
                "key": key,
                "value": inner_val,
                "topic": "run_history",
            }

            # Parent with known recovery child — link them
            if run_kind == "primary" and recovery_run_id and recovery_run_id in by_key:
                result["linked"] = {
                    "kind": "linked_run_history",
                    "parent": inner_val,
                    "recovery": by_key[recovery_run_id],
                }
                processed.add(recovery_run_id)

            # Recovery child surfaced first — resolve parent if available
            elif run_kind == "recovery" and parent_run_id and parent_run_id not in processed:
                parent_outer = memory.facts.get(parent_run_id)
                if parent_outer and isinstance(parent_outer, dict):
                    parent_inner = parent_outer.get("value", parent_outer)
                    result["linked"] = {
                        "kind": "linked_run_history",
                        "parent": parent_inner,
                        "recovery": inner_val,
                    }
                    processed.add(parent_run_id)

            results.append(result)

            if len(results) >= limit:
                break

        return results

    # Tokens that override triggers — general/architectural queries that happen
    # to contain trigger words (e.g. "explain the recent architecture refactor").
    _RECENT_TASK_ANTITOKENS = (
        "architecture",
        "how does",
        "explain the",
        "what is karma",
        "summarize the project",
        "describe the",
        "design of",
        "recent changes to the code",
        "recent commit",
        "recent version",
        "history of the",
        "git history",
    )

    @classmethod
    def _is_recent_task_query(cls, query: str) -> bool:
        """Return True when query is clearly about recent execution history.

        Uses a two-phase check: anti-tokens veto first, then trigger match.
        Deterministic and fast — no model needed.
        """
        q = query.lower().strip()
        for anti in cls._RECENT_TASK_ANTITOKENS:
            if anti in q:
                return False
        for trigger in cls._RECENT_TASK_TRIGGERS:
            if trigger in q:
                return True
        return False

    @staticmethod
    def _run_history_lookup(memory, limit: int) -> List[Dict[str, Any]]:
        """Return facts with topic='run_history' sorted by recency (newest first).

        Returns at most `limit` entries. Empty list if memory absent or no
        run_history facts exist.
        """
        if not memory or not hasattr(memory, "facts"):
            return []
        entries = []
        for key, val in memory.facts.items():
            if not isinstance(val, dict):
                continue
            if val.get("topic") == "run_history":
                entries.append((key, val))
        # Sort newest first (run:<hash> written after run:last → slightly newer timestamp)
        entries.sort(key=lambda x: x[1].get("last_updated", ""), reverse=True)
        # Deduplicate by run_id: run:last and run:<hash8> share the same run_id.
        # Since run:<hash8> is written microseconds after run:last, it sorts first.
        # When we encounter run:last with the same run_id, it is skipped.
        seen_run_ids: set = set()
        results = []
        for key, val in entries:
            inner = val.get("value", val)
            run_id = inner.get("run_id") if isinstance(inner, dict) else None
            if run_id and run_id in seen_run_ids:
                continue
            if run_id:
                seen_run_ids.add(run_id)
            results.append({
                "source": "run_history",
                "key": key,
                "value": inner,
                "topic": "run_history",
            })
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _merge_with_prefix(
        prefix: List[Dict[str, Any]],
        general: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Merge prefix results with general results, deduplicating by key."""
        seen = {r.get("key") for r in prefix if r.get("key")}
        tail = [r for r in general if r.get("key") not in seen]
        return (prefix + tail)[:limit]

    def _get_embed_adapter(self):
        """Get the assigned embedding adapter."""
        try:
            from core.agent_model_manager import get_agent_model_manager
            from core.slot_manager import get_slot_manager

            sm = get_slot_manager()
            assignment = sm.get_role_assignment("retriever")
            if not assignment or not assignment.assigned_model_id:
                return None
            mgr = get_agent_model_manager()
            adapter = mgr._models.get(assignment.assigned_model_id)
            if adapter is None:
                return None
            if not adapter.is_loaded:
                adapter.load()
            return adapter if adapter.is_loaded else None
        except Exception:
            return None

    # In-process cache: {md5_hex: list[float]}
    _embed_cache: dict = {}
    _cache_loaded = False
    _index_path: str = ""

    # ── persistent index ────────────────────────────────────────

    @classmethod
    def _get_index_path(cls) -> str:
        if not cls._index_path:
            import os

            base = os.path.join(os.path.dirname(__file__), "..", "data")
            cls._index_path = os.path.normpath(os.path.join(base, "embed_index.db"))
        return cls._index_path

    @classmethod
    def _ensure_db(cls):
        import sqlite3
        import os

        path = cls._get_index_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE IF NOT EXISTS vectors "
            "(key TEXT PRIMARY KEY, vector BLOB, updated_at REAL, meta TEXT)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS bootstrap_log "
            "(bootstrapped_at REAL, item_count INTEGER)"
        )
        con.commit()
        return con

    @classmethod
    def bootstrap_index(cls, adapter):
        """Bootstrap persistent index with project structure for cold-start."""
        import os
        import time

        if not adapter:
            return False

        # Check if already bootstrapped
        con = cls._ensure_db()
        log = con.execute("SELECT MAX(bootstrapped_at) FROM bootstrap_log").fetchone()
        if log and log[0]:
            con.close()
            return False  # Already bootstrapped

        root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        skip = {
            "__pycache__",
            ".git",
            "node_modules",
            ".venv",
            "venv",
            "data",
            "docs",
            "ml_models",
            "logs",
            ".pytest_cache",
        }

        items_embedded = 0
        items = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in skip and not d.startswith(".")
            ]
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > 2:
                continue

            for fn in filenames:
                if fn.startswith("."):
                    continue
                path = os.path.join(rel, fn) if rel != "." else fn
                ext = os.path.splitext(fn)[1]
                if ext in (".py", ".js", ".ts", ".json", ".md", ".txt"):
                    items.append(path)

        for item in items:
            try:
                # Prefer embedding file contents for richer vectors. Fall back to
                # embedding the path string when file read or embedding fails.
                full = os.path.join(root, item) if not os.path.isabs(item) else item
                content = None
                try:
                    with open(full, 'r', encoding='utf-8', errors='ignore') as fh:
                        content = fh.read(8192)  # limit read size
                except Exception:
                    content = None
                if content:
                    vec = adapter.embed(content)
                else:
                    vec = adapter.embed(item)
                cls._persist_vector(item, vec, meta="bootstrap")
                items_embedded += 1
            except Exception:
                # keep going on any embed failure
                pass

        con.execute(
            "INSERT INTO bootstrap_log VALUES (?, ?)", (time.time(), items_embedded)
        )
        con.commit()
        con.close()
        return items_embedded > 0

    # TTL / eviction policy
    _EMBED_TTL_DAYS: float = 30.0  # non-bootstrap rows older than this are evicted
    _EMBED_MAX_ROWS: int = 5000  # hard cap; evict oldest non-bootstrap rows first
    _EVICT_EVERY_N_WRITES: int = 200  # run eviction after this many writes
    _write_counter: int = 0  # class-level write counter

    @classmethod
    def _evict_stale(cls):
        """Remove expired or excess non-bootstrap vectors from the persistent index.

        Rules:
        - Bootstrap rows (meta contains 'bootstrap') are never evicted.
        - Rows older than _EMBED_TTL_DAYS are evicted.
        - If remaining rows exceed _EMBED_MAX_ROWS, evict oldest first.
        Evicted keys are also removed from the in-process cache.
        """
        import sqlite3
        import time as _t

        cutoff = _t.time() - cls._EMBED_TTL_DAYS * 86400
        try:
            con = sqlite3.connect(cls._get_index_path())
            # TTL eviction: drop non-bootstrap rows older than cutoff
            stale = [
                r[0]
                for r in con.execute(
                    "SELECT key FROM vectors WHERE updated_at < ? AND (meta IS NULL OR meta NOT LIKE '%bootstrap%')",
                    (cutoff,),
                )
            ]
            if stale:
                con.executemany(
                    "DELETE FROM vectors WHERE key = ?", [(k,) for k in stale]
                )
                for k in stale:
                    cls._embed_cache.pop(k, None)

            # Cap eviction: if still over max, remove oldest non-bootstrap rows
            total = con.execute(
                "SELECT COUNT(*) FROM vectors WHERE meta IS NULL OR meta NOT LIKE '%bootstrap%'"
            ).fetchone()[0]
            if total > cls._EMBED_MAX_ROWS:
                overflow = total - cls._EMBED_MAX_ROWS
                excess = [
                    r[0]
                    for r in con.execute(
                        "SELECT key FROM vectors WHERE (meta IS NULL OR meta NOT LIKE '%bootstrap%') "
                        "ORDER BY updated_at ASC LIMIT ?",
                        (overflow,),
                    )
                ]
                if excess:
                    con.executemany(
                        "DELETE FROM vectors WHERE key = ?", [(k,) for k in excess]
                    )
                    for k in excess:
                        cls._embed_cache.pop(k, None)

            con.commit()
            con.close()
        except Exception:
            pass

    @classmethod
    def _load_persistent_cache(cls):
        """Load all persisted vectors into _embed_cache on first use."""
        if cls._cache_loaded:
            return
        cls._cache_loaded = True
        try:
            import sqlite3
            import struct

            con = sqlite3.connect(cls._get_index_path())
            for row in con.execute("SELECT key, vector FROM vectors"):
                k, blob = row
                n = len(blob) // 4
                cls._embed_cache[k] = list(struct.unpack(f"{n}f", blob))
            con.close()
        except Exception:
            pass

    @classmethod
    def _persist_vector(cls, key: str, vec: list, meta: str = ""):
        """Write one vector to the persistent DB and trigger periodic eviction."""
        try:
            import struct
            import time as _t
            import json

            blob = struct.pack(f"{len(vec)}f", *vec)
            con = cls._ensure_db()
            con.execute(
                "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)",
                (key, blob, _t.time(), json.dumps({"source": meta}) if meta else None),
            )
            con.commit()
            con.close()
            cls._write_counter += 1
            if cls._write_counter % cls._EVICT_EVERY_N_WRITES == 0:
                cls._evict_stale()
        except Exception:
            pass

    def _embed_cached(self, text: str, adapter) -> list:
        """Embed with persistent SQLite-backed cache (survives restarts)."""
        import hashlib

        RetrieverAgent._load_persistent_cache()
        key = hashlib.md5(text.encode()).hexdigest()
        if key not in RetrieverAgent._embed_cache:
            vec = adapter.embed(text)
            RetrieverAgent._embed_cache[key] = vec
            RetrieverAgent._persist_vector(key, vec)
        return RetrieverAgent._embed_cache[key]

    def _embed_search(self, query: str, memory, retrieval, adapter, limit: int):
        """Cosine-similarity search over memory facts with embedding cache."""
        import math

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            ma = math.sqrt(sum(x * x for x in a))
            mb = math.sqrt(sum(x * x for x in b))
            return dot / (ma * mb) if ma and mb else 0.0

        try:
            q_vec = self._embed_cached(query[:300], adapter)
        except Exception:
            return []

        scored = []
        if memory and hasattr(memory, "facts"):
            items = list(memory.facts.items())[
                :500
            ]  # expanded; cache absorbs repeat cost
            for key, val in items:
                doc = (
                    f"{key}: {val}"
                    if not isinstance(val, dict)
                    else f"{key}: {val.get('value', val)}"
                )
                try:
                    d_vec = self._embed_cached(doc[:300], adapter)
                    sim = cosine(q_vec, d_vec)
                    scored.append(
                        (
                            sim,
                            {
                                "source": "facts",
                                "key": key,
                                "value": val,
                                "score": round(sim, 3),
                            },
                        )
                    )
                except Exception:
                    continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for sim, r in scored[:limit] if sim > 0.4]

    def _keyword_search(self, query: str, memory, retrieval, limit: int):
        """Fallback keyword search."""
        results = []
        if memory and hasattr(memory, "facts"):
            q_low = query.lower()
            for key, val in memory.facts.items():
                if q_low in key.lower() or q_low in str(val).lower():
                    results.append({"source": "facts", "key": key, "value": val})
                    if len(results) >= limit:
                        break
        if retrieval:
            try:
                for ev in retrieval.retrieve_context_bundle(query, "respond")[:limit]:
                    results.append(
                        {
                            "source": "retrieval_bus",
                            "value": str(ev.value)[:200],
                            "relevance": round(ev.relevance, 3),
                        }
                    )
            except Exception:
                pass
        return results


def create_retriever_agent() -> RetrieverAgent:
    """Factory function to create retriever agent."""
    return RetrieverAgent()
