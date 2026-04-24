"""Worker Registry - Registry for distributed worker nodes.

Manages registration and discovery of worker nodes. The local node defaults to
STG because that is the active machine for this deployment; override with the
KARMA_LOCAL_NODE_ID / KARMA_LOCAL_NODE_NAME environment variables when needed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class WorkerCapabilities:
    """Capabilities of a worker node."""

    can_plan: bool = False
    can_execute: bool = False
    can_retrieve: bool = False
    can_summarize: bool = False
    can_criticize: bool = False
    can_navigate: bool = False
    can_embed: bool = False
    has_gpu: bool = False
    memory_mb: int = 0
    max_concurrent_tasks: int = 1


@dataclass
class WorkerNode:
    """A registered worker node."""

    node_id: str
    name: str
    host: str
    port: int
    capabilities: WorkerCapabilities = field(default_factory=WorkerCapabilities)
    roles: List[str] = field(default_factory=list)
    status: str = "offline"
    last_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class WorkerRegistry:
    """Registry for distributed worker nodes."""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        auto_register_local: bool = True,
        local_node_id: Optional[str] = None,
        local_node_name: Optional[str] = None,
    ):
        self._workers: Dict[str, WorkerNode] = {}
        self._storage_path = storage_path
        self._local_node_id = local_node_id or os.environ.get("KARMA_LOCAL_NODE_ID", "stg")
        self._local_node_name = local_node_name or os.environ.get("KARMA_LOCAL_NODE_NAME", "STG")
        self._load()
        if auto_register_local and self._local_node_id not in self._workers:
            self.register_local()

    def register(
        self,
        node_id: str,
        name: str,
        host: str,
        port: int,
        capabilities: Optional[WorkerCapabilities] = None,
        roles: Optional[List[str]] = None,
    ) -> WorkerNode:
        """Register a worker node."""
        node = WorkerNode(
            node_id=node_id,
            name=name,
            host=host,
            port=port,
            capabilities=capabilities or WorkerCapabilities(),
            roles=roles or [],
            status="online",
        )
        self._workers[node_id] = node
        self._save()
        return node

    def unregister(self, node_id: str) -> bool:
        if node_id in self._workers:
            del self._workers[node_id]
            self._save()
            return True
        return False

    def get(self, node_id: str) -> Optional[WorkerNode]:
        return self._workers.get(node_id)

    def get_all(self) -> List[WorkerNode]:
        return list(self._workers.values())

    def get_by_role(self, role: str) -> List[WorkerNode]:
        return [w for w in self._workers.values() if role in w.roles]

    def get_online(self) -> List[WorkerNode]:
        return [w for w in self._workers.values() if w.status == "online"]

    def get_by_status(self, status: str) -> List[WorkerNode]:
        return [w for w in self._workers.values() if w.status == status]

    def update_status(self, node_id: str, status: str) -> bool:
        if node_id in self._workers:
            self._workers[node_id].status = status
            self._workers[node_id].last_seen = datetime.now().isoformat()
            self._save()
            return True
        return False

    def update_heartbeat(self, node_id: str) -> bool:
        return self.update_status(node_id, "online")

    def is_local(self, node_id: str) -> bool:
        return node_id == self._local_node_id

    def get_local(self) -> Optional[WorkerNode]:
        worker = self._workers.get(self._local_node_id)
        if worker is None:
            worker = self.register_local()
        return worker

    def register_local(self) -> WorkerNode:
        return self.register(
            node_id=self._local_node_id,
            name=self._local_node_name,
            host=os.environ.get("KARMA_LOCAL_HOST", "localhost"),
            port=int(os.environ.get("KARMA_LOCAL_PORT", "5000")),
            capabilities=WorkerCapabilities(
                can_plan=True,
                can_execute=True,
                can_retrieve=True,
                can_summarize=True,
                can_criticize=True,
                can_navigate=True,
                can_embed=True,
                has_gpu=os.environ.get("KARMA_LOCAL_HAS_GPU", "0") in ("1", "true", "yes"),
                memory_mb=int(os.environ.get("KARMA_LOCAL_MEMORY_MB", "16000")),
                max_concurrent_tasks=int(os.environ.get("KARMA_LOCAL_MAX_TASKS", "4")),
            ),
            roles=[
                "planner",
                "executor",
                "retriever",
                "summarizer",
                "critic",
                "navigator",
                "coder",
                "embedder",
            ],
        )

    def get_summary(self) -> Dict[str, Any]:
        return {
            "local_node_id": self._local_node_id,
            "total": len(self._workers),
            "online": len(self.get_by_status("online")),
            "offline": len(self.get_by_status("offline")),
            "busy": len(self.get_by_status("busy")),
            "workers": [
                {
                    "node_id": w.node_id,
                    "name": w.name,
                    "status": w.status,
                    "roles": w.roles,
                    "last_seen": w.last_seen,
                }
                for w in self._workers.values()
            ],
        }

    def _save(self) -> None:
        if not self._storage_path:
            return
        data = {
            node_id: {
                "node_id": w.node_id,
                "name": w.name,
                "host": w.host,
                "port": w.port,
                "roles": w.roles,
                "status": w.status,
                "last_seen": w.last_seen,
                "metadata": w.metadata,
                "capabilities": w.capabilities.__dict__,
            }
            for node_id, w in self._workers.items()
        }
        p = Path(self._storage_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        if not self._storage_path:
            return
        p = Path(self._storage_path)
        if not p.exists():
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            for node_id, wdata in data.items():
                caps_data = wdata.pop("capabilities", {})
                capabilities = WorkerCapabilities(**caps_data)
                self._workers[node_id] = WorkerNode(capabilities=capabilities, **wdata)
        except Exception:
            pass


_global_registry: Optional[WorkerRegistry] = None


def get_worker_registry(storage_path: Optional[str] = None) -> WorkerRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = WorkerRegistry(storage_path=storage_path)
    return _global_registry
