#!/usr/bin/env python3
"""
Planner - HTN (Hierarchical Task Network) Planning Engine

Implements hierarchical task planning with:
- Primitive and compound actions
- Preconditions and effects checking
- Action chaining and goal decomposition
- Cost-based planning optimization
"""

import os
from typing import List, Dict, Any, Tuple
from datetime import datetime


class Planner:
    """HTN planning engine for goal decomposition and action selection.

    v2: Evidence-conditioned candidate generation — workflows, failures,
    and capability memory influence what candidates are produced.
    """

    def __init__(self, capability_map=None, workspace_root: str | None = None):
        self.actions = {}
        self.world_state = {}
        self.plan_trace = []
        self._cap_map = capability_map
        self.workspace_root = workspace_root or os.getcwd()

    def add_action(self, name: str, action_def: Dict[str, Any]):
        """Add an action definition to the planner"""
        self.actions[name] = action_def
        self._log_trace(f"Added action: {name}")

    def plan_actions(self, intent: Dict[str, Any],
                     evidence: List = None) -> List[Dict[str, Any]]:
        """Generate candidate Action dicts from an intent dict.

        Evidence bundle (from retrieval bus) can influence candidate generation:
        - Workflows boost/suggest specific tool+param combos
        - Failures suppress weak patterns
        - Capability memory fills missing entities when safe
        """
        intent_name = intent.get('intent', 'unknown')
        entities = intent.get('entities', {}) or {}
        candidates: List[Dict[str, Any]] = []

        # Pre-process evidence for candidate conditioning
        _ev_workflows = []
        _ev_failures = set()
        _ev_tools = {}
        for ev in (evidence or []):
            if not hasattr(ev, 'type'):
                continue
            if ev.type == "workflow" and isinstance(ev.value, dict):
                _ev_workflows.append(ev.value)
            elif ev.type == "failure" and isinstance(ev.value, dict):
                _ev_failures.add(ev.value.get("tool", ""))
            elif ev.type == "tool_memory" and isinstance(ev.value, dict):
                # Key by tool name to preserve multiple tool_memory entries
                tool_key = ev.value.get("tool_name") or ev.value.get("tool") or str(ev.source)
                _ev_tools[tool_key] = ev.value

        # Basic mappings to tool operations
        if intent_name == 'list_files':
            candidates.append({
                'name': 'list_files',
                'tool': 'file',
                'parameters': {'operation': 'list', 'path': entities.get('path', self.workspace_root)},
                'cost': 1,
                'confidence': float(intent.get('confidence', 0.5)),
            })
        elif intent_name == 'read_file':
            filename = entities.get('filename') or entities.get('path') or ''
            candidates.append({
                'name': 'read_file',
                'tool': 'file',
                'parameters': {'operation': 'read', 'path': filename},
                'cost': 2,
                'confidence': float(intent.get('confidence', 0.5)),
            })
        elif intent_name == 'search_files':
            candidates.append({
                'name': 'search_files',
                'tool': 'file',
                'parameters': {'operation': 'search', 'path': entities.get('path', self.workspace_root), 'pattern': entities.get('pattern','*')},
                'cost': 2,
                'confidence': float(intent.get('confidence', 0.5)),
            })
        elif intent_name == 'run_shell':
            cmd = entities.get('cmd','') or entities.get('command','')
            candidates.append({
                'name': 'run_shell',
                'tool': 'shell',
                'parameters': {'command': cmd},
                'cost': 2,
                'confidence': float(intent.get('confidence', 0.5)),
            })
        elif intent_name == 'golearn':
            topic = entities.get('topic', '')
            minutes = int(entities.get('minutes', '5'))
            mode = entities.get('mode') or 'auto'
            candidates.append({
                'name': 'golearn',
                'tool': 'golearn',
                'parameters': {'topic': topic, 'minutes': minutes, 'mode': mode},
                'cost': 3,
                'confidence': float(intent.get('confidence', 0.9)),
            })
        elif intent_name == 'create_tool':
            candidates.append({
                'name': 'create_tool',
                'tool': 'create_tool',
                'parameters': {'name': entities.get('name', ''), 'lang': entities.get('lang', 'bash'), 'code': entities.get('code', '')},
                'cost': 1,
                'confidence': float(intent.get('confidence', 0.9)),
            })
        elif intent_name == 'run_custom_tool':
            candidates.append({
                'name': 'run_custom_tool',
                'tool': 'run_custom_tool',
                'parameters': {'name': entities.get('name', '')},
                'cost': 1,
                'confidence': float(intent.get('confidence', 0.9)),
            })
        elif intent_name == 'list_custom_tools':
            candidates.append({
                'name': 'list_custom_tools',
                'tool': 'list_custom_tools',
                'parameters': {},
                'cost': 0,
                'confidence': float(intent.get('confidence', 0.9)),
            })
        elif intent_name == 'delete_tool':
            candidates.append({
                'name': 'delete_tool',
                'tool': 'delete_tool',
                'parameters': {'name': entities.get('name', '')},
                'cost': 1,
                'confidence': float(intent.get('confidence', 0.9)),
            })
        elif intent_name == 'teach_response':
            candidates.append({
                'name': 'teach_response',
                'tool': 'teach_response',
                'parameters': {'trigger': entities.get('trigger', ''), 'response': entities.get('response', '')},
                'cost': 0,
                'confidence': float(intent.get('confidence', 0.9)),
            })
        elif intent_name == 'forget_response':
            candidates.append({
                'name': 'forget_response',
                'tool': 'forget_response',
                'parameters': {'trigger': entities.get('trigger', '')},
                'cost': 0,
                'confidence': float(intent.get('confidence', 0.9)),
            })
        elif intent_name == 'reload_language':
            candidates.append({
                'name': 'reload_language',
                'tool': None,
                'parameters': {},
                'cost': 0,
                'confidence': float(intent.get('confidence', 0.95)),
            })
        else:
            # Ambiguity mode: if intent is unknown or low confidence,
            # generate plausible candidates from entity hints
            if float(intent.get('confidence', 0)) < 0.5:
                return self._ambiguity_candidates(intent_name, entities, intent, _ev_workflows)
            return []

        # Boost confidence by capability map success rate
        if self._cap_map:
            for c in candidates:
                tool = c.get("tool")
                if tool:
                    cap_rate = self._cap_map.tool_score(tool, context=intent_name, intent=intent_name)
                    c["confidence"] = round(c["confidence"] * (0.7 + 0.3 * cap_rate), 3)

        # Evidence conditioning: suppress candidates whose tool has recent failures
        if _ev_failures:
            for c in candidates:
                if c.get("tool") in _ev_failures:
                    c["confidence"] = round(c["confidence"] * 0.7, 3)

        # Evidence conditioning: boost candidates that match known workflows
        for c in candidates:
            tool = c.get("tool") or ""
            for wf in _ev_workflows:
                if tool in wf.get("tool_sequence", []):
                    c["confidence"] = round(min(1.0, c["confidence"] + 0.1), 3)
                    break

        # Evidence conditioning: fill missing entities from capability memory
        for c in candidates:
            params = c.get("parameters", {})
            for tool_info in _ev_tools.values():
                for inp in tool_info.get("common_inputs", []):
                    # Only fill if param is empty and input matches a param key
                    for pk, pv in params.items():
                        if not pv and pk in inp:
                            # Don't auto-fill — just note it's available
                            c.setdefault("entity_hints", {})[pk] = inp

        return candidates

    def _ambiguity_candidates(self, intent_name: str, entities: Dict[str, Any],
                               intent: Dict[str, Any],
                               workflows: List = None) -> List[Dict[str, Any]]:
        """Generate 2-3 plausible candidates when intent is ambiguous.

        Workflows from evidence can add additional candidates.
        """
        candidates = []
        conf = float(intent.get('confidence', 0.3))
        has_path = bool(entities.get('path'))
        has_pattern = bool(entities.get('pattern'))
        has_filename = bool(entities.get('filename'))

        if has_path or has_filename:
            candidates.append({
                'name': 'list_files', 'tool': 'file',
                'parameters': {'operation': 'list', 'path': entities.get('path', self.workspace_root)},
                'cost': 1, 'confidence': conf,
            })
        if has_pattern or has_filename:
            candidates.append({
                'name': 'search_files', 'tool': 'file',
                'parameters': {'operation': 'search', 'path': entities.get('path', self.workspace_root),
                               'pattern': entities.get('pattern') or entities.get('filename', '*')},
                'cost': 2, 'confidence': conf * 0.9,
            })
        if has_filename:
            candidates.append({
                'name': 'read_file', 'tool': 'file',
                'parameters': {'operation': 'read', 'path': entities.get('filename', '')},
                'cost': 2, 'confidence': conf * 0.8,
            })

        return candidates[:3]

    def plan(self, goal: str, context: Dict[str, Any] = None) -> Tuple[bool, List[str], float]:
        """Plan to achieve a goal using HTN planning
        
        Returns:
            Tuple of (success, action_sequence, total_cost)
        """
        self._log_trace(f"Planning for goal: {goal}")

        context = context or {}

        # Check if goal is already achieved
        if self._is_goal_achieved(goal, context):
            self._log_trace("Goal already achieved")
            return True, [], 0.0

        # Try to find primitive action
        if goal in self.actions:
            action = self.actions[goal]
            if self._check_preconditions(action, context):
                self._log_trace(f"Found primitive action: {goal}")
                return True, [goal], action.get('cost', 1)

        # Try to find compound actions
        for action_name, action in self.actions.items():
            if goal in action.get('effects', []):
                if self._check_preconditions(action, context):
                    self._log_trace(f"Found compound action: {action_name}")
                    # Recursively plan for action's effects
                    subplan, subcost = self._plan_subgoals(action.get('subgoals', []), context)
                    if subplan:
                        return True, [action_name] + subplan, action.get('cost', 1) + subcost

        # Try to decompose goal into subgoals
        subgoals = self._decompose_goal(goal, context)
        if subgoals:
            self._log_trace(f"Decomposed goal into subgoals: {subgoals}")
            subplan, subcost = self._plan_subgoals(subgoals, context)
            if subplan:
                return True, subplan, subcost

        self._log_trace("No valid plan found")
        return False, [], float('inf')

    def _plan_subgoals(self, subgoals: List[str], context: Dict[str, Any]) -> Tuple[List[str], float]:
        """Plan for multiple subgoals"""
        total_plan = []
        total_cost = 0

        for subgoal in subgoals:
            success, plan, cost = self.plan(subgoal, context)
            if not success:
                self._log_trace(f"Subgoal failed: {subgoal}")
                return [], float('inf')
            total_plan.extend(plan)
            total_cost += cost

        return total_plan, total_cost

    def _decompose_goal(self, goal: str, context: Dict[str, Any]) -> List[str]:
        """Decompose a goal into subgoals"""
        # Simple decomposition: split by logical operators
        if 'and' in goal:
            return [g.strip() for g in goal.split('and')]

        # Try to find compound actions that achieve this goal
        for action_name, action in self.actions.items():
            if goal in action.get('effects', []):
                return action.get('subgoals', [])

        return []

    def _is_goal_achieved(self, goal: str, context: Dict[str, Any]) -> bool:
        """Check if goal is already achieved"""
        # Check world state
        if goal in self.world_state and self.world_state[goal]:
            return True

        # Check context
        if goal in context and context[goal]:
            return True

        return False

    def _check_preconditions(self, action: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Check if action preconditions are met"""
        if not action.get('preconditions'):
            return True

        # Check world state preconditions
        for condition in action['preconditions']:
            if condition not in self.world_state or not self.world_state[condition]:
                # Check context as fallback
                if condition not in context or not context[condition]:
                    self._log_trace(f"Precondition not met: {condition}")
                    return False

        self._log_trace("All preconditions met")
        return True

    def update_world_state(self, state: Dict[str, Any]):
        """Update the world state"""
        self.world_state.update(state)
        self._log_trace(f"Updated world state: {state}")

    def get_trace(self) -> List[Dict[str, Any]]:
        """Get planning trace"""
        return self.plan_trace.copy()

    def _log_trace(self, message: str):
        """Log planning step"""
        self.plan_trace.append({
            'timestamp': datetime.now().isoformat(),
            'message': message
        })


# Example HTN planner usage
if __name__ == "__main__":
    planner = Planner()

    # Add primitive actions
    planner.add_action('list_files', {
        'preconditions': ['filesystem_available'],
        'effects': ['file_list_available'],
        'cost': 1,
        'subgoals': [],
        'parameters': {'path': {'type': 'string', 'required': False}}
    })

    planner.add_action('read_file', {
        'preconditions': ['file_exists', 'filesystem_available'],
        'effects': ['file_content_available'],
        'cost': 2,
        'subgoals': [],
        'parameters': {'filename': {'type': 'string', 'required': True}}
    })

    # Add compound actions
    planner.add_action('search_and_read', {
        'preconditions': ['filesystem_available'],
        'effects': ['file_content_available'],
        'cost': 3,
        'subgoals': ['find_file', 'read_file'],
        'parameters': {'filename': {'type': 'string', 'required': True}}
    })

    # Set initial world state
    planner.update_world_state({
        'filesystem_available': True
    })

    # Test planning
    print("HTN Planning Tests:")

    # Simple goal
    success, plan, cost = planner.plan('list_files')
    print(f"Goal: list_files -> Success: {success}, Plan: {plan}, Cost: {cost}")

    # Compound goal
    success, plan, cost = planner.plan('search_and_read', {'filename': 'report.txt'})
    print(f"Goal: search_and_read -> Success: {success}, Plan: {plan}, Cost: {cost}")

    # Complex goal with decomposition
    success, plan, cost = planner.plan('file_content_available')
    print(f"Goal: file_content_available -> Success: {success}, Plan: {plan}, Cost: {cost}")

    # Show trace
    print("\nPlanning Trace:")
    for step in planner.get_trace():
        print(f"{step['timestamp']}: {step['message']}")
