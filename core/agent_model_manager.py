"""Agent Model Manager - orchestration for functional agents and local models."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents import get_all_agents
from agents.base_agent import AgentContext, BaseAgent
from core.identity_guard import get_identity_guard
from core.response_normalizer import get_response_normalizer
from core.role_router import get_role_router
from models.base_model_adapter import BaseModelAdapter
from models.local_embedding_adapter import create_embedding_adapter
from models.local_llm_adapter import create_llm_adapter


@dataclass
class PipelineResult:
    """Result from the agent/model pipeline."""

    success: bool
    output: Any
    error: Optional[str] = None
    role_used: Optional[str] = None
    model_used: Optional[str] = None
    pipeline_type: str = "karma_only"
    execution_time_ms: float = 0.0
    identity_guard_applied: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ManagerConfig:
    """Configuration for agent/model manager."""

    enable_agents: bool = True
    enable_models: bool = True
    default_to_deterministic: bool = True
    model_load_timeout_seconds: int = 30
    agent_timeout_seconds: int = 60


def get_slot_manager(storage_path: Optional[str] = None):
    """Compatibility shim for tests."""
    from core.slot_manager import get_slot_manager as _gsm

    return _gsm(storage_path)


class AgentModelManager:
    """Manages agents and local model adapters for Karma."""

    # Compatibility constants retained for older tests and tooling.
    # Tuple shape: (model_id, roles, context_window, max_tokens)
    _OLLAMA_LLM_SEATS = [
        ("qwen3:4b", ["planner", "executor", "critic"], 32768, 4096),
        ("granite3.3:2b", ["summarizer", "navigator"], 8192, 2048),
    ]

    # Tuple shape: (model_id, roles, embedding_dim)
    _OLLAMA_EMBED_SEATS = [
        ("nomic-embed-text", ["retriever"], 768),
    ]

    _DEFAULT_MODEL_REGISTRY = [
        {
            "model_id": "qwen3:4b",
            "type": "llm",
            "backend": "ollama",
            "roles": ["planner", "executor", "critic"],
            "context_window": 32768,
            "max_tokens": 4096,
        },
        {
            "model_id": "granite3.3:2b",
            "type": "llm",
            "backend": "ollama",
            "roles": ["summarizer", "navigator"],
            "context_window": 8192,
            "max_tokens": 2048,
        },
        {
            "model_id": "nomic-embed-text",
            "type": "embedding",
            "backend": "ollama",
            "roles": ["retriever"],
            "embedding_dim": 768,
        },
    ]

    def __init__(self, config: Optional[ManagerConfig] = None):
        self.config = config or ManagerConfig()
        self.identity_guard = get_identity_guard()
        self.role_router = get_role_router()
        self.response_normalizer = get_response_normalizer()
        self._agents: Dict[str, BaseAgent] = {}
        self._agent_enabled: Dict[str, bool] = {}
        self._models: Dict[str, BaseModelAdapter] = {}
        self._model_enabled: Dict[str, bool] = {}
        self._initialized = False
        self._no_model_mode = True

    def initialize(self) -> None:
        """Initialize agents and model adapters.

        Model registry is loaded from config/model_registry.json when present.
        Built-in defaults are used only as fallback. If Ollama or configured
        models are unavailable, Karma remains usable in deterministic mode.
        """
        if self._initialized:
            return

        for role, agent in get_all_agents().items():
            self.register_agent(role, agent)

        from models.local_llm_adapter import _ollama_available

        if _ollama_available() and self.config.enable_models:
            loaded_count = self._register_ollama_models()
            self._no_model_mode = loaded_count == 0
            if loaded_count == 0:
                self._register_mock_models()
        else:
            self._register_mock_models()
            self._no_model_mode = True

        self._initialized = True

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _data_dir(self) -> Path:
        return self._project_root() / "data"

    def _load_model_registry(self) -> List[Dict[str, Any]]:
        path = self._project_root() / "config" / "model_registry.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            models = data.get("models", [])
            if isinstance(models, list) and models:
                return [m for m in models if isinstance(m, dict)]
        except Exception:
            pass
        return list(self._DEFAULT_MODEL_REGISTRY)

    def _slot_manager(self):
        from core.slot_manager import get_slot_manager as _gsm

        return _gsm(str(self._data_dir() / "slot_assignments.json"))

    def _register_mock_models(self) -> None:
        llm = create_llm_adapter("mock_llm", backend="mock")
        self.register_model("mock_llm", llm)
        emb = create_embedding_adapter("mock_embed", backend="mock")
        self.register_model("mock_embed", emb)

    def _register_ollama_models(self) -> int:
        """Register configured Ollama adapters and assign roles to slots."""
        from models.local_llm_adapter import _ollama_model_present

        loaded_count = 0
        slot_mgr = self._slot_manager()

        for entry in self._load_model_registry():
            model_id = entry.get("model_id")
            backend = entry.get("backend", "ollama")
            model_type = entry.get("type", "llm")
            roles = entry.get("roles", []) or []
            if not model_id or backend != "ollama":
                continue
            if not _ollama_model_present(model_id):
                continue

            if model_type == "embedding":
                adapter = create_embedding_adapter(
                    model_id=model_id,
                    backend="ollama",
                    embedding_dim=int(entry.get("embedding_dim", 768)),
                )
            else:
                adapter = create_llm_adapter(
                    model_id=model_id,
                    backend="ollama",
                    max_tokens=int(entry.get("max_tokens", 4096)),
                    context_window=int(entry.get("context_window", 8192)),
                )

            self.register_model(model_id, adapter)
            if not adapter.load():
                print(
                    f"[karma] Warning: model '{model_id}' registered but failed to load: "
                    f"{adapter.last_error}"
                )
                continue

            loaded_count += 1
            for role in roles:
                slot_mgr.assign_role(str(role), model_id)

        return loaded_count

    def register_agent(self, role: str, agent: BaseAgent) -> None:
        self._agents[role] = agent
        self._agent_enabled[role] = True

    def unregister_agent(self, role: str) -> bool:
        if role in self._agents:
            del self._agents[role]
            del self._agent_enabled[role]
            return True
        return False

    def enable_agent(self, role: str) -> bool:
        if role in self._agent_enabled:
            self._agent_enabled[role] = True
            return True
        return False

    def disable_agent(self, role: str) -> bool:
        if role in self._agent_enabled:
            self._agent_enabled[role] = False
            return True
        return False

    def get_agent(self, role: str) -> Optional[BaseAgent]:
        if role in self._agents and self._agent_enabled.get(role, False):
            return self._agents[role]
        return None

    def get_available_agents(self) -> List[Dict[str, Any]]:
        result = []
        for role, agent in self._agents.items():
            result.append(
                {
                    "role": role,
                    "enabled": self._agent_enabled.get(role, False),
                    "status": agent.status.value,
                    "capabilities": agent.get_capabilities().__dict__,
                }
            )
        return result

    def register_model(self, model_id: str, model: BaseModelAdapter) -> None:
        self._models[model_id] = model
        self._model_enabled[model_id] = True

    def unregister_model(self, model_id: str) -> bool:
        if model_id in self._models:
            self._models[model_id].unload()
            del self._models[model_id]
            del self._model_enabled[model_id]
            return True
        return False

    def load_model(self, model_id: str) -> bool:
        if model_id not in self._models:
            return False
        return self._models[model_id].load()

    def unload_model(self, model_id: str) -> bool:
        if model_id not in self._models:
            return False
        return self._models[model_id].unload()

    def get_available_models(self) -> List[Dict[str, Any]]:
        result = []
        for model_id, model in self._models.items():
            result.append(
                {
                    "model_id": model_id,
                    "enabled": self._model_enabled.get(model_id, False),
                    "status": model.status.value,
                    "metadata": model.get_stats(),
                }
            )
        return result

    def get_loaded_models(self) -> List[str]:
        return [model_id for model_id, model in self._models.items() if model.is_loaded]

    def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        explicit_role: Optional[str] = None,
        force_no_model: bool = None,
    ) -> PipelineResult:
        start_time = time.time()
        if not self._initialized:
            self.initialize()

        context = context or {}
        if force_no_model is None:
            force_no_model = self._no_model_mode

        available_models = self.get_loaded_models() if not force_no_model else []
        decision = self.role_router.route(
            task=task,
            intent=context.get("intent"),
            explicit_role=explicit_role,
            available_models=available_models,
            force_no_model=force_no_model,
        )

        if decision.role == "none" or decision.role is None:
            return PipelineResult(
                success=True,
                output=context.get("input", task),
                pipeline_type="karma_only",
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        agent = self.get_agent(decision.role)
        if agent is None:
            return PipelineResult(
                success=False,
                error=f"Agent not available: {decision.role}",
                role_used=decision.role,
                pipeline_type="karma_only",
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        agent_context = AgentContext(
            task=task,
            input_data=context,
            memory=context.get("memory"),
            retrieval=context.get("retrieval"),
            config=context.get("config", {}),
            metadata=context.get("metadata", {}),
        )
        agent_result = agent.run(agent_context)
        raw_output = agent_result.output if agent_result.success else agent_result.error
        guard_result = self.identity_guard.guard(raw_output, context)
        final_output = self.response_normalizer.normalize(guard_result.output)
        pipeline_type = "model_assisted" if decision.model_used else "agent_only"

        return PipelineResult(
            success=agent_result.success,
            output=final_output,
            error=agent_result.error,
            role_used=decision.role,
            model_used=decision.model_id,
            pipeline_type=pipeline_type,
            execution_time_ms=(time.time() - start_time) * 1000,
            identity_guard_applied=guard_result.normalized,
            metadata={
                "route_decision": decision.__dict__,
                "guard_modifications": guard_result.modifications,
                "agent_stats": agent.get_stats(),
            },
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "no_model_mode": self._no_model_mode,
            "agents": {
                "total": len(self._agents),
                "enabled": sum(1 for e in self._agent_enabled.values() if e),
            },
            "models": {
                "total": len(self._models),
                "loaded": len(self.get_loaded_models()),
                "enabled": sum(1 for e in self._model_enabled.values() if e),
            },
            "config": self.config.__dict__,
        }


_global_manager: Optional[AgentModelManager] = None


def get_agent_model_manager() -> AgentModelManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = AgentModelManager()
    return _global_manager
