"""Service Container - Dependency Injection for Karma.

Replaces singleton getters (get_pulse, get_spine, get_ingestor, get_cache, get_learner)
with a centralized service container that provides dependency injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from research.pulse import Pulse
    from research.knowledge_spine import KnowledgeSpine
    from research.ingestor import SeedIngestor
    from research.cache import GoLearnCache
    from research.patch_learning import PatchLearner
    from storage.memory import MemorySystem
    from core.telemetry.event_bus import TelemetryEventBus


class ServiceContainer:
    """Centralized dependency injection container for Karma services.
    
    Replaces singleton accessors with constructor injection.
    Initialize once during bootstrap, then pass to subsystems.
    """
    
    _instance: ServiceContainer | None = None
    
    def __init__(self):
        self._pulse: Pulse | None = None
        self._spine: KnowledgeSpine | None = None
        self._ingestor: SeedIngestor | None = None
        self._cache: GoLearnCache | None = None
        self._learner: PatchLearner | None = None
        self._memory: MemorySystem | None = None
        self._telemetry: TelemetryEventBus | None = None
        self._initialized = False
    
    @classmethod
    def get_instance(cls) -> ServiceContainer:
        """Get the global service container instance."""
        if cls._instance is None:
            cls._instance = ServiceContainer()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the container instance (for testing)."""
        cls._instance = None
    
    @property
    def pulse(self) -> Pulse:
        if self._pulse is None:
            from research.pulse import Pulse
            self._pulse = Pulse()
        return self._pulse
    
    @property
    def spine(self) -> KnowledgeSpine:
        if self._spine is None:
            from research.knowledge_spine import KnowledgeSpine
            self._spine = KnowledgeSpine()
        return self._spine
    
    @property
    def ingestor(self) -> SeedIngestor:
        if self._ingestor is None:
            from research.ingestor import SeedIngestor
            self._ingestor = SeedIngestor()
        return self._ingestor
    
    @property
    def cache(self) -> GoLearnCache:
        if self._cache is None:
            from research.cache import GoLearnCache
            self._cache = GoLearnCache()
        return self._cache
    
    @property
    def learner(self) -> PatchLearner:
        if self._learner is None:
            from research.patch_learning import PatchLearner
            self._learner = PatchLearner()
        return self._learner
    
    def set_memory(self, memory: MemorySystem) -> None:
        """Set memory system after construction."""
        self._memory = memory
    
    @property
    def memory(self) -> MemorySystem:
        if self._memory is None:
            raise RuntimeError("Memory not set in ServiceContainer. Call set_memory() first.")
        return self._memory
    
    def set_telemetry(self, telemetry: TelemetryEventBus) -> None:
        """Set telemetry bus after construction."""
        self._telemetry = telemetry
    
    @property
    def telemetry(self) -> TelemetryEventBus:
        if self._telemetry is None:
            from core.telemetry.event_bus import TelemetryEventBus
            self._telemetry = TelemetryEventBus()
        return self._telemetry
    
    def initialize(self) -> None:
        """Initialize all lazy-loaded services."""
        _ = self.pulse
        _ = self.spine
        _ = self.cache
        _ = self.learner
        self._initialized = True
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized


def get_container() -> ServiceContainer:
    """Get the global service container (backwards compatibility)."""
    return ServiceContainer.get_instance()
