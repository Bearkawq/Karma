from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models.local_llm_adapter import OLLAMA_BASE_URL


SMALL_MODEL_POOL = [
    "qwen3:4b",
    "granite3.3:2b",
    "gemma3:4b",
    "phi4-mini",
    "nomic-embed-text",
]

ROLE_BOOTSTRAP_FALLBACKS = {
    "planner": ["qwen3:4b", "phi4-mini", "gemma3:4b", "granite3.3:2b"],
    "executor": ["qwen3:4b", "phi4-mini", "gemma3:4b", "granite3.3:2b"],
    "critic": ["qwen3:4b", "phi4-mini", "gemma3:4b", "granite3.3:2b"],
    "summarizer": ["granite3.3:2b", "gemma3:4b", "phi4-mini", "qwen3:4b"],
    "navigator": ["granite3.3:2b", "gemma3:4b", "phi4-mini", "qwen3:4b"],
    "retriever": ["nomic-embed-text"],
}


def _request_json(path: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _model_names_from_manager(manager) -> List[str]:
    if not manager or not hasattr(manager, "get_available_models"):
        return []
    names = []
    for model in manager.get_available_models():
        model_id = model.get("model_id") if isinstance(model, dict) else None
        if model_id:
            names.append(model_id)
    return names


def _loaded_names_from_manager(manager) -> List[str]:
    if manager and hasattr(manager, "get_loaded_models"):
        return list(manager.get_loaded_models())
    return []


def _ollama_inventory(manager=None) -> Dict[str, Any]:
    tags = _request_json("/api/tags")
    ps = _request_json("/api/ps")

    if tags is None:
        model_names = _model_names_from_manager(manager)
        source = "manager"
        reachable = False
    else:
        model_names = [
            item.get("name")
            for item in tags.get("models", [])
            if isinstance(item, dict) and item.get("name")
        ]
        source = "ollama"
        reachable = True

    if ps is None:
        loaded_names = _loaded_names_from_manager(manager)
    else:
        loaded_names = [
            item.get("name")
            for item in ps.get("models", [])
            if isinstance(item, dict) and item.get("name")
        ]

    return {
        "reachable": reachable,
        "source": source,
        "models": sorted(set(model_names)),
        "loaded": sorted(set(loaded_names)),
    }


def _model_matches(listed: str, wanted: str) -> bool:
    if listed == wanted:
        return True
    if listed.startswith(wanted + ":"):
        return True
    if ":" not in wanted and listed.split(":", 1)[0] == wanted:
        return True
    return False


def _find_model(inventory: Dict[str, Any], model_id: Optional[str]) -> Optional[str]:
    if not model_id:
        return None
    for listed in inventory.get("models", []):
        if _model_matches(listed, model_id):
            return listed
    return None


def _is_loaded(inventory: Dict[str, Any], model_id: Optional[str]) -> bool:
    if not model_id:
        return False
    return any(_model_matches(listed, model_id) for listed in inventory.get("loaded", []))


def _preference_path(role: str, preferences_path: Optional[Path] = None) -> List[str]:
    candidates: List[str] = []
    if preferences_path is None:
        preferences_path = Path(__file__).resolve().parents[2] / "config" / "model_preferences.json"

    try:
        data = json.loads(preferences_path.read_text(encoding="utf-8"))
        pref = data.get("role_preferences", {}).get(role, {})
        preferred = pref.get("preferred_model")
        if preferred:
            candidates.append(preferred)
        candidates.extend(pref.get("fallback_models", []))
    except (OSError, json.JSONDecodeError):
        pass

    candidates.extend(ROLE_BOOTSTRAP_FALLBACKS.get(role, []))
    seen = set()
    return [m for m in candidates if not (m in seen or seen.add(m))]


def build_inventory_rows(manager, slot_mgr) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    inventory = _ollama_inventory(manager)
    rows: List[Dict[str, Any]] = []

    for role in sorted(slot_mgr.ROLE_TO_SLOT):
        slot = slot_mgr.ROLE_TO_SLOT.get(role)
        assignment = slot_mgr.get_slot(slot) if slot else None
        assigned = assignment.assigned_model_id if assignment else None
        matched_model = _find_model(inventory, assigned)
        issues = []

        if not slot or assignment is None:
            issues.append("broken-role-mapping")
        if not assigned:
            issues.append("unassigned")
        elif matched_model is None:
            issues.append("model-missing")

        rows.append({
            "role": role,
            "slot": slot or "<missing>",
            "assigned_model_id": assigned,
            "ollama_model": matched_model,
            "exists_in_ollama": matched_model is not None,
            "installed_in_ollama": matched_model is not None,
            "loaded": _is_loaded(inventory, assigned),
            "warm_now": _is_loaded(inventory, assigned),
            "deterministic_only": bool(assignment.deterministic_only) if assignment else False,
            "issues": issues,
        })

    return rows, inventory


def build_model_status_text(manager, slot_mgr) -> str:
    """Return multi-line status of roles, slots, and models."""
    lines: List[str] = []
    rows, inventory = build_inventory_rows(manager, slot_mgr)

    lines.append("Model status:")
    lines.append(
        f"Ollama reachable: {inventory['reachable']} | inventory source: {inventory['source']}"
    )
    for row in rows:
        if not row["assigned_model_id"]:
            status = "UNASSIGNED"
        elif not row["exists_in_ollama"]:
            status = "MISSING"
        elif row["warm_now"]:
            status = "INSTALLED_WARM"
        else:
            status = "INSTALLED_IDLE"
        issue_text = ", ".join(row["issues"]) if row["issues"] else "none"
        lines.append(
            f"- role: {row['role']} | slot: {row['slot']} | "
            f"assigned: {row['assigned_model_id'] or '<none>'} | "
            f"ollama: {row['ollama_model'] or '<missing>'} | "
            f"present_on_disk: {row['installed_in_ollama']} | loaded(warm): {row['warm_now']} | "
            f"deterministic_only: {row['deterministic_only']} | "
            f"status: {status} | issues: {issue_text}"
        )
    lines.append("")

    lines.append("Small model pool:")
    for model_id in SMALL_MODEL_POOL:
        matched = _find_model(inventory, model_id)
        loaded = _is_loaded(inventory, model_id)
        lines.append(
            f"- {model_id} | present_on_disk: {matched is not None} | "
            f"ollama: {matched or '<missing>'} | loaded(warm): {loaded}"
        )

    lines.append("")
    lines.append("Available Ollama models:")
    for model_id in inventory.get("models", []):
        loaded_flag = " (loaded/warm)" if _is_loaded(inventory, model_id) else ""
        lines.append(f"- {model_id}{loaded_flag}")

    broken = [row for row in rows if row["issues"]]
    if broken:
        lines.append("")
        lines.append("Broken mappings:")
        for row in broken:
            lines.append(
                f"- {row['role']} -> {row['slot']}: {', '.join(row['issues'])}"
            )

    return "\n".join(lines)


def build_readiness_report(manager, slot_mgr) -> Dict[str, Any]:
    """Return a read-only operator readiness report for local model ops."""
    rows, inventory = build_inventory_rows(manager, slot_mgr)

    small_models = []
    missing_small_models = []
    for model_id in SMALL_MODEL_POOL:
        matched = _find_model(inventory, model_id)
        present = matched is not None
        if not present:
            missing_small_models.append(model_id)
        small_models.append({
            "model": model_id,
            "present": present,
            "installed": present,
            "ollama_model": matched,
            "loaded": _is_loaded(inventory, model_id),
            "warm_now": _is_loaded(inventory, model_id),
        })

    role_issues = []
    layout_issues = []
    for row in rows:
        issues = list(row["issues"])
        if row["deterministic_only"]:
            issues.append("deterministic-only")
        assigned = row["assigned_model_id"]
        preferences = _preference_path(row["role"])
        if assigned and row["exists_in_ollama"] and assigned not in preferences:
            issues.append("outside-recommended-layout")
            layout_issues.append({
                "role": row["role"],
                "slot": row["slot"],
                "assigned_model_id": assigned,
                "recommended": preferences,
            })
        if issues:
            role_issues.append({
                "role": row["role"],
                "slot": row["slot"],
                "assigned_model_id": assigned,
                "issues": issues,
            })

    checks = [
        {
            "name": "Ollama reachable",
            "ok": inventory["reachable"],
            "detail": "reachable at localhost:11434" if inventory["reachable"] else "not reachable at localhost:11434",
        },
        {
            "name": "Small model pool installed",
            "ok": not missing_small_models,
            "detail": "all present" if not missing_small_models else "missing: " + ", ".join(missing_small_models),
        },
        {
            "name": "Role assignments valid",
            "ok": not role_issues,
            "detail": "all roles assigned to installed recommended models" if not role_issues else f"{len(role_issues)} role issue(s)",
        },
        {
            "name": "Bootstrap layout sane",
            "ok": not layout_issues and not role_issues,
            "detail": "current assignments match recommended layout" if not layout_issues and not role_issues else "run bootstrap after fixing prerequisites",
        },
    ]

    ready = all(check["ok"] for check in checks)
    next_steps = []
    if not inventory["reachable"]:
        next_steps.append("Start Ollama: ollama serve")
    for model_id in missing_small_models:
        next_steps.append(f"Install missing model: ollama pull {model_id}")
    if role_issues or layout_issues:
        next_steps.append("Apply recommended assignments: python3 agent/agent_loop.py --bootstrap-models")
        next_steps.append("Inspect assignments: python3 agent/agent_loop.py --models")
    if not next_steps:
        next_steps.append("Ready to roll: run python3 agent/agent_loop.py or inspect with --models.")

    return {
        "ready": ready,
        "status": "READY" if ready else "NOT READY",
        "inventory": inventory,
        "small_models": small_models,
        "roles": rows,
        "checks": checks,
        "issues": {
            "missing_small_models": missing_small_models,
            "role_issues": role_issues,
            "layout_issues": layout_issues,
        },
        "next_steps": next_steps,
    }


def format_readiness_report(report: Dict[str, Any]) -> str:
    lines = [f"Karma model readiness: {report['status']}"]
    inventory = report["inventory"]
    lines.append(
        f"Ollama reachable: {inventory['reachable']} | inventory source: {inventory['source']}"
    )
    lines.append("")

    lines.append("Checks:")
    for check in report["checks"]:
        marker = "ok" if check["ok"] else "fail"
        lines.append(f"- {marker}: {check['name']} - {check['detail']}")
    lines.append("")

    lines.append("Required small models:")
    for model in report["small_models"]:
        lines.append(
            f"- {model['model']} | present_on_disk: {model['present']} | "
            f"ollama: {model['ollama_model'] or '<missing>'} | loaded(warm): {model['warm_now']}"
        )
    lines.append("")

    lines.append("Role assignments:")
    role_issue_map = {
        (item["role"], item["slot"]): item["issues"]
        for item in report["issues"]["role_issues"]
    }
    for row in report["roles"]:
        issues = role_issue_map.get((row["role"], row["slot"]), row["issues"])
        issue_text = ", ".join(issues) if issues else "none"
        lines.append(
            f"- {row['role']} -> {row['slot']} | assigned: {row['assigned_model_id'] or '<none>'} | "
            f"ollama: {row['ollama_model'] or '<missing>'} | present_on_disk: {row['installed_in_ollama']} | "
            f"loaded(warm): {row['warm_now']} | "
            f"deterministic_only: {row['deterministic_only']} | issues: {issue_text}"
        )
    lines.append("")

    lines.append("Next steps:")
    for step in report["next_steps"]:
        lines.append(f"- {step}")

    return "\n".join(lines)


def build_readiness_text(manager, slot_mgr) -> Tuple[bool, str]:
    report = build_readiness_report(manager, slot_mgr)
    return report["ready"], format_readiness_report(report)


def _validate_model(manager, model_id: str) -> Tuple[bool, str]:
    inventory = _ollama_inventory(manager)
    matched = _find_model(inventory, model_id)
    if matched:
        return True, matched
    if inventory["reachable"]:
        return False, f"Model not found in Ollama inventory: {model_id}"
    return False, f"Model not found in available model inventory: {model_id}"


def assign_model_to_role(
    manager,
    slot_mgr,
    role: str,
    model_id: str,
    deterministic: bool = False,
) -> Tuple[bool, str]:
    """Assign model to role. Validates model exists in manager inventory."""
    slot = slot_mgr.ROLE_TO_SLOT.get(role)
    if not slot:
        return False, f"Unknown role: {role}"

    valid, detail = _validate_model(manager, model_id)
    if not valid:
        return False, detail

    ok = slot_mgr.assign_role(role, model_id, deterministic=deterministic)
    if ok:
        return True, f"Assigned {model_id} to role {role} (slot {slot}); resolved as {detail}"
    return False, "Assignment failed"


def assign_model_to_slot(
    manager,
    slot_mgr,
    slot: str,
    model_id: str,
    deterministic: bool = False,
) -> Tuple[bool, str]:
    if slot not in slot_mgr._slots:
        return False, f"Unknown slot: {slot}"

    valid, detail = _validate_model(manager, model_id)
    if not valid:
        return False, detail

    ok = slot_mgr.assign_model(slot, model_id, deterministic=deterministic)
    if ok:
        return True, f"Assigned {model_id} to slot {slot}; resolved as {detail}"
    return False, "Assignment failed"


def bootstrap_layout(manager, slot_mgr) -> Dict[str, Any]:
    """Assign a conservative small-model layout from installed Ollama models."""
    inventory = _ollama_inventory(manager)
    report = {
        "assigned": [],
        "skipped": [],
        "inventory_source": inventory["source"],
        "ollama_reachable": inventory["reachable"],
    }

    for role, slot in slot_mgr.ROLE_TO_SLOT.items():
        candidate = None
        resolved = None
        for model_id in _preference_path(role):
            resolved_model = _find_model(inventory, model_id)
            if resolved_model:
                candidate = model_id
                resolved = resolved_model
                break

        if candidate and resolved:
            slot_mgr.assign_role(role, candidate)
            report["assigned"].append({
                "role": role,
                "slot": slot,
                "model": candidate,
                "ollama_model": resolved,
            })
        else:
            report["skipped"].append({
                "role": role,
                "slot": slot,
                "reason": "no suitable installed model",
                "candidates": _preference_path(role),
            })
    return report
