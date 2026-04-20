"""Retrieval Bus — unified context retrieval across memory strata.

Modes: parse, plan, execute, respond, reflect, repair
Returns structured evidence bundles that influence agent behavior.

v2: Shape-aware retrieval — uses intent, entity types, domain, and
    tool family for matching instead of pure word overlap.
"""

from __future__ import annotations
import json
from collections import defaultdict, OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.evidence_score import score_evidence, extract_shape, shape_similarity, _recency_score
from storage.persistence import atomic_write_text

# Per-mode bundle size limits (from IFO spec)
_MODE_LIMITS = {
    "parse": 5,
    "plan": 7,
    "execute": 5,
    "respond": 7,
    "reflect": 5,
    "repair": 5,
}


class EvidenceItem:
    """Single piece of retrieved evidence."""
    __slots__ = ("type", "value", "confidence", "relevance", "recency",
                 "source", "effect_hint")

    def __init__(self, type: str, value: Any, confidence: float, relevance: float,
                 source: str, effect_hint: str = "", recency: float = 0.5):
        self.type = type
        self.value = value
        self.confidence = confidence
        self.relevance = relevance
        self.recency = recency
        self.source = source
        self.effect_hint = effect_hint

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type, "value": self.value,
            "confidence": self.confidence, "relevance": round(self.relevance, 3),
            "recency": round(self.recency, 3),
            "source": self.source, "effect_hint": self.effect_hint,
        }


