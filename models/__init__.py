"""Models package - Swappable local model adapters.

Model adapters provide a uniform interface to local models.
Karma doesn't care about model family - only capabilities.
"""

from models.base_model_adapter import (
    BaseModelAdapter,
    ModelMetadata,
    ModelCapabilities,
    ModelStatus,
    ModelType,
    NullModelAdapter,
)

from models.local_llm_adapter import LocalLLMAdapter, create_llm_adapter
from models.local_embedding_adapter import LocalEmbeddingAdapter, create_embedding_adapter
from models.registry import ModelRegistry, get_model_registry


def get_all_model_adapters():
    """Get all available model adapters.

    Returns Ollama-backed adapters when Ollama is running, otherwise mocks.
    """
    from models.local_llm_adapter import _ollama_available, _ollama_model_present

    if not _ollama_available():
        return [
            create_llm_adapter("mock_llm", backend="mock", max_tokens=4096, context_window=8192),
            create_embedding_adapter("mock_embed", backend="mock", embedding_dim=384),
        ]

    adapters = []
    llm_seats = [
        ("qwen3:4b",     4096, 32768),
        ("granite3.3:2b", 2048, 8192),
    ]
    for model_id, max_tokens, ctx in llm_seats:
        if _ollama_model_present(model_id):
            adapters.append(create_llm_adapter(
                model_id=model_id, backend="ollama",
                max_tokens=max_tokens, context_window=ctx,
            ))

    embed_seats = [("nomic-embed-text", 768)]
    for model_id, dim in embed_seats:
        if _ollama_model_present(model_id):
            adapters.append(create_embedding_adapter(
                model_id=model_id, backend="ollama", embedding_dim=dim,
            ))

    return adapters


__all__ = [
    "BaseModelAdapter",
    "ModelMetadata",
    "ModelCapabilities",
    "ModelStatus",
    "ModelType",
    "NullModelAdapter",
    "LocalLLMAdapter",
    "create_llm_adapter",
    "LocalEmbeddingAdapter",
    "create_embedding_adapter",
    "ModelRegistry",
    "get_model_registry",
    "get_all_model_adapters",
]
