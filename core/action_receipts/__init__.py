"""Action Receipts - Structured receipts for executed actions.

Receipt fields:
- action_name
- handler
- execution_time
- inputs
- artifacts_generated
- state_mutations
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from threading import Lock
from collections import deque


@dataclass
class ActionReceipt:
    """Structured receipt for an executed action."""
    action_name: str
    handler: str
    execution_time_ms: float
    timestamp: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    artifacts_generated: List[str] = field(default_factory=list)
    state_mutations: List[Dict[str, Any]] = field(default_factory=list)
    result_status: str = "success"
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReceiptStore:
    """Stores action receipts."""
    
    def __init__(self, max_receipts: int = 500):
        self._receipts: deque = deque(maxlen=max_receipts)
        self._lock = Lock()
    
    def add_receipt(self, receipt: ActionReceipt) -> None:
        """Add a new action receipt."""
        with self._lock:
            self._receipts.append(receipt)
    
    def create_receipt(
        self,
        action_name: str,
        handler: str,
        execution_time_ms: float,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> ActionReceipt:
        """Create and store a new receipt."""
        receipt = ActionReceipt(
            action_name=action_name,
            handler=handler,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.now().isoformat(),
            inputs=inputs or {},
        )
        self.add_receipt(receipt)
        return receipt
    
    def get_latest_receipt(self) -> Optional[ActionReceipt]:
        """Get the most recent receipt."""
        with self._lock:
            if self._receipts:
                return self._receipts[-1]
        return None
    
    def get_recent_receipts(self, limit: int = 20) -> List[ActionReceipt]:
        """Get recent receipts."""
        with self._lock:
            return list(self._receipts)[-limit:]
    
    def get_receipts_for_action(self, action_name: str) -> List[ActionReceipt]:
        """Get receipts for a specific action."""
        with self._lock:
            return [r for r in self._receipts if r.action_name == action_name]
    
    def add_artifact(self, receipt: ActionReceipt, artifact_id: str) -> None:
        """Add an artifact to a receipt."""
        with self._lock:
            if receipt in self._receipts:
                receipt.artifacts_generated.append(artifact_id)
    
    def add_mutation(self, receipt: ActionReceipt, mutation: Dict[str, Any]) -> None:
        """Add a state mutation to a receipt."""
        with self._lock:
            if receipt in self._receipts:
                receipt.state_mutations.append(mutation)
    
    def set_error(self, receipt: ActionReceipt, error: str) -> None:
        """Mark receipt as failed."""
        with self._lock:
            if receipt in self._receipts:
                receipt.result_status = "failure"
                receipt.error = error
    
    def set_status(self, receipt: ActionReceipt, status: str) -> None:
        """Set receipt status."""
        with self._lock:
            if receipt in self._receipts:
                receipt.result_status = status
    
    def get_summary(self) -> Dict[str, Any]:
        """Get receipt statistics."""
        with self._lock:
            total = len(self._receipts)
            if total == 0:
                return {"total": 0, "success": 0, "failure": 0}
            
            success = sum(1 for r in self._receipts if r.result_status == "success")
            failure = sum(1 for r in self._receipts if r.result_status == "failure")
            
            times = [r.execution_time_ms for r in self._receipts]
            avg_time = sum(times) / len(times) if times else 0
            
            action_counts: Dict[str, int] = {}
            for r in self._receipts:
                action_counts[r.action_name] = action_counts.get(r.action_name, 0) + 1
            
            return {
                "total": total,
                "success": success,
                "failure": failure,
                "success_rate": success / total,
                "avg_execution_time_ms": avg_time,
                "action_counts": action_counts,
            }
    
    def save_receipts(self, path: str) -> None:
        """Persist receipts to file."""
        with self._lock:
            receipts = [r.to_dict() for r in self._receipts]
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(receipts, f, indent=2)
    
    def clear(self) -> None:
        """Clear all receipts (for testing)."""
        with self._lock:
            self._receipts.clear()


_global_store: Optional[ReceiptStore] = None


def get_receipt_store() -> ReceiptStore:
    """Get global receipt store."""
    global _global_store
    if _global_store is None:
        _global_store = ReceiptStore()
    return _global_store
