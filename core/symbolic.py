#!/usr/bin/env python3
"""
Symbolic Core - Rule-based Intent Parser and HTN Planner

This module implements:
- Rule-based intent classification using pattern matching
- HTN (Hierarchical Task Network) planning
- Action metadata management
- Transparent reasoning traces
"""

import re
from typing import Dict, List, Any, Optional
from datetime import datetime


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


# Key command words that trigger intents — used for fuzzy matching
_COMMAND_WORDS = {
    "list": "list", "show": "show", "read": "read", "find": "find",
    "search": "search", "run": "run", "execute": "execute", "create": "create",
    "delete": "delete", "remove": "remove", "teach": "teach", "forget": "forget",
    "golearn": "golearn", "reload": "reload",
}


class SymbolicCore:
    """Symbolic reasoning and planning engine"""

    def __init__(self):
        self.rules = []
        self.actions = {}
        self.world_state = {}
        self.trace = []

    def add_rule(self, pattern: str, intent: str, confidence: float = 0.8):
        """Add a pattern-based intent classification rule"""
        self.rules.append({
            'pattern': re.compile(pattern, re.IGNORECASE),
            'intent': intent,
            'confidence': confidence
        })
        self._log_trace(f"Added rule for intent '{intent}' with pattern '{pattern}'")

    def parse_intent(self, text: str) -> Optional[Dict[str, Any]]:
        """Alias for classify_intent; returns None if unknown."""
        res = self.classify_intent(text)
        return None if res.get('intent') == 'unknown' else res

    def score_action(self, action: Dict[str, Any], intent: Dict[str, Any]) -> float:
        """Symbolic score for an action candidate.
        Heuristics:
          - prefer actions whose name matches intent
          - prefer lower cost
        Returns 0..1.
        """
        if not action:
            return 0.0
        base = 0.5
        if action.get('name') == intent.get('intent'):
            base += 0.3
        cost = float(action.get('cost', 1.0))
        base += max(0.0, 0.2 - min(cost, 10.0) * 0.02)
        return max(0.0, min(1.0, base))

    def classify_intent(self, text: str) -> Dict[str, Any]:
        """Classify intent using pattern matching"""
        self._log_trace(f"Classifying intent for text: '{text}'")

        for rule in self.rules:
            if rule['pattern'].search(text):
                self._log_trace(f"Matched rule: {rule['intent']}")
                entities = self._extract_entities(text, rule['pattern'])
                entities = self._fallback_heuristics(text, rule['intent'], entities)
                return {
                    'intent': rule['intent'],
                    'confidence': rule['confidence'],
                    'entities': entities
                }

        # Typo tolerance: fix misspelled command words and retry
        corrected = self._fix_typos(text)
        if corrected != text:
            self._log_trace(f"Typo correction: '{text}' -> '{corrected}'")
            for rule in self.rules:
                if rule['pattern'].search(corrected):
                    self._log_trace(f"Matched rule after typo fix: {rule['intent']}")
                    entities = self._extract_entities(corrected, rule['pattern'])
                    entities = self._fallback_heuristics(corrected, rule['intent'], entities)
                    return {
                        'intent': rule['intent'],
                        'confidence': rule['confidence'] * 0.85,  # slight penalty
                        'entities': entities
                    }

        self._log_trace("No matching rule found")
        return {
            'intent': 'unknown',
            'confidence': 0.1,
            'entities': {}
        }

    def _extract_entities(self, text: str, pattern: re.Pattern) -> Dict[str, str]:
        """Extract entities from text using named regex groups."""
        match = pattern.search(text)
        if match:
            return {k: v for k, v in match.groupdict().items() if v is not None}
        return {}

    @staticmethod
    def _fix_typos(text: str) -> str:
        """Try to correct misspelled command words using edit distance."""
        words = text.split()
        changed = False
        for i, word in enumerate(words):
            if i > 0:
                break  # only correct the command word (always first)
            low = word.lower()
            if low in _COMMAND_WORDS:
                continue  # already correct
            # Only check short-ish words (command words are short)
            if len(low) > 12 or len(low) < 3:
                continue
            best_match = None
            best_dist = 2  # max 2 edits tolerated
            for cmd in _COMMAND_WORDS:
                d = _levenshtein(low, cmd)
                if d <= best_dist and d > 0 and d <= len(cmd) // 2:
                    best_dist = d
                    best_match = cmd
            if best_match:
                words[i] = best_match
                changed = True
        return " ".join(words) if changed else text

    @staticmethod
    def _fallback_heuristics(text: str, intent: str, entities: Dict[str, str]) -> Dict[str, str]:
        """Fill in missing entities using token-level heuristics."""
        tokens = text.split()

        # Quoted text preference: if quoted strings exist, use them for topic/name/code
        quoted = re.findall(r'"([^"]+)"', text) or re.findall(r"'([^']+)'", text)

        # Path heuristic: tokens starting with / or ~ are paths
        if 'path' not in entities:
            for tok in tokens:
                if tok.startswith('/') or tok.startswith('~'):
                    entities['path'] = tok
                    break

        # Filename heuristic: tokens with common extensions
        if 'filename' not in entities and intent in ('read_file', 'search_files'):
            for tok in tokens:
                if re.search(r'\.\w{1,5}$', tok) and not tok.startswith('/') and not tok.startswith('~'):
                    entities['filename'] = tok
                    break

        # Pattern heuristic: if search intent and no pattern, check for glob/extension tokens
        if intent == 'search_files' and 'pattern' not in entities:
            for tok in tokens:
                if '*' in tok or '?' in tok or re.search(r'\.\w{1,5}$', tok):
                    entities['pattern'] = tok
                    break
            # Fall back to quoted text as pattern
            if 'pattern' not in entities and quoted:
                entities['pattern'] = quoted[0]

        # Golearn heuristic: last number token is minutes
        if intent == 'golearn':
            if 'minutes' not in entities:
                for tok in reversed(tokens):
                    if tok.isdigit():
                        entities['minutes'] = tok
                        break
            if 'topic' not in entities:
                if quoted:
                    entities['topic'] = quoted[0]
                else:
                    low = text.lower()
                    idx = low.find('golearn')
                    if idx >= 0:
                        rest = text[idx + 7:].strip().strip('"').strip("'")
                        rest = re.sub(r'\s+\d+\s*(?:depth|breadth|auto)?\s*$', '', rest, flags=re.IGNORECASE).strip()
                        if rest:
                            entities['topic'] = rest

        # Tool name/code: prefer quoted text
        if intent in ('create_tool', 'run_custom_tool', 'delete_tool'):
            if 'name' not in entities and quoted:
                entities['name'] = quoted[0]
            if intent == 'create_tool' and 'code' not in entities and len(quoted) >= 2:
                entities['code'] = quoted[-1]

        # Teach response: prefer quoted text
        if intent == 'teach_response':
            if 'trigger' not in entities and len(quoted) >= 1:
                entities['trigger'] = quoted[0]
            if 'response' not in entities and len(quoted) >= 2:
                entities['response'] = quoted[1]

        return entities

    def add_action(self, name: str, action_def: Dict[str, Any]):
        """Add an action definition"""
        self.actions[name] = action_def
        self._log_trace(f"Added action: {name}")

    def plan(self, goal: str, context: Dict[str, Any] = None) -> List[str]:
        """HTN planning to achieve a goal"""
        self._log_trace(f"Planning for goal: {goal}")

        if goal in self.actions:
            action = self.actions[goal]
            if self._check_preconditions(action, context):
                self._log_trace(f"Found primitive action: {goal}")
                return [goal]

        # Try to find compound actions
        for action_name, action in self.actions.items():
            if goal in action.get('effects', []):
                if self._check_preconditions(action, context):
                    self._log_trace(f"Found compound action: {action_name}")
                    return [action_name]

        self._log_trace("No valid plan found")
        return []

    def _check_preconditions(self, action: Dict[str, Any], context: Dict[str, Any] = None) -> bool:
        """Check if action preconditions are met"""
        if not action.get('preconditions'):
            return True

        context = context or {}
        for condition in action['preconditions']:
            if condition not in self.world_state and condition not in context:
                self._log_trace(f"Precondition not met: {condition}")
                return False

        self._log_trace("All preconditions met")
        return True

    def update_world_state(self, state: Dict[str, Any]):
        """Update the world state"""
        self.world_state.update(state)
        self._log_trace(f"Updated world state: {state}")

    def get_trace(self) -> List[Dict[str, Any]]:
        """Get reasoning trace"""
        return self.trace.copy()

    def _log_trace(self, message: str):
        """Log reasoning step"""
        self.trace.append({
            'timestamp': datetime.now().isoformat(),
            'message': message
        })
        # Cap trace to prevent memory leak
        if len(self.trace) > 500:
            self.trace = self.trace[-500:]


