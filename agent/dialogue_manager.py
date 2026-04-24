"""Dialogue manager — handles conversation-first turn routing.

Extracted from AgentLoop to keep the orchestrator lean.
Handles: introspection, clarification, follow-up, continuation, summary.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.dialogue import choose_response_goal, retrieval_mode_for_goal
from core.conversation_state import ConversationState


class DialogueManager:
    """Manages dialogue responses, introspection, and clarification."""

    def __init__(self, conversation: ConversationState, retrieval, responder, memory):
        self.conversation = conversation
        self.retrieval = retrieval
        self.responder = responder
        self.memory = memory
        self._last_result: Optional[str] = None
        self._last_code_context: Optional[Dict[str, Any]] = None
        self._last_golearn_result: Optional[Dict[str, Any]] = None  # Last golearn session result

    def set_last_result(self, result: Optional[str]):
        self._last_result = result

    def set_last_code_context(self, ctx: Optional[Dict[str, Any]]):
        self._last_code_context = ctx

    def set_last_golearn_result(self, result: Optional[Dict[str, Any]]):
        """Store last golearn result for follow-up queries."""
        self._last_golearn_result = result

    def handle_turn(self, user_input: str, dialogue: Dict[str, str]) -> Optional[str]:
        act = dialogue.get("act", "statement")
        if act == "introspection":
            return self._handle_introspection(user_input)
        if act == "clarification_answer" and self.conversation.current_topic:
            return f"Noted for the current topic: {self.conversation.current_topic}"
        # Check if this is a code follow-up before generic dialogue
        code_response = self._handle_code_followup(user_input)
        if code_response is not None:
            return code_response
        # Check if this is a golearn follow-up
        golearn_response = self._handle_golearn_followup(user_input)
        if golearn_response is not None:
            return golearn_response
        # Check if this is a status follow-up (any errors, what failed, etc.)
        status_response = self._handle_status_followup(user_input)
        if status_response is not None:
            return status_response
        return self._build_dialogue_response(user_input, act)

    # ── code follow-up resolution ─────────────────────────────

    _CODE_FOLLOWUP_PATTERNS = re.compile(
        r"^(?:go on|continue|summarize that|explain that|fix it|what happened|"
        r"what went wrong|what was the error|show the error|run it again|"
        r"try again|what evidence supports that)\s*[?.!]?\s*$",
        re.IGNORECASE,
    )

    def _handle_code_followup(self, user_input: str) -> Optional[str]:
        """Resolve code follow-ups against last_code_context. Returns None if not a code follow-up."""
        if not self._CODE_FOLLOWUP_PATTERNS.match(user_input.strip()):
            return None
        ctx = self._last_code_context
        if not ctx:
            return None  # no code context — fall through to generic dialogue

        low = user_input.strip().lower().rstrip("?.!")
        path = ctx.get("path", "unknown")
        action = ctx.get("action", "")
        result_text = ctx.get("result", "")
        error_type = ctx.get("error_type")

        if low in ("go on", "continue"):
            if ctx.get("success"):
                return f"Last code action on {path} succeeded:\n{result_text[:400]}"
            else:
                return f"Last code action on {path} failed ({error_type or 'unknown error'}):\n{result_text[:400]}"

        if low in ("summarize that", "explain that"):
            summary = f"Action: {action} on {path}\n"
            if ctx.get("success"):
                summary += f"Result: success\n{result_text[:300]}"
            else:
                summary += f"Result: failed — {error_type or 'unknown'}\n{result_text[:300]}"
            return summary

        if low == "fix it":
            if error_type and path and path != "unknown":
                # Re-dispatch to code_debug
                return None  # let it fall through — caller should re-route to debug
            return f"No fixable error in last code context for {path}."

        if low in ("what happened", "what went wrong", "what was the error", "show the error"):
            if error_type:
                return f"Error on {path}: {error_type}\n{result_text[:400]}"
            return f"No error recorded for last code action on {path}."

        return None

    # ── golearn follow-up resolution ────────────────────────────

    _GOLEARN_FOLLOWUP_PATTERNS = re.compile(
        r"^(?:go on|continue|summarize that|explain that|what did you learn|"
        r"what was that about|continue learning)\s*[?.!]?\s*$",
        re.IGNORECASE,
    )

    def _handle_golearn_followup(self, user_input: str) -> Optional[str]:
        """Resolve golearn follow-ups against last_golearn_result."""
        if not self._GOLEARN_FOLLOWUP_PATTERNS.match(user_input.strip()):
            return None
        result = self._last_golearn_result
        if not result:
            return None

        low = user_input.strip().lower().rstrip("?.!")

        # Extract key info from the golearn result
        session = result.get("session", {})
        topic = session.get("topic", "unknown topic")
        stop_reason = session.get("stop_reason", "unknown")
        visited = session.get("visited", [])
        artifacts = session.get("artifacts", [])
        provider_diag = session.get("provider_diagnostic")
        cache_status = session.get("cache_status")
        cache_hits = session.get("cache_hits", 0)

        if low in ("go on", "continue", "continue learning"):
            if visited or artifacts:
                cache_note = f" ({cache_hits} from cache)" if cache_hits > 0 else ""
                return f"Continuing research on '{topic}': visited {len(visited)} topics, {len(artifacts)} sources{cache_note}."
            elif cache_status in ("cache_hit", "cache_partial") and cache_hits > 0:
                return f"Research on '{topic}' used cached results ({cache_hits} cache hits). Would you like to learn more?"
            elif provider_diag:
                return f"Research on '{topic}' was limited: {provider_diag}"
            else:
                return f"Research on '{topic}' completed. Would you like to learn more about a specific aspect?"

        if low in ("summarize that", "explain that", "what did you learn", "what was that about"):
            summary = [f"Research on '{topic}'"]
            if visited:
                summary.append(f"Explored {len(visited)} subtopics: {', '.join(visited[:5])}")
                if len(visited) > 5:
                    summary[-1] += f" ... and {len(visited) - 5} more"
            if artifacts:
                summary.append(f"Gathered {len(artifacts)} source artifacts.")
            if cache_status == "cache_hit":
                summary.append("Note: Results were served from cache.")
            elif cache_status == "cache_partial":
                summary.append(f"Note: Some results served from cache ({cache_hits} cache hits).")
            if stop_reason in ("search_provider_blocked", "search_timeout"):
                summary.append(f"Note: Live search provider was blocked or timed out ({provider_diag or stop_reason}).")
            elif stop_reason == "low_yield":
                summary.append(f"Note: Search results were limited ({provider_diag or 'low yield'}).")
            elif stop_reason == "provider_blocked":
                summary.append(f"Note: Search provider blocked requests ({provider_diag}).")
            summary.append(f"Stopped because: {stop_reason}")
            return "\n".join(summary)

        return None

    # ── status follow-up resolution ───────────────────────────────

    def _handle_status_followup(self, user_input: str) -> Optional[str]:
        """Handle natural follow-up queries about status, errors, blockers."""
        try:
            from research.pulse import get_pulse
            from research.truth_layer import handle_followup
        except ImportError:
            return None

        low = user_input.strip().lower().rstrip("?.!")

        # Only handle explicit status questions
        status_phrases = [
            "any errors", "what errors", "did it fail", "what failed", "errors", "failures",
            "what failed", "what went wrong", "what didn't work", "what problem", "what issue",
            "what do you need", "what do you want", "what do you need more",
            "why did it stop", "why did it end", "what made it stop",
            "what should i feed", "what should i feed you", "what to feed", "feed me", "what to add",
            "what worked", "what succeeded", "what went well", "any wins",
            "what happened", "what's going on", "what's the status",
            "what did you learn", "learn anything", "learned anything",
            "what are the blockers", "what's blocking", "what's stopping", "any blockers",
            "what do you need", "what do you need?",
        ]

        if not any(low == p or low.startswith(p.rstrip("?")) for p in status_phrases):
            return None

        pulse = get_pulse()
        pulse_summary = pulse.generate_summary()

        return handle_followup(user_input, pulse_summary, self._last_golearn_result)

    def clarification_prompt(self, user_input: str) -> str:
        low = user_input.lower()
        kind = "item"
        if "folder" in low or "dir" in low:
            kind = "folder"
        elif "file" in low:
            kind = "file"
        elif "result" in low:
            kind = "result"
        recent = self.conversation.active_artifacts[-5:]
        if recent:
            items = ", ".join(recent)
            return f"Which {kind} do you mean? Recent items: {items}"
        entities = [v for v in self.conversation.recent_entities.values() if v]
        if entities:
            return f"Which {kind} do you mean? Recent context: {', '.join(entities[-3:])}"
        return f"Which {kind} are you referring to?"

    def _build_dialogue_response(self, user_input: str, act: str) -> str:
        goal = choose_response_goal(user_input, act=act)
        mode = retrieval_mode_for_goal(goal)
        ref = self.conversation.resolve_reference(user_input)
        ambiguous = any(tok in user_input.lower() for tok in (
            "that", "the third one", "the second one", "the first one", "that folder", "that file", "those results"
        ))
        if ambiguous and not ref and not self.conversation.active_options and not self.conversation.artifact_ledger:
            self.conversation.add_scar("unresolved_reference", reason=user_input, severity=0.1)
            return self.clarification_prompt(user_input)
        if goal == "clarify" or self._dialogue_uncertain(mode):
            if not ref and self.conversation.unresolved_references:
                self.conversation.add_scar("unresolved_reference", reason=user_input, severity=0.1)
                return self.clarification_prompt(user_input)
        bundle = self.retrieval.retrieve_context_bundle(self.conversation.current_topic or user_input, mode) if self.retrieval else []
        resolved = self.conversation.resolve_reference(user_input)
        if goal == "continue":
            cs = self.conversation
            th = cs.active_thread()
            subj_label = (cs.current_subject or {}).get("human_label") or cs.last_subject
            seed = subj_label or (th or {}).get("topic") or resolved or cs.current_topic or "the current thread"
            # Prefer subject-bound content over stale parent fragments
            base = self._subject_content(subj_label, mode="continue")
            if not base:
                claims = []
                for ev in bundle:
                    if ev.type == "answer_fragment":
                        claims = ev.value.get("main_claims", [])[:2]
                        break
                if claims:
                    base = "\n".join(f"- {c}" for c in claims)
                elif self._last_result and not self._is_wrapper(self._last_result):
                    base = self._last_result
                else:
                    base = cs.summary()
            return f"Continuing on {seed}:\n{base}"
        if goal == "summarize":
            cs = self.conversation
            subj_label = (cs.current_subject or {}).get("human_label") or cs.last_subject
            subject = subj_label or resolved
            if subject:
                # Prefer subject-bound content
                content = self._subject_content(subj_label)
                if content:
                    return f"Summary of {subject}:\n{content}"
                # Fall back to subject-matching answer fragment
                frag = self._find_subject_fragment(subj_label)
                if frag:
                    claims = frag.get("main_claims", [])
                    if claims:
                        return f"Summary of {subject}:\n" + "\n".join(f"- {c}" for c in claims[:4])
                return f"Summary of {subject}:\n{cs.summary()}"
            frags = cs.answer_fragments
            if frags:
                last_frag = frags[-1]
                claims = last_frag.get("main_claims", [])
                topic = last_frag.get("topic") or cs.current_topic or "recent activity"
                if claims:
                    return f"Summary of {topic}:\n" + "\n".join(f"- {c}" for c in claims[:4])
            th = cs.active_thread()
            if th:
                episodes = th.get("linked_episodes", [])[-3:]
                lines = [f"Thread: {th.get('topic', '?')}"]
                for ep in episodes:
                    lines.append(f"- {ep.get('user', '')[:80]}")
                return "\n".join(lines)
            return cs.summary()
        if goal == "acknowledge_correction" and resolved:
            kind = self.conversation._infer_subject_kind(resolved)
            self.conversation.set_current_subject(kind=kind, label=resolved, confidence=0.9)
            return f"Got it. You mean: {resolved}"
        if resolved and act in {"correction", "statement"}:
            kind = self.conversation._infer_subject_kind(resolved)
            self.conversation.set_current_subject(kind=kind, label=resolved, confidence=0.85)
            return f"I'm tracking {resolved} in the current thread."
        if self.responder:
            return self.responder.respond(user_input, self.memory)
        return self.conversation.summary() or "No context available."

    def _handle_introspection(self, user_input: str) -> str:
        cs = self.conversation
        low = user_input.lower()
        # Crown-jewel: current subject
        if any(tok in low for tok in ("current subject", "what is the subject", "what subject")):
            subj = cs.current_subject
            if not subj:
                return f"No subject selected yet.\nTopic: {cs.current_topic or '(none)'}"
            label = subj.get("human_label", "?")
            kind = subj.get("kind", "?")
            lines = [f"Current subject: {label} ({kind})"]
            # Enrich with file role if available
            if kind == "file":
                enrichment = self._enrich_file(label, mode="summary")
                if enrichment:
                    for el in enrichment.splitlines()[1:4]:  # skip "File:" line, take role+symbols
                        lines.append(f"  {el}")
            if subj.get("related_artifacts"):
                lines.append(f"  Related: {', '.join(subj['related_artifacts'][:5])}")
            th = cs.active_thread()
            if th:
                lines.append(f"  In thread: {th.get('topic', '?')}")
            return "\n".join(lines)
        # Crown-jewel: why are we talking about this
        if "why" in low and any(tok in low for tok in ("talking", "discussing")):
            th = cs.active_thread()
            subj = cs.current_subject
            lines = []
            if subj and th:
                eps = th.get("linked_episodes", [])
                origin = eps[0].get("user", "?")[:80] if eps else "?"
                lines.append(f"You selected {subj.get('human_label', '?')} from the {th.get('topic', '?')} thread.")
                lines.append(f"Thread started with: \"{origin}\"")
            elif subj:
                lines.append(f"Current subject: {subj.get('human_label', '?')}")
            if cs.current_topic and (not subj or cs.current_topic != subj.get("human_label")):
                lines.append(f"Active topic: {cs.current_topic}")
            return "\n".join(lines) if lines else "No context for why we are discussing this."
        # Crown-jewel: what evidence / what supports
        if any(tok in low for tok in ("what evidence", "what supports")):
            subj = cs.current_subject
            lines = []
            if subj:
                label = subj.get("human_label", "?")
                lines.append(f"Evidence for {label}:")
                # File-level evidence
                if subj.get("kind") == "file":
                    enrichment = self._enrich_file(label)
                    if enrichment:
                        for el in enrichment.splitlines()[:4]:
                            lines.append(f"  {el}")
                # Artifact links
                for aid in subj.get("related_artifacts", [])[:5]:
                    art = next((a for a in cs.artifact_ledger if a.get("id") == aid), None)
                    if art:
                        lines.append(f"  - [{art.get('status', '?')}] {art.get('gist', '?')}")
                # Selection history
                th = cs.active_thread()
                if th:
                    eps = th.get("linked_episodes", [])
                    if eps:
                        lines.append(f"  Selected during: \"{eps[0].get('user', '?')[:60]}\"")
            else:
                lines.append("No subject selected — no evidence to show.")
            return "\n".join(lines)
        # Crown-jewel: what else did you think / what other
        if any(tok in low for tok in ("what else", "what other")):
            subj = cs.current_subject
            lines = []
            # Nearby artifacts as alternatives
            if subj:
                label = subj.get("human_label", "").lower()
                nearby = [a.get("gist", "") for a in cs.artifact_ledger
                          if a.get("gist", "").lower() != label and a.get("gist")][-6:]
                if nearby:
                    lines.append("Other items in the same result set:")
                    for n in nearby:
                        lines.append(f"  - {n}")
            alts = cs.contrastive_alternatives()
            if alts:
                lines.append("Previous conclusions:")
                for a in alts:
                    lines.append(f"  - {a}")
            corrected = cs.corrected_artifacts()
            if corrected:
                lines.append("Corrected:")
                for art in corrected:
                    lines.append(f"  - {art.get('gist', '?')}")
            return "\n".join(lines) if lines else "No alternative interpretations available."
        # Crown-jewel: what changed / what was corrected
        if any(tok in low for tok in ("what changed", "what was corrected")):
            th = cs.active_thread()
            subj = cs.current_subject
            lines = []
            if subj and cs.previous_topic:
                lines.append(f"Moved from {cs.previous_topic} to {subj.get('human_label', '?')}.")
            elif subj:
                lines.append(f"Selected {subj.get('human_label', '?')} as current subject.")
            if th:
                superseded = th.get("superseded_conclusions", [])
                if superseded:
                    lines.append("Superseded:")
                    for s in superseded[-4:]:
                        lines.append(f"  - {s}")
                if th.get("resolved_conclusion"):
                    lines.append(f"Current conclusion: {th['resolved_conclusion']}")
            corrected = cs.corrected_artifacts()
            if corrected:
                lines.append("Corrected:")
                for art in corrected:
                    lines.append(f"  - {art.get('gist', '?')}")
            return "\n".join(lines) if lines else "No changes recorded."
        # Existing: referring / think i mean / what do you mean
        if any(tok in low for tok in ("referring", "think i mean", "what do you mean")):
            lines = []
            subj = cs.current_subject
            if subj:
                lines.append(f"Current subject: {subj.get('human_label', '?')} ({subj.get('kind', '?')})")
            elif cs.last_subject:
                lines.append(f"Current subject: {cs.last_subject}")
            if cs.current_topic:
                lines.append(f"Current topic: {cs.current_topic}")
            if cs.active_artifacts:
                lines.append(f"Recent artifacts: {', '.join(cs.active_artifacts[-3:])}")
            if cs.unresolved_references:
                lines.append(f"Unresolved: {', '.join(cs.unresolved_references)}")
            th = cs.active_thread()
            if th:
                lines.append(f"Active thread: {th.get('topic', '?')}")
            return "\n".join(lines) if lines else "No active context to refer to."
        if "subject" in low:
            subj = cs.current_subject
            if subj:
                return f"Current subject: {subj.get('human_label', '?')} ({subj.get('kind', '?')})\nTopic: {cs.current_topic or '(none)'}"
            return f"Current subject: {cs.last_subject or '(none)'}\nCurrent topic: {cs.current_topic or '(none)'}"
        if "artifact" in low:
            arts = cs.active_artifacts[-8:]
            if not arts:
                return "No active artifacts."
            return "Active artifacts:\n" + "\n".join(f"  {i}. {a}" for i, a in enumerate(arts, 1))
        if "thread" in low:
            th = cs.active_thread()
            if not th:
                return "No active thread."
            eps = th.get("linked_episodes", [])[-3:]
            lines = [f"Thread: {th.get('topic', '?')} (state: {th.get('current_state', '?')})"]
            if th.get("current_subject"):
                lines.append(f"  Subject: {th['current_subject'].get('human_label', '?')}")
            for ep in eps:
                lines.append(f"  - {ep.get('user', '')[:80]}")
            return "\n".join(lines)
        if "unresolved" in low:
            refs = cs.unresolved_references
            if not refs:
                return "No unresolved references."
            return "Unresolved references:\n" + "\n".join(f"  - {r}" for r in refs)
        lines = []
        lines.append(f"Current topic: {cs.current_topic or '(none)'}")
        if cs.previous_topic:
            lines.append(f"Previous topic: {cs.previous_topic}")
        if cs.current_subject:
            lines.append(f"Subject: {cs.current_subject.get('human_label', '?')} ({cs.current_subject.get('kind', '?')})")
        if cs.active_artifacts:
            lines.append(f"Artifacts: {len(cs.artifact_ledger)} ({', '.join(cs.active_artifacts[-3:])})")
        if cs.threads:
            lines.append(f"Threads: {len(cs.threads)}")
        if cs.scars:
            lines.append(f"Scars: {', '.join(cs.scars.keys())}")
        return "\n".join(lines) if lines else "No active conversation state."

    @staticmethod
    def _is_wrapper(text: str) -> bool:
        return any(text.startswith(p) for p in (
            "Got it.", "I'm tracking", "Which ", "Current subject", "Current topic",
            "No active", "No current", "No changes", "No alternative", "Subject:",
            "Thread:", "Summary of", "Continuing on",
        ))

    def _subject_content(self, subj_label: str, mode: str = "summary") -> str:
        """Build enriched content string for the current subject."""
        if not subj_label:
            return ""
        cs = self.conversation
        subj = cs.current_subject or {}
        kind = subj.get("kind", cs._infer_subject_kind(subj_label))
        # File enrichment: read the actual file for role/symbols
        if kind == "file":
            enrichment = self._enrich_file(subj_label, mode)
            if enrichment:
                return enrichment
        # Folder: list what's known
        if kind == "folder":
            arts = [a.get("gist", "") for a in cs.artifact_ledger if subj_label.lower() in a.get("raw", "").lower()]
            if arts:
                return f"{subj_label}/ contains: {', '.join(arts[:8])}"
        # Fallback: artifact raw or thread episode
        low = subj_label.lower()
        matching = [a for a in cs.artifact_ledger if low in a.get("gist", "").lower()]
        if matching:
            raw = matching[-1].get("raw", "")
            if raw and not self._is_wrapper(raw) and raw.lower() != low:
                return raw[:300]
        th = cs.active_thread()
        if th:
            for ep in reversed(th.get("linked_episodes", [])[-5:]):
                resp = ep.get("response", "")
                if low in resp.lower() and not self._is_wrapper(resp):
                    return resp[:300]
        return ""

    def _enrich_file(self, filename: str, mode: str = "summary") -> str:
        """Read a file and extract role, docstring, and top symbols."""
        from agent.bootstrap import get_project_root
        root = get_project_root()
        # Try to find the file
        candidates = list(root.rglob(filename))
        candidates = [c for c in candidates if ".venv" not in str(c) and "__pycache__" not in str(c)]
        if not candidates:
            return ""
        fpath = candidates[0]
        try:
            lines = fpath.read_text(errors="replace").splitlines()[:60]
        except Exception:
            return ""
        text = "\n".join(lines)
        parts = []
        relpath = str(fpath.relative_to(root))
        parts.append(f"File: {relpath}")
        # Extract module docstring
        doc = self._extract_docstring(text)
        if doc:
            parts.append(f"Role: {doc}")
        # Extract top-level classes and functions
        symbols = []
        for line in lines:
            m = re.match(r"^(class|def)\s+(\w+)", line)
            if m:
                symbols.append(f"{m.group(1)} {m.group(2)}")
        if symbols:
            parts.append(f"Symbols: {', '.join(symbols[:8])}")
        # Thread connection
        th = self.conversation.active_thread()
        if th:
            parts.append(f"Thread: {th.get('topic', '?')}")
        if mode == "continue":
            # Add relationships hint
            imports = [l.strip() for l in lines if l.startswith(("from ", "import ")) and "." in l][:4]
            if imports:
                parts.append("Imports: " + "; ".join(imports))
        return "\n".join(parts)

    @staticmethod
    def _extract_docstring(text: str) -> str:
        """Extract module-level docstring from Python source."""
        m = re.search(r'^(?:from\s|import\s|#).*?\n*"""(.+?)"""', text, re.DOTALL)
        if not m:
            m = re.search(r'^"""(.+?)"""', text, re.DOTALL)
        if not m:
            m = re.search(r"^'''(.+?)'''", text, re.DOTALL)
        if m:
            doc = m.group(1).strip().splitlines()[0].strip()
            return doc[:120]
        return ""

    def _find_subject_fragment(self, subj_label: str):
        """Find an answer fragment whose topic matches the subject."""
        if not subj_label:
            return None
        cs = self.conversation
        low = subj_label.lower()
        # Search fragments in reverse (newest first)
        for frag in reversed(cs.answer_fragments):
            ftopic = (frag.get("topic") or "").lower()
            if low in ftopic or ftopic in low:
                return frag
        # Fall back to last fragment if any
        return cs.answer_fragments[-1] if cs.answer_fragments else None

    def _dialogue_uncertain(self, mode: str) -> bool:
        if not self.retrieval:
            return False
        bundle = self.retrieval.retrieve_context_bundle(self.conversation.current_topic or "", mode)
        if not bundle:
            return True
        flags = self.conversation.uncertainty_flags()
        return flags.get("has_unresolved_references", False) and flags.get("thread_missing", False)
