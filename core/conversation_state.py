from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional
import re


_TRUTH_STATUS_ORDER = ["observed", "corrected", "stable", "inferred", "provisional", "superseded"]


@dataclass
class ConversationState:
    max_turns: int = 8
    current_topic: Optional[str] = None
    previous_topic: Optional[str] = None
    recent_entities: Dict[str, str] = field(default_factory=dict)
    unresolved_references: List[str] = field(default_factory=list)
    recent_user_goal: Optional[str] = None
    last_agent_commitments: List[str] = field(default_factory=list)
    short_history_summary: str = ""
    active_options: List[str] = field(default_factory=list)
    active_artifacts: List[str] = field(default_factory=list)
    last_subject: Optional[str] = None
    current_subject: Optional[Dict[str, Any]] = None
    turns: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=8))
    artifact_ledger: List[Dict[str, Any]] = field(default_factory=list)
    answer_fragments: List[Dict[str, Any]] = field(default_factory=list)
    threads: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_thread_id: Optional[str] = None
    concepts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    scars: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    compression_every: int = 6
    last_code_context: Optional[Dict[str, Any]] = None

    def set_current_subject(self, *, kind: str, label: str, id: Optional[str] = None,
                            path: Optional[str] = None, confidence: float = 0.8,
                            related_artifacts: Optional[List[str]] = None):
        self.current_subject = {
            "kind": kind, "human_label": label, "id": id, "path": path,
            "source_turn": len(self.turns), "confidence": confidence,
            "related_artifacts": list(related_artifacts or []),
        }
        self.last_subject = label
        th = self.active_thread()
        if th is not None:
            th["current_subject"] = self.current_subject

    @staticmethod
    def _infer_subject_kind(label: str) -> str:
        if not label:
            return "topic"
        basename = label.rstrip("/").rsplit("/", 1)[-1] if "/" in label else label
        if "." in basename:
            return "file"
        if label.endswith("/") or ("." not in basename and len(basename) < 40):
            return "folder"
        return "topic"

    def note_turn(self, *, user_input: str, response: str, act: str,
                  intent: Optional[str] = None, entities: Optional[Dict[str, str]] = None,
                  response_goal: Optional[str] = None):
        entities = entities or {}
        topic = self._infer_topic(user_input, response, entities)
        if topic and topic != self.current_topic:
            self.previous_topic = self.current_topic
            self.current_topic = topic
        if entities:
            self.recent_entities.update({k: str(v) for k, v in entities.items() if v})
        self.recent_user_goal = intent or act or self.recent_user_goal
        self.active_options = self._extract_options(user_input, response)
        self.last_agent_commitments = self._extract_commitments(response)
        self.unresolved_references = self._extract_unresolved_references(user_input)
        inferred_subj = self._infer_last_subject(user_input, entities)
        # Dialogue-handled acts (correction, continuation, summary) have current_subject
        # already set by the dialogue manager — don't overwrite with a weaker inference
        _dialogue_acts = {"correction", "continuation", "summary_request", "introspection"}
        if act not in _dialogue_acts:
            self.last_subject = inferred_subj
            if self.last_subject:
                kind = self._infer_subject_kind(self.last_subject)
                self.set_current_subject(kind=kind, label=self.last_subject, confidence=0.7)
        self._update_thread(topic, user_input, response, act, response_goal)
        self.turns.append({
            "user": user_input,
            "response": response,
            "act": act,
            "intent": intent,
            "topic": topic,
            "response_goal": response_goal,
        })
        self.short_history_summary = self._build_summary()
        self._maybe_promote_concept()

    def register_artifact(self, *, type: str, gist: str, raw: str = "", source_turn: Optional[int] = None,
                          ordering: Optional[int] = None, confidence: float = 0.8):
        idx = len(self.artifact_ledger) + 1
        art = {
            "id": f"a{idx}", "type": type, "gist": gist[:120], "raw": raw,
            "source_turn": source_turn if source_turn is not None else len(self.turns),
            "ordering": ordering if ordering is not None else idx,
            "thread_id": self.active_thread_id, "concepts": [],
            "confidence": confidence, "status": "observed",
        }
        self.artifact_ledger.append(art)
        if gist:
            self.active_artifacts.append(gist)
            kind = self._infer_subject_kind(gist)
            self.set_current_subject(kind=kind, label=gist, id=art["id"],
                                     path=gist if "/" in gist or "." in gist else None,
                                     confidence=confidence)
        self.active_artifacts = self.active_artifacts[-8:]
        th = self.active_thread()
        if th is not None:
            th.setdefault("linked_artifacts", []).append(art["id"])
        return art

    def register_answer_fragment(self, *, text: str, response_goal: str = "answer"):
        claims = [ln.strip('- ').strip() for ln in text.splitlines() if ln.strip()][:4]
        frag = {
            "id": f"ans{len(self.answer_fragments)+1}",
            "topic": self.current_topic,
            "main_claims": claims,
            "compared_options": list(self.active_options[:4]),
            "supporting_artifacts": [a["id"] for a in self.artifact_ledger[-4:]],
            "unresolved_branches": list(self.unresolved_references[:4]),
            "response_goal": response_goal,
            "status": "observed",
        }
        self.answer_fragments.append(frag)
        self.answer_fragments = self.answer_fragments[-10:]
        return frag

    def add_scar(self, name: str, *, reason: str = "", severity: float = 0.2):
        scar = self.scars.setdefault(name, {"count": 0, "reason": reason, "severity": 0.0})
        scar["count"] += 1
        scar["reason"] = reason or scar.get("reason", "")
        scar["severity"] = min(1.0, float(scar.get("severity", 0.0)) + severity)
        return scar

    def resolve_reference(self, text: str) -> Optional[str]:
        low = text.strip().lower()
        if "third" in low:
            if len(self.active_options) >= 3:
                return self.active_options[2]
            arts = self._recent_artifact_gists()
            if len(arts) >= 3:
                return arts[2]
        if "second" in low:
            if len(self.active_options) >= 2:
                return self.active_options[1]
            arts = self._recent_artifact_gists()
            if len(arts) >= 2:
                return arts[1]
        if "first" in low:
            if len(self.active_options) >= 1:
                return self.active_options[0]
            arts = self._recent_artifact_gists()
            if len(arts) >= 1:
                return arts[0]
        if "last" in low or "latest" in low:
            arts = self._recent_artifact_gists()
            if arts:
                return arts[-1]
            if self.active_options:
                return self.active_options[-1]
        if "other option" in low and len(self.active_options) >= 2:
            return self.active_options[1]
        if "that folder" in low:
            arts = [a for a in self._recent_artifact_gists() if self._looks_like_folder(a)]
            if arts:
                return arts[-1]
            return None
        if "that file" in low:
            arts = [a for a in self._recent_artifact_gists() if self._looks_like_file(a)]
            if arts:
                return arts[-1]
            return None
        if any(tok in low for tok in ("that bug", "that result", "those results")):
            arts = self._recent_artifact_gists()
            if arts:
                return arts[-1]
            return None
        if any(tok in low for tok in ("go on", "continue", "more")):
            # Continuation: prefer active thread topic > current topic
            th = self.active_thread()
            if th:
                return th.get("topic") or self.current_topic
            return self.current_topic
        if any(tok in low for tok in ("summarize", "summary")):
            # Summary: prefer active thread > last subject > current topic
            th = self.active_thread()
            if th:
                return th.get("topic") or self.current_topic
            return self.last_subject or self.current_topic
        if low in ("fix it",) and self.last_code_context:
            return self.last_code_context.get("path") or self.last_subject or self.current_topic
        if any(tok in low for tok in ("that one", "it")):
            return self.last_subject or self.current_topic
        return None

    def summary(self) -> str:
        if self.short_history_summary:
            return self.short_history_summary
        if self.current_topic:
            return f"Active topic: {self.current_topic}"
        return "No active conversation topic."

    def active_thread(self) -> Optional[Dict[str, Any]]:
        if self.active_thread_id:
            return self.threads.get(self.active_thread_id)
        return None

    def uncertainty_flags(self) -> Dict[str, bool]:
        return {
            "has_unresolved_references": bool(self.unresolved_references),
            "has_scars": bool(self.scars),
            "thread_missing": self.active_thread_id is None,
        }

    def truth_weight(self, status: str) -> float:
        return {
            "observed": 1.0,
            "stable": 0.95,
            "corrected": 0.75,
            "inferred": 0.6,
            "provisional": 0.5,
            "superseded": 0.2,
        }.get(status or "inferred", 0.5)

    def truth_status_rank(self, status: str) -> int:
        try:
            return _TRUTH_STATUS_ORDER.index(status or "inferred")
        except ValueError:
            return 4  # provisional-level

    def contrastive_alternatives(self) -> List[str]:
        out = []
        for th in self.threads.values():
            for s in th.get("superseded_conclusions", [])[-2:]:
                out.append(s)
        return out[-4:]

    def corrected_artifacts(self) -> List[Dict[str, Any]]:
        th = self.active_thread()
        if not th:
            return []
        out = []
        for art_id in th.get("linked_artifacts", [])[-8:]:
            art = next((a for a in self.artifact_ledger if a.get("id") == art_id), None)
            if art and art.get("status") in ("corrected", "superseded"):
                out.append(art)
        return out[-4:]

    def reopen_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        th = self.threads.get(thread_id)
        if th and th.get("current_state") in ("stable", "closed"):
            th["current_state"] = "active"
            self.active_thread_id = thread_id
            return th
        return None

    def find_thread_by_topic(self, topic: str) -> Optional[str]:
        low = topic.strip().lower()
        for tid, th in self.threads.items():
            if low in str(th.get("topic", "")).lower():
                return tid
        return None

    def scar_severity(self, name: str) -> float:
        scar = self.scars.get(name)
        if not scar:
            return 0.0
        return float(scar.get("severity", 0.0))

    def _recent_artifact_gists(self) -> List[str]:
        return [a.get("gist", "") for a in self.artifact_ledger[-8:] if a.get("gist")]

    @staticmethod
    def _looks_like_file(name: str) -> bool:
        # A file has an extension (e.g. foo.py, tests/foo.py)
        basename = name.rstrip("/").rsplit("/", 1)[-1] if "/" in name else name
        return "." in basename

    @staticmethod
    def _looks_like_folder(name: str) -> bool:
        # A folder has no extension in the last component
        basename = name.rstrip("/").rsplit("/", 1)[-1] if "/" in name else name
        return "." not in basename or name.endswith("/")


    def _update_thread(self, topic: Optional[str], user_input: str, response: str, act: str, response_goal: Optional[str]):
        tid = self.active_thread_id
        if topic:
            slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip('-')[:32] or "thread"
            tid = f"th-{slug}"
            # Reopen existing thread if it was stable/closed
            if tid in self.threads and self.threads[tid].get("current_state") in ("stable", "closed"):
                self.threads[tid]["current_state"] = "active"
            self.active_thread_id = tid
        if not tid:
            return
        th = self.threads.setdefault(tid, {
            "thread_id": tid, "topic": topic or self.current_topic or "thread", "current_state": "active",
            "linked_artifacts": [], "linked_episodes": [], "hypotheses": [], "resolved_conclusion": None,
            "superseded_conclusions": [], "pending_question": None, "gravity": 0.5, "status": "provisional",
        })
        th["topic"] = topic or th.get("topic")
        if self.current_subject:
            th["current_subject"] = self.current_subject
        th["gravity"] = min(1.0, float(th.get("gravity", 0.5)) + 0.05)
        th["linked_episodes"].append({"user": user_input[:160], "response": response[:200], "act": act, "goal": response_goal})
        th["linked_episodes"] = th["linked_episodes"][-8:]
        if act == "correction" and th.get("resolved_conclusion"):
            th.setdefault("superseded_conclusions", []).append(th["resolved_conclusion"])
            th["status"] = "corrected"
        if response_goal == "summarize":
            th["resolved_conclusion"] = response[:200]
            th["status"] = "stable"
            th["current_state"] = "stable"
        elif act == "question":
            th["pending_question"] = user_input[:140]

    def _maybe_promote_concept(self):
        if len(self.turns) < 3:
            return
        topics = [t.get("topic") for t in self.turns if t.get("topic")]
        if not topics:
            return
        topic, count = Counter(topics).most_common(1)[0]
        if count < 2:
            return
        cid = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip('_')[:32] or "concept"
        concept = self.concepts.setdefault(cid, {
            "concept_id": cid, "name": topic, "summary": f"Recurring pattern around {topic}",
            "linked_threads": [], "linked_artifacts": [], "linked_files": [],
            "confidence": 0.5, "gravity": 0.5,
            "last_updated": len(self.turns), "unresolved_questions": [], "status": "provisional",
        })
        if self.active_thread_id and self.active_thread_id not in concept["linked_threads"]:
            concept["linked_threads"].append(self.active_thread_id)
        # Link file-like artifacts to concept
        for art in self.artifact_ledger[-8:]:
            gist = art.get("gist", "")
            if gist and ("." in gist or "/" in gist) and gist not in concept.get("linked_files", []):
                concept.setdefault("linked_files", []).append(gist)
        concept["linked_files"] = concept.get("linked_files", [])[-12:]
        concept["gravity"] = min(1.0, concept["gravity"] + 0.05)
        concept["confidence"] = min(1.0, concept["confidence"] + 0.05)
        concept["last_updated"] = len(self.turns)

    _PRONOUN_JUNK = {"that", "it", "this", "those", "them", "these", "one", "ones"}
    _META_JUNK = {"the current subject", "the current topic", "the active thread",
                  "current subject", "current topic", "active thread", "active artifacts",
                  "you referring to", "you think i mean", "you mean"}

    def _infer_topic(self, user_input: str, response: str, entities: Dict[str, str]) -> Optional[str]:
        for key in ("topic", "path", "filename", "pattern", "name"):
            if entities.get(key):
                return str(entities[key])
        low = user_input.strip().lower()
        # Exact-match dialogue phrases: keep current topic, don't extract junk
        if low in {"go on", "continue", "more", "summarize that", "summarize it",
                    "the third one", "the second one", "the first one", "that one", "that file",
                    "that folder", "those results", "that bug"}:
            return self.current_topic
        # Introspection inputs: don't change topic
        if any(m in low for m in ("current subject", "current topic", "active thread",
                                   "active artifact", "referring to", "think i mean",
                                   "what changed", "what evidence", "what else did",
                                   "why are we talking", "why are you talking")):
            return self.current_topic
        for prefix in (
            "what is ", "what are ", "tell me about ", "explain ",
            "compare ", "what can you do", "what files are in ",
        ):
            if low.startswith(prefix):
                candidate = low[len(prefix):].strip(" ?.")
                if candidate and candidate not in self._PRONOUN_JUNK and candidate not in self._META_JUNK:
                    return candidate
        head = response.splitlines()[0].strip() if response else ""
        if head and not any(head.startswith(p) for p in ("Got it.", "I'm tracking", "Which ", "Continuing on", "Summary of", "Noted for", "Current subject", "No ")):
            return head[:80]
        return self.current_topic

    def _infer_last_subject(self, user_input: str, entities: Dict[str, str]) -> Optional[str]:
        for key in ("filename", "path", "name", "topic"):
            if entities.get(key):
                return str(entities[key])
        return self.current_topic

    def _extract_options(self, user_input: str, response: str) -> List[str]:
        text = f"{user_input} {response}"
        m = re.search(r"compare\s+(.+?)\s+and\s+(.+?)(?:$|[?.!])", text, re.IGNORECASE)
        if m:
            return [m.group(1).strip(), m.group(2).strip()]
        m = re.search(r"(?:options?|choices?)\s*:\s*(.+)", text, re.IGNORECASE)
        if m:
            parts = [p.strip() for p in re.split(r",|/|or|and", m.group(1)) if p.strip()]
            return parts[:4]
        return self.active_options

    def _extract_commitments(self, response: str) -> List[str]:
        lines = []
        for line in response.splitlines()[:3]:
            if any(token in line.lower() for token in ("i can", "i will", "next", "available commands")):
                lines.append(line.strip())
        return lines[:3]

    def _extract_unresolved_references(self, user_input: str) -> List[str]:
        low = user_input.lower()
        refs = []
        if any(tok in low for tok in ("that", "it", "the other one", "the third one", "the second one", "that folder")) and not self.current_topic and not self.active_options and not self.artifact_ledger:
            refs.append(user_input)
        return refs

    def _build_summary(self) -> str:
        parts: List[str] = []
        if self.current_topic:
            parts.append(f"Topic: {self.current_topic}")
        if self.active_options:
            parts.append("Options: " + ", ".join(self.active_options[:3]))
        if self.active_artifacts:
            parts.append("Artifacts: " + ", ".join(self.active_artifacts[-2:]))
        if self.turns:
            last = self.turns[-1]
            parts.append(f"Last act: {last.get('act', 'unknown')}")
        if len(self.turns) >= self.compression_every:
            parts.append("Compressed: yes")
        return " | ".join(parts)