# Example rule-based intent parser
if __name__ == "__main__":
    sc = SymbolicCore()

    # Add intent classification rules
    sc.add_rule(r'(?P<command>list|show).*files', 'list_files', 0.9)
    sc.add_rule(r'(?P<command>read).*file.*named (?P<filename>\w+)', 'read_file', 0.8)
    sc.add_rule(r'(?P<command>delete).*file.*named (?P<filename>\w+)', 'delete_file', 0.8)
    sc.add_rule(r'what.*can.*you.*do', 'list_capabilities', 0.9)

    # Add action definitions
    sc.add_action('list_files', {
        'preconditions': ['filesystem_available'],
        'effects': ['file_list_available'],
        'cost': 1,
        'parameters': {'path': {'type': 'string', 'required': False}},
        'failure_modes': ['permission_denied', 'path_not_found']
    })

    sc.add_action('read_file', {
        'preconditions': ['file_exists'],
        'effects': ['file_content_available'],
        'cost': 2,
        'parameters': {'filename': {'type': 'string', 'required': True}},
        'failure_modes': ['file_not_found', 'permission_denied']
    })

    # Test intent classification
    print("Intent Classification:")
    print(sc.classify_intent("List all files in my directory"))
    print(sc.classify_intent("Read the file named report.txt"))
    print(sc.classify_intent("What can you do?"))

    # Test planning
    print("\nPlanning:")
    sc.update_world_state({'filesystem_available': True})
    print(sc.plan('list_files'))

    # Show trace
    print("\nReasoning Trace:")
    for step in sc.get_trace():
        print(f"{step['timestamp']}: {step['message']}")
