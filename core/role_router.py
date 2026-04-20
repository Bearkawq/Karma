"""Role Router - Selection logic for agents and models.

Determines which agent and/or model to use for a given task.
Deterministic by default with support for explicit or automatic routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum


class InvocationMode(Enum):
    """How to invoke the role."""
    AUTO = "auto"
    EXPLICIT = "explicit"
    NONE = "none"  # No model/agent needed


@dataclass
class RoleMapping:
    """Maps a task type to an agent role."""
    task_pattern: str
    role: str
    requires_model: bool = False
    model_role_preference: Optional[str] = None
    fallback_role: Optional[str] = None
    confidence_threshold: float = 0.0


@dataclass
class RouteDecision:
    """Result of routing decision."""
    role: str
    mode: InvocationMode
    model_id: Optional[str] = None
    model_used: bool = False
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class RoleRouter:
    """Routes tasks to appropriate agents and models.
    
    Requirements:
    - Deterministic by default
    - Support explicit mode selection
    - Support auto mode with confidence threshold
    - Low confidence falls back to Karma core behavior
    - Don't invoke heavy models when deterministic is enough
    """
    
    def __init__(self):
        self._mappings: List[RoleMapping] = []
        self._role_to_agent: Dict[str, str] = {}
        self._role_to_model_role: Dict[str, str] = {}
        self._default_fallback_role = "executor"
        self._init_default_mappings()
    
    def _init_default_mappings(self) -> None:
        """Initialize default role mappings."""
        # Planning tasks
        self.add_mapping(RoleMapping(
            task_pattern="plan",
            role="planner",
            requires_model=False,
            fallback_role="executor",
        ))
        
        # Retrieval tasks
        self.add_mapping(RoleMapping(
            task_pattern="retrieve",
            role="retriever",
            requires_model=False,
        ))
        self.add_mapping(RoleMapping(
            task_pattern="search",
            role="retriever",
            requires_model=False,
        ))
        self.add_mapping(RoleMapping(
            task_pattern="find",
            role="retriever",
            requires_model=False,
        ))
        
        # Summarization tasks
        self.add_mapping(RoleMapping(
            task_pattern="summarize",
            role="summarizer",
            requires_model=True,
            model_role_preference="summarizer",
        ))
        self.add_mapping(RoleMapping(
            task_pattern="summary",
            role="summarizer",
            requires_model=True,
            model_role_preference="summarizer",
        ))
        
        # Review tasks
        self.add_mapping(RoleMapping(
            task_pattern="review",
            role="critic",
            requires_model=False,
        ))
        self.add_mapping(RoleMapping(
            task_pattern="critique",
            role="critic",
            requires_model=False,
        ))
        self.add_mapping(RoleMapping(
            task_pattern="analyze",
            role="critic",
            requires_model=False,
        ))
        
        # Navigation tasks
        self.add_mapping(RoleMapping(
            task_pattern="navigate",
            role="navigator",
            requires_model=False,
        ))
        self.add_mapping(RoleMapping(
            task_pattern="browse",
            role="navigator",
            requires_model=False,
        ))
        
        # Execution tasks (default)
        self.add_mapping(RoleMapping(
            task_pattern="execute",
            role="executor",
            requires_model=False,
        ))
        self.add_mapping(RoleMapping(
            task_pattern="run",
            role="executor",
            requires_model=False,
        ))

        # Question / explain tasks → planner (qwen3:4b, most capable for reasoning)
        for pattern in ("what ", "how ", "why ", "explain", "describe", "tell me", "what is", "how do"):
            self.add_mapping(RoleMapping(
                task_pattern=pattern,
                role="planner",
                requires_model=False,
                fallback_role="executor",
            ))
    
    def add_mapping(self, mapping: RoleMapping) -> None:
        """Add a role mapping."""
        self._mappings.append(mapping)
    
    def set_role_agent(self, role: str, agent_id: str) -> None:
        """Set which agent implements a role."""
        self._role_to_agent[role] = agent_id
    
    def set_role_model(self, role: str, model_role: str) -> None:
        """Set preferred model role for an agent role."""
        self._role_to_model_role[role] = model_role
    
    def route(
        self,
        task: str,
        intent: Optional[Dict[str, Any]] = None,
        explicit_role: Optional[str] = None,
        available_models: Optional[List[str]] = None,
        force_no_model: bool = False,
    ) -> RouteDecision:
        """Route task to appropriate agent/model.
        
        Args:
            task: Task description
            intent: Parsed intent (optional)
            explicit_role: Force a specific role
            available_models: List of available model IDs
            force_no_model: Force deterministic mode
            
        Returns:
            RouteDecision with selected role and model
        """
        # Explicit role selection — check for available models if not forcing no model
        if explicit_role:
            model_id = None
            model_used = False
            if not force_no_model and available_models:
                model_id = available_models[0]
                model_used = True
            return RouteDecision(
                role=explicit_role,
                mode=InvocationMode.EXPLICIT,
                model_id=model_id,
                model_used=model_used,
            )
        
        # Find matching mapping — prefer longer patterns; use word boundary for
        # short patterns (≤4 chars) to avoid "run" matching inside "return"
        import re as _re
        task_lower = task.lower()
        best_mapping: Optional[RoleMapping] = None

        def _pattern_matches(pattern: str, text: str) -> bool:
            if len(pattern) <= 4:
                return bool(_re.search(r'\b' + _re.escape(pattern.strip()) + r'\b', text))
            return pattern in text

        for mapping in self._mappings:
            if _pattern_matches(mapping.task_pattern, task_lower):
                if best_mapping is None or len(mapping.task_pattern) > len(best_mapping.task_pattern):
                    best_mapping = mapping
        
        # Use default if no match
        if best_mapping is None:
            return RouteDecision(
                role=self._default_fallback_role,
                mode=InvocationMode.AUTO,
                fallback_used=True,
                fallback_reason="no_matching_mapping",
            )
        
        # Check if model should be used
        model_used = False
        model_id = None
        
        if best_mapping.requires_model and not force_no_model:
            if available_models:
                # Find suitable model
                preferred = best_mapping.model_role_preference
                if preferred and available_models:
                    model_id = available_models[0]  # Use first available
                    model_used = True
        
        # Determine fallback
        fallback_used = False
        fallback_reason = None
        
        if best_mapping.requires_model and not model_used:
            if best_mapping.fallback_role:
                fallback_used = True
                fallback_reason = "no_model_available"
                return RouteDecision(
                    role=best_mapping.fallback_role,
                    mode=InvocationMode.AUTO,
                    model_used=False,
                    fallback_used=True,
                    fallback_reason=fallback_reason,
                )
        
        return RouteDecision(
            role=best_mapping.role,
            mode=InvocationMode.AUTO,
            model_id=model_id,
            model_used=model_used,
            confidence=0.9 if best_mapping else 0.5,
        )
    
    def get_available_roles(self) -> List[str]:
        """Get all registered roles."""
        roles = set()
        for mapping in self._mappings:
            roles.add(mapping.role)
            if mapping.fallback_role:
                roles.add(mapping.fallback_role)
        roles.add(self._default_fallback_role)
        return sorted(roles)


_global_router: Optional[RoleRouter] = None


def get_role_router() -> RoleRouter:
    """Get global role router."""
    global _global_router
    if _global_router is None:
        _global_router = RoleRouter()
    return _global_router
