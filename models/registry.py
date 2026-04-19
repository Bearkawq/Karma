"""Model Registry - Registry for local model metadata.

Manages registration and discovery of available local models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import asdict

from models.base_model_adapter import ModelMetadata, ModelType


class ModelRegistry:
    """Registry for local model metadata.
    
    Manages model registration, discovery, and capability-based selection.
    """
    
    def __init__(self):
        self._models: Dict[str, ModelMetadata] = {}
        self._registry_file: Optional[str] = None
    
    def register(self, metadata: ModelMetadata) -> None:
        """Register a model."""
        self._models[metadata.model_id] = metadata
    
    def unregister(self, model_id: str) -> bool:
        """Unregister a model."""
        if model_id in self._models:
            del self._models[model_id]
            return True
        return False
    
    def get(self, model_id: str) -> Optional[ModelMetadata]:
        """Get model metadata by ID."""
        return self._models.get(model_id)
    
    def get_all(self) -> List[ModelMetadata]:
        """Get all registered models."""
        return list(self._models.values())
    
    def find_by_capability(
        self,
        supports_generate: bool = False,
        supports_embed: bool = False,
        supports_classify: bool = False,
        supports_rerank: bool = False,
    ) -> List[ModelMetadata]:
        """Find models matching capability requirements."""
        results = []
        for metadata in self._models.values():
            caps = metadata.capabilities
            if (
                (not supports_generate or caps.supports_generate) and
                (not supports_embed or caps.supports_embed) and
                (not supports_classify or caps.supports_classify) and
                (not supports_rerank or caps.supports_rerank)
            ):
                results.append(metadata)
        return results
    
    def find_by_role(self, role: str) -> List[ModelMetadata]:
        """Find models suitable for a role."""
        results = []
        for metadata in self._models.values():
            if role in metadata.capabilities.recommended_roles:
                results.append(metadata)
        return results
    
    def find_by_type(self, model_type: ModelType) -> List[ModelMetadata]:
        """Find models by type."""
        return [m for m in self._models.values() if m.model_type == model_type]
    
    def save_registry(self, path: str) -> None:
        """Save registry to file."""
        data = {
            model_id: {
                "model_id": m.model_id,
                "model_type": m.model_type.value,
                "local_path": m.local_path,
                "quantization": m.quantization,
                "memory_footprint_mb": m.memory_footprint_mb,
                "capabilities": asdict(m.capabilities),
                "tags": m.tags,
            }
            for model_id, m in self._models.items()
        }
        
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(data, f, indent=2)
    
    def load_registry(self, path: str) -> int:
        """Load registry from file.
        
        Returns:
            Number of models loaded
        """
        p = Path(path)
        if not p.exists():
            return 0
        
        try:
            with open(p, "r") as f:
                data = json.load(f)
            
            for model_id, mdata in data.items():
                caps_data = mdata.pop("capabilities", {})
                capabilities = ModelCapabilities(**caps_data)
                
                metadata = ModelMetadata(
                    model_id=model_id,
                    model_type=ModelType(mdata.get("model_type", "llm")),
                    capabilities=capabilities,
                    **mdata,
                )
                self._models[model_id] = metadata
            
            return len(self._models)
            
        except Exception:
            return 0
    
    def get_summary(self) -> Dict[str, Any]:
        """Get registry summary."""
        by_type: Dict[str, int] = {}
        total_memory = 0
        
        for m in self._models.values():
            t = m.model_type.value
            by_type[t] = by_type.get(t, 0) + 1
            total_memory += m.memory_footprint_mb
        
        return {
            "total_models": len(self._models),
            "by_type": by_type,
            "total_memory_mb": total_memory,
            "models": [
                {
                    "model_id": m.model_id,
                    "type": m.model_type.value,
                    "path": m.local_path,
                }
                for m in self._models.values()
            ],
        }


_global_registry: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """Get global model registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ModelRegistry()
    return _global_registry
