"""Grammar Engine — flexible natural language command matching.

Maps casual phrasing to intents using pattern groups.
Runs BEFORE symbolic parsing. If confidence > 0.7, symbolic is skipped.
"""

import re
from typing import Dict, List, Optional, Tuple

GRAMMAR_RULES: Dict[str, List[str]] = {
    "list_files": [
        r"(?:list|show|display|what)\s*(?:me\s+)?(?:the\s+)?(?:all\s+)?files(?:\s+(?:in|at|from|under)\s+(?P<path>\S+))?",
        r"what\s+files\s+(?:are|do\s+we\s+have)(?:\s+(?:in|at|from|under)\s+(?P<path>\S+))?",
        r"(?:ls|dir)(?:\s+(?P<path>\S+))?",
        r"(?:show|list)\s+(?:the\s+)?(?:contents?|directory)(?:\s+(?:of|in|at|from)\s+(?P<path>\S+))?",
    ],
    "read_file": [
        r"(?:read|open|cat|view|show)\s+(?:the\s+)?(?:file\s+)?(?:named?\s+)?(?P<filename>\S+\.\w{1,5})",
        r"(?:what(?:'s| is) in|show me)\s+(?P<filename>\S+\.\w{1,5})",
    ],
    "search_files": [
        r"(?:find|search|look for|where(?:'s| is))\s+(?:the\s+)?(?:files?\s+)?(?:named?\s+|matching\s+|called\s+)?(?P<pattern>\S+)(?:\s+(?:in|at|from|under)\s+(?P<path>\S+))?",
        r"(?:can you |could you )?find\s+(?P<pattern>\S+)(?:\s+(?:in|at|from|under)\s+(?P<path>\S+))?",
    ],
    "code_run": [
        r"(?:run|execute)\s+(?:the\s+)?(?:code\s+|script\s+)?(?P<path>/\S+\.(?:py|sh))",
        r"(?:run|execute)\s+(?:code|script)\s+(?P<path>\S+\.(?:py|sh))",
    ],
    "code_read": [
        r"(?:read|show|view)\s+(?:the\s+)?(?:code\s+)?(?:in\s+|from\s+|of\s+)?(?P<path>/\S+\.(?:py|sh|js|ts|c|cpp|h|rs|go|java|rb))",
        r"(?:read|show|view)\s+(?:code|script)\s+(?P<path>\S+\.(?:py|sh|js|ts|c|cpp|h|rs|go|java|rb))",
    ],
    "code_debug": [
        r"debug\s+(?P<path>\S+\.(?:py|sh))",
    ],
    "code_structure": [
        r"(?:structure|outline|analyze)\s+(?:the\s+)?(?:code\s+)?(?:in\s+|of\s+)?(?P<path>\S+\.(?:py|sh|js|ts|c|cpp|h|rs|go|java|rb))",
    ],
    "run_shell": [
        r"(?:run|exec(?:ute)?)\s+(?P<cmd>.+)",
        r"(?:can you |please )?(?:run|execute)\s+(?P<cmd>.+)",
    ],
    "golearn": [
        r"(?:go\s*learn|learn about|research|study)\s+[\"']?(?P<topic>[^\"']+)[\"']?\s+(?P<minutes>\d+)(?:\s+(?P<mode>depth|breadth|auto))?",
        r"(?:go\s*learn|learn about|research|study)\s+[\"']?(?P<topic>[^\"']+)[\"']?\s+(?P<minutes>\d+)\s*$",
        r"(?:go\s*learn|learn about|research|study)\s+[\"']?(?P<topic>[^\"']+)[\"']?$",
    ],
    "ingest": [
        r"(?:ingest|import|load|seed)\s+(?P<path>\S+)",
        r"(?:ingest|import|load|seed)\s+seeds?\s+(?P<path>\S+)",
        r"golearn\s+(?:ingest|import|load)\s+(?P<path>\S+)",
        r"karma\s+(?:ingest|import|load)\s+(?P<path>\S+)",
    ],
    "pulse": [
        r"(?:show\s+)?(?:karma\s+)?pulse\b",
        r"(?:status|state)\b",
        r"what\s+is\s+karma\s+doing",
        r"(?:show|get)\s+(?:status|state)",
    ],
    "digest": [
        r"(?:run\s+)?digest\b",
        r"(?:auto-?)?ingest\b",
        r"process\s+drop\s*folder",
    ],
    "navigate": [
        r"navigate\s+wikipedia\s+(?P<topic>.+)",
        r"golearn\s+wikipedia\s+(?P<topic>.+)",
        r"crawl\s+wikipedia\s+(?P<topic>.+)",
        r"wiki\s+(?P<topic>.+)",
    ],
    "list_capabilities": [
        r"what\s+can\s+you\s+do",
        r"(?:help|commands|options|capabilities)\b",
        r"what\s+(?:do\s+you\s+do|are\s+your\s+(?:commands|capabilities))",
    ],
    "status_query": [
        r"any\s+errors\??",
        r"what\s+errors\??",
        r"what\s+failed\??",
        r"what\s+(?:do\s+you|do\s+i)\s+need\??",
        r"what\s+do\s+you\s+want\??",
        r"why\s+did\s+it\s+stop\??",
        r"what\s+should\s+i\s+feed\??",
        r"what\s+worked\??",
        r"what\s+happened\??",
        r"what\s+did\s+you\s+learn\??",
        r"what\s+(?:are|is)\s+the\s+blockers?\??",
    ],
    "list_custom_tools": [
        r"(?:list|show)\s+(?:my\s+)?(?:custom\s+)?tools",
        r"what\s+tools\s+(?:do\s+(?:i|we)\s+have|exist)",
    ],
}

# Pre-compile all patterns
_COMPILED: Dict[str, List[re.Pattern]] = {}
for _intent, _patterns in GRAMMAR_RULES.items():
    _COMPILED[_intent] = [re.compile(p, re.IGNORECASE) for p in _patterns]


# Code intents get a priority boost over generic shell dispatch
_CODE_INTENTS = frozenset({"code_run", "code_read", "code_debug", "code_structure", "code_test"})


def grammar_match(text: str) -> Optional[Dict]:
    """Match text against grammar rules.

    Returns dict with intent, confidence, entities, matched_rule
    or None if no match. Code intents are prioritized over run_shell.
    """
    text = text.strip()
    best: Optional[Dict] = None
    best_score = 0.0

    for intent, patterns in _COMPILED.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                match_len = m.end() - m.start()
                score = min(0.95, 0.7 + (match_len / max(len(text), 1)) * 0.25)
                # Boost code intents so they beat run_shell for code-like inputs
                if intent in _CODE_INTENTS:
                    score = min(0.95, score + 0.05)
                if score > best_score:
                    entities = {k: v for k, v in m.groupdict().items() if v is not None}
                    best = {
                        "intent": intent,
                        "confidence": score,
                        "entities": entities,
                        "matched_rule": pat.pattern,
                    }
                    best_score = score

    return best
