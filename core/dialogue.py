from __future__ import annotations

from typing import Dict, Optional
import re

_COMMAND_VERBS = {"list", "show", "search", "find", "read", "open", "create", "delete", "run", "execute", "inspect", "compare", "use", "test", "debug"}
_TOOL_NOUNS = {"file", "files", "folder", "path", "paths", "tool", "tools", "shell", "repo", "tests", "core", "output", "results"}


def classify_dialogue_act(text: str) -> Dict[str, str]:
    raw = (text or "").strip()
    low = raw.lower()
    if not raw:
        return {"act": "empty", "route": "respond_only"}
    if re.search(r"\b(current topic|active topic|current subject|active artifacts?|show artifacts?|active threads?|show threads?|unresolved references?|conversation state|what are you referring|what do you think i mean|what do you mean|what thread|what evidence|what supports|what else did you|what changed|what was corrected)\b", low) or re.search(r"why (?:are (?:we|you)|am i) (?:talking|discussing)", low):
        return {"act": "introspection", "route": "respond_only"}
    if re.search(r"\b(go on|continue|more|continue from there)\b", low):
        return {"act": "continuation", "route": "retrieve_and_respond"}
    if re.search(r"\b(summarize that|summarize it|summary|sum it up)\b", low):
        return {"act": "summary_request", "route": "retrieve_and_respond"}
    if re.search(r"\b(no[, ]|i meant|rather|the other one|the third one|the second one|the first one|that one|that file|that bug|that folder)\b", low):
        return {"act": "correction", "route": "ask_clarification"}
    if re.search(r"\b(yes|yeah|yep|nope|no)\b", low) and len(low.split()) <= 4:
        return {"act": "clarification_answer", "route": "respond_only"}
    if re.search(r"\b(compare|brainstorm|ideas?|theorycraft)\b", low):
        return {"act": "brainstorming", "route": "retrieve_and_respond"}
    if "?" in raw or re.match(r"^(what|why|how|when|where|who|can|could|would|should|is|are|do)\b", low):
        return {"act": "question", "route": "respond_only"}
    if re.match(r"^(run|execute|list|show|search|find|read|open|create|delete|teach|forget|golearn|self\s*check)\b", low):
        return {"act": "command", "route": "act_and_report"}
    return {"act": "statement", "route": "respond_only"}


def command_signal_score(text: str, *, grammar_confidence: float = 0.0, symbolic_intent: Optional[str] = None) -> float:
    low = (text or "").strip().lower()
    words = set(re.findall(r"[a-zA-Z0-9_.*/-]+", low))
    score = 0.0
    if grammar_confidence:
        score += min(grammar_confidence, 1.0) * 0.45
    if symbolic_intent:
        score += 0.35
    if words & _COMMAND_VERBS:
        score += 0.2
    if words & _TOOL_NOUNS:
        score += 0.15
    if re.search(r"\b(can|could|would|should|what)\b", low) and (words & _COMMAND_VERBS or words & _TOOL_NOUNS):
        score += 0.1
    if low.endswith('?') and not (words & _COMMAND_VERBS):
        score -= 0.05
    return max(0.0, min(score, 1.0))


def choose_response_goal(text: str, *, act: str = "statement") -> str:
    low = (text or "").strip().lower()
    if act == "summary_request" or "summarize" in low or "summary" in low:
        return "summarize"
    if act == "continuation" or re.search(r"\b(go on|continue|more|why)\b", low):
        return "continue"
    if re.search(r"\b(compare|versus|vs)\b", low):
        return "compare"
    if act == "correction":
        return "acknowledge_correction"
    if act == "brainstorming" or re.search(r"\b(recommend|suggest|idea|ideas)\b", low):
        return "recommend"
    if act == "question" and re.search(r"\b(what is|how does|why does|explain)\b", low):
        return "explain"
    if act == "clarification_answer":
        return "clarify"
    return "answer"


def retrieval_mode_for_goal(goal: str) -> str:
    mapping = {
        "answer": "dialogue_answer",
        "explain": "dialogue_answer",
        "summarize": "dialogue_summary",
        "compare": "dialogue_compare",
        "continue": "dialogue_continue",
        "clarify": "dialogue_clarify",
        "recommend": "dialogue_answer",
        "acknowledge_correction": "dialogue_reference",
    }
    return mapping.get(goal, "dialogue_answer")
