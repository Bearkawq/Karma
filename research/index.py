"""NoteWriter — produce structured notes from fetched artifacts and save to memory.

Evidence-first: every fact references artifact IDs.
Also extracts language equivalences (synonyms, slang) for the Normalizer.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.langmap import extract_mappings, store_mappings


class NoteWriter:
    """Produce structured notes from fetched artifacts and save to memory."""

    def __init__(self, memory=None, bus=None):
        self.memory = memory
        self.bus = bus

    def write_note(self, topic: str, artifacts: List[Dict[str, Any]],
                   session_id: str) -> Dict[str, Any]:
        """Produce a structured note from artifacts for a single subtopic slice."""
        texts = [a.get("text", "") for a in artifacts if a]
        combined = " ".join(texts)

        code_patterns = self._extract_code_patterns(combined)
        solutions = self._extract_solutions(combined, topic)

        # Extract structured information
        concepts = self._extract_concepts(combined, topic)
        commands = self._extract_commands(combined)
        procedures = self._extract_procedures(combined, topic)
        caveats = self._extract_caveats(combined)

        # Score evidence quality
        evidence_quality = self._score_evidence_quality(combined, artifacts)

        note = {
            "topic": topic,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "summary": self._summarize(combined, topic),
            "key_points": self._extract_key_points(combined),
            "code_snippets": self._extract_code(combined),
            "code_patterns": code_patterns,
            "solutions": solutions,
            "open_questions": self._identify_questions(combined, topic),
            "concepts": concepts,
            "commands": commands,
            "procedures": procedures,
            "caveats": caveats,
            "evidence_quality": evidence_quality,
            "evidence": [
                {"artifact_id": a["id"], "url": a["url"], "title": a.get("title", ""), "quality": self._score_single_artifact(a)}
                for a in artifacts if a
            ],
            "artifact_ids": [a["id"] for a in artifacts if a],
        }

        self._persist_to_memory(note)

        # Extract language equivalences and store as lang:map:* facts
        lang_count = self._extract_language_mappings(combined, note["artifact_ids"], session_id)

        if self.bus:
            self.bus.emit("note_written", topic=topic,
                          key_points=len(note["key_points"]),
                          artifacts=len(note["artifact_ids"]),
                          lang_mappings=lang_count)
        return note

    def _score_single_artifact(self, artifact: Dict[str, Any]) -> str:
        """Score a single artifact's quality."""
        text = artifact.get("text", "")
        size = len(text)
        
        if size < 200:
            return "weak"
        if size > 5000:
            return "strong"
        return "medium"

    def _score_evidence_quality(self, combined: str, artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Score the overall evidence quality for a note."""
        total_text = sum(len(a.get("text", "")) for a in artifacts if a)
        artifact_count = len([a for a in artifacts if a])
        
        if total_text < 500:
            level = "weak"
        elif total_text < 2000:
            level = "medium"
        else:
            level = "strong"
        
        return {
            "level": level,
            "total_text_bytes": total_text,
            "artifact_count": artifact_count,
        }

    def _extract_concepts(self, text: str, topic: str) -> List[str]:
        """Extract key concepts/definitions from text."""
        concepts = []
        topic_words = set(topic.lower().split())
        
        definition_patterns = [
            r"(\w+(?:\s+\w+)?)\s+is\s+(?:a|an|the)\s+[^.!?]{10,100}",
            r"(\w+(?:\s+\w+)?)\s+refers\s+to\s+[^.!?]{10,100}",
            r"(\w+(?:\s+\w+)?)\s+means\s+[^.!?]{10,100}",
        ]
        
        for pattern in definition_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                phrase = match.group(0).strip()
                if 15 < len(phrase) < 150:
                    concepts.append(phrase)
                if len(concepts) >= 5:
                    break
            if len(concepts) >= 5:
                break
        
        return concepts[:5]

    def _extract_commands(self, text: str) -> List[str]:
        """Extract command-line examples from text."""
        commands = []
        
        cmd_patterns = [
            r"\$\s+[a-zA-Z0-9_\-./]+[^\n]{5,100}",
            r">\s+[a-zA-Z0-9_\-./]+[^\n]{5,100}",
            r"pip\s+install\s+[^\n]{5,50}",
            r"npm\s+install\s+[^\n]{5,50}",
            r"git\s+\w+[^\n]{5,50}",
            r"python\s+[^\n]{5,50}",
            r"curl\s+[^\n]{5,100}",
        ]
        
        for pattern in cmd_patterns:
            for match in re.finditer(pattern, text):
                cmd = match.group(0).strip()
                if cmd and len(cmd) > 5:
                    commands.append(cmd)
                if len(commands) >= 5:
                    break
            if len(commands) >= 5:
                break
        
        return commands[:5]

    def _extract_procedures(self, text: str, topic: str) -> List[Dict[str, str]]:
        """Extract step-by-step procedures from text."""
        procedures = []
        
        step_patterns = [
            r"(?:step\s+)?\d+[\.\)]\s*([^.\n]{10,100})",
            r"first(?:ly)?\s+([^.\n]{10,100})",
            r"second(?:ly)?\s+([^.\n]{10,100})",
            r"then\s+([^.\n]{10,100})",
            r"next\s+([^.\n]{10,100})",
            r"finally\s+([^.\n]{10,100})",
        ]
        
        for pattern in step_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                step = match.group(1).strip()
                if len(step) > 10:
                    procedures.append({"step": step})
                if len(procedures) >= 5:
                    break
            if len(procedures) >= 5:
                break
        
        return procedures[:5]

    def _extract_caveats(self, text: str) -> List[str]:
        """Extract warnings and caveats from text."""
        caveats = []
        
        caveat_patterns = [
            r"(?:warning|caution|注意)[^:]*:\s*([^.\n]{10,100})",
            r"(?:but|however|although)[^.]*not\s+[^.!?]{10,100}",
            r"(?:don't|do\s+not|avoid)[^.!?]{10,100}",
            r"(?:careful|注意)[^.!?]{10,100}",
            r"(?:error|fail|exception)[^.]*(?:when|if|in)[^.!?]{10,100}",
        ]
        
        for pattern in caveat_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                caveat = match.group(0).strip()
                if len(caveat) > 15:
                    caveats.append(caveat)
                if len(caveats) >= 3:
                    break
            if len(caveats) >= 3:
                break
        
        return caveats[:3]

    # ── extraction heuristics ─────────────────────────────────

    _NAV_WORDS = frozenset({
        "skip to", "previous topic", "next topic", "start here",
        "learn more", "sign up", "log in", "subscribe", "cookie",
        "privacy policy", "terms of", "copyright", "all rights",
        "click here", "read more", "share this", "follow us",
        "newsletter", "advertisement", "sponsored", "related posts",
        "table of contents", "back to top", "jump to", "toggle menu",
        "accept cookies", "manage preferences", "dismiss",
    })

    # Sentence-level junk filter: reject lines that are mostly non-informative
    _JUNK_INDICATORS = re.compile(
        r"(?:click|tap|swipe|scroll|download|install our app|"
        r"©\s*\d{4}|all rights reserved|terms of service|"
        r"this (?:post|article|page) (?:was|is) (?:published|written|updated)|"
        r"^\s*(?:home|about|contact|faq|menu|search)\s*$)",
        re.IGNORECASE,
    )

    def _summarize(self, text: str, topic: str) -> str:
        # Collapse whitespace before splitting
        clean = " ".join(text.split())
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        topic_words = set(topic.lower().split())
        relevant: List[str] = []
        for s in sentences:
            s = s.strip()
            if len(s) < 40 or len(s) > 400:
                continue
            s_low = s.lower()
            if any(nav in s_low for nav in self._NAV_WORDS):
                continue
            if self._JUNK_INDICATORS.search(s):
                continue
            if any(w in s_low for w in topic_words):
                relevant.append(s)
            if len(relevant) >= 3:
                break
        if not relevant:
            for s in sentences:
                s = s.strip()
                if 40 < len(s) < 400:
                    s_low = s.lower()
                    if not any(nav in s_low for nav in self._NAV_WORDS) \
                       and not self._JUNK_INDICATORS.search(s):
                        relevant.append(s)
                if len(relevant) >= 3:
                    break
        return " ".join(relevant)[:1000]

    def _extract_key_points(self, text: str) -> List[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        patterns = [
            r"\bis\b.*\b(?:a|an|the)\b",
            r"\bprovides?\b",
            r"\benables?\b",
            r"\brequires?\b",
            r"\bsupports?\b",
            r"\bcan be\b",
            r"\bused (?:for|to|in)\b",
            r"\b(?:important|key|critical|essential)\b",
        ]
        points: List[str] = []
        for s in sentences:
            if len(s) < 30 or len(s) > 300:
                continue
            s_stripped = s.strip()
            # Skip navigation/boilerplate/junk
            s_low = s_stripped.lower()
            if any(nav in s_low for nav in self._NAV_WORDS):
                continue
            if self._JUNK_INDICATORS.search(s_stripped):
                continue
            # Prefer sentences with technical density (numbers, code-like tokens)
            for pattern in patterns:
                if re.search(pattern, s_stripped, re.IGNORECASE):
                    if s_stripped not in points:
                        points.append(s_stripped)
                    break
            if len(points) >= 8:
                break
        return points

    def _extract_code(self, text: str) -> List[str]:
        snippets: List[str] = []
        code_patterns = [
            r"```[\s\S]*?```",
            r"(?:def |class |import |from |pip install|npm install|curl |wget |sudo )\S.*",
            # Inline code blocks
            r"`[^`]{10,200}`",
            # Variable assignments
            r"(?:^|\n)\s*\w+\s*=\s*(?:\{|\[|\"|\').{5,200}",
            # Shell one-liners
            r"\$\s+\S+.*",
        ]
        for pattern in code_patterns:
            for m in re.findall(pattern, text):
                clean = m.strip().strip("`")
                if clean and 10 < len(clean) < 500 and clean not in snippets:
                    snippets.append(clean)
                if len(snippets) >= 10:
                    break
            if len(snippets) >= 10:
                break
        return snippets

    def _identify_questions(self, text: str, topic: str) -> List[str]:
        questions: List[str] = []
        for q in re.findall(r"[^.!?]*\?", text):
            q = q.strip()
            if 15 < len(q) < 200:
                questions.append(q)
            if len(questions) >= 3:
                break
        for v in re.findall(r"[^.]*(?:unclear|unknown|debat|controver|depend)[^.]*\.",
                            text, re.IGNORECASE)[:2]:
            questions.append(f"[gap] {v.strip()}")
        return questions[:5]

    # ── programming-specific extraction ──────────────────────

    def _extract_code_patterns(self, text: str) -> List[Dict[str, Any]]:
        """Extract code patterns: error→solution pairs, API signatures, import patterns."""
        patterns_found = []

        # Error → solution pairs (e.g. "NameError ... fix: import X")
        for m in re.finditer(
            r"(\w+(?:Error|Exception))\s*[:\-]\s*(.{10,200}?)(?:\.|$)"
            r".*?(?:fix|solution|resolve|workaround|answer)\s*[:\-]\s*(.{10,300}?)(?:\.|$)",
            text, re.IGNORECASE | re.DOTALL
        ):
            patterns_found.append({
                "type": "error_solution",
                "error": f"{m.group(1)}: {m.group(2).strip()}",
                "solution": m.group(3).strip(),
            })

        # Standalone errors with context
        for m in re.finditer(
            r"(\w+(?:Error|Exception))\s*:\s*(.{10,200}?)(?:\n|$)",
            text
        ):
            patterns_found.append({
                "type": "error_pattern",
                "error": m.group(1),
                "message": m.group(2).strip(),
            })

        # Function/method signatures: def name(args) -> return
        for m in re.finditer(
            r"def\s+(\w+)\(([^)]*)\)(?:\s*->\s*(\w+))?",
            text
        ):
            patterns_found.append({
                "type": "function_sig",
                "name": m.group(1),
                "args": m.group(2).strip(),
                "returns": m.group(3) or "",
            })

        # Import patterns: from X import Y, import X
        for m in re.finditer(r"(?:from\s+(\S+)\s+)?import\s+([\w, ]+)", text):
            module = m.group(1) or m.group(2).split(",")[0].strip()
            patterns_found.append({
                "type": "import_pattern",
                "module": module,
                "names": m.group(2).strip(),
            })

        # API usage: requests.get, os.path.join, etc.
        for m in re.finditer(r"(\w+(?:\.\w+){1,3})\(", text):
            call = m.group(1)
            if len(call) > 5 and not call[0].isupper():
                patterns_found.append({
                    "type": "api_call",
                    "call": call,
                })

        return patterns_found[:20]

    def _extract_solutions(self, text: str, topic: str) -> List[Dict[str, str]]:
        """Extract step-by-step solutions and how-to instructions."""
        solutions = []
        # Numbered steps
        steps = re.findall(r"(?:^|\n)\s*\d+[.)]\s+(.{15,200})", text)
        if len(steps) >= 2:
            solutions.append({
                "type": "steps",
                "topic": topic,
                "steps": steps[:10],
            })

        # "To X, you need to Y" patterns
        for m in re.finditer(
            r"[Tt]o\s+(\w.{10,80}?),\s*(?:you\s+)?(?:need to|can|should|must)\s+(.{10,200}?)(?:\.|$)",
            text
        ):
            solutions.append({
                "type": "how_to",
                "goal": m.group(1).strip(),
                "method": m.group(2).strip(),
            })

        return solutions[:8]

    # ── language mapping extraction ───────────────────────────

    def _extract_language_mappings(self, text: str, artifact_ids: List[str],
                                   session_id: str) -> int:
        """Scan text for synonym/equivalence patterns and store as lang:map:* facts."""
        if not self.memory:
            return 0
        mappings = extract_mappings(text, artifact_ids=artifact_ids)
        return store_mappings(mappings, self.memory, session_id)

    # ── memory persistence ────────────────────────────────────

    def _persist_to_memory(self, note: Dict[str, Any]) -> None:
        if not self.memory:
            return
        topic = note["topic"]
        session_id = note["session_id"]
        source = f"golearn:{session_id}"
        topic_key = topic.lower().replace(" ", "_")

        if note["summary"]:
            self.memory.save_fact(
                key=f"learn:{topic}:summary",
                value=note["summary"],
                source=source,
                confidence=0.7,
            )
        for i, point in enumerate(note["key_points"]):
            self.memory.save_fact(
                key=f"learn:{topic}:point_{i}",
                value=point,
                source=source,
                confidence=0.6,
            )

        # Persist code snippets
        for i, snippet in enumerate(note.get("code_snippets", [])[:5]):
            self.memory.save_fact(
                key=f"code:{topic_key}:snippet_{i}",
                value=snippet,
                source=source,
                confidence=0.65,
            )

        # Persist code patterns (error→solution, function sigs, API calls)
        for i, pat in enumerate(note.get("code_patterns", [])[:10]):
            ptype = pat.get("type", "unknown")
            if ptype == "error_solution":
                self.memory.save_fact(
                    key=f"solution:{topic_key}:error_{i}",
                    value=f"{pat['error']} → {pat['solution']}",
                    source=source,
                    confidence=0.75,
                )
            elif ptype == "error_pattern":
                self.memory.save_fact(
                    key=f"error:{topic_key}:{pat['error'].lower()}_{i}",
                    value=pat.get("message", ""),
                    source=source,
                    confidence=0.6,
                )
            elif ptype == "function_sig":
                self.memory.save_fact(
                    key=f"code:{topic_key}:func_{pat['name']}",
                    value=f"def {pat['name']}({pat['args']})" + (f" -> {pat['returns']}" if pat.get('returns') else ""),
                    source=source,
                    confidence=0.7,
                )
            elif ptype == "import_pattern":
                self.memory.save_fact(
                    key=f"pattern:{topic_key}:import_{pat['module'].replace('.', '_')}",
                    value=f"import {pat['names']}" + (f" from {pat['module']}" if pat.get('module') != pat['names'].split(',')[0].strip() else ""),
                    source=source,
                    confidence=0.7,
                )
            elif ptype == "api_call":
                self.memory.save_fact(
                    key=f"pattern:{topic_key}:api_{pat['call'].replace('.', '_')}",
                    value=f"{pat['call']}()",
                    source=source,
                    confidence=0.6,
                )

        # Persist solutions (how-to, steps)
        for i, sol in enumerate(note.get("solutions", [])[:5]):
            if sol["type"] == "steps":
                val = " | ".join(sol["steps"][:5])
                self.memory.save_fact(
                    key=f"solution:{topic_key}:steps_{i}",
                    value=val,
                    source=source,
                    confidence=0.7,
                )
            elif sol["type"] == "how_to":
                self.memory.save_fact(
                    key=f"solution:{topic_key}:howto_{i}",
                    value=f"To {sol['goal']}: {sol['method']}",
                    source=source,
                    confidence=0.65,
                )

    # ── report generation ─────────────────────────────────────

    def generate_report(self, session_id: str, root_topic: str,
                        notes: List[Dict[str, Any]], elapsed_seconds: float,
                        visited_topics: List[str], report_path: Path,
                        provider: Optional[str] = None, provider_code: Optional[str] = None,
                        provider_diagnostic: Optional[str] = None, stop_reason: Optional[str] = None,
                        accepted_sources: Optional[int] = None, useful_artifacts: Optional[int] = None,
                        cache_status: Optional[str] = None, cache_hits: Optional[int] = None,
                        providers_attempted: Optional[List[str]] = None,
                        provider_used: Optional[str] = None,
                        provider_failures: Optional[Dict[str, str]] = None,
                        result_origin: Optional[str] = None,
                        accepted_sources_live: Optional[int] = None,
                        accepted_sources_cached: Optional[int] = None,
                        useful_artifacts_live: Optional[int] = None,
                        useful_artifacts_cached: Optional[int] = None) -> str:
        sources_count = sum(len(n.get('artifact_ids', [])) for n in notes)
        
        lines = [
            f"# GoLearn Report: {root_topic}",
            "",
            f"**Session**: {session_id}",
            f"**Duration**: {elapsed_seconds:.0f}s",
            f"**Search provider**: {provider or 'duckduckgo'}",
            f"**Topics explored**: {len(visited_topics)}",
            f"**Sources fetched**: {sources_count}",
        ]
        
        # PHASE 2: MultiProvider truth - show all providers attempted
        if providers_attempted:
            lines.append(f"**Providers attempted**: {', '.join(providers_attempted)}")
        if provider_used:
            lines.append(f"**Provider used**: {provider_used}")
        if provider_failures:
            lines.append("**Provider failures**:")
            for prov, fail in provider_failures.items():
                lines.append(f"  - {prov}: {fail}")
        
        # PHASE 3: Cache truth - show result origin
        if result_origin:
            origin_label = {
                "live": "Fresh live web search",
                "cache": "Cached/local replay only",
                "mixed": "Mixed live and cached sources",
                "live_failed": "Live search failed, fallback used",
            }.get(result_origin, result_origin)
            lines.append(f"**Result origin**: {origin_label}")
        
        # Add cache status if available
        if cache_status:
            lines.append(f"**Cache status**: {cache_status}")
            if cache_hits is not None and cache_hits > 0:
                lines.append(f"**Cache hits**: {cache_hits}")
        
        # Add provider diagnostics if available
        if provider_code or provider_diagnostic:
            lines.append(f"**Provider status**: {provider_code or 'ok'}")
            if provider_diagnostic:
                lines.append(f"**Provider message**: {provider_diagnostic}")
        
        # PHASE 4: Artifact truth - separate live vs cached
        if accepted_sources is not None:
            live_str = f" (live: {accepted_sources_live})" if accepted_sources_live else ""
            cached_str = f" (cached: {accepted_sources_cached})" if accepted_sources_cached else ""
            lines.append(f"**Accepted sources**: {accepted_sources}{live_str}{cached_str}")
        
        if useful_artifacts is not None:
            live_str = f" (live: {useful_artifacts_live})" if useful_artifacts_live else ""
            cached_str = f" (cached: {useful_artifacts_cached})" if useful_artifacts_cached else ""
            lines.append(f"**Useful artifacts**: {useful_artifacts}{live_str}{cached_str}")
        
        # Add stop reason if available
        if stop_reason:
            lines.append(f"**Stop reason**: {stop_reason}")
        
        # Add provenance warning for cache-only replay
        if result_origin in ("cache", "cache_replay_only") or cache_status in ("cache_hit",):
            lines.append("")
            lines.append("> **Note**: Results are from cache/local replay, not fresh live search.")
            
        lines.extend(["", "---", ""])

        for note in notes:
            lines.append(f"## {note['topic']}")
            lines.append("")
            if note.get("summary"):
                lines.append(f"**Summary**: {note['summary']}")
                lines.append("")
            if note.get("key_points"):
                lines.append("**Key Points**:")
                for pt in note["key_points"]:
                    lines.append(f"- {pt}")
                lines.append("")
            if note.get("code_snippets"):
                lines.append("**Code Snippets**:")
                for snippet in note["code_snippets"]:
                    lines.append(f"```\n{snippet}\n```")
                lines.append("")
            if note.get("code_patterns"):
                lines.append("**Code Patterns**:")
                for pat in note["code_patterns"]:
                    if pat["type"] == "error_solution":
                        lines.append(f"- {pat['error']} → {pat['solution']}")
                    elif pat["type"] == "function_sig":
                        sig = f"def {pat['name']}({pat['args']})"
                        if pat.get("returns"):
                            sig += f" -> {pat['returns']}"
                        lines.append(f"- `{sig}`")
                    elif pat["type"] == "api_call":
                        lines.append(f"- `{pat['call']}()`")
                lines.append("")
            if note.get("solutions"):
                lines.append("**Solutions**:")
                for sol in note["solutions"]:
                    if sol["type"] == "steps":
                        for j, step in enumerate(sol["steps"][:5], 1):
                            lines.append(f"  {j}. {step}")
                    elif sol["type"] == "how_to":
                        lines.append(f"- To {sol['goal']}: {sol['method']}")
                lines.append("")
            if note.get("open_questions"):
                lines.append("**Open Questions**:")
                for q in note["open_questions"]:
                    lines.append(f"- {q}")
                lines.append("")
            if note.get("evidence"):
                lines.append("**Sources**:")
                for e in note["evidence"]:
                    lines.append(f"- [{e['artifact_id']}] {e['title']} - {e['url']}")
                lines.append("")
            lines.extend(["---", ""])

        report_text = "\n".join(lines)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
        return report_text
