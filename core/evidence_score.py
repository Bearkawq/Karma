"""Centralized evidence scoring utility (#7).

Provides consistent scoring for evidence items across:
- retrieval ranking
- planner evidence conditioning
- repair suggestion ranking
- responder evidence-first answering

All scoring is deterministic — no ML, no external deps.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List


def score_evidence(item: Dict[str, Any], query_words: set,
                   query_intent: str = "", query_domain: str = "",
                   query_tool: str = "") -> float:
    """Score a single evidence item against a query context.

    Factors:
      - keyword relevance (word overlap)
      - intent match
      - domain match
      - tool family match
      - recency
      - confidence
      - usage weight

    Returns float 0.0-1.0.
    """
    score = 0.0

    # 1. Keyword relevance (0-0.3)
    item_words = _extract_words(item)
    if query_words and item_words:
        overlap = len(query_words & item_words)
        score += min(0.3, 0.3 * overlap / max(len(query_words), 1))

    # 2. Intent match (0-0.2)
    item_intent = item.get("intent", "") or item.get("signature", "")
    if query_intent and item_intent:
        if query_intent == item_intent:
            score += 0.2
        elif query_intent in item_intent or item_intent in query_intent:
            score += 0.1

    # 3. Domain match (0-0.15)
    item_domain = item.get("domain", "") or _infer_domain(item)
    if query_domain and item_domain:
        if query_domain == item_domain:
            score += 0.15
        elif query_domain in item_domain or item_domain in query_domain:
            score += 0.07

    # 4. Tool family match (0-0.15)
    item_tool = item.get("tool", "") or ""
    if query_tool and item_tool:
        if query_tool == item_tool:
            score += 0.15
        elif _tool_family(query_tool) == _tool_family(item_tool):
            score += 0.08

    # 5. Recency (0-0.1)
    ts = item.get("timestamp") or item.get("last_used") or item.get("created", "")
    if ts:
        score += _recency_score(ts) * 0.1

    # 6. Confidence (0-0.05)
    conf = float(item.get("confidence", 0.5))
    score += conf * 0.05

    # 7. Usage weight (0-0.05)
    use_count = int(item.get("use_count", 0) or item.get("success_count", 0) or 0)
    if use_count > 0:
        score += min(0.05, 0.01 * use_count)

    return min(1.0, score)


def rank_evidence(items: List[Dict[str, Any]], query_words: set,
                  query_intent: str = "", query_domain: str = "",
                  query_tool: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """Score and rank a list of evidence items. Returns top `limit`."""
    scored = []
    for item in items:
        s = score_evidence(item, query_words, query_intent, query_domain, query_tool)
        scored.append((s, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


# ── shape extraction ─────────────────────────────────────

def extract_shape(intent_name: str, entities: Dict[str, Any],
                  tool: str = "") -> Dict[str, Any]:
    """Extract a lightweight shape descriptor for a task.

    Used by retrieval and planner to match task shapes.
    """
    entity_types = sorted(entities.keys()) if entities else []
    domain = _infer_domain_from_intent(intent_name)
    family = _tool_family(tool) if tool else ""
    return {
        "intent": intent_name,
        "entity_types": entity_types,
        "domain": domain,
        "tool_family": family,
        "action_shape": f"{intent_name}({','.join(entity_types)})",
    }


def shape_similarity(shape_a: Dict[str, Any], shape_b: Dict[str, Any]) -> float:
    """Compare two task shapes. Returns 0.0-1.0."""
    score = 0.0
    # Intent match
    if shape_a.get("intent") == shape_b.get("intent"):
        score += 0.35
    elif shape_a.get("domain") == shape_b.get("domain") and shape_a.get("domain"):
        score += 0.15
    # Entity type overlap
    et_a = set(shape_a.get("entity_types", []))
    et_b = set(shape_b.get("entity_types", []))
    if et_a and et_b:
        overlap = len(et_a & et_b) / max(len(et_a | et_b), 1)
        score += 0.3 * overlap
    elif not et_a and not et_b:
        score += 0.1
    # Tool family
    if shape_a.get("tool_family") and shape_a.get("tool_family") == shape_b.get("tool_family"):
        score += 0.2
    # Domain
    if shape_a.get("domain") and shape_a.get("domain") == shape_b.get("domain"):
        score += 0.15
    return min(1.0, score)


# ── helpers ──────────────────────────────────────────────

_DOMAIN_MAP = {
    "list_files": "filesystem", "read_file": "filesystem", "search_files": "filesystem",
    "run_shell": "shell", "golearn": "research", "salvage_golearn": "research",
    "create_tool": "tooling", "run_custom_tool": "tooling", "delete_tool": "tooling",
    "list_custom_tools": "tooling",
    "teach_response": "conversation", "forget_response": "conversation",
    "code_read": "code", "code_structure": "code", "code_debug": "code",
    "code_test": "code", "code_recall": "code", "code_run": "code",
    "self_check": "health", "repair_report": "health",
    "self_upgrade": "upgrade", "crystallize": "memory",
}

_TOOL_FAMILIES = {
    "file": "filesystem", "shell": "shell", "system": "system",
    "golearn": "research", "create_tool": "tooling", "run_custom_tool": "tooling",
}


def _infer_domain_from_intent(intent: str) -> str:
    return _DOMAIN_MAP.get(intent, "")


def _infer_domain(item: Dict[str, Any]) -> str:
    intent = item.get("intent", "")
    if intent:
        return _infer_domain_from_intent(intent)
    tool = item.get("tool", "")
    return _TOOL_FAMILIES.get(tool, "")


def _tool_family(tool: str) -> str:
    return _TOOL_FAMILIES.get(tool, tool.split("_")[0] if tool else "")


def _extract_words(item: Dict[str, Any]) -> set:
    """Extract searchable words from an evidence item."""
    parts = []
    for field in ("intent", "signature", "tool", "error_class", "topic", "issue"):
        v = item.get(field, "")
        if v:
            parts.append(str(v))
    text = " ".join(parts).lower().replace("_", " ").replace(":", " ").replace(".", " ").replace("->", " ")
    return set(text.split())


def _recency_score(ts_str: str) -> float:
    """Score 0.0-1.0 based on recency. 1.0 = now, 0.0 = 30+ days old."""
    try:
        ts = datetime.fromisoformat(ts_str)
        age_days = (datetime.now() - ts).total_seconds() / 86400
        if age_days <= 0:
            return 1.0
        if age_days >= 30:
            return 0.0
        return 1.0 - (age_days / 30)
    except (ValueError, TypeError):
        return 0.3  # unknown age, neutral
