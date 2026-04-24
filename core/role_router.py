"""Role Router - Selection logic for agents and models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class InvocationMode(Enum):
    """How to invoke the role."""

    AUTO = "auto"
    EXPLICIT = "explicit"
    NONE = "none"


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
    """Routes tasks to appropriate agents and models."""

    def __init__(self):
        self._mappings: List[RoleMapping] = []
        self._role_to_agent: Dict[str, str] = {}
        self._role_to_model_role: Dict[str, str] = {}
        self._default_fallback_role = "executor"
        self._init_default_mappings()

    def _init_default_mappings(self) -> None:
        self.add_mapping(RoleMapping("plan", "planner", fallback_role="executor"))
        for pattern in ("retrieve", "search", "find"):
            self.add_mapping(RoleMapping(pattern, "retriever"))
        for pattern in ("summarize", "summary"):
            self.add_mapping(
                RoleMapping(
                    pattern,
                    "summarizer",
                    requires_model=True,
                    model_role_preference="summarizer",
                )
            )
        for pattern in ("review", "critique", "analyze"):
            self.add_mapping(RoleMapping(pattern, "critic"))
        for pattern in ("navigate", "browse"):
            self.add_mapping(RoleMapping(pattern, "navigator"))
        for pattern in ("execute", "run"):
            self.add_mapping(RoleMapping(pattern, "executor"))
        for pattern in (
            "what ",
            "how ",
            "why ",
            "explain",
            "describe",
            "tell me",
            "what is",
            "how do",
        ):
            self.add_mapping(RoleMapping(pattern, "planner", fallback_role="executor"))

    def add_mapping(self, mapping: RoleMapping) -> None:
        self._mappings.append(mapping)

    def set_role_agent(self, role: str, agent_id: str) -> None:
        self._role_to_agent[role] = agent_id

    def set_role_model(self, role: str, model_role: str) -> None:
        self._role_to_model_role[role] = model_role

    def _assigned_model_for_role(self, role: str, available_models: Optional[List[str]]) -> Optional[str]:
        """Prefer slot assignment for a role, then fall back to loaded models."""
        available = set(available_models or [])
        if not available:
            return None
        try:
            from core.slot_manager import get_slot_manager

            assignment = get_slot_manager().get_role_assignment(role)
            model_id = getattr(assignment, "assigned_model_id", None) if assignment else None
            if model_id in available:
                return model_id
        except Exception:
            pass
        return sorted(available)[0]

    def route(
        self,
        task: str,
        intent: Optional[Dict[str, Any]] = None,
        explicit_role: Optional[str] = None,
        available_models: Optional[List[str]] = None,
        force_no_model: bool = False,
    ) -> RouteDecision:
        if explicit_role:
            model_id = None if force_no_model else self._assigned_model_for_role(explicit_role, available_models)
            return RouteDecision(
                role=explicit_role,
                mode=InvocationMode.EXPLICIT,
                model_id=model_id,
                model_used=model_id is not None,
            )

        import re as _re

        task_lower = task.lower()
        best_mapping: Optional[RoleMapping] = None

        def _pattern_matches(pattern: str, text: str) -> bool:
            if len(pattern) <= 4:
                return bool(_re.search(r"\b" + _re.escape(pattern.strip()) + r"\b", text))
            return pattern in text

        for mapping in self._mappings:
            if _pattern_matches(mapping.task_pattern, task_lower):
                if best_mapping is None or len(mapping.task_pattern) > len(best_mapping.task_pattern):
                    best_mapping = mapping

        if best_mapping is None:
            return RouteDecision(
                role=self._default_fallback_role,
                mode=InvocationMode.AUTO,
                fallback_used=True,
                fallback_reason="no_matching_mapping",
            )

        model_id = None
        model_used = False
        if best_mapping.requires_model and not force_no_model:
            model_id = self._assigned_model_for_role(best_mapping.role, available_models)
            model_used = model_id is not None

        if best_mapping.requires_model and not model_used and best_mapping.fallback_role:
            return RouteDecision(
                role=best_mapping.fallback_role,
                mode=InvocationMode.AUTO,
                model_used=False,
                fallback_used=True,
                fallback_reason="no_model_available",
            )

        return RouteDecision(
            role=best_mapping.role,
            mode=InvocationMode.AUTO,
            model_id=model_id,
            model_used=model_used,
            confidence=0.9,
        )

    def get_available_roles(self) -> List[str]:
        roles = set()
        for mapping in self._mappings:
            roles.add(mapping.role)
            if mapping.fallback_role:
                roles.add(mapping.fallback_role)
        roles.add(self._default_fallback_role)
        return sorted(roles)


_global_router: Optional[RoleRouter] = None


def get_role_router() -> RoleRouter:
    global _global_router
    if _global_router is None:
        _global_router = RoleRouter()
    return _global_router
