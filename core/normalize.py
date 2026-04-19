"""Normalizer — deterministic text normalization for intent matching.

Two modes:
  normalize_for_match(text) — lowered, contractions expanded, fillers removed
  normalize_keep_case(text) — contractions expanded but case preserved

Language mappings from GoLearn are loaded lazily from memory and applied
only in natural-language mode (not inside quoted strings or file paths).
"""

import re
from typing import Dict, Optional

# Contraction map (deterministic, no LLM)
_CONTRACTIONS: Dict[str, str] = {
    "i'm": "i am",
    "i've": "i have",
    "i'll": "i will",
    "i'd": "i would",
    "you're": "you are",
    "you've": "you have",
    "you'll": "you will",
    "you'd": "you would",
    "he's": "he is",
    "she's": "she is",
    "it's": "it is",
    "we're": "we are",
    "we've": "we have",
    "we'll": "we will",
    "we'd": "we would",
    "they're": "they are",
    "they've": "they have",
    "they'll": "they will",
    "they'd": "they would",
    "that's": "that is",
    "there's": "there is",
    "here's": "here is",
    "what's": "what is",
    "where's": "where is",
    "who's": "who is",
    "how's": "how is",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "hasn't": "has not",
    "haven't": "have not",
    "hadn't": "had not",
    "won't": "will not",
    "wouldn't": "would not",
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "can't": "cannot",
    "couldn't": "could not",
    "shouldn't": "should not",
    "let's": "let us",
    "ain't": "is not",
}

# Slang / casual speech map
_SLANG: Dict[str, str] = {
    "wanna": "want to",
    "gonna": "going to",
    "gotta": "got to",
    "gimme": "give me",
    "lemme": "let me",
    "kinda": "kind of",
    "sorta": "sort of",
    "dunno": "do not know",
    "gotcha": "got you",
    "imma": "i am going to",
    "tryna": "trying to",
    "hafta": "have to",
    "coulda": "could have",
    "shoulda": "should have",
    "woulda": "would have",
    "whatcha": "what are you",
    "howdy": "hello",
    "sup": "what is up",
    "nah": "no",
    "yep": "yes",
    "yup": "yes",
    "ya": "yes",
    "nope": "no",
    "pls": "please",
    "plz": "please",
    "thx": "thanks",
    "ty": "thank you",
    "np": "no problem",
    "bruh": "",
    "bro": "",
    "dude": "",
    "fam": "",
    "tbh": "to be honest",
    "imo": "in my opinion",
    "idk": "i do not know",
    "btw": "by the way",
    "rn": "right now",
    "asap": "as soon as possible",
}

# Filler tokens to strip for matching (only full-word match)
_FILLERS = {"uh", "um", "like", "yo", "so", "well", "basically", "literally",
            "actually", "just", "really", "honestly", "ok", "okay"}

# Pre-compile word-boundary patterns for contractions + slang
_EXPAND_RE = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in
                       sorted(list(_CONTRACTIONS) + list(_SLANG), key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)

_FILLER_RE = re.compile(
    r'\b(' + '|'.join(re.escape(f) for f in _FILLERS) + r')\b',
    re.IGNORECASE,
)

_WS_RE = re.compile(r'\s+')


def _expand_match(m: re.Match) -> str:
    word = m.group(0).lower()
    return _CONTRACTIONS.get(word, _SLANG.get(word, word))


class Normalizer:
    """Deterministic text normalizer for intent matching."""

    def __init__(self, langmap_facts: Optional[Dict[str, dict]] = None):
        # lang:map:* facts loaded from memory
        self._langmap: Dict[str, str] = {}
        if langmap_facts:
            self.load_langmap(langmap_facts)

    # ── public API ─────────────────────────────────────────────

    def normalize_for_match(self, text: str) -> str:
        """Lowercase + expand contractions/slang + remove fillers + normalize whitespace."""
        text = text.lower()
        text = self._normalize_quotes(text)
        text = _EXPAND_RE.sub(_expand_match, text)
        # Apply golearn language mappings (skip quoted strings and paths)
        text = self._apply_langmap(text)
        text = _FILLER_RE.sub('', text)
        text = _WS_RE.sub(' ', text).strip()
        return text

    def normalize_keep_case(self, text: str) -> str:
        """Expand contractions but preserve case and fillers."""
        text = self._normalize_quotes(text)
        text = _EXPAND_RE.sub(_expand_match, text)
        text = _WS_RE.sub(' ', text).strip()
        return text

    # ── language map ───────────────────────────────────────────

    def load_langmap(self, facts: Dict[str, dict]) -> None:
        """Load language mappings from memory facts (key prefix 'lang:map:')."""
        self._langmap.clear()
        for key, val in facts.items():
            if not key.startswith("lang:map:"):
                continue
            phrase = key[len("lang:map:"):]
            target = val.get("value", val) if isinstance(val, dict) else val
            if isinstance(target, dict):
                target = target.get("to", "")
            if phrase and target:
                self._langmap[phrase.lower()] = str(target).lower()

    def reload_from_memory(self, memory) -> int:
        """Reload language mappings from a MemorySystem instance."""
        facts = {k: v for k, v in memory.facts.items() if k.startswith("lang:map:")}
        self.load_langmap(facts)
        return len(self._langmap)

    def _apply_langmap(self, text: str) -> str:
        """Apply learned language mappings, skipping quoted strings and paths."""
        if not self._langmap:
            return text
        # Protect quoted strings and paths from rewriting
        protected: list = []
        def _protect(m: re.Match) -> str:
            protected.append(m.group(0))
            return f"\x00PROT{len(protected) - 1}\x00"
        # Protect: "...", '...', /path/like/this, ~/something
        safe = re.sub(r'"[^"]*"|\'[^\']*\'|(?<!\w)[~/]\S+', _protect, text)
        # Apply mappings (longest first to avoid partial matches)
        for phrase in sorted(self._langmap, key=len, reverse=True):
            safe = re.sub(r'\b' + re.escape(phrase) + r'\b', self._langmap[phrase], safe)
        # Restore protected segments
        for i, orig in enumerate(protected):
            safe = safe.replace(f"\x00PROT{i}\x00", orig)
        return safe

    @staticmethod
    def _normalize_quotes(text: str) -> str:
        """Normalize curly/smart quotes to straight quotes."""
        return text.replace('\u2018', "'").replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
