from __future__ import annotations

from typing import Dict, Any, List, Tuple


def build_model_status_text(manager, slot_mgr) -> str:
    """Return multi-line status of roles, slots, and models."""
    lines: List[str] = []

    roles = sorted(slot_mgr.ROLE_TO_SLOT.keys())
    available = {m["model_id"]: m for m in manager.get_available_models()} if hasattr(manager, 'get_available_models') else {}
    loaded = set(manager.get_loaded_models()) if hasattr(manager, 'get_loaded_models') else set()

    lines.append("Model status:")
    for role in roles:
        slot = slot_mgr.ROLE_TO_SLOT.get(role)
        slot_info = slot_mgr.get_slot(slot)
        assigned = slot_info.assigned_model_id if slot_info else None
        deterministic = slot_info.deterministic_only if slot_info else False
        model_known = assigned in available if assigned else False
        model_loaded = assigned in loaded if assigned else False
        status = []
        if not assigned:
            status.append("UNASSIGNED")
        else:
            if not model_known:
                status.append("MISSING")
            elif model_loaded:
                status.append("LOADED")
            else:
                status.append("REGISTERED")
        lines.append(
            f"- role: {role} | slot: {slot} | assigned: {assigned or '<none>'} | "
            f"deterministic: {deterministic} | status: {', '.join(status)}"
        )
    lines.append("")

    # Summarize available models
    lines.append("Available models:")
    for m in manager.get_available_models():
        mid = m.get("model_id")
        loaded_flag = "(loaded)" if mid in loaded else ""
        lines.append(f"- {mid} {loaded_flag}")

    return "\n".join(lines)


def assign_model_to_role(manager, slot_mgr, role: str, model_id: str) -> Tuple[bool, str]:
    """Assign model to role. Validates model exists in manager inventory."""
    # validate role
    slot = slot_mgr.ROLE_TO_SLOT.get(role)
    if not slot:
        return False, f"Unknown role: {role}"

    avail = [m.get("model_id") for m in manager.get_available_models()]
    if model_id not in avail:
        return False, f"Model not found: {model_id}"

    ok = slot_mgr.assign_role(role, model_id)
    return ok, f"Assigned {model_id} to role {role}" if ok else (False, "Assignment failed")


def assign_model_to_slot(manager, slot_mgr, slot: str, model_id: str) -> Tuple[bool, str]:
    if slot not in slot_mgr._slots:
        return False, f"Unknown slot: {slot}"
    avail = [m.get("model_id") for m in manager.get_available_models()]
    if model_id not in avail:
        return False, f"Model not found: {model_id}"
    ok = slot_mgr.assign_model(slot, model_id)
    return ok, f"Assigned {model_id} to slot {slot}" if ok else (False, "Assignment failed")


def bootstrap_layout(manager, slot_mgr) -> Dict[str, Any]:
    """Assign available models across roles (best-effort). Returns report."""
    report = {"assigned": [], "skipped": []}
    # prefer loaded models
    available = manager.get_loaded_models() if hasattr(manager, 'get_loaded_models') else []
    if not available:
        available = [m.get('model_id') for m in manager.get_available_models()]

    used = set()
    for role, slot in slot_mgr.ROLE_TO_SLOT.items():
        # pick next available model not used
        candidate = None
        for mid in available:
            if mid not in used:
                candidate = mid
                break
        if candidate:
            slot_mgr.assign_role(role, candidate)
            used.add(candidate)
            report['assigned'].append({'role': role, 'slot': slot, 'model': candidate})
        else:
            report['skipped'].append({'role': role, 'slot': slot})
    return report
