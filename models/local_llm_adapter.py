"""Local LLM Adapter - Adapter for local LLM runtimes.

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

OLLAMA_BASE_URL = "http://localhost:11434"


def _ollama_available() -> bool:
    """Check if Ollama HTTP API is reachable."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _ollama_model_present(model_id: str) -> bool:
    """Check if a specific model is available in Ollama."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        # Accept exact match (e.g. "qwen3:4b") or tag-less prefix (e.g. "qwen3" matches "qwen3:4b")
        def _match(listed: str, want: str) -> bool:
            if listed == want:
                return True
            if listed.startswith(want + ":"):
                return True
            # want has no tag: match any tagged version
            if ":" not in want and listed.split(":")[0] == want:
                return True
            return False
        return any(_match(m, model_id) for m in models)
    except Exception:
        return False


class LocalLLMAdapter(BaseModelAdapter):
    """Adapter for local LLM runtimes via Ollama HTTP API."""

    def __init__(
        self,
        metadata: ModelMetadata,
        backend: str = "mock",
        model_path: Optional[str] = None,
    ):
        super().__init__(metadata)
        self.backend = backend
        self.model_path = model_path
        self._model = None

    def load(self) -> bool:
        """Check model availability and mark ready."""
        if self._status == ModelStatus.READY:
            return True

        self._status = ModelStatus.LOADING

        try:
            if self.backend == "mock":
                self._model = {"loaded": True}
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
                self._model = {"backend": "ollama", "model_id": self.metadata.model_id}
                self._status = ModelStatus.READY
                return True

            elif self.backend == "llama_cpp":
                self._last_error = "llama_cpp backend not implemented"
                self._status = ModelStatus.ERROR
                return False

            else:
                self._last_error = f"Unknown backend: {self.backend}"
                self._status = ModelStatus.ERROR
                return False

        except Exception as e:
            self._last_error = str(e)
            self._status = ModelStatus.ERROR
            return False

    def unload(self) -> bool:
        """Unload model (Ollama manages its own memory)."""
        try:
            self._model = None
            self._status = ModelStatus.UNLOADED
            return True
        except Exception as e:
            self._last_error = str(e)
            return False

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text via Ollama or mock."""
        if not self.is_loaded:
            if not self.load():
                raise RuntimeError(f"Failed to load model: {self._last_error}")

        max_tokens = kwargs.get("max_tokens", 512)
        temperature = kwargs.get("temperature", 0.7)
        system = kwargs.get("system", "")

        if self.backend == "mock":
            return self._mock_generate(prompt, max_tokens, temperature)

        if self.backend == "ollama":
            return self._ollama_generate(prompt, max_tokens, temperature, system)

        raise NotImplementedError(f"Generate not implemented for {self.backend} backend")

    def _ollama_generate(self, prompt: str, max_tokens: int, temperature: float, system: str) -> str:
        """Call Ollama /api/generate."""
        payload: Dict[str, Any] = {
            "model": self.metadata.model_id,
            "prompt": prompt,
            "stream": False,
            "think": False,  # disable thinking tokens (qwen3 etc.) so response field is populated
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                result = json.loads(r.read())
            return result.get("response", "").strip()
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama request failed: {e}")

    def _mock_generate(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Mock generation for testing."""
        if "plan" in prompt.lower():
            return "1. Analyze the task\n2. Execute the plan\n3. Report results"
        elif "summarize" in prompt.lower():
            return "Summary: Key points extracted from the content."
        elif "critique" in prompt.lower():
            return "The plan looks good but could use more detail in step 2."
        else:
            return f"Generated response to: {prompt[:50]}..."

    def embed(self, text: str) -> List[float]:
        """Generate embeddings if supported."""
        if not self.metadata.capabilities.supports_embed:
            return super().embed(text)
        return [0.1] * 384

    def classify(self, text: str, labels: List[str]) -> Dict[str, float]:
        """Classify text if supported."""
        if not self.metadata.capabilities.supports_classify:
            return super().classify(text, labels)
        return {label: 1.0 / len(labels) for label in labels}


def create_llm_adapter(
    model_id: str,
    local_path: Optional[str] = None,
    backend: str = "mock",
    quantization: Optional[str] = None,
    max_tokens: int = 4096,
    context_window: int = 8192,
) -> LocalLLMAdapter:
    """Factory function to create a local LLM adapter."""
    capabilities = ModelCapabilities(
        supports_generate=True,
        supports_embed=False,
        supports_classify=False,
        max_tokens=max_tokens,
        context_window=context_window,
        recommended_roles=["general", "coder", "planner", "summarizer"],
    )
    metadata = ModelMetadata(
        model_id=model_id,
        model_type=ModelType.LLM,
        local_path=local_path,
        quantization=quantization,
        memory_footprint_mb=max_tokens * 2,
        capabilities=capabilities,
        tags=["local", "llm", backend],
    )
    return LocalLLMAdapter(metadata, backend=backend, model_path=local_path)
