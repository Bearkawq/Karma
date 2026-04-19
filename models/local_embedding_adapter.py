"""Local Embedding Adapter - Adapter for local embedding models.

Supports Ollama backend via HTTP. Falls back to mock for tests.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from models.base_model_adapter import (
    BaseModelAdapter, ModelMetadata, ModelCapabilities, ModelStatus, ModelType
)
from models.local_llm_adapter import OLLAMA_BASE_URL, _ollama_available, _ollama_model_present


class LocalEmbeddingAdapter(BaseModelAdapter):
    """Adapter for local embedding models via Ollama HTTP API."""

    def __init__(
        self,
        metadata: ModelMetadata,
        backend: str = "mock",
        model_path: Optional[str] = None,
        embedding_dim: int = 384,
    ):
        super().__init__(metadata)
        self.backend = backend
        self.model_path = model_path
        self.embedding_dim = embedding_dim
        self._model = None

    def load(self) -> bool:
        """Check embedding model availability."""
        if self._status == ModelStatus.READY:
            return True

        self._status = ModelStatus.LOADING

        try:
            if self.backend == "mock":
                self._model = {"loaded": True, "dim": self.embedding_dim}
                self._status = ModelStatus.READY
                return True

            elif self.backend == "ollama":
                if not _ollama_available():
                    self._last_error = "Ollama service not reachable at localhost:11434"
                    self._status = ModelStatus.ERROR
                    return False
                if not _ollama_model_present(self.metadata.model_id):
                    self._last_error = f"Model '{self.metadata.model_id}' not found in Ollama"
                    self._status = ModelStatus.ERROR
                    return False
                # Probe actual embedding dimension
                try:
                    dim = self._get_embedding_dim()
                    if dim:
                        self.embedding_dim = dim
                except Exception:
                    pass  # Use default dim
                self._model = {"backend": "ollama", "model_id": self.metadata.model_id, "dim": self.embedding_dim}
                self._status = ModelStatus.READY
                return True

            else:
                self._last_error = f"Backend {self.backend} not implemented"
                self._status = ModelStatus.ERROR
                return False

        except Exception as e:
            self._last_error = str(e)
            self._status = ModelStatus.ERROR
            return False

    def _get_embedding_dim(self) -> Optional[int]:
        """Probe Ollama for actual embedding dimension."""
        vec = self._ollama_embed("test")
        return len(vec) if vec else None

    def unload(self) -> bool:
        """Unload embedding model."""
        try:
            self._model = None
            self._status = ModelStatus.UNLOADED
            return True
        except Exception as e:
            self._last_error = str(e)
            return False

    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError("Use embed() for embeddings")

    def embed(self, text: str) -> List[float]:
        """Generate embeddings via Ollama or mock."""
        if not self.is_loaded:
            if not self.load():
                raise RuntimeError(f"Failed to load model: {self._last_error}")

        if self.backend == "mock":
            import hashlib
            h = hashlib.sha256(text.encode()).digest()
            vec = [float(b) / 255.0 for b in h]
            # Pad/truncate to embedding_dim
            while len(vec) < self.embedding_dim:
                vec.extend(vec)
            return vec[:self.embedding_dim]

        if self.backend == "ollama":
            return self._ollama_embed(text)

        raise NotImplementedError(f"Embed not implemented for {self.backend}")

    def _ollama_embed(self, text: str) -> List[float]:
        """Call Ollama /api/embed."""
        payload = {
            "model": self.metadata.model_id,
            "input": text,
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/embed",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
            # Ollama /api/embed returns {"embeddings": [[...]], ...}
            embeddings = result.get("embeddings", [])
            if embeddings and isinstance(embeddings[0], list):
                return embeddings[0]
            # Fallback for older API: {"embedding": [...]}
            return result.get("embedding", [])
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama embed request failed: {e}")


def create_embedding_adapter(
    model_id: str,
    local_path: Optional[str] = None,
    backend: str = "mock",
    embedding_dim: int = 768,
) -> LocalEmbeddingAdapter:
    """Factory function to create an embedding adapter."""
    capabilities = ModelCapabilities(
        supports_generate=False,
        supports_embed=True,
        supports_classify=False,
        supports_rerank=False,
    )
    metadata = ModelMetadata(
        model_id=model_id,
        model_type=ModelType.EMBEDDING,
        local_path=local_path,
        memory_footprint_mb=embedding_dim * 4,
        capabilities=capabilities,
        tags=["local", "embedding", backend],
    )
    return LocalEmbeddingAdapter(
        metadata,
        backend=backend,
        model_path=local_path,
        embedding_dim=embedding_dim,
    )
