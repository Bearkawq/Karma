"""LangMap — deterministic extraction of language equivalences from text.

Scans combined text for common synonym/equivalence patterns and returns
structured facts for storage in memory.

No LLM. Uses regex + frequency thresholds only.
"""

import re
from collections import Counter
from typing import Any, Dict, List, Tuple


# Patterns that indicate equivalence in natural text
_EQUIV_PATTERNS = [
    # "X is also known as Y", "X aka Y", "X (also called Y)"
    re.compile(
        r'\b(?P<term>[a-z][\w\s]{1,30}?)\s+'
        r'(?:is\s+)?(?:also\s+)?(?:known\s+as|called|referred\s+to\s+as|aka)\s+'
        r'(?P<equiv>[a-z][\w\s]{1,30})',
        re.IGNORECASE,
    ),
    # "X, or Y," / "X (or Y)"
    re.compile(
        r'\b(?P<term>[a-z][\w\s]{1,25}?)\s*'
        r'[,(]\s*or\s+(?P<equiv>[a-z][\w\s]{1,25}?)\s*[,)]',
        re.IGNORECASE,
    ),
    # "X means Y" / "X stands for Y"
    re.compile(
        r'\b(?P<term>[a-z][\w\s]{1,20}?)\s+'
        r'(?:means?|stands?\s+for)\s+'
        r'(?P<equiv>[a-z][\w\s]{1,30})',
        re.IGNORECASE,
    ),
    # "X i.e. Y" / "X (i.e., Y)"
    re.compile(
        r'\b(?P<term>[a-z][\w\s]{1,25}?)\s*'
        r'[,(]?\s*i\.?e\.?,?\s*(?P<equiv>[a-z][\w\s]{1,30}?)\s*[,)]',
        re.IGNORECASE,
    ),
]


def extract_mappings(
    text: str,
    artifact_ids: List[str] = None,
    min_occurrences: int = 1,
) -> List[Dict[str, Any]]:
    """Extract language equivalences from text.

    Returns list of dicts:
      {"phrase": str, "to": str, "why": str, "source_artifacts": [...], "confidence": float}
    """
    raw_pairs: List[Tuple[str, str, str]] = []

    for pat in _EQUIV_PATTERNS:
        for m in pat.finditer(text):
            term = m.group("term").strip().lower()
            equiv = m.group("equiv").strip().lower()
            if term and equiv and term != equiv and len(term) < 40 and len(equiv) < 40:
                raw_pairs.append((term, equiv, m.group(0)[:80]))

    if not raw_pairs:
        return []

    # Deduplicate and count
    pair_counts: Counter = Counter()
    pair_evidence: Dict[Tuple[str, str], str] = {}
    for term, equiv, evidence in raw_pairs:
        key = (term, equiv)
        pair_counts[key] += 1
        if key not in pair_evidence:
            pair_evidence[key] = evidence

    results: List[Dict[str, Any]] = []
    for (term, equiv), count in pair_counts.items():
        if count < min_occurrences:
            continue
        # Confidence: base 0.5, +0.1 per extra occurrence, cap at 0.8
        conf = min(0.8, 0.5 + (count - 1) * 0.1)
        results.append({
            "phrase": term,
            "to": equiv,
            "why": pair_evidence[(term, equiv)],
            "source_artifacts": artifact_ids or [],
            "confidence": conf,
        })

    return results


def store_mappings(
    mappings: List[Dict[str, Any]],
    memory,
    session_id: str,
) -> int:
    """Store extracted mappings as facts in memory (key: lang:map:<phrase>).

    Returns number of mappings stored.
    """
    if not memory or not mappings:
        return 0

    stored = 0
    source = f"golearn:{session_id}"
    for m in mappings:
        key = f"lang:map:{m['phrase']}"
        memory.save_fact(
            key=key,
            value={"to": m["to"], "why": m["why"], "source_artifacts": m["source_artifacts"]},
            source=source,
            confidence=m.get("confidence", 0.5),
        )
        stored += 1
    return stored
