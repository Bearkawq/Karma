"""Post-execution handler — offloaded from AgentLoop (#1).

Handles:
- Capability map recording
- Workflow storage on success
- Failure fingerprint storage on failure
- Meta timing
"""

from __future__ import annotations
from typing import Any, Dict


class PostExecutor:
    """Handles post-execution bookkeeping so AgentLoop stays lean."""

    def __init__(self, meta, capability_map, retrieval):
        self._meta = meta
        self._cap_map = capability_map
        self._retrieval = retrieval

    def run(self, action: Dict[str, Any], result: Dict[str, Any]):
        """Execute all post-execution hooks."""
        action_name = action.get("name", "unknown")
        tool_name = action.get("tool") or action_name
        success = result.get("success", False)

        # Time tracking
        self._meta.end_action(action_name)

        # Capability map update
        self._cap_map.record(
            tool_name, action_name, success,
            context=action_name,
            inputs=str(list((action.get("parameters") or {}).keys())),
        )

        # Workflow on success (with shape metadata)
        if success and tool_name:
            sig = f"{tool_name}.{action_name}"
            self._retrieval.store_workflow(
                sig, [action_name], [tool_name],
                intent=action_name,
                entities=action.get("parameters"),
            )

        # Failure fingerprint on failure
        if not success:
            error = result.get("error", "")
            error_class = error.split(":")[0] if error else "unknown"
            params = action.get("parameters") or {}
            self._retrieval.store_failure(
                intent=action_name, tool=tool_name,
                params=params, error_class=error_class,
                context=str(params)[:200],
                lesson=f"Action {action_name} with tool {tool_name} failed: {error[:100]}",
            )
