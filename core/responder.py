"""Responder — offline conversation engine.

Three layers:
  1. Learned responses (data/responses.json) — user-taught, grows over time
  2. Knowledge recall — fuzzy search over memory facts
  3. Base templates — hardcoded fallbacks so it's never mute
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class Responder:
    def __init__(self, base_dir: str, config: Dict[str, Any] = None, retrieval_bus=None):
        self.base_dir = Path(base_dir)
        self.config = config or {}
        self.responses_file = self.base_dir / "data" / "responses.json"
        self.learned: List[Dict[str, Any]] = []
        self._retrieval = retrieval_bus
        self._load_learned()

    # ── persistence ────────────────────────────────────────────

    def _load_learned(self):
        if self.responses_file.exists():
            try:
                with open(self.responses_file) as f:
                    data = json.load(f)
                self.learned = data.get("patterns", [])
            except Exception:
                self.learned = []

    def _save_learned(self):
        self.responses_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.responses_file, "w") as f:
            json.dump({"patterns": self.learned}, f, indent=2)

    # ── teach / forget ─────────────────────────────────────────

    def teach(self, trigger: str, response: str) -> str:
        """Add or update a learned response."""
        trigger_low = trigger.strip().lower()
        for entry in self.learned:
            if entry["trigger"] == trigger_low:
                entry["response"] = response
                entry["updated"] = datetime.now().isoformat()
                self._save_learned()
                return f"Updated response for '{trigger}'."
        self.learned.append({
            "trigger": trigger_low,
            "response": response,
            "confidence": 0.5,
            "uses": 0,
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
        })
        self._save_learned()
        return f"Learned: when you say '{trigger}', I'll respond with that."

    def forget(self, trigger: str) -> str:
        trigger_low = trigger.strip().lower()
        before = len(self.learned)
        self.learned = [e for e in self.learned if e["trigger"] != trigger_low]
        if len(self.learned) < before:
            self._save_learned()
            return f"Forgot response for '{trigger}'."
        return f"No learned response for '{trigger}'."

    # ── respond ────────────────────────────────────────────────

    def respond(self, text: str, memory=None) -> str:
        """Generate a response. Checks base templates first, then learned → evidence → facts.

        Base templates (greetings, identity, status) are checked BEFORE retrieval so that
        conversational queries like "are you functioning" are never answered with retrieved
        facts from the knowledge store.
        """
        text_low = text.strip().lower()

        # Layer 0: base templates — checked first so identity/status/greeting queries
        # are never intercepted by retrieval.
        base = self._base_response(text_low)
        if not base.startswith(("I don't understand", "Not sure")):
            return base

        # Layer 1: learned responses (user-taught, outrank retrieval)
        learned = self._match_learned(text_low)
        if learned:
            return learned

        # Layer 2: evidence-first answering via retrieval bus
        if self._retrieval:
            evidence_answer = self._evidence_answer(text_low)
            if evidence_answer:
                return evidence_answer

        # Layer 3: knowledge recall from facts
        if memory:
            knowledge = self._recall_knowledge(text_low, memory)
            if knowledge:
                return knowledge

        # Layer 4: if truly unknown and memory has facts, suggest guesses
        if memory:
            guesses = self._suggest_guesses(text_low, memory)
            if guesses:
                return guesses

        return base

    def _evidence_answer(self, text: str) -> Optional[str]:
        """Synthesize answer from retrieval bus evidence before falling back."""
        if not self._retrieval:
            return None
        evidence = self._retrieval.retrieve_context_bundle(text, "respond")
        # Filter to answer_fact hints with decent relevance
        answers = [e for e in evidence if e.effect_hint == "answer_fact" and e.relevance >= 0.3]
        if not answers:
            return None
        # Synthesize from top evidence
        lines = []
        seen = set()
        for item in answers[:6]:
            val = str(item.value)[:200]
            if val in seen:
                continue
            seen.add(val)
            source_tag = item.source.replace("_", " ")
            lines.append(f"  - {val}")
        if not lines:
            return None
        header = "Here's what I found:"
        return header + "\n" + "\n".join(lines)

    # ── layer 1: learned ───────────────────────────────────────

    def _match_learned(self, text: str) -> Optional[str]:
        best = None
        best_score = 0.0
        for entry in self.learned:
            score = self._fuzzy_score(text, entry["trigger"])
            if score < 0.4:
                continue
            weight = score * (1 + entry.get("uses", 0) * 0.1) * entry.get("confidence", 0.5)
            if weight > best_score:
                best_score = weight
                best = entry
        if best:
            best["uses"] = best.get("uses", 0) + 1
            self._save_learned()
            return best["response"]
        return None

    # ── layer 2: facts recall ──────────────────────────────────

    def _recall_knowledge(self, text: str, memory) -> Optional[str]:
        # Extract topic from "what is X", "tell me about X", "explain X"
        topic = None
        for pat in [
            r"(?:what\s+is|what\s+are|whats|what\'s)\s+(.+)",
            r"(?:tell\s+me\s+about|explain|describe)\s+(.+)",
            r"(?:do\s+you\s+know\s+about)\s+(.+)",
        ]:
            m = re.match(pat, text, re.IGNORECASE)
            if m:
                topic = m.group(1).strip().rstrip("?.")
                break

        # "what do you know" / "what have you learned"
        if re.match(r"what\s+(?:do\s+you\s+know|have\s+you\s+learned)", text):
            return self._summarize_knowledge(memory)

        if not topic:
            return None

        # Search facts for topic
        matches = []
        topic_words = set(topic.lower().split())
        for key, val in memory.facts.items():
            key_low = key.lower()
            if topic.lower() in key_low:
                matches.append((key, val, 1.0))
            else:
                key_words = set(key_low.replace(":", " ").replace("_", " ").split())
                overlap = len(topic_words & key_words)
                if overlap > 0:
                    matches.append((key, val, overlap / max(len(topic_words), 1)))

        if not matches:
            return f"I don't know about '{topic}' yet. Try: golearn \"{topic}\" 2"

        # Sort by relevance
        matches.sort(key=lambda x: x[2], reverse=True)

        # Build response from top matches
        lines = [f"Here's what I know about '{topic}':"]
        seen = set()
        for key, val, _score in matches[:8]:
            value = memory.get_fact_value(key, val) if hasattr(memory, 'get_fact_value') else (val.get("value", val) if isinstance(val, dict) else val)
            text_val = str(value)[:200]
            if text_val in seen:
                continue
            seen.add(text_val)
            # Clean up key for display
            display_key = key.split(":")[-1].replace("_", " ").strip()
            if display_key.startswith("point"):
                lines.append(f"  - {text_val}")
            elif display_key == "summary":
                lines.insert(1, text_val)
            else:
                lines.append(f"  [{display_key}] {text_val}")

        return "\n".join(lines)

    def _summarize_knowledge(self, memory) -> str:
        if not memory.facts:
            return "I don't know anything yet. Use golearn to teach me topics."
        # Group by topic
        topics = {}
        for key in memory.facts:
            parts = key.split(":")
            if len(parts) >= 2 and parts[0] == "learn":
                topic = parts[1]
                topics[topic] = topics.get(topic, 0) + 1
        if topics:
            lines = [f"I've learned about {len(topics)} topics:"]
            for t, count in sorted(topics.items(), key=lambda x: -x[1])[:15]:
                lines.append(f"  - {t} ({count} facts)")
            lines.append(f"\nTotal facts: {len(memory.facts)}")
            return "\n".join(lines)
        return f"I have {len(memory.facts)} facts stored, but no golearn topics yet."

    # ── layer 3: base templates ────────────────────────────────

    _BASE = [
        # Greetings (time-aware)
        (r"^good\s+morning\b", "_morning"),
        (r"^good\s+(afternoon|evening)\b", "_time_greet"),
        (r"^good\s+night\b", "_goodnight"),
        (r"^(hello|hi|hey|yo|sup|what'?s?\s*up|howdy|hola|ayo)\b", "_greet"),
        # Identity
        (r"^(who|what)\s+are\s+you", "_identity"),
        (r"^what'?s?\s+your\s+name", "_identity"),
        # Status / feelings
        (r"^how\s+are\s+you", "_status"),
        (r"^how'?s?\s+it\s+going", "_status"),
        (r"^you\s+(good|ok|alright|alive)\b", "_status"),
        (r"^(status|you\s+up)\b", "_status"),
        # Functioning / operational checks — explicit "are you X" phrasing
        (r"^(are\s+you|is\s+karma)\s+(functioning|working|operational|online|active|running|alive|ok|okay|fine|healthy)\b", "_status"),
        (r"^(functioning|operational)\b", "_status"),
        # Identity — agent type queries that otherwise fall through to the model
        (r"^(are|is)\s+you\s+(?:an?\s+)?(bot|ai|robot|program|computer|machine|assistant|virtual|language\s+model)\b", "_identity"),
        (r"^do\s+you\s+have\s+(feelings|emotions|consciousness|sentience|a\s+soul|desires)\b", "_purpose"),
        # Capability entry-points with "can you" phrasing
        (r"^can\s+you\s+help\s+(me|us)\b", "_help"),
        (r"^what\s+are\s+you\s+(good\s+at|capable\s+of|able\s+to|built\s+for)\b", "_help"),
        # Capabilities
        (r"^(help|what\s+can\s+you\s+do|commands|options)\b", "_help"),
        (r"^(what\s+do\s+you\s+do|how\s+do\s+you\s+work)\b", "_help"),
        # Gratitude
        (r"^(thanks|thank\s+you|thx|ty|cheers|appreciate\s+it)\b", "_thanks"),
        # Compliments (before agreement so "nice work" doesn't match "nice" alone)
        (r"^(good\s+job|nice\s+(?:work|one)|well\s+done|you\s*'?r?e?\s+(?:the\s+)?(?:best|great|awesome|goat|amazing|sick|fire))", "_compliment"),
        # Insults (before agreement so "you suck" etc. match first)
        (r"^you\s*'?r?e?\s+(?:trash|bad|dumb|stupid|useless|wack|mid)", "_insult"),
        (r"^you\s+suck", "_insult"),
        # Agreement / affirmation
        (r"^(ok|okay|cool|nice|bet|word|dope|sick|got\s+it|noted)\b", "_affirm"),
        (r"^(yes|yeah|yep|yup|ya|sure)\b", "_affirm"),
        # Disagreement
        (r"^(no|nah|nope|naw|negative)\b", "_disagree"),
        # Farewell
        (r"^(bye|goodbye|exit|quit|later|peace|see\s+ya|cya|dip)\b", "_bye"),
        # Boredom
        (r"^(i'?m?\s+bored|nothing\s+to\s+do|entertain\s+me)\b", "_bored"),
        # Time
        (r"^what\s+time\s+is\s+it\b", "_time"),
        (r"^what'?s?\s+the\s+(?:time|date)\b", "_time"),
        (r"^(date|today)\b", "_time"),
        # Ping / test
        (r"^(ping|test|you\s+there|alive)\b", "_ping"),
        # Jokes
        (r"^(tell\s+me\s+a\s+joke|joke|make\s+me\s+laugh)\b", "_joke"),
        # Meaning of life
        (r"^(meaning\s+of\s+life|what\s+is\s+the\s+meaning)\b", "_philosophy"),
        (r"^(why\s+do\s+you\s+exist|what'?s?\s+your\s+purpose)\b", "_purpose"),
    ]

    def _base_response(self, text: str) -> str:
        for pattern, method_name in self._BASE:
            if re.match(pattern, text, re.IGNORECASE):
                return getattr(self, method_name)()
        return self._unknown(text)

    def _morning(self) -> str:
        return "Morning. What are we working on today?"

    def _time_greet(self) -> str:
        return "What's up. Need something?"

    def _goodnight(self) -> str:
        return "Night. I'll be here when you're back."

    def _greet(self) -> str:
        return "Hey. I'm Karma — your local agent. Ask me something, run a command, or teach me."

    def _identity(self) -> str:
        v = self.config.get("system", {}).get("version", "?")
        return f"I'm Karma v{v} — a local autonomous agent. I run offline, learn from the web via golearn, execute tools, and remember what you teach me."

    def _status(self) -> str:
        return "I'm running. All systems local, no cloud, no APIs. What do you need?"

    def _thanks(self) -> str:
        return "No problem."

    def _affirm(self) -> str:
        return "Got it."

    def _disagree(self) -> str:
        return "Alright, what do you want instead?"

    def _help(self) -> str:
        return (
            "Here's what I can do:\n"
            "  - Answer questions from what I've learned (golearn topics)\n"
            "  - Learn new topics: golearn \"topic\" minutes\n"
            "  - Create tools: create tool \"name\" bash \"command\"\n"
            "  - Run tools: run tool name\n"
            "  - List/show files, search, run shell commands\n"
            "  - Teach me: teach \"trigger\" \"response\"\n"
            "  - Check memory: what do you know\n"
            "  - System: status, log, clean"
        )

    def _bye(self) -> str:
        return "Later."

    def _compliment(self) -> str:
        return "Appreciate it. Let's keep building."

    def _insult(self) -> str:
        return "Fair enough. Teach me better then."

    def _bored(self) -> str:
        return "Run golearn on a topic, create a tool, or ask me to explore something."

    def _time(self) -> str:
        from datetime import datetime
        now = datetime.now()
        return f"It's {now.strftime('%H:%M')} on {now.strftime('%A, %B %d %Y')}."

    def _ping(self) -> str:
        return "Pong. I'm here."

    def _joke(self) -> str:
        import random
        jokes = [
            "I'd tell you a UDP joke but you might not get it.",
            "There are 10 types of people — those who understand binary and those who don't.",
            "A SQL query walks into a bar, sees two tables, and asks... can I JOIN you?",
            "Why do programmers prefer dark mode? Because light attracts bugs.",
            "I tried to write a joke about recursion but I tried to write a joke about recursion.",
        ]
        return random.choice(jokes)

    def _philosophy(self) -> str:
        return "42. But more practically — learn, build, repeat."

    def _purpose(self) -> str:
        return "I exist to run tasks, learn topics, and get smarter the more you use me. No cloud, no leash."

    _CLARIFY_HINTS = [
        ({"list", "show", "file", "files", "dir", "directory", "folder"}, "list files [in /path]"),
        ({"read", "open", "cat", "view", "file"}, "read file <filename>"),
        ({"find", "search", "grep", "look", "where"}, 'search files <pattern> [in /path]'),
        ({"run", "exec", "execute", "shell", "command", "cmd"}, "run <command>"),
        ({"learn", "golearn", "research", "study", "teach"}, 'golearn "<topic>" <minutes>'),
        ({"tool", "create", "make", "build", "new"}, 'create tool "<name>" bash "<code>"'),
        ({"know", "memory", "fact", "remember", "recall"}, "what do you know"),
    ]

    def _unknown(self, text: str) -> str:
        words = set(text.lower().split())
        suggestions = []
        for keywords, hint in self._CLARIFY_HINTS:
            if words & keywords:
                suggestions.append(hint)
            if len(suggestions) >= 3:
                break
        if suggestions:
            opts = ", ".join(suggestions)
            return f"Not sure what you mean. Try: {opts}"
        return f"I don't understand '{text[:60]}'. Type 'help' to see what I can do."

    # ── guess suggestions ──────────────────────────────────────

    def _suggest_guesses(self, text: str, memory) -> Optional[str]:
        """If unknown input has word overlap with known facts, suggest guesses."""
        if not memory or not memory.facts:
            return None
        words = set(text.lower().split())
        if not words:
            return None
        matches: list = []
        for key in memory.facts:
            key_words = set(key.lower().replace(":", " ").replace("_", " ").split())
            overlap = len(words & key_words)
            if overlap > 0:
                matches.append((key, overlap))
        if not matches:
            return None
        matches.sort(key=lambda x: x[1], reverse=True)
        # Build suggestions from top 3 topics
        topics = []
        seen = set()
        for key, _ in matches[:6]:
            parts = key.split(":")
            topic = parts[1] if len(parts) >= 2 else parts[0]
            topic = topic.replace("_", " ")
            if topic not in seen:
                seen.add(topic)
                topics.append(topic)
            if len(topics) >= 3:
                break
        if not topics:
            return None
        suggestions = ", ".join(f"'{t}'" for t in topics)
        return f"Not sure what you mean. Did you mean something about {suggestions}? Type 'help' for commands."

    # ── fuzzy matching ─────────────────────────────────────────

    @staticmethod
    def _fuzzy_score(text: str, trigger: str) -> float:
        """Word overlap + substring score between 0 and 1."""
        if trigger in text or text in trigger:
            return 1.0
        t_words = set(text.split())
        r_words = set(trigger.split())
        if not r_words:
            return 0.0
        overlap = len(t_words & r_words)
        return overlap / max(len(r_words), len(t_words))
