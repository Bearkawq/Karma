"""Slot Manager - Role to Model Assignment.

Manages assignment of models to functional slots/roles.
Provides persistence and GUI-friendly state tracking.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from storage.persistence import atomic_write_text, quarantine_file


@dataclass
class SlotAssignment:
    """Assignment of a model to a slot/role."""
    slot_name: str
    assigned_model_id: Optional[str] = None
    fallback_enabled: bool = True
    deterministic_only: bool = False
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SlotState:
    """Current state of a slot."""
    slot_name: str
    assigned_model_id: Optional[str] = None
    model_loaded: bool = False
    model_enabled: bool = True
    is_deterministic: bool = False
    last_used: Optional[str] = None
    status: str = "idle"  # idle, active, error


class SlotManager:
    """Manages model slots and role assignments."""

    # Default slots
    DEFAULT_SLOTS = [
        "planner_slot",
        "coder_slot",
        "summarizer_slot",
        "embedder_slot",
        "navigator_slot",
        "general_language_slot",
    ]

    # Role to slot mapping
    ROLE_TO_SLOT = {
        "planner": "planner_slot",
        "executor": "coder_slot",
        "summarizer": "summarizer_slot",
        "retriever": "embedder_slot",
        "navigator": "navigator_slot",
        "critic": "general_language_slot",
    }

    def __init__(self, storage_path: Optional[str] = None):
        self._slots: Dict[str, SlotAssignment] = {}
        self._slot_states: Dict[str, SlotState] = {}
        self._storage_path = storage_path
        self._load_quarantined: bool = False

        # Initialize default slots
        for slot_name in self.DEFAULT_SLOTS:
            self._slots[slot_name] = SlotAssignment(slot_name=slot_name)
            self._slot_states[slot_name] = SlotState(slot_name=slot_name)

        # Load from disk if available
        if storage_path:
            self._load()

    def assign_model(
        self,
        slot_name: str,
        model_id: Optional[str],
        deterministic: bool = False,
    ) -> bool:
        """Assign a model to a slot.
        
        Args:
            slot_name: Slot to assign to
            model_id: Model to assign (None to clear)
            deterministic: Use deterministic mode
            
        Returns:
            True if assignment successful
        """
        if slot_name not in self._slots:
            return False

        assignment = self._slots[slot_name]
        assignment.assigned_model_id = model_id
        assignment.deterministic_only = deterministic
        assignment.last_updated = datetime.now().isoformat()

        # Update state
        state = self._slot_states[slot_name]
        state.assigned_model_id = model_id
        state.is_deterministic = deterministic
        state.status = "idle"

        self._save()
        return True

    def assign_role(
        self,
        role: str,
        model_id: Optional[str],
        deterministic: bool = False,
    ) -> bool:
        """Assign a model to a role (auto-maps to slot).
        
        Args:
            role: Role to assign to
            model_id: Model to assign
            deterministic: Use deterministic mode
            
        Returns:
            True if assignment successful
        """
        slot = self.ROLE_TO_SLOT.get(role)
        if slot:
            return self.assign_model(slot, model_id, deterministic)
        return False

    def get_slot(self, slot_name: str) -> Optional[SlotAssignment]:
        """Get slot assignment."""
        return self._slots.get(slot_name)

    def get_role_assignment(self, role: str) -> Optional[SlotAssignment]:
        """Get assignment for a role."""
        slot = self.ROLE_TO_SLOT.get(role)
        if slot:
            return self._slots.get(slot)
        return None

    def get_all_slots(self) -> List[Dict[str, Any]]:
        """Get all slots with current state."""
        result = []
        for slot_name, assignment in self._slots.items():
            state = self._slot_states[slot_name]
            result.append({
                "slot_name": slot_name,
                "assigned_model_id": assignment.assigned_model_id,
                "fallback_enabled": assignment.fallback_enabled,
                "deterministic_only": assignment.deterministic_only,
                "last_updated": assignment.last_updated,
                "model_loaded": state.model_loaded,
                "model_enabled": state.model_enabled,
                "is_deterministic": state.is_deterministic,
                "status": state.status,
            })
        return result

    def get_all_roles(self) -> List[Dict[str, Any]]:
        """Get all roles with assignments."""
        result = []
        for role, slot in self.ROLE_TO_SLOT.items():
            assignment = self._slots.get(slot)
            state = self._slot_states.get(slot)
            if assignment and state:
                result.append({
                    "role": role,
                    "slot": slot,
                    "assigned_model_id": assignment.assigned_model_id,
                    "deterministic_only": assignment.deterministic_only,
                    "model_loaded": state.model_loaded,
                    "status": state.status,
                })
        return result

    def set_slot_loaded(self, slot_name: str, loaded: bool) -> None:
        """Update slot load state."""
        if slot_name in self._slot_states:
            self._slot_states[slot_name].model_loaded = loaded
            self._slot_states[slot_name].status = "active" if loaded else "idle"

    def set_slot_error(self, slot_name: str, error: str) -> None:
        """Mark slot as errored."""
        if slot_name in self._slot_states:
            self._slot_states[slot_name].status = "error"

    def is_compatible(self, slot_name: str, model_capability: str) -> bool:
        """Check if a model capability is compatible with a slot."""
        slot_lower = slot_name.lower()

        if "embed" in slot_lower:
            return model_capability in ["embedding", "llm"]
        elif "summar" in slot_lower:
            return model_capability in ["llm", "summarizer"]
        elif "coder" in slot_lower or "planner" in slot_lower:
            return model_capability in ["llm", "coder"]
        elif "navigator" in slot_lower:
            return True  # Any model works
        else:
            return True  # Default allow

    def get_compatible_models(
        self,
        slot_name: str,
        available_models: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Get models compatible with a slot."""
        compatible = []
        for model in available_models:
            capability = model.get("metadata", {}).get("capabilities", {}).get("supports_generate", False)
            if capability:
                capability = "llm"
            else:
                capability = model.get("metadata", {}).get("capabilities", {}).get("supports_embed", False)
                if capability:
                    capability = "embedding"

            if self.is_compatible(slot_name, capability):
                compatible.append(model)

        return compatible

    def _save(self) -> None:
        """Save assignments to disk."""
        if not self._storage_path:
            return

        data = {
            slot_name: {
                "assigned_model_id": assignment.assigned_model_id,
                "fallback_enabled": assignment.fallback_enabled,
                "deterministic_only": assignment.deterministic_only,
                "last_updated": assignment.last_updated,
            }
            for slot_name, assignment in self._slots.items()
        }

        atomic_write_text(Path(self._storage_path), json.dumps(data, indent=2))

    @property
    def load_quarantined(self) -> bool:
        """True if the slots file was unreadable/corrupt at last load."""
        return self._load_quarantined

    def _load(self) -> None:
        """Load assignments from disk."""
        if not self._storage_path:
            return

        p = Path(self._storage_path)
        if not p.exists():
            return

        self._load_quarantined = False
        try:
            with open(p, "r") as f:
                data = json.load(f)

            for slot_name, slot_data in data.items():
                if slot_name in self._slots:
                    self._slots[slot_name].assigned_model_id = slot_data.get("assigned_model_id")
                    self._slots[slot_name].fallback_enabled = slot_data.get("fallback_enabled", True)
                    self._slots[slot_name].deterministic_only = slot_data.get("deterministic_only", False)
                    self._slots[slot_name].last_updated = slot_data.get("last_updated", datetime.now().isoformat())
        except Exception:
            try:
                quarantine_file(p)
            except Exception:
                pass
            self._load_quarantined = True


_global_manager: Optional[SlotManager] = None


def get_slot_manager(storage_path: Optional[str] = None) -> SlotManager:
    """Get global slot manager."""
    global _global_manager
    if _global_manager is None:
        _global_manager = SlotManager(storage_path=storage_path)
    return _global_manager
