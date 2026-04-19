"""Action registry for agent loop.

Provides a registry-based dispatch system for action handlers,
replacing the long if/elif chain in _execute_action.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


ActionHandler = Callable[[Dict[str, Any]], Dict[str, Any]]


class ActionRegistry:
    """Registry for action handlers.
    
    Allows actions to be registered and dispatched without modifying
    a large conditional block.
    """
    
    def __init__(self):
        self._handlers: Dict[str, ActionHandler] = {}
        self._direct_intents: Dict[str, Optional[str]] = {}
    
    def register(self, name: str, handler: ActionHandler, tool_name: Optional[str] = None) -> None:
        """Register an action handler.
        
        Args:
            name: The action name (e.g., "golearn", "ingest")
            handler: Callable that takes params dict and returns result dict
            tool_name: Optional tool name for the action
        """
        self._handlers[name] = handler
        self._direct_intents[name] = tool_name
    
    def get_handler(self, name: str) -> Optional[ActionHandler]:
        """Get a registered handler by name."""
        return self._handlers.get(name)
    
    def get_tool_name(self, name: str) -> Optional[str]:
        """Get the tool name for an action."""
        return self._direct_intents.get(name)
    
    def is_registered(self, name: str) -> bool:
        """Check if an action is registered."""
        return name in self._handlers
    
    def list_actions(self) -> list[str]:
        """List all registered action names."""
        return list(self._handlers.keys())
    
    def execute(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a registered action.
        
        Returns error dict if handler not found.
        """
        handler = self.get_handler(name)
        if handler is None:
            return {
                "success": False,
                "output": None,
                "error": f"Unknown action: {name}"
            }
        return handler(params)


_global_registry: Optional[ActionRegistry] = None


def get_action_registry() -> ActionRegistry:
    """Get the global action registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ActionRegistry()
    return _global_registry


ACTION_REGISTRY = get_action_registry()
