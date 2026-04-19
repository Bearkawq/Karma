#!/usr/bin/env python3
"""Role Engine Runtime - loads, merges, validates role specs."""

import os
import sys
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from copy import deepcopy

ROLES_DIR = Path("/home/mikoleye/karma/orchestrator/roles")
BASE_DIR = ROLES_DIR / "base"
SPECS_DIR = ROLES_DIR / "specs"


class RoleEngine:
    """Loads and manages role specs with inheritance."""
    
    def __init__(self):
        self.cache: Dict[str, Dict] = {}
    
    def load_yaml(self, path: Path) -> Dict:
        """Load a YAML file."""
        with open(path) as f:
            return yaml.safe_load(f) or {}
    
    def load_base_role(self, base_name: str) -> Dict:
        """Load a base role."""
        base_path = BASE_DIR / f"{base_name}.yaml"
        if not base_path.exists():
            raise ValueError(f"Base role not found: {base_name}")
        return self.load_yaml(base_path)
    
    def merge_roles(self, base: Dict, spec: Dict) -> Dict:
        """Merge spec into base, with spec overriding base."""
        result = deepcopy(base)
        
        for key, value in spec.items():
            if key == "extends":
                continue
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_dict(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def _merge_dict(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dicts, override takes precedence."""
        result = deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_dict(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result
    
    def load_role(self, role_name: str, overrides: Optional[Dict] = None) -> Dict:
        """Load a role with inheritance and overrides."""
        cache_key = f"{role_name}:{str(overrides)}"
        if cache_key in self.cache:
            return deepcopy(self.cache[cache_key])
        
        spec_path = SPECS_DIR / f"{role_name}.yaml"
        if not spec_path.exists():
            raise ValueError(f"Role spec not found: {role_name}")
        
        spec = self.load_yaml(spec_path)
        
        if "extends" in spec:
            base_name = spec["extends"]
            base = self.load_base_role(base_name)
            role = self.merge_roles(base, spec)
        else:
            role = spec
        
        if overrides:
            role = self.merge_dict_deep(role, overrides)
        
        role["_meta"] = {
            "name": role_name,
            "base": spec.get("extends", "none"),
            "overrides_applied": bool(overrides)
        }
        
        self.cache[cache_key] = role
        return deepcopy(role)
    
    def merge_dict_deep(self, base: Dict, override: Dict) -> Dict:
        """Apply overrides to a loaded role."""
        return self._merge_dict(base, override)
    
    def validate_role(self, role: Dict) -> list:
        """Validate a role spec."""
        errors = []
        
        required_identity = ["name", "purpose", "class"]
        for field in required_identity:
            if "identity" not in role or field not in role.get("identity", {}):
                errors.append(f"Missing required identity field: {field}")
        
        if "permissions" in role:
            perms = role["permissions"]
            bool_fields = ["can_read", "can_write", "can_execute", "can_delegate", "can_split_tasks", "can_escalate"]
            for field in bool_fields:
                if field in perms and not isinstance(perms[field], bool):
                    errors.append(f"Permission {field} must be boolean")
        
        if "limits" in role:
            limits = role["limits"]
            int_fields = ["max_files_touched", "max_turns", "max_commands", "max_runtime_seconds"]
            for field in int_fields:
                if field in limits and not isinstance(limits[field], int):
                    errors.append(f"Limit {field} must be integer")
                if field in limits and limits[field] < 0:
                    errors.append(f"Limit {field} must be non-negative")
        
        if "behavior_tuning" in role:
            behavior = role["behavior_tuning"]
            for field, value in behavior.items():
                if not isinstance(value, (int, float)):
                    errors.append(f"Behavior {field} must be numeric")
                if isinstance(value, (int, float)) and (value < 0 or value > 10):
                    errors.append(f"Behavior {field} must be 0-10")
        
        required_output = ["status", "summary", "files_read", "blockers", "recommended_next_role"]
        if "output_contract" in role:
            for field in required_output:
                if field not in role["output_contract"].get("required_fields", []):
                    errors.append(f"Output contract missing required field: {field}")
        
        return errors
    
    def render_prompt(self, role: Dict, task: Dict) -> str:
        """Render a backend prompt from a role spec."""
        identity = role.get("identity", {})
        permissions = role.get("permissions", {})
        limits = role.get("limits", {})
        behavior = role.get("behavior_tuning", {})
        output = role.get("output_contract", {})
        
        prompt = f"""You are {identity.get('name', 'agent')} - {identity.get('purpose', '')}.
Class: {identity.get('class', 'unknown')}

TASK:
{task.get('objective', '')}

FILES IN SCOPE:
{task.get('files_in_scope', '')}

INSTRUCTIONS:
{task.get('instructions', '')}

PERMISSIONS:
- Read: {permissions.get('can_read', False)}
- Write: {permissions.get('can_write', False)}
- Execute: {permissions.get('can_execute', False)}
- Delegate: {permissions.get('can_delegate', False)}

LIMITS:
- Max files touched: {limits.get('max_files_touched', 'unlimited')}
- Max turns: {limits.get('max_turns', 'unlimited')}
- Max commands: {limits.get('max_commands', 'unlimited')}

BEHAVIOR:
- Initiative: {behavior.get('initiative', 5)}/10
- Caution: {behavior.get('caution', 5)}/10
- Skepticism: {behavior.get('skepticism', 5)}/10
- Creativity: {behavior.get('creativity', 5)}/10
- Persistence: {behavior.get('persistence', 5)}/10

OUTPUT FORMAT ({output.get('format', 'markdown')}):
Required fields: {', '.join(output.get('required_fields', []))}

Return only these sections with your response.
"""
        return prompt


def main():
    import json
    engine = RoleEngine()
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    
    if command == "list":
        print("Available roles:")
        for f in SPECS_DIR.glob("*.yaml"):
            print(f"  - {f.stem}")
        print("\nBase classes:")
        for f in BASE_DIR.glob("*.yaml"):
            print(f"  - {f.stem}")
    
    elif command == "load":
        role_name = sys.argv[2] if len(sys.argv) > 2 else "scout"
        role = engine.load_role(role_name)
        print(yaml.dump(role, default_flow_style=False))
    
    elif command == "validate":
        role_name = sys.argv[2] if len(sys.argv) > 2 else "scout"
        role = engine.load_role(role_name)
        errors = engine.validate_role(role)
        if errors:
            print("Validation errors:")
            for e in errors:
                print(f"  - {e}")
        else:
            print("Role is valid")
    
    elif command == "prompt":
        role_name = sys.argv[2] if len(sys.argv) > 2 else "scout"
        role = engine.load_role(role_name)
        task = {
            "objective": "Sample task objective",
            "files_in_scope": "- tests/\n- src/",
            "instructions": "1. Analyze files\n2. Report findings"
        }
        print(engine.render_prompt(role, task))
    
    elif command == "override":
        role_name = sys.argv[2] if len(sys.argv) > 2 else "scout"
        overrides = {
            "limits": {"max_turns": 12},
            "permissions": {"can_write": True}
        }
        role = engine.load_role(role_name, overrides)
        print(yaml.dump(role, default_flow_style=False))
    
    else:
        print(f"Unknown command: {command}")
        print("Usage: role_engine.py [list|load|validate|prompt|override] [role_name]")


if __name__ == "__main__":
    main()
