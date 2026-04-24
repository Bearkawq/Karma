"""Base Model Adapter - Abstract interface for local language models.

Model adapters are swappable engines for language-heavy work.
They are NOT hardwired logic - Karma should only care about capability profiles.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class ModelStatus(Enum):
    """Model operational status."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


class ModelType(Enum):
    """Types of local models."""
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    ENCODER = "encoder"


@dataclass
class ModelCapabilities:
    """What this model can do."""
    supports_generate: bool = False
    supports_embed: bool = False
    supports_classify: bool = False
    supports_rerank: bool = False
    max_tokens: int = 0
    context_window: int = 0
    recommended_roles: List[str] = field(default_factory=list)


@dataclass
class ModelMetadata:
    """Model metadata manifest."""
    model_id: str
    model_type: ModelType
    local_path: Optional[str] = None
    quantization: Optional[str] = None
    memory_footprint_mb: int = 0
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    tags: List[str] = field(default_factory=list)


class BaseModelAdapter(ABC):
    """Abstract base class for model adapters.
    
    Adapters provide a uniform interface to local models.
    Karma doesn't care about model family - only capabilities.
    """

    def __init__(self, metadata: ModelMetadata):
        self.metadata = metadata
        self._status = ModelStatus.UNLOADED
        self._last_error: Optional[str] = None

    @property
    def model_id(self) -> str:
        return self.metadata.model_id

    @property
    def status(self) -> ModelStatus:
        return self._status

    @property
    def is_loaded(self) -> bool:
        return self._status == ModelStatus.READY

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @abstractmethod
    def load(self) -> bool:
        """Load the model into memory.
        
        Returns:
            True if load successful
        """
        pass

    @abstractmethod
    def unload(self) -> bool:
        """Unload the model from memory.
        
        Returns:
            True if unload successful
        """
        pass

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text completion.
        
        Args:
            prompt: Input prompt
            
        Returns:
            Generated text
        """
        pass

    def embed(self, text: str) -> List[float]:
        """Generate embeddings.
        
        Args:
            text: Input text
            
        Returns:
            Embedding vector
        """
        raise NotImplementedError(f"{self.model_id} does not support embeddings")

    def classify(self, text: str, labels: List[str]) -> Dict[str, float]:
        """Classify text into labels.
        
        Args:
            text: Input text
            labels: Possible labels
            
        Returns:
            Label -> confidence mapping
        """
        raise NotImplementedError(f"{self.model_id} does not support classification")

    def get_stats(self) -> Dict[str, Any]:
        """Get model statistics."""
        return {
            "model_id": self.model_id,
            "model_type": self.metadata.model_type.value,
            "status": self._status.value,
            "local_path": self.metadata.local_path,
            "quantization": self.metadata.quantization,
            "memory_footprint_mb": self.metadata.memory_footprint_mb,
            "capabilities": {
                "supports_generate": self.metadata.capabilities.supports_generate,
                "supports_embed": self.metadata.capabilities.supports_embed,
                "supports_classify": self.metadata.capabilities.supports_classify,
                "supports_rerank": self.metadata.capabilities.supports_rerank,
                "max_tokens": self.metadata.capabilities.max_tokens,
                "context_window": self.metadata.capabilities.context_window,
            },
            "last_error": self._last_error,
        }


class NullModelAdapter(BaseModelAdapter):
    """Null model for when no model is available."""

    def __init__(self):
        super().__init__(ModelMetadata(
            model_id="null",
            model_type=ModelType.LLM,
        ))
        self._status = ModelStatus.UNLOADED

    def load(self) -> bool:
        return False

    def unload(self) -> bool:
        return True

    def generate(self, prompt: str, **kwargs) -> str:
        raise RuntimeError("No model available")