class RetrievalBus:
    """Retrieve context bundles from memory strata for different agent phases."""

    def __init__(self, memory, capability_map=None, data_dir: str = "data"):
        self._memory = memory
        self._cap_map = capability_map
        self._data_dir = Path(data_dir)
        # Workflow cache
        self._workflows_file = self._data_dir / "workflows.json"
        self._workflows: List[Dict[str, Any]] = self._load_json(self._workflows_file, [])
        # Failure fingerprints
        self._failures_file = self._data_dir / "failure_fingerprints.json"
        self._failures: List[Dict[str, Any]] = self._load_json(self._failures_file, [])
        # Concept crystals
        self._crystals_file = self._data_dir / "concept_crystals.json"
        self._crystals: List[Dict[str, Any]] = self._load_json(self._crystals_file, [])
        # Health memory
        self._health_file = self._data_dir / "health_memory.json"
        self._health: List[Dict[str, Any]] = self._load_json(self._health_file, [])
        # Procedure memory (reusable multi-step sequences)
        self._procedures_file = self._data_dir / "procedures.json"
        self._procedures: List[Dict[str, Any]] = self._load_json(self._procedures_file, [])
        # Retrieval metrics
        self._metrics: Dict[str, int] = defaultdict(int)
        # In-memory bundle cache to avoid recomputing identical retrievals every turn
        self._bundle_cache: OrderedDict[Tuple[Any, ...], List[EvidenceItem]] = OrderedDict()
        self._cache_generation = 0
        self.tool_manager = None
        self.conversation_state = None

    @staticmethod
    def _load_json(path: Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return default

    def _save_json(self, path: Path, data):
        atomic_write_text(path, json.dumps(data, indent=2, default=str))

    # ── run_history prioritization helpers ─────────────────────────────────
    def _is_recent_task_query(self, text: str) -> bool:
        """Detect whether a text string is asking about recent runs/tasks.

        Uses a conservative anti-token veto followed by trigger substring checks.
        This mirrors RetrieverAgent's classifier but is kept local to RetrievalBus
        to allow retrieval-level prioritization without changing higher layers.
        """
        if not text:
            return False
        q = text.lower().strip()
        antitokens = (
            "architecture",
            "how does",
            "explain the",
            "what is karma",
            "summarize the project",
            "recent commit",
            "recent version",
            "git history",
        )
        for anti in antitokens:
            if anti in q:
                return False
        triggers = (
            "just did",
            "just ran",
            "just happened",
            "just completed",
            "just finished",
            "last run",
            "last task",
            "last job",
            "last execution",
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
            "what was the last",
            "show me the run",
            "show last run",
        )
        for t in triggers:
            if t in q:
                return True
        return False

    def _retrieve_run_history_items(self, words: set, limit: int) -> List[EvidenceItem]:
        """Return run_history facts as EvidenceItem objects, newest-first but query-relevant.

        Uses query words to filter run_history entries for better relevance.
        """
        items: List[EvidenceItem] = []
        memory = getattr(self, "_memory", None)
        if not memory or not hasattr(memory, "facts"):
            return items

        raw = []
        for key, val in memory.facts.items():
            if not isinstance(val, dict):
                continue
            if val.get("topic") == "run_history":
                raw.append((key, val))
        if not raw:
            return items
        # Sort newest-first by last_updated
        raw.sort(key=lambda x: x[1].get("last_updated", ""), reverse=True)
        seen_run_ids: set = set()
        for key, outer in raw:
            inner = outer.get("value", outer)
            run_id = inner.get("run_id") if isinstance(inner, dict) else None
            if run_id and run_id in seen_run_ids:
                continue
            if run_id:
                    seen_run_ids.add(run_id)
            # Query relevance: check if run_history entry contains query words
            relevance = 0.5  # base relevance
            if words:
                run_text = str(inner.get("command", "")).lower() + str(inner.get("output", "")).lower()
                word_matches = sum(1 for w in words if w in run_text)
                relevance = min(0.95, 0.5 + word_matches * 0.15)
            confidence = outer.get("confidence", 0.9)
            if isinstance(confidence, (int, float)):
                confidence = float(confidence)
            else:
                confidence = 0.9
            # Only include if queryRelevant or recent signal matched elsewhere
            recency = 1.0
            items.append(EvidenceItem("run", inner, confidence, relevance, "run_history", "run_history", recency))
            if len(items) >= limit:
                break
        return items

    def invalidate_cache(self):
        self._cache_generation += 1
        self._bundle_cache.clear()

    # ── main entry ──────────────────────────────────────────────

    def retrieve_context_bundle(self, query: str, mode: str,
                               intent: str = "", entities: Dict[str, Any] = None,
                               tool: str = "") -> List[EvidenceItem]:
        """Retrieve evidence for a given query and mode.

        Modes: parse, plan, execute, respond, reflect, repair
        Optional shape context (intent, entities, tool) for shape-aware retrieval.

        Added: prefer run_history evidence for clearly recent-run / recent-task
        queries by injecting high-relevance run_history EvidenceItems before
        general retrievals. This keeps retrieval logic narrow and explainable.
        """
        entities = entities or {}
        query = query or ""
        intent = intent or ""
        tool = tool or ""
        cache_key = (
            mode,
            query.strip().lower(),
            intent.strip().lower(),
            tool.strip().lower(),
            tuple(sorted((str(k), str(v)) for k, v in entities.items())),
        )
        # LRU cache: move to end on access (most recently used)
        if cache_key in self._bundle_cache:
            self._bundle_cache.move_to_end(cache_key)
            self._metrics["cache_hits"] += 1
            return list(self._bundle_cache[cache_key])

        items: List[EvidenceItem] = []
        query_words = set(query.lower().replace("_", " ").replace(":", " ").split())

        # Build shape for shape-aware retrievers
        shape = extract_shape(intent or query, entities, tool) if (intent or entities or tool) else None

        # Detect recent-run / recent-task intent (use intent first, else query)
        recent_signal = False
        try:
            recent_signal = self._is_recent_task_query(intent) or self._is_recent_task_query(query)
        except Exception:
            recent_signal = False

        # If recent signal present, fetch run_history evidence as high-relevance items
        if recent_signal:
            try:
                # Use mode limit as an upper bound for run_history items to avoid oversaturation
                rh_limit = _MODE_LIMITS.get(mode, 7)
                rh_items = self._retrieve_run_history_items(query_words, rh_limit)
                items.extend(rh_items)
                # Telemetry: count injected run_history items
                self._metrics["run_history_injected"] += len(rh_items)
            except Exception:
                # safe degrade
                pass

        if mode == "parse":
            items.extend(self._retrieve_lexicon(query, query_words))
        elif mode == "plan":
            items.extend(self._retrieve_workflows(query, query_words, shape))
            items.extend(self._retrieve_failures(query, query_words, shape))
            items.extend(self._retrieve_tool_memory(query, query_words, shape))
            items.extend(self._retrieve_procedures(query, query_words, shape))
        elif mode == "execute":
            items.extend(self._retrieve_tool_memory(query, query_words, shape))
            items.extend(self._retrieve_failures(query, query_words, shape))
            items.extend(self._retrieve_procedures(query, query_words, shape))
        elif mode == "respond":
            items.extend(self._retrieve_world(query, query_words))
            items.extend(self._retrieve_crystals(query, query_words))
            items.extend(self._retrieve_golearn_facts(query, query_words))
        elif mode == "reflect":
            items.extend(self._retrieve_world(query, query_words))
            items.extend(self._retrieve_workflows(query, query_words, shape))
            items.extend(self._retrieve_failures(query, query_words, shape))
        elif mode == "repair":
            items.extend(self._retrieve_health(query, query_words))
            items.extend(self._retrieve_failures(query, query_words, shape))
            items.extend(self._retrieve_workflows(query, query_words, shape))
        elif mode.startswith("dialogue_"):
            items.extend(self._retrieve_dialogue_context(query, query_words, mode))
            items.extend(self._retrieve_world(query, query_words))

        # Deduplicate by (type, source, serialized value) to avoid duplicate
        # evidence from multiple strata. Keep first-seen (highest-added) item.
        seen = set()
        deduped: List[EvidenceItem] = []
        for e in items:
            try:
                if isinstance(e.value, (dict, list, tuple)):
                    val_key = json.dumps(e.value, sort_keys=True)
                else:
                    val_key = str(e.value)
            except Exception:
                val_key = str(e.value)
            # Deduplicate irrespective of source; keep first-seen evidence
            key = (e.type, val_key)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        items = deduped

        # Sort by relevance * confidence. run_history items were created with high relevance
        items.sort(key=lambda e: e.relevance * e.confidence, reverse=True)
        # Track metrics
        self._metrics["total_hits"] += len(items)
        self._metrics[f"hits_{mode}"] += len(items)
        # Per-mode bundle size limit
        limit = _MODE_LIMITS.get(mode, 7)
        bundle = items[:limit]
        self._bundle_cache[cache_key] = list(bundle)
        # LRU eviction: remove oldest entries when over limit
        while len(self._bundle_cache) > 256:
            self._bundle_cache.popitem(last=False)
        self._cache_generation += 1
        return bundle

    def get_metrics(self, reset: bool = False) -> dict:
        """Return a shallow copy of retrieval metrics. If reset=True, clear them."""
        out = dict(self._metrics)
        if reset:
            self._metrics = defaultdict(int)
        return out

    # ── strata retrievers ───────────────────────────────────────

    def _retrieve_dialogue_context(self, query: str, words: set, mode: str) -> List[EvidenceItem]:
        items: List[EvidenceItem] = []
        cs = self.conversation_state
        if not cs:
            return items
        topic = getattr(cs, "current_topic", None)
        if topic:
            overlap = len(words & set(topic.lower().split())) if words else 1
            items.append(EvidenceItem("thread", topic, 0.9, 0.55 + min(overlap * 0.1, 0.2), "conversation", "continue_thread"))
        for art in getattr(cs, "artifact_ledger", [])[-5:]:
            gist = art.get("gist", "")
            awords = set(gist.lower().split())
            overlap = len(words & awords) if words else 1
            relevance = 0.45 + min(overlap * 0.08, 0.2)
            if mode in {"dialogue_reference", "dialogue_compare", "dialogue_continue"}:
                relevance += 0.15
            items.append(EvidenceItem("artifact", art, cs.truth_weight(art.get("status", "observed")), relevance, "artifact_ledger", "answer_artifact"))
        for frag in getattr(cs, "answer_fragments", [])[-4:]:
            fwords = set(" ".join(frag.get("main_claims", [])).lower().split())
            overlap = len(words & fwords) if words else 1
            relevance = 0.4 + min(overlap * 0.08, 0.2)
            if mode in {"dialogue_continue", "dialogue_summary"}:
                relevance += 0.2
            items.append(EvidenceItem("answer_fragment", frag, cs.truth_weight(frag.get("status", "observed")), relevance, "answer_memory", "continue_answer"))
        for th in getattr(cs, "threads", {}).values():
            topic_words = set(str(th.get("topic", "")).lower().split())
            overlap = len(words & topic_words) if words else 1
            relevance = 0.35 + min(overlap * 0.08, 0.2) + float(th.get("gravity", 0.0)) * 0.2
            items.append(EvidenceItem("thread", th, cs.truth_weight(th.get("status", "provisional")), relevance, "thread_memory", "continue_thread"))
        for alt in getattr(cs, "contrastive_alternatives", lambda: [])():
            awords = set(str(alt).lower().split())
            overlap = len(words & awords) if words else 1
            items.append(EvidenceItem("contrast", alt, 0.6, 0.25 + min(overlap * 0.05, 0.15), "thread_memory", "compare_alternative"))
        # Contrastive: corrected/superseded from active thread
        active_th = cs.active_thread() if hasattr(cs, "active_thread") else None
        if active_th:
            for art_id in active_th.get("linked_artifacts", [])[-8:]:
                art = next((a for a in cs.artifact_ledger if a.get("id") == art_id), None)
                if art and art.get("status") in ("corrected", "superseded"):
                    items.append(EvidenceItem("contrast", art, 0.5, 0.3, "artifact_ledger", "show_correction"))
        # Concept memory — promoted recurring patterns
        for concept in getattr(cs, "concepts", {}).values():
            cwords = set(str(concept.get("name", "")).lower().split())
            overlap = len(words & cwords) if words else 0
            if overlap > 0:
                relevance = 0.3 + min(overlap * 0.1, 0.3) + float(concept.get("gravity", 0.0)) * 0.15
                items.append(EvidenceItem("concept", concept, cs.truth_weight(concept.get("status", "provisional")), relevance, "concept_memory", "continue_thread"))
        # Truth-status-aware: boost observed/corrected, penalize superseded
        for item in items:
            if hasattr(item, "value") and isinstance(item.value, dict):
                status = item.value.get("status", "inferred")
                rank = cs.truth_status_rank(status)
                item.relevance += max(0, (5 - rank)) * 0.03
        return items

    def _retrieve_lexicon(self, query: str, words: set) -> List[EvidenceItem]:
        """Lexicon memory: language mappings, known synonyms."""
        items = []
        for key, val in self._memory.facts.items():
            if not key.startswith("lang:map:"):
                continue
            key_words = set(key.lower().replace(":", " ").split())
            overlap = len(words & key_words)
            if overlap > 0:
                v = val.get("value", val) if isinstance(val, dict) else val
                items.append(EvidenceItem(
                    type="lexicon", value=v,
                    confidence=float(val.get("confidence", 0.5)) if isinstance(val, dict) else 0.5,
                    relevance=overlap / max(len(words), 1),
                    source="lexicon_memory", effect_hint="rewrite_input",
                ))
        return items[:5]

    def _retrieve_world(self, query: str, words: set) -> List[EvidenceItem]:
        """World memory: general facts (non-learn, non-lang)."""
        items = []
        for key, val in self._memory.facts.items():
            if key.startswith(("lang:map:", "learn:")):
                continue
            key_words = set(key.lower().replace(":", " ").replace("_", " ").split())
            overlap = len(words & key_words)
            if overlap > 0:
                v = val.get("value", val) if isinstance(val, dict) else val
                conf = float(val.get("confidence", 0.5)) if isinstance(val, dict) else 0.5
                items.append(EvidenceItem(
                    type="world", value=str(v)[:200],
                    confidence=conf, relevance=overlap / max(len(words), 1),
                    source="world_memory", effect_hint="answer_fact",
                ))
        return sorted(items, key=lambda e: e.relevance, reverse=True)[:10]

    def _retrieve_golearn_facts(self, query: str, words: set) -> List[EvidenceItem]:
        """GoLearn facts: learn:* entries."""
        items = []
        for key, val in self._memory.facts.items():
            if not key.startswith("learn:"):
                continue
            key_words = set(key.lower().replace(":", " ").replace("_", " ").split())
            overlap = len(words & key_words)
            if overlap > 0:
                v = val.get("value", val) if isinstance(val, dict) else val
                conf = float(val.get("confidence", 0.5)) if isinstance(val, dict) else 0.5
                items.append(EvidenceItem(
                    type="golearn", value=str(v)[:200],
                    confidence=conf, relevance=overlap / max(len(words), 1),
                    source="golearn_facts", effect_hint="answer_fact",
                ))
        return sorted(items, key=lambda e: e.relevance * e.confidence, reverse=True)[:10]

    def _retrieve_crystals(self, query: str, words: set) -> List[EvidenceItem]:
        """Concept crystals: compressed knowledge summaries."""
        items = []
        for crystal in self._crystals:
            c_words = set(crystal.get("topic", "").lower().split())
            c_words |= set(crystal.get("summary", "").lower().split()[:10])
            overlap = len(words & c_words)
            if overlap > 0:
                items.append(EvidenceItem(
                    type="crystal", value=crystal.get("summary", ""),
                    confidence=crystal.get("confidence", 0.5),
                    relevance=overlap / max(len(words), 1),
                    source="concept_crystals", effect_hint="answer_fact",
                ))
        return items[:5]

    def _retrieve_workflows(self, query: str, words: set,
                            query_shape: Dict[str, Any] = None) -> List[EvidenceItem]:
        """Workflow cache: shape-aware + keyword matching."""
        items = []
        for wf in self._workflows:
            sig_words = set(wf.get("signature", "").lower().replace(".", " ").replace("->", " ").replace("_", " ").replace(":", " ").split())
            overlap = len(words & sig_words)
            # Shape similarity boost
            shape_bonus = 0.0
            if query_shape and wf.get("shape"):
                shape_bonus = shape_similarity(query_shape, wf["shape"]) * 0.3
            # Centralized evidence score
            ev_score = score_evidence(wf, words,
                                      query_intent=query_shape.get("intent", "") if query_shape else "",
                                      query_domain=query_shape.get("domain", "") if query_shape else "",
                                      query_tool=query_shape.get("tool_family", "") if query_shape else "")
            relevance = max(overlap / max(len(words), 1), ev_score, shape_bonus)
            if relevance > 0.05:
                recency = _recency_score(wf.get("last_used", wf.get("created", "")))
                items.append(EvidenceItem(
                    type="workflow", value=wf,
                    confidence=wf.get("confidence", 0.5),
                    relevance=relevance,
                    source="workflow_cache", effect_hint="boost_action",
                    recency=recency,
                ))
        items.sort(key=lambda e: e.relevance * e.confidence, reverse=True)
        return items[:5]

    def _retrieve_failures(self, query: str, words: set,
                           query_shape: Dict[str, Any] = None) -> List[EvidenceItem]:
        """Failure fingerprints: shape-aware + keyword matching."""
        items = []
        for fp in self._failures:
            fp_words = set()
            for field in ("intent", "tool", "error_class"):
                fp_words |= set(fp.get(field, "").lower().replace("_", " ").replace(":", " ").split())
            overlap = len(words & fp_words)
            # Use centralized scoring
            ev_score = score_evidence(fp, words,
                                      query_intent=query_shape.get("intent", "") if query_shape else "",
                                      query_domain=query_shape.get("domain", "") if query_shape else "",
                                      query_tool=query_shape.get("tool_family", "") if query_shape else "")
            relevance = max(overlap / max(len(words), 1), ev_score)
            if relevance > 0.05:
                recency = _recency_score(fp.get("timestamp", ""))
                items.append(EvidenceItem(
                    type="failure", value=fp,
                    confidence=0.8, relevance=relevance,
                    source="failure_memory", effect_hint="block_action",
                    recency=recency,
                ))
        items.sort(key=lambda e: e.relevance, reverse=True)
        return items[:5]

    def _retrieve_tool_memory(self, query: str, words: set,
                              query_shape: Dict[str, Any] = None) -> List[EvidenceItem]:
        """Tool operational memory from capability map.

        Matches by: direct name, tool family, related workflows, and
        prior success in similar contexts.
        """
        if not self._cap_map:
            return []
        items = []
        cap = self._cap_map.get_full_map()
        query_family = query_shape.get("tool_family", "") if query_shape else ""
        query_intent = query_shape.get("intent", "") if query_shape else ""

        for tool_name, info in cap.items():
            relevance = 0.0
            tool_lower = tool_name.lower()

            # Direct name match
            if tool_lower in words or any(w in tool_lower for w in words):
                relevance = 0.8

            # Tool family match
            from core.evidence_score import _tool_family
            if query_family and _tool_family(tool_name) == query_family:
                relevance = max(relevance, 0.5)

            # Related workflow match
            for wf_sig in info.get("linked_workflows", []):
                if any(w in wf_sig.lower() for w in words):
                    relevance = max(relevance, 0.4)
                    break

            # Intent match via tasks list
            if query_intent and query_intent in info.get("tasks", []):
                relevance = max(relevance, 0.6)

            # Context match — check best_contexts
            for ctx in info.get("best_contexts", []):
                if any(w in ctx.lower() for w in words):
                    relevance = max(relevance, 0.35)
                    break

            if relevance < 0.1:
                continue

            sr = info.get("success_rate", 0.5) if isinstance(info.get("success_rate"), (int, float)) else 0.5
            hint = "boost_action" if sr > 0.6 else "block_action"
            items.append(EvidenceItem(
                type="tool_memory", value=info,
                confidence=sr,
                relevance=relevance, source="capability_memory",
                effect_hint=hint,
            ))
        items.sort(key=lambda e: e.relevance * e.confidence, reverse=True)
        return items[:5]

    def _retrieve_health(self, query: str, words: set) -> List[EvidenceItem]:
        """Health memory: past repairs and diagnostics."""
        items = []
        for h in self._health[-20:]:
            h_words = set(h.get("issue", "").lower().split())
            overlap = len(words & h_words)
            if overlap > 0:
                recency = _recency_score(h.get("timestamp", ""))
                items.append(EvidenceItem(
                    type="health", value=h,
                    confidence=0.7, relevance=overlap / max(len(words), 1),
                    source="health_memory", effect_hint="suggest_repair",
                    recency=recency,
                ))
        return items[:5]

    def _retrieve_procedures(self, query: str, words: set,
                             query_shape: Dict[str, Any] = None) -> List[EvidenceItem]:
        """Procedure memory: reusable multi-step sequences."""
        items = []
        for proc in self._procedures:
            proc_words = set(proc.get("name", "").lower().replace("_", " ").split())
            proc_words |= set(proc.get("trigger_intent", "").lower().replace("_", " ").split())
            overlap = len(words & proc_words)
            # Shape matching
            shape_bonus = 0.0
            if query_shape and proc.get("trigger_intent"):
                if query_shape.get("intent") == proc["trigger_intent"]:
                    shape_bonus = 0.3
                elif query_shape.get("domain") == proc.get("domain", ""):
                    shape_bonus = 0.1
            relevance = max(overlap / max(len(words), 1), shape_bonus)
            if relevance > 0.05:
                recency = _recency_score(proc.get("last_used", proc.get("created", "")))
                items.append(EvidenceItem(
                    type="procedure", value=proc,
                    confidence=proc.get("confidence", 0.5),
                    relevance=relevance,
                    source="procedure_memory", effect_hint="boost_action",
                    recency=recency,
                ))
        items.sort(key=lambda e: e.relevance * e.confidence, reverse=True)
        return items[:3]

    # ── storage: procedures ──────────────────────────────────────

    def store_procedure(self, name: str, trigger_intent: str, steps: List[Dict[str, Any]],
                        domain: str = ""):
        """Store a reusable multi-step procedure."""
        for proc in self._procedures:
            if proc["name"] == name:
                proc["steps"] = steps
                proc["use_count"] = proc.get("use_count", 0) + 1
                proc["confidence"] = min(1.0, proc.get("confidence", 0.5) + 0.05)
                proc["last_used"] = datetime.now().isoformat()
                self._save_json(self._procedures_file, self._procedures)
                self.invalidate_cache()
                return
        self._procedures.append({
            "name": name,
            "trigger_intent": trigger_intent,
            "steps": steps,
            "domain": domain,
            "use_count": 1,
            "confidence": 0.6,
            "created": datetime.now().isoformat(),
            "last_used": datetime.now().isoformat(),
        })
        if len(self._procedures) > 100:
            self._procedures = sorted(self._procedures, key=lambda p: p.get("use_count", 0), reverse=True)[:100]
        self._save_json(self._procedures_file, self._procedures)
        self.invalidate_cache()

    # ── storage: workflows ──────────────────────────────────────

    def store_workflow(self, signature: str, steps: List[str], tool_sequence: List[str],
                       intent: str = "", entities: Dict[str, Any] = None):
        """Store a successful workflow with optional shape metadata."""
        shape = extract_shape(intent or signature, entities or {},
                              tool_sequence[0] if tool_sequence else "") if intent or entities else None
        # Check for existing
        for wf in self._workflows:
            if wf["signature"] == signature:
                wf["success_count"] = wf.get("success_count", 0) + 1
                wf["confidence"] = min(1.0, wf["confidence"] + 0.05)
                wf["last_used"] = datetime.now().isoformat()
                if shape and not wf.get("shape"):
                    wf["shape"] = shape
                self._save_json(self._workflows_file, self._workflows)
                self.invalidate_cache()
                return
        entry = {
            "signature": signature,
            "steps": steps,
            "tool_sequence": tool_sequence,
            "success_count": 1,
            "confidence": 0.6,
            "created": datetime.now().isoformat(),
            "last_used": datetime.now().isoformat(),
        }
        if shape:
            entry["shape"] = shape
        self._workflows.append(entry)
        # Cap at 200
        if len(self._workflows) > 200:
            self._workflows = sorted(self._workflows, key=lambda w: w.get("success_count", 0), reverse=True)[:200]
        self._save_json(self._workflows_file, self._workflows)
        self.invalidate_cache()

    # ── storage: failure fingerprints ───────────────────────────

    def store_failure(self, intent: str, tool: str, params: Dict, error_class: str, context: str, lesson: str):
        """Store a failure fingerprint."""
        self._failures.append({
            "intent": intent, "tool": tool,
            "parameter_shape": list(params.keys()) if params else [],
            "error_class": error_class, "context": context[:200],
            "lesson": lesson, "timestamp": datetime.now().isoformat(),
        })
        # Cap at 300
        if len(self._failures) > 300:
            self._failures = self._failures[-300:]
        self._save_json(self._failures_file, self._failures)
        self.invalidate_cache()

    # ── storage: concept crystals ───────────────────────────────

    def crystallize(self, topic: str) -> Optional[Dict[str, Any]]:
        """Compress related knowledge about a topic into a concept crystal."""
        # Gather all facts about this topic
        related = []
        for key, val in self._memory.facts.items():
            if topic.lower() in key.lower():
                v = val.get("value", val) if isinstance(val, dict) else val
                conf = float(val.get("confidence", 0.5)) if isinstance(val, dict) else 0.5
                related.append({"key": key, "value": str(v)[:150], "confidence": conf})
        if len(related) < 3:
            return None

        # Build crystal
        related.sort(key=lambda r: r["confidence"], reverse=True)
        top_values = [r["value"] for r in related[:5]]
        avg_conf = sum(r["confidence"] for r in related) / len(related)

        # Check for contradictions (very different values for similar keys)
        contradictions = 0
        values_set = set()
        for r in related:
            v_norm = r["value"].strip().lower()[:50]
            if v_norm in values_set:
                continue
            values_set.add(v_norm)
        # If many unique values relative to count, some may contradict
        if len(values_set) > len(related) * 0.8:
            contradictions = int(len(values_set) - len(related) * 0.5)

        # Find linked workflows
        linked_wf = []
        for wf in self._workflows:
            if topic.lower() in wf.get("signature", "").lower():
                linked_wf.append(wf["signature"])

        # Find linked failures
        linked_fail = []
        for fp in self._failures:
            if topic.lower() in fp.get("intent", "").lower() or topic.lower() in fp.get("tool", "").lower():
                linked_fail.append(fp.get("error_class", "unknown"))

        crystal = {
            "topic": topic,
            "summary": " | ".join(top_values),
            "supporting_memory_count": len(related),
            "confidence_band": [round(min(r["confidence"] for r in related), 2),
                                round(max(r["confidence"] for r in related), 2)],
            "contradiction_count": contradictions,
            "linked_workflows": linked_wf[:5],
            "linked_failures": linked_fail[:5],
            "created": datetime.now().isoformat(),
        }

        # Upsert
        for i, c in enumerate(self._crystals):
            if c.get("topic", "").lower() == topic.lower():
                self._crystals[i] = crystal
                self._save_json(self._crystals_file, self._crystals)
                self.invalidate_cache()
                return crystal
        self._crystals.append(crystal)
        if len(self._crystals) > 100:
            self._crystals = self._crystals[-100:]
        self._save_json(self._crystals_file, self._crystals)
        self.invalidate_cache()
        return crystal

    # ── storage: health ─────────────────────────────────────────

    def store_health_event(self, issue: str, severity: str, suggestion: str, subsystem: str = ""):
        """Record a health event."""
        self._health.append({
            "issue": issue, "severity": severity,
            "suggestion": suggestion, "subsystem": subsystem,
            "timestamp": datetime.now().isoformat(),
        })
        if len(self._health) > 200:
            self._health = self._health[-200:]
        self._save_json(self._health_file, self._health)
        self.invalidate_cache()

    # ── metrics ─────────────────────────────────────────────────

    def log_decision_metrics(self, hits: int, used: int, ignored: int):
        """Log retrieval influence for a single decision."""
        self._metrics["decisions"] = self._metrics.get("decisions", 0) + 1
        self._metrics["total_used"] = self._metrics.get("total_used", 0) + used
        self._metrics["total_ignored"] = self._metrics.get("total_ignored", 0) + ignored
