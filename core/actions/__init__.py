"""Base action handler module.

Defines the interface for action handlers.
"""

from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING


class ActionContext:
    """Context passed to action handlers.
    
    Provides access to agent subsystems without relying on singletons.
    """
    
    def __init__(self, agent: Any):
        self.agent = agent
        self.memory = agent.memory
        self.retrieval = agent.retrieval
        self.capability_map = agent.capability_map
        self.tool_manager = agent.tool_manager
        self.base_dir = agent.base_dir
        self.config = agent.config
        self.logger = agent.logger


class BaseActionHandler:
    """Base class for action handlers."""
    
    def __init__(self, context: ActionContext):
        self.context = context
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the action.
        
        Override this method in subclasses.
        """
        raise NotImplementedError
