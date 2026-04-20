"""Agent Model Manager - Main orchestration for agents and models.

Ties together agents, models, identity guard, and role router
into a cohesive modular execution framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time

from agents.base_agent import BaseAgent, AgentContext, AgentResult, NullAgent
from agents import get_agent_by_role, get_all_agents

from models.base_model_adapter import BaseModelAdapter, NullModelAdapter
from models import get_model_registry, get_all_model_adapters
from models.local_llm_adapter import create_llm_adapter
from models.local_embedding_adapter import create_embedding_adapter

from core.identity_guard import IdentityGuard, get_identity_guard
from core.role_router import RoleRouter, get_role_router, InvocationMode, RouteDecision
from core.response_normalizer import ResponseNormalizer, get_response_normalizer


@dataclass
class PipelineResult:
    """Result from the agent/model pipeline."""
    success: bool
    output: Any
    error: Optional[str] = None
    role_used: Optional[str] = None
    model_used: Optional[str] = None
    pipeline_type: str = "karma_only"  # karma_only, agent_only, model_assisted, mixed
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
    """Compatibility shim: expose get_slot_manager at module level for tests.

    Delegates to core.slot_manager.get_slot_manager.
    """
    from core.slot_manager import get_slot_manager as _gsm
    return _gsm(storage_path)


class AgentModelManager:
    """Manages agents and models for Karma.
    
    This is the main orchestration layer that:
    - Registers available agents and models
    - Routes tasks to appropriate agents/models
    - Applies identity guard to all outputs
    - Falls back to deterministic behavior when needed
    """
    
    def __init__(self, config: Optional[ManagerConfig] = None):
        self.config = config or ManagerConfig()
        
        # Core components
        self.identity_guard = get_identity_guard()
        self.role_router = get_role_router()
        self.response_normalizer = get_response_normalizer()
        
        # Agent registry
        self._agents: Dict[str, BaseAgent] = {}
        self._agent_enabled: Dict[str, bool] = {}
        
        # Model registry
        self._models: Dict[str, BaseModelAdapter] = {}
        self._model_enabled: Dict[str, bool] = {}
        
        # State
        self._initialized = False
        self._no_model_mode = True  # Start in no-model mode
    
    def initialize(self) -> None:
        """Initialize the manager with default agents and models.

        If Ollama is reachable, registers real local adapters and wires
        slot assignments. Falls back to mock adapters so the system is
        always functional without a GPU.
        """
        if self._initialized:
            return

        # Register default agents
        all_agents = get_all_agents()
        for role, agent in all_agents.items():
            self.register_agent(role, agent)

        # Try Ollama first
        from models.local_llm_adapter import _ollama_available, _ollama_model_present

        if _ollama_available():
            self._no_model_mode = False
            self._register_ollama_models()
        else:
            # Deterministic fallback
            llm = create_llm_adapter("mock_llm", backend="mock")
            self.register_model("mock_llm", llm)

            emb = create_embedding_adapter("mock_embed", backend="mock")
            self.register_model("mock_embed", emb)

        self._initialized = True

    # --- Seat mapping constants ---
    # These match config/model_preferences.json and config/model_registry.json
    _OLLAMA_LLM_SEATS = [
        # (model_id, roles, max_tokens, context_window)
        ("qwen3:4b",     ["planner", "executor", "critic"],   4096, 32768),
        ("granite3.3:2b",["summarizer", "navigator"],         2048,  8192),
    ]
    _OLLAMA_EMBED_SEATS = [
        # (model_id, roles, embedding_dim)
        ("nomic-embed-text", ["retriever"], 768),
    ]

    def _register_ollama_models(self) -> None:
        """Register Ollama-backed adapters and wire slot assignments."""
        from models.local_llm_adapter import _ollama_model_present
        from core.slot_manager import get_slot_manager
        import os

        base_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        slot_mgr = get_slot_manager(
            os.path.join(base_dir, "slot_assignments.json")
        )

        for model_id, roles, max_tokens, ctx in self._OLLAMA_LLM_SEATS:
            if not _ollama_model_present(model_id):
                continue
            adapter = create_llm_adapter(
                model_id=model_id,
                backend="ollama",
                max_tokens=max_tokens,
                context_window=ctx,
            )
            self.register_model(model_id, adapter)
            if not adapter.load():
                # Surface the failure but don't abort — other models may still load.
                print(f"[karma] Warning: model '{model_id}' registered but failed to load: {adapter.last_error}")
                continue
            for role in roles:
                slot_mgr.assign_role(role, model_id)

        for model_id, roles, embedding_dim in self._OLLAMA_EMBED_SEATS:
            if not _ollama_model_present(model_id):
                continue
            adapter = create_embedding_adapter(
                model_id=model_id,
                backend="ollama",
                embedding_dim=embedding_dim,
            )
            self.register_model(model_id, adapter)
            if not adapter.load():
                print(f"[karma] Warning: embedding model '{model_id}' registered but failed to load: {adapter.last_error}")
                continue
            for role in roles:
                slot_mgr.assign_role(role, model_id)
    
    # --- Agent Management ---
    
    def register_agent(self, role: str, agent: BaseAgent) -> None:
        """Register an agent for a role."""
        self._agents[role] = agent
        self._agent_enabled[role] = True
    
    def unregister_agent(self, role: str) -> bool:
        """Unregister an agent."""
        if role in self._agents:
            del self._agents[role]
            del self._agent_enabled[role]
            return True
        return False
    
    def enable_agent(self, role: str) -> bool:
        """Enable an agent."""
        if role in self._agent_enabled:
            self._agent_enabled[role] = True
            return True
        return False
    
    def disable_agent(self, role: str) -> bool:
        """Disable an agent."""
        if role in self._agent_enabled:
            self._agent_enabled[role] = False
            return True
        return False
    
    def get_agent(self, role: str) -> Optional[BaseAgent]:
        """Get agent by role."""
        if role in self._agents and self._agent_enabled.get(role, False):
            return self._agents[role]
        return None
    
    def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get all available agents with status."""
        result = []
        for role, agent in self._agents.items():
            result.append({
                "role": role,
                "enabled": self._agent_enabled.get(role, False),
                "status": agent.status.value,
                "capabilities": agent.get_capabilities().__dict__,
            })
        return result
    
    # --- Model Management ---
    
    def register_model(self, model_id: str, model: BaseModelAdapter) -> None:
        """Register a model."""
        self._models[model_id] = model
        self._model_enabled[model_id] = True
    
    def unregister_model(self, model_id: str) -> bool:
        """Unregister a model."""
        if model_id in self._models:
            # Unload first
            self._models[model_id].unload()
            del self._models[model_id]
            del self._model_enabled[model_id]
            return True
        return False
    
    def load_model(self, model_id: str) -> bool:
        """Load a model into memory."""
        if model_id not in self._models:
            return False
        
        model = self._models[model_id]
        return model.load()
    
    def unload_model(self, model_id: str) -> bool:
        """Unload a model from memory."""
        if model_id not in self._models:
            return False
        
        model = self._models[model_id]
        return model.unload()
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get all available models with status."""
        result = []
        for model_id, model in self._models.items():
            result.append({
                "model_id": model_id,
                "enabled": self._model_enabled.get(model_id, False),
                "status": model.status.value,
                "metadata": model.get_stats(),
            })
        return result
    
    def get_loaded_models(self) -> List[str]:
        """Get list of loaded model IDs."""
        return [
            model_id for model_id, model in self._models.items()
            if model.is_loaded
        ]
    
    # --- Pipeline Execution ---
    
    def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        explicit_role: Optional[str] = None,
        force_no_model: bool = None,
    ) -> PipelineResult:
        """Execute task through the pipeline.
        
        This is the main entry point for processing tasks through
        agents and models with identity protection.
        """
        start_time = time.time()
        
        # Initialize if needed
        if not self._initialized:
            self.initialize()
        
        context = context or {}
        
        # Determine if we should use models
        if force_no_model is None:
            force_no_model = self._no_model_mode
        
        # Get available models
        available_models = self.get_loaded_models() if not force_no_model else []
        
        # Route to appropriate agent
        decision = self.role_router.route(
            task=task,
            intent=context.get("intent"),
            explicit_role=explicit_role,
            available_models=available_models,
            force_no_model=force_no_model,
        )
        
        # Execute based on routing
        if decision.role == "none" or decision.role is None:
            # No agent needed - Karma handles directly
            return PipelineResult(
                success=True,
                output=context.get("input", task),
                pipeline_type="karma_only",
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        
        # Get the agent
        agent = self.get_agent(decision.role)
        
        if agent is None:
            return PipelineResult(
                success=False,
                error=f"Agent not available: {decision.role}",
                role_used=decision.role,
                pipeline_type="karma_only",
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        
        # Build agent context
        agent_context = AgentContext(
            task=task,
            input_data=context,
            memory=context.get("memory"),
            retrieval=context.get("retrieval"),
            config=context.get("config", {}),
            metadata=context.get("metadata", {}),
        )
        
        # Execute agent
        agent_result = agent.run(agent_context)
        
        # Apply identity guard
        raw_output = agent_result.output if agent_result.success else agent_result.error
        guard_result = self.identity_guard.guard(raw_output, context)
        
        # Normalize response
        final_output = self.response_normalizer.normalize(guard_result.output)
        
        # Determine pipeline type
        pipeline_type = "agent_only"
        if decision.model_used:
            pipeline_type = "model_assisted"
        
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
    
    # --- Status ---
    
    def get_status(self) -> Dict[str, Any]:
        """Get overall system status."""
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
    """Get global agent model manager."""
    global _global_manager
    if _global_manager is None:
        _global_manager = AgentModelManager()
    return _global_manager
